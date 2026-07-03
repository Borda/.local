#!/usr/bin/env node
// inject-preamble.js — UserPromptSubmit hook
//
// Injects a terse codemap status line before each user turn when a codemap
// index exists at .cache/codemap/<project>.json.
//
// No index yet: for Python projects (root/flat __init__.py, a src/<pkg>/__init__.py
// src-layout, or a pyproject.toml/setup.py at the root) emit a once-per-session
// directive asking the agent to offer building
// the index — hooks are stdout-only and cannot call AskUserQuestion themselves,
// so the agent raises it and, on yes, runs scan-index foreground. Non-Python
// dirs stay silent (zero output, ≤3 stat calls) — see handleMissingIndex().
//
// When stale (git HEAD differs from indexed sha, OR uncommitted .py files
// exist): spawns scan-index --incremental --root in the background (non-blocking,
// lockfile-guarded) so the index silently refreshes while Claude answers.
// --incremental re-parses only changed files (~75 ms vs ~60 s full rescan);
// scan-index falls back to a full scan when the on-disk index predates v3.
// Staleness definition matches Tier-1 of check-index-currency.
//
// Output written to stdout (Claude Code prepends it to conversation context):
//   [codemap] .cache/codemap/proj.json · N modules · current (git: abc1234) · scanned: 2026-06-20
//   Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol.
//
// EXIT CODES: always 0 — must never block user messages.

"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execSync, spawn } = require("child_process");

const MAX_PARSE_BYTES = 10 * 1024 * 1024; // full parse skipped for indexes >10 MB
const LOCK_TTL_MS = 10 * 60 * 1000; // 10 min — max expected scan duration before re-allow
const HEADER_PEEK_BYTES = 8 * 1024; // header fields always appear before file_shas (first ~1-2 KB)
const NOINDEX_TTL_MS = 30 * 60 * 1000; // 30 min — ask to bootstrap the index at most once per session

// Extract a plain string field from the first N bytes of the JSON file via regex.
// Sufficient for our header fields (git_sha = hex, scanned_at = ISO dt, scan_root = path).
function extractField(key, text) {
  const m = text.match(new RegExp('"' + key + '"\\s*:\\s*"([^"]*)"'));
  return m ? m[1] : "";
}

// No-index branch: a project with zero index never bootstraps itself (the stale
// auto-refresh below only fires on an already-existing index). For Python projects
// emit a once-per-session directive; the agent turns it into an AskUserQuestion and,
// on consent, runs scan-index foreground. Always exits 0 — never blocks the turn.
function handleMissingIndex(projRoot, proj) {
  // Python-only gate. Any one signal is sufficient (all checks bounded — non-Python
  // dirs still return fast):
  //   1. __init__.py at git root (root-level package)
  //   2. __init__.py one level down (flat multi-package layout)
  //   3. src/<pkg>/__init__.py two levels down (PEP 517 src-layout — depth 3)
  //   4. pyproject.toml / setup.py at root (Python project-root marker for layouts 1–3 miss)
  const hasInit = (dir) => {
    try {
      return fs.statSync(path.join(dir, "__init__.py")).isFile();
    } catch {
      return false;
    }
  };
  const isPython = (() => {
    if (hasInit(projRoot)) return true;
    let dirs = [];
    try {
      dirs = fs
        .readdirSync(projRoot, { withFileTypes: true })
        .filter((e) => e.isDirectory() && !e.name.startsWith("."));
    } catch {
      dirs = [];
    }
    if (dirs.some((d) => hasInit(path.join(projRoot, d.name)))) return true;
    // src-layout: src/<pkg>/__init__.py
    if (dirs.some((d) => d.name === "src")) {
      const srcDir = path.join(projRoot, "src");
      try {
        const found = fs
          .readdirSync(srcDir, { withFileTypes: true })
          .filter((e) => e.isDirectory() && !e.name.startsWith("."))
          .some((d) => hasInit(path.join(srcDir, d.name)));
        if (found) return true;
      } catch {}
    }
    // Packaging-file fallback — Python-specific project-root markers.
    return ["pyproject.toml", "setup.py"].some((f) => {
      try {
        return fs.statSync(path.join(projRoot, f)).isFile();
      } catch {
        return false;
      }
    });
  })();
  if (!isPython) process.exit(0);

  // Ask at most once per session per project — flag write precedes emit so a
  // user "no" is not re-asked within the TTL.
  const askFlag = path.join(os.tmpdir(), `codemap-noindex-${proj}`);
  try {
    if (Date.now() - parseInt(fs.readFileSync(askFlag, "utf8"), 10) < NOINDEX_TTL_MS) process.exit(0);
  } catch {
    /* no flag yet */
  }
  try {
    fs.writeFileSync(askFlag, String(Date.now()));
  } catch {
    /* best-effort; flag write failures never block */
  }

  process.stdout.write(
    `[codemap] No structural index for "${proj}" (.cache/codemap/${proj}.json missing) — blast-radius / coupling queries unavailable.\n` +
      `ACTION (ask once): call AskUserQuestion — ask the user whether to build the codemap index now.\n` +
      `  • yes → run scan-index (\${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index) in the FOREGROUND and WAIT until it finishes, then continue using scan-query.\n` +
      `  • no  → proceed without codemap; do not raise again this session.\n`,
  );
  process.exit(0);
}

