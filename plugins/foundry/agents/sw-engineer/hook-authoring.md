<!-- Loaded by foundry:sw-engineer (opus + xhigh) -->
# Hook Authoring (foundry:sw-engineer specialized guidance)

Read this file only when working on hook code (JavaScript files under `.claude/hooks/`, hook registrations in `settings.json`, `PostToolUse`/`PreToolUse`/`SubagentStop` event handlers). Skip for Python implementation tasks.

Hook authoring and editing owned exclusively by `foundry:sw-engineer` (per curator NOT-for boundary — curator does not touch hook files). `foundry:curator` reviews hook-adjacent markdown config files only. For hook creation or modification, `foundry:sw-engineer` owns the work end-to-end.

## File Header Structure

Every hook file must start with:

```js
#!/usr/bin/env node
 // <filename>.js — <HookType> hook  ← the word `hook` is literal, not a placeholder
//
// PURPOSE
//   <one-paragraph description of what this hook does and why>
//
// HOW IT WORKS
//   1. <step>
//   2. <step>
//   ...
//
// EXIT CODES
//   0  <success case>
//   2  <feedback case — Claude Code shows output and Claude acts on it>
```

Subsection order: `PURPOSE` → `HOW IT WORKS` → `EXIT CODES` (add others like `HOOK EVENT RESPONSIBILITIES` as needed).
`HOW IT WORKS` may not be omitted even for simple hooks — use at least one numbered step.

## Exit Code Rules

- **Always exit 0 on unexpected errors** — hooks must never crash or block Claude due to hook bug
- **Exit 2 to surface feedback** — Claude Code shows exit-2 output to Claude, which acts on it
- **Exit 2 only when Claude caused condition and can fix it** (e.g. file it wrote failed linting). Use exit 0 for all environmental conditions: missing tools, missing config files, unexpected input formats.
- Exit 1 not used; Claude Code maps it to exit 2 behavior (hooks not wired to git pre-commit)

## Implementation Pattern

- CommonJS: `require()` imports, stdin JSON parse, `process.exit()`
- **Only permitted stdin pattern** — use event-based accumulation; do not use `fs.readFileSync("/dev/stdin")` or any synchronous stdin read:
  ```js
  let raw = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (d) => (raw += d));
  process.stdin.on("end", () => {
      const data = JSON.parse(raw);
      // ... handler logic
  });
  ```
- Wrap all logic in try/catch; catch behaviour depends on hook type:
  - **PreToolUse gatekeeper hooks** (those that emit `permissionDecision`): catch → `process.exit(1)` — erroring gatekeeper must **block**, not allow. Mapping: `exit(1)` = blocked, `exit(0)` = allowed. Allowing a tool call when the gate logic crashed is a security bypass.
  - **Logging hooks** (PostToolUse, SubagentStop, observational PreToolUse without decision output): catch → `process.exit(0)` — silent-swallow acceptable; logging hooks must not interfere with Claude's execution.
- Use `execFileSync` or `spawnSync` (not `execSync` with shell strings) for subprocess calls — both take args array, avoiding shell injection. Use `execFileSync` when command MUST succeed (throws on non-zero exit, use in try/catch). Use `spawnSync` when need to inspect result code (returns `{status, stdout, stderr}`, does not throw).

## PreToolUse Decision Output

When `PreToolUse` hook needs to approve or block tool call, use `hookSpecificOutput` (current format):

```json
{
  "hookSpecificOutput": {
    "permissionDecision": "allow",
    "permissionDecisionReason": "optional explanation shown to user"
  }
}
```

- `permissionDecision`: `"allow"` or `"block"` — use `"block"` to prevent tool call
- **Deprecated**: top-level `"decision"` and `"reason"` fields — still work but may be removed in future Claude Code release; migrate to `hookSpecificOutput`
- Most hooks need no decision output — only emit when hook acts as gatekeeper

## PostToolUse and SubagentStop Hooks

Logging hooks (timing, file-writes, audit trails) need no output — exit 0 silently.
Never emit to stdout from logging hook; unexpected output can interfere with Claude's tool result handling.

- `PostToolUse` receives tool result payload on stdin — use for timing deltas, logging tool output size, or writing audit records
- `SubagentStop` fires when spawned agent completes — use to clean up per-agent state files (e.g. `/tmp/claude-state-<session>/agents/<id>.json`)
- Both hook types: wrap all logic in try/catch; catch → `process.exit(0)` always

## Anti-patterns

- **Prohibited**: `execSync` with shell string — shell injection risk; takes raw string parsed by `/bin/sh`. Use `execFileSync(cmd, argsArray)` or `spawnSync(cmd, argsArray)` instead.
