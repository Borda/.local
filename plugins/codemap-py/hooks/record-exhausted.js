#!/usr/bin/env node
// record-exhausted.js — PostToolUse(Bash) hook.
// When a `scan-query rdeps <module>` / `fn-rdeps <module>::<fn>` call returns a
// complete result (`query_complete: true` — the import graph is authoritative and
// complete for this global-in query; `exhaustive` is the legacy alias), record the
// module in a per-session sentinel. Matches every real emitted form: quoted or
// unquoted args, the `$SQ` / resolved-binary fallback (query-code SKILL.md), and
// interposed flags like `--timeout 5` (develop codemap-context.md).
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
    input = JSON.parse(fs.readFileSync(0, "utf8"));
  } catch {
    process.exit(0);
  }

  const cmd = String(input?.tool_input?.command || "");
  // Gate: command must invoke scan-query in some real form — the literal binary, a
  // resolved path ending in scan-query, or the `$SQ` fallback var (query-code SKILL.md).
  if (!/\bscan-query\b|\$SQ\b/.test(cmd)) process.exit(0);
  // Capture the exhausting subcommand (`rdeps` or `fn-rdeps`) and its first positional
  // arg. Tolerates quoted/unquoted args and a `module::function` qname for fn-rdeps.
  // Interposed flags (`--timeout 5`) sit before the subcommand, so they don't interfere.
  const m = cmd.match(/\b(?:fn-)?rdeps\s+["']?([A-Za-z0-9_.]+(?:::[A-Za-z0-9_.]+)?)["']?/);
  if (!m) process.exit(0);

  // tool_response is the Bash stdout — string or object depending on Claude Code version.
  const resp =
    typeof input.tool_response === "string" ? input.tool_response : JSON.stringify(input.tool_response || "");
  // Forward field is `query_complete` (direction-scoped); `exhaustive` is the legacy
  // alias emitted byte-compatibly for one deprecation cycle. Match either so the
  // sentinel arms whether the reader is on the old or new field.
  if (!/"(?:query_complete|exhaustive)"\s*:\s*true/.test(resp)) process.exit(0);

  // For fn-rdeps the arg is `module::function`; record the module portion — the guard
  // operates on module names when blocking redundant import-greps.
  const dotted = m[1].split("::")[0];
  const slashed = dotted.replace(/\./g, "/");
  try {
    fs.appendFileSync(sentinelPath(input.session_id), `${dotted}\n${slashed}\n`);
  } catch {
    /* best-effort — never block */
  }
  process.exit(0);
}

main();
