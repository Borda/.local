#!/usr/bin/env node
// lint-on-save.js — PostToolUse hook
//
// PURPOSE
//   Closes the gap between Claude editing a file and pre-commit running at
//   commit time. Auto-fixable violations are applied the moment they're
//   introduced. Pairs with md-compress.js: after the first Edit on any .md
//   file, this hook permanently normalizes it via pre-commit (mdformat,
//   trailing-whitespace). From that point, md-compress.js finds the file
//   already normalized and skips the write — both hooks converge to steady
//   state after first edit.
//
// WHY EXPLICIT --config
//   Hook fires globally across all projects. Passing --config with the
//   project-root .pre-commit-config.yaml ensures pre-commit uses the correct
//   project config, not one found by walking parent directories.
//
// HOW IT WORKS
//   1. Fires on every PostToolUse event for the Write and Edit tools.
//   2. Checks whether .pre-commit-config.yaml exists in the project root.
//      If absent, exits 0 silently — safe no-op in repos without pre-commit.
//   3. Runs `pre-commit run --config <configPath> --files <file_path>`
//      targeting only the changed file (no full-repo scan).
//   4. On success (exit 0) → silent, no output.
//      On failure (exit 1 or 2) → writes hook output to stderr and exits 2,
//      which causes Claude Code to surface the message as feedback so Claude
//      can immediately read it and apply the necessary fix.
//      If pre-commit exits non-zero with no output (e.g. no hooks apply to
//      the file type), this hook exits 0 silently — no false-positive block.
//
// EXIT CODES
//   0  All hooks passed, or pre-commit is not configured / not installed.
//   2  One or more hooks failed or auto-modified the file.
//      Claude Code treats exit 2 as "blocking feedback" — the output is shown
//      and Claude will re-read the file and/or apply corrections.
//
// PRE-COMMIT EXIT CODE MAPPING
//   pre-commit 0 → this hook exits 0 (silent pass)
//   pre-commit 1 → auto-fix applied (file changed) → exits 2 so Claude re-reads
//   pre-commit 2 → errors found → exits 2 so Claude sees the diagnostics
//
// ASYNC SPAWN
//   Uses child_process.spawn (async) with explicit SIGTERM kill-on-timeout so
//   Claude Code's hook pipeline is never blocked by a stalled pre-commit run.
//   The hook process waits for the child via a Promise and exits with the
//   correct code once pre-commit finishes or the timer fires.
//
// CROSS-SESSION LOCK
//   A project-scoped lock at /tmp/claude-precommit-<project-hash>.lock prevents
//   parallel Claude terminals from running pre-commit on the same project
//   simultaneously (which would race pre-commit's own internal lock file and
//   produce spurious failures). Lock is acquired after all early-exit checks and
//   released in every exit path. Stale locks (>20 s) are stolen automatically.
//
// TIMEOUT
//   15 s hard limit per single-file invocation.  Heavy hooks (mypy, eslint full
//   project) should be configured with `--show-diff-on-failure` or
//   `pass_filenames: false` in .pre-commit-config.yaml to avoid slow runs.
//

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

function getSentinelDir() {
  return process.platform === "win32" ? os.tmpdir() : "/tmp";
}

