## Task lifecycle sequencing

### TaskUpdate before long output

Call `TaskUpdate(status="completed")` **before** any long output block (audit report, calibration summary, release notes, multi-item list). Tool calls placed after long output block may never execute if context compaction fires mid-response, leaving tasks permanently "in_progress".

Correct sequence: `TaskUpdate(completed)` → emit output. Wrong: emit output → `TaskUpdate(completed)`.

### Subagent task prohibition

Tasks created inside subagents are session-local — invisible in parent `TaskList`. Never useful for tracking.

Subagents must NOT call `TaskCreate` or `TaskUpdate`. Orchestrator creates all tasks before first `Agent()` spawn.

Subagent spawn prompts must include:

```text
Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state.
```

Orchestrator: mark each teammate's task `completed` as its delta arrives — never batch at session end.

### Spawn-prompt lead line

FleetView/agent-list shows leading chars of the `Agent()` prompt as each agent's description — Agent tool has no separate description field. Boilerplate-first spawn prompt → every agent reads identical useless label (e.g. "Task tracking: do NOT call TaskCreate or TaskUpdat…").

Rule: **first line = concise task label** — role + target, ≤10 words, no boilerplate. Place all boilerplate (`Task tracking:`, `Compact Instructions:`, TEAM_PROTOCOL read, run-dir preamble, envelope spec) **after** the task line.

```text
✓  foundry:sw-engineer — fix token-expiry off-by-one in auth/middleware.py
   Read ${HOME}/.claude/TEAM_PROTOCOL.md — AgentSpeak v2. …
   Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. …

✗  Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state.
   You are a foundry:sw-engineer teammate fixing … [label now useless]
```
