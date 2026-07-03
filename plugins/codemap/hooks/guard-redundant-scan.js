#!/usr/bin/env node
// guard-redundant-scan.js — PreToolUse(Bash) hook.
// Denies an import-discovery grep when codemap has already returned the EXHAUSTIVE caller
// set for that module this session (recorded by record-exhausted.js). The index is
// authoritative when exhaustive, so re-grepping it is pure wasted tokens — and on weak
// models it triggers verify-loops that burn 2M+ input tokens at erec=0.
//
// Scope is narrow by design (the upgrade path if it ever false-blocks):
//   - only fires on import-discovery greps (grep/rg + import/from) — NOT source reads
//   - only for a module already marked exhaustive THIS session (no sentinel → allow)
//   - fail-open: any error or missing sentinel exits 0 (allow)
// Naturally inert in non-codemap arms/sessions: no scan-query → no sentinel → no denial.
// Disable: remove the PreToolUse(Bash) entry for this script from hooks/hooks.json.

"use strict";

const fs = require("fs");
const path = require("path");
const os = require("os");

// Same import-discovery signature the benchmark uses for `bash_for_imports`.
const IMPORT_GREP = /\b(grep|rg)\b.*\bimport\b|\b(grep|rg)\b.*\bfrom\b|\bimport\b.*-r\b/;

function sentinelPath(sessionId) {
  const key = String(sessionId || "").trim() || "nosession";
  return path.join(os.tmpdir(), `codemap-exhausted-${key}`);
}

function deny(reason) {
  process.stdout.write(
    JSON.stringify({
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: reason,
      },
    }),
  );
  process.exit(0);
}

function main() {
  let input;
  try {
    input = JSON.parse(fs.readFileSync(0, "utf8"));
  } catch {
    process.exit(0);
  }

  const cmd = String(input?.tool_input?.command || "");
  if (!IMPORT_GREP.test(cmd)) process.exit(0);

  let modules;
  try {
    modules = fs
      .readFileSync(sentinelPath(input.session_id), "utf8")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  } catch {
    process.exit(0); // no sentinel = nothing answered exhaustively yet → allow
  }

  const hit = modules.find((mod) => cmd.includes(mod));
  if (hit) {
    deny(
      `codemap already returned the EXHAUSTIVE caller set for ${hit.replace(/\//g, ".")} this session. ` +
        `Re-grepping is disabled — the import-graph index is authoritative. Use the codemap result and write your answer.`,
    );
  }
  process.exit(0);
}

main();