function runPrecommit(configPath, filePath, root, timeoutMs) {
  return new Promise((resolve) => {
    const child = spawn("pre-commit", ["run", "--config", configPath, "--files", filePath], {
      cwd: root,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "",
      stderr = "";
    child.stdout.on("data", (d) => {
      stdout += d;
    });
    child.stderr.on("data", (d) => {
      stderr += d;
    });

    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ timedOut: true, stdout, stderr, status: null });
    }, timeoutMs);

    child.on("close", (code, signal) => {
      clearTimeout(timer);
      resolve({ timedOut: false, stdout, stderr, status: code, signal });
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      resolve({ error: err, stdout, stderr, status: null });
    });
  });
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", async () => {
  let crossLockAcquired = false;
  let crossLock = null;
  try {
    const data = JSON.parse(raw);
    const { hook_event_name, tool_name, tool_input, session_id } = data;

    // Only act on PostToolUse for Write or Edit
    if (hook_event_name !== "PostToolUse") process.exit(0);
    if (tool_name !== "Write" && tool_name !== "Edit") process.exit(0);

    const filePath = tool_input?.file_path;
    if (!filePath) process.exit(0);

    // Resolve project root (hooks run with CWD = project root)
    const root = process.cwd();

    // Skip files outside the project root (e.g. edits to ~/.claude/ files)
    const rel = path.relative(root, filePath);
    if (rel.startsWith("..") || path.isAbsolute(rel)) process.exit(0);

    // Skip ephemeral handover dirs — agents write subagent-handover .md files into
    // .temp/ at high volume during multi-agent workflows (e.g. /oss:review spawns
    // 7+ agents writing .md output concurrently). Linting each via pre-commit
    // serializes under the cross-session lock and can stall the orchestrator
    // for minutes while it waits for Agent() to return. These files are never
    // committed — short-circuit before lock acquisition.
    if (rel.startsWith(".temp/") || rel.startsWith(".temp" + path.sep)) process.exit(0);

    // Skip if no pre-commit config in this project
    const configPath = path.join(root, ".pre-commit-config.yaml");
    if (!fs.existsSync(configPath)) process.exit(0);

    // Deduplication lock — project and home settings.json both register this hook,
    // so two instances fire concurrently for every Edit. The second instance would
    // race pre-commit's own lock file and exit non-zero. Guard: if a lock file for
    // this exact file exists and is < 5s old, skip silently (already being linted).
    // Lock lives in the session-scoped tmpDir so it is cleaned up on SessionEnd
    // and cannot collide with other concurrent Claude sessions.
    const sid = (session_id || "default").replace(/[^a-zA-Z0-9_-]/g, "_");
    const tmpDir = path.join(getSentinelDir(), `claude-state-${sid}`);
    const sanitized = filePath.replace(/[^a-zA-Z0-9_-]/g, "_");
    const lockFile = path.join(tmpDir, `lock-lint-on-save-${sanitized}.lock`);
    try {
      const lockStat = fs.statSync(lockFile);
      if (Date.now() - lockStat.mtimeMs < 5_000) process.exit(0); // already running
    } catch (_) {} // lock absent — first instance, proceed
    try {
      fs.mkdirSync(tmpDir, { recursive: true });
      fs.writeFileSync(lockFile, String(process.pid));
    } catch (_) {}

    // Cross-session lock: one pre-commit run per project at a time.
    // Key by project root to avoid blocking unrelated projects.
    const projectHash = root.replace(/[^a-zA-Z0-9]/g, "_").slice(-40);
    crossLock = path.join(getSentinelDir(), `claude-precommit-${projectHash}.lock`);
    const CROSS_LOCK_TTL = 20_000; // 20s — covers 15s timeout + startup overhead

    try {
      const fd = fs.openSync(crossLock, "wx"); // atomic exclusive create
      fs.writeSync(fd, String(process.pid));
      fs.closeSync(fd);
      crossLockAcquired = true;
    } catch (e) {
      if (e.code === "EEXIST") {
        // Lock exists — check if stale
        try {
          const age = Date.now() - fs.statSync(crossLock).mtimeMs;
          if (age < CROSS_LOCK_TTL) {
            process.exit(0); // Another session running pre-commit — skip
          }
          // Stale lock — steal it
          fs.writeFileSync(crossLock, String(process.pid));
          crossLockAcquired = true;
        } catch (_) {
          process.exit(0); // Can't determine state — skip safely
        }
      }
    }

    // Run pre-commit on the specific file (async, 15s timeout)
    const result = await runPrecommit(configPath, filePath, root, 15_000);

    if (crossLockAcquired) {
      try {
        fs.unlinkSync(crossLock);
      } catch (_) {}
      crossLockAcquired = false;
    }

    if (result.timedOut) {
      process.exit(0); // Timeout — don't block Claude
    }

    if (result.error) {
      // Missing pre-commit binary should not block Claude.
      if (result.error.code === "ENOENT") process.exit(0);
      const errMsg = `pre-commit failed to run: ${result.error.message}`;
      const out = [result.stdout, result.stderr, errMsg].filter(Boolean).join("\n").trim();
      process.stderr.write(out);
      process.exit(2);
    }

    if (result.status !== 0) {
      const raw = [result.stdout, result.stderr].filter(Boolean).join("\n");
      if (!raw.trim()) process.exit(0); // no hooks apply to this file type — silent pass
      // Strip dot-padded progress header lines (Passed/Skipped/Failed) — only show error details.
      // Removes the long "hookname.....Result" lines that wrap in Claude Code's narrow blocking pane.
      const filtered = raw
        .split("\n")
        .filter((line) => !/\.{10,}\s*(Passed|Skipped|Failed)\s*$/.test(line))
        .join("\n")
        .trim();
      if (!filtered) process.exit(0);
      process.stderr.write(filtered);
      process.exit(2);
    }

    process.exit(0);
  } catch (_) {
    // Never block Claude — swallow all errors
    if (crossLockAcquired && crossLock) {
      try {
        fs.unlinkSync(crossLock);
      } catch (_) {}
    }
    process.exit(0);
  }
});
