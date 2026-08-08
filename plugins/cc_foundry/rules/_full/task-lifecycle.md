## Task lifecycle sequencing — worked examples

Full detail behind the `rules/task-lifecycle.md` stub — spawn-prompt lead-line convention and FleetView description examples. Rules themselves (TaskUpdate-before-long-output, subagent task prohibition, lead-line/unique-first constraints) live in the stub, always loaded — this file is illustration only.

### Spawn-prompt lead line

FleetView/agent-list shows leading chars of the `Agent()` prompt as each agent's description — Agent tool has no separate description field. Boilerplate-first spawn prompt → every agent reads identical useless label (e.g. "Task tracking: do NOT call TaskCreate or TaskUpdat…").

```text
✓  foundry:sw-engineer — fix token-expiry off-by-one in auth/middleware.py
   Read ${HOME}/.claude/TEAM_PROTOCOL.md — AgentSpeak v2. …
   Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. …

✗  Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state.
   You are a foundry:sw-engineer teammate fixing … [label now useless]
```

### Fleet-view description: unique-first

N agents, same task family → description leads with per-agent delta (dir/plugin/module), shared boilerplate after. Cap 1 terminal line — front-load differentiator, FleetView truncates tail not head.

```text
✓  B1 — cc_develop: session-scope TMPDIR sentinels
✓  B2 — cc_foundry: session-scope TMPDIR sentinels

✗  B1 — session-scope TMPDIR sentinels in plugins/cc_...
✗  B2 — session-scope TMPDIR sentinels in plugins/cc_...  [same prefix, rows indistinguishable]
```
