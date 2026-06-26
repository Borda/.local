#!/usr/bin/env node
// inject-preamble.js — UserPromptSubmit hook
//
// Injects a terse codemap status line before each user turn when a codemap
// index exists at .cache/codemap/<project>.json. Zero output (zero cost)
// when no index is present — unindexed projects are unaffected.
//
// When stale (git HEAD differs from indexed sha, OR uncommitted .py files
// exist): spawns scan-index --root in the background (non-blocking,
// lockfile-guarded) so the index silently refreshes while Claude answers.
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

// Extract a plain string field from the first N bytes of the JSON file via regex.
// Sufficient for our header fields (git_sha = hex, scanned_at = ISO dt, scan_root = path).
function extractField(key, text) {
  const m = text.match(new RegExp('"' + key + '"\\s*:\\s*"([^"]*)"'));
  return m ? m[1] : "";
}

function main() {
  // Drain stdin (UserPromptSubmit sends event JSON we don't need here)
  try {
    fs.readFileSync("/dev/stdin");
  } catch {
    /* ok */
  }

  const cwd = process.cwd();
  const proj = path.basename(cwd);

  // Resolve index path (CODEMAP_INDEX_DIR env override supported)
  const idxDir = process.env.CODEMAP_INDEX_DIR || path.join(cwd, ".cache", "codemap");
  const idxPath = path.join(idxDir, `${proj}.json`);

  // No index → exit silently; zero output, zero overhead
  let idxStat;
  try {
    idxStat = fs.statSync(idxPath);
  } catch {
    process.exit(0);
  }
  if (!idxStat.isFile()) process.exit(0);

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

    // Module count: full parse only for reasonably-sized indexes
    if (idxStat.size <= MAX_PARSE_BYTES) {
      const raw = fs.readFileSync(idxPath, "utf8");
      const idx = JSON.parse(raw);
      moduleCount = Object.keys(idx.file_shas || {}).length;
    }
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