function main() {
  // Drain stdin (UserPromptSubmit sends event JSON we don't need here)
  try {
    fs.readFileSync("/dev/stdin");
  } catch {
    /* ok */
  }

  const cwd = process.cwd();

  // Project identity mirrors scan-index / scan-query / seed-session: git-root basename
  // (fallback cwd basename). Using cwd basename would miss the index on a subdir launch —
  // the index is named for the git root and stored under <git-root>/.cache/codemap. Resolve
  // once and reuse for both the lookup path and the Python gate.
  let projRoot = cwd;
  try {
    const r = execSync("git rev-parse --show-toplevel", { cwd, timeout: 3000, stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
    if (r) projRoot = r;
  } catch {
    /* non-git → cwd */
  }
  const proj = path.basename(projRoot);

  // Resolve index path (CODEMAP_INDEX_DIR env override supported)
  const idxDir = process.env.CODEMAP_INDEX_DIR || path.join(projRoot, ".cache", "codemap");
  const idxPath = path.join(idxDir, `${proj}.json`);

  // No index → prompt once per session (Python projects only); non-Python dirs stay silent
  let idxStat;
  try {
    idxStat = fs.statSync(idxPath);
  } catch {
    return handleMissingIndex(projRoot, proj);
  }
  if (!idxStat.isFile()) return handleMissingIndex(projRoot, proj);

  // Parse header fields from the first HEADER_PEEK_BYTES only — avoids full
  // parse of the large file_shas dict on every prompt for big indexes.
  let gitSha = "",
    scannedAt = "",
    scanRoot = cwd,
    moduleCount = "?";
  try {
    const fd = fs.openSync(idxPath, "r");
    const buf = Buffer.allocUnsafe(HEADER_PEEK_BYTES);
    const bytesRead = fs.readSync(fd, buf, 0, HEADER_PEEK_BYTES, 0);
    fs.closeSync(fd);
    const header = buf.slice(0, bytesRead).toString("utf8");

    gitSha = extractField("git_sha", header);
    scannedAt = extractField("scanned_at", header).slice(0, 10);
    const rawRoot = extractField("scan_root", header);
    // Resolve and validate scan_root before use in spawn — never pass raw index value directly.
    if (rawRoot) {
      const resolved = path.resolve(rawRoot);
      // Accept only absolute paths (path.resolve always returns absolute; guard against edge cases).
      scanRoot = path.isAbsolute(resolved) ? resolved : cwd;
    }
    // Module count is NOT computed here — the full JSON.parse of file_shas is
    // deferred until just before emit (below), so the common current+recently-
    // injected prompt short-circuits at the session-TTL check without ever
    // parsing the ≤10 MB index. moduleCount stays "?" until then.
  } catch {
    process.exit(0);
  }

  // Currency check — Tier 1: git sha + dirty .py count (matches check-index-currency Tier 1).
  // Only run git commands when sha is available.
  let headSha = "";
  let dirtyPyCount = 0;
  try {
    headSha = execSync("git rev-parse HEAD", { cwd, timeout: 3000 }).toString().trim();
  } catch {
    /* non-git project or git unavailable */
  }
  // Dirty-tree check only when SHA matches — avoids double-stale trigger.
  if (headSha && gitSha && gitSha === headSha) {
    try {
      const dirty = execSync("git status --porcelain -- '*.py'", { cwd, timeout: 3000 }).toString().trim();
      dirtyPyCount = dirty ? dirty.split("\n").filter(Boolean).length : 0;
    } catch {
      /* git unavailable or non-git project */
    }
  }

  const currency = !headSha || !gitSha ? "unknown" : gitSha !== headSha || dirtyPyCount > 0 ? "stale" : "current";

  // Auto-refresh on stale: spawn scan-index in background with lockfile guard
  let refreshNote = "";
  if (currency === "stale") {
    const lockFile = path.join(os.tmpdir(), `codemap-refresh-${proj}`);
    let scanning = false;
    try {
      const lockAge = Date.now() - parseInt(fs.readFileSync(lockFile, "utf8"), 10);
      if (lockAge < LOCK_TTL_MS) {
        scanning = true;
      } else {
        fs.unlinkSync(lockFile); // stale lock — remove and allow re-trigger
      }
    } catch {
      /* no lock file yet */
    }

    if (!scanning) {
      // Plugin root: CLAUDE_PLUGIN_ROOT env (set by Claude Code) or __dirname/../
      const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || path.dirname(__dirname);
      const scanBin = path.join(pluginRoot, "bin", "scan-index");
      if (fs.existsSync(scanBin)) {
        try {
          fs.writeFileSync(lockFile, String(Date.now()));
          // Non-blocking: detached child, stdin/stdout/stderr all ignored
          const child = spawn(scanBin, ["--root", scanRoot, "--timeout", "300"], {
            detached: true,
            stdio: "ignore",
            cwd,
          });
          child.unref();
          refreshNote = " · refresh started";
        } catch {
          /* best-effort; spawn errors never block */
        }
      }
    } else {
      refreshNote = " · refresh in progress";
    }
  }

  // Inject preamble only once per session per project — skip when current + recently injected.
  // Stale index always outputs so the auto-refresh note reaches the agent.
  const SESSION_TTL_MS = 30 * 60 * 1000; // 30 min ≈ typical session length
  const sessionFlag = path.join(os.tmpdir(), `codemap-preamble-${proj}`);
  if (currency === "current") {
    try {
      const flagAge = Date.now() - parseInt(fs.readFileSync(sessionFlag, "utf8"), 10);
      if (flagAge < SESSION_TTL_MS) process.exit(0); // already injected this session
    } catch {
      /* no flag yet */
    }
  }
  try {
    fs.writeFileSync(sessionFlag, String(Date.now()));
  } catch {
    /* best-effort; flag write failures never block */
  }

  // Module count: full parse deferred to here so the current+recently-injected
  // early-exit above never pays for it. Only parse reasonably-sized indexes;
  // a parse failure keeps "?" rather than blocking the emit.
  if (idxStat.size <= MAX_PARSE_BYTES) {
    try {
      const idx = JSON.parse(fs.readFileSync(idxPath, "utf8"));
      moduleCount = Object.keys(idx.file_shas || {}).length;
    } catch {
      /* keep "?" — never block the preamble on a parse error */
    }
  }

  const relIdx = path.relative(cwd, idxPath);
  const shortSha = gitSha.slice(0, 7);
  const shaLabel = currency === "current" ? ` (git: ${shortSha})` : "";

  process.stdout.write(
    `[codemap] ${relIdx} · ${moduleCount} modules · ${currency}${shaLabel}${refreshNote} · scanned: ${scannedAt}\n` +
      `Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol.\n`,
  );
}

try {
  main();
} catch {
  process.exit(0);
}
