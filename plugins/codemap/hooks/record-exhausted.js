#!/usr/bin/env node
// record-exhausted.js — PostToolUse(Bash) hook.
// When a `scan-query rdeps <module>` call returns an exhaustive result (the import
// graph is authoritative and complete), record the module in a per-session sentinel.
// guard-redundant-scan.js then blocks any later import-grep for that same module —
// re-grepping an exhaustive caller set is the dominant wasted-token pattern (benchmark:
// 40/48 codemap runs grepped after the skill already answered; haiku looped to 2M+
// input tokens at erec=0). Fail-open: any error exits 0 so a broken hook never blocks work.

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

function sentinelPath(sessionId) {
  const key = String(sessionId || "").trim() || "nosession";
  return path.join(os.tmpdir(), `codemap-exhausted-${key}`);
}

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync("/dev/stdin", "utf8"));
  } catch {
    process.exit(0);
  }

  const cmd = String(input?.tool_input?.command || "");
  const m = cmd.match(/scan-query\s+rdeps\s+([A-Za-z0-9_.]+)/);
  if (!m) process.exit(0);

  // tool_response is the Bash stdout — string or object depending on Claude Code version.
  const resp =
    typeof input.tool_response === "string" ? input.tool_response : JSON.stringify(input.tool_response || "");
  if (!/"exhaustive"\s*:\s*true/.test(resp)) process.exit(0);

  const dotted = m[1];
  const slashed = dotted.replace(/\./g, "/");
  try {
    fs.appendFileSync(sentinelPath(input.session_id), `${dotted}\n${slashed}\n`);
  } catch {
    /* best-effort — never block */
  }
  process.exit(0);
}

main();
