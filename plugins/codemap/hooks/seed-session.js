#!/usr/bin/env node
// seed-session.js — SessionStart hook: seed the per-project session tmpfile.
// Without this, the codemap CLI (scan-query) only got a session id when a
// `codemap:*` skill ran first (log-skill-start.js wrote the tmpfile). CLI-only
// usage — the common path, since /oss and /develop gates call scan-query but are
// not codemap: skills — left every cli.jsonl record with "session":"".
// Seeding here writes the real Claude session_id once per session so both the
// CLI and skill layers join on the same key.

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");
const { execFileSync } = require("child_process");

function projName(cwd) {
  // Match scan-query _log_session(): git-root basename, fallback cwd basename.
  try {
    const root = execFileSync("git", ["rev-parse", "--show-toplevel"], {
      cwd,
      timeout: 2000,
      stdio: ["ignore", "pipe", "ignore"],
    })
      .toString()
      .trim();
    if (root) return path.basename(root);
  } catch {
    /* not a git repo */
  }
  return path.basename(cwd);
}

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));
  } catch {
    process.exit(0);
  }

  const sid = String(input.session_id || "").trim();
  if (!sid) process.exit(0);

  const cwd = process.cwd();
  const sidFile = path.join(os.tmpdir(), `codemap-${projName(cwd)}-session`);

  try {
    fs.writeFileSync(sidFile, sid, { flag: "w" });
  } catch {
    /* best-effort — never block session start */
  }

  process.exit(0);
}

main();
