---
description: Task lifecycle sequencing — TaskUpdate ordering, subagent task prohibition, spawn-prompt lead line
paths:
  - '**'
---

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

FleetView/agent-list shows leading chars of the `Agent()` prompt as each agent's description — Agent tool has no separate description field. Boilerplate-first spawn prompt → every agent reads identical useless label.

Rule: **first line = concise task label** — role + target, ≤10 words, no boilerplate. Place all boilerplate (`Task tracking:`, `Compact Instructions:`, TEAM_PROTOCOL read, run-dir preamble, envelope spec) **after** the task line.

### Fleet-view description: unique-first

N agents, same task family → description leads with per-agent delta (dir/plugin/module), shared boilerplate after. Cap 1 terminal line — front-load differentiator, FleetView truncates tail not head.

> Full detail (worked ✓/✗ spawn-prompt and FleetView-label examples) in `_full/task-lifecycle.md`. Read before composing multi-agent spawn prompts:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/task-lifecycle.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/cc_foundry/rules/_full/task-lifecycle.md"  # timeout: 5000
> ```
