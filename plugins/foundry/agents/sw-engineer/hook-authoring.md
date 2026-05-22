<!-- Loaded by foundry:sw-engineer (opus + high) -->
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
//   1  <error case — blocking hooks: blocks Claude execution; non-blocking hooks: logged as error only, does NOT block>
//   2  <feedback case — Claude Code shows output and Claude acts on it>
```

Subsection order: `PURPOSE` → `HOW IT WORKS` → `EXIT CODES` (add others like `HOOK EVENT RESPONSIBILITIES` as needed).
`HOW IT WORKS` may not be omitted even for simple hooks — use at least one numbered step.

### Minimal exit-code template (always pair success + error paths)

```bash
# success path
exit 0

# error path
echo "Error: <message>" >&2
exit 1
```

Every hook must explicitly handle the error path — never leave it implicit. For blocking hooks (`exit 1` = block), the message on stderr surfaces to the user; for non-blocking hooks, it is logged but does not stop execution.

## Exit Code Rules

Exit 1 behavior depends on hook type — do not use exit 1 uniformly:

| Hook type | exit 0 | exit 1 | exit 2 |
| --- | --- | --- | --- |
| **Blocking** (UserPromptSubmit, PreToolUse gatekeeper, PreCompact) | allow / proceed | **blocks Claude execution** | show output to Claude; Claude acts on it |
| **Non-blocking** (PostToolUse, Stop, SubagentStop, SubagentStart, observational PreToolUse) | proceed | logged as error only — does **NOT** block execution | show output to Claude; Claude acts on it |

- **Blocking hooks** (those that emit `permissionDecision`): exit 1 to block; exit 0 to allow
- **Non-blocking/logging hooks**: exit 0 always on unexpected errors — exit 1 is logged but does not stop Claude; hooks must never crash or interfere with execution due to hook bug
- **Exit 2 to surface feedback** — Claude Code shows exit-2 output to Claude, which acts on it
- **Exit 2 only when Claude caused condition and can fix it** (e.g. file it wrote failed linting). Use exit 0 for environmental conditions: missing tools, missing config files, unexpected input formats.

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
- Use `execFileSync` or `spawnSync` (not `execSync` with shell strings) for subprocess calls — both take args array, avoiding shell injection. Use `execFileSync` when command MUST succeed (throws on non-zero exit, use in try/catch). Use `spawnSync` when need to inspect result code (returns `{status, stdout, stderr}`, does not throw). **Always pass `{ maxBuffer: 10 * 1024 * 1024 }` (10 MB) to `execFileSync`** — default buffer is 1 MB; subprocess producing unbounded output (e.g. large lint run) will hang or crash the Claude Code session without this cap.

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
- `SubagentStop` fires when spawned agent completes — use to clean up per-agent state files (e.g. `/tmp/claude-state-<session>/agents/<id>.json`) (harness-managed path: `${TMPDIR:-/tmp}/claude-state-<session-id>`; not user-configurable)
- Both hook types: wrap all logic in try/catch; catch → `process.exit(0)` always

## Anti-patterns

- **Prohibited**: `execSync` with shell string — shell injection risk; takes raw string parsed by `/bin/sh`. Use `execFileSync(cmd, argsArray)` or `spawnSync(cmd, argsArray)` instead.
