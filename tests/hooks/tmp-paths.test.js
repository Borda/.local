// Smoke test: verify no literal /tmp/ paths remain in foundry hook source code.
// Run from repo root: node tests/hooks/tmp-paths.test.js
"use strict";

const assert = require("node:assert");
const fs = require("fs");
const path = require("path");

const HOOKS_DIR = path.join(__dirname, "..", "..", "plugins", "cc_foundry", "hooks");
const hooks = [
  "task-log.js",
  "commit-guard.js",
  "md-compress.js",
  "agent-router.js",
  "lint-on-save.js",
  "statusline.js",
];

for (const h of hooks) {
  const src = fs.readFileSync(path.join(HOOKS_DIR, h), "utf8");
  // Strip block and line comments before checking so getSentinelDir body
  // ('/tmp' fallback value) does not trigger a false positive.
  const code = src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");

  assert.ok(!code.includes('"/tmp/'), `${h}: double-quoted /tmp/ found in code`);
  assert.ok(!code.includes("`/tmp/"), `${h}: template-literal /tmp/ found in code`);
  console.log(`PASS ${h}`);
}

console.log(`\nAll ${hooks.length} hooks clean.`);
process.exitCode = 0;
