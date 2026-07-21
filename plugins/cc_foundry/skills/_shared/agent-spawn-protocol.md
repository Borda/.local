# Agent Spawn Protocol — Health Monitoring (CLAUDE.md §6)

Reference from any skill that spawns agents — resolve `$_FOUNDRY_SHARED` and load in the same bash block:
```bash
cat "$_FOUNDRY_SHARED/agent-spawn-protocol.md"
```
Apply monitoring for `<skill-name>` run.

Claude Code harness runs one Bash call at a time (max ~10 min per call, foreground `sleep` blocked). Skill therefore **cannot** sit in a `while true; do sleep … done` poll loop waiting on a background agent — that loop never runs. Monitoring is event-driven and post-hoc, not a busy-wait.

## Background spawns — `Agent(..., run_in_background=true)`

1. Harness delivers a **completion notification** when the background agent finishes — the primary liveness signal. Act on it when it arrives; do not block waiting for it.
2. Optional between-turn liveness: the `Monitor` tool, or a **single** `health_sentinel.py` probe per turn (one `find` call, no sleep loop) — see §8b.
3. On completion: read the agent's output file. Empty or missing after completion → mark `timed_out` with ⏱ and record `{"verdict":"timed_out"}`; never silently omit a stalled agent.

## Synchronous spawns — blocking `Agent(...)`

A blocking `Agent()` call returns only when the agent finishes; no polling possible or needed. After it returns, read the agent's output file. Empty or missing → `timed_out`, surface with ⏱.

## §8b health_sentinel.py liveness helper (optional)

For a single between-turn liveness probe on a background run, `health_sentinel.py` validates run dir and emits a quoted sentinel path:

```bash
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_foundry}/bin/health_sentinel.py" start <SKILL>-<ID> 2>/dev/null)"  # timeout: 5000
[ -n "$SENTINEL" ] || printf "⚠ health monitoring disabled — health_sentinel.py missing or failed\n"
```

Later (a separate Bash call — e.g. after a completion notification), probe progress: `find <output-dir> -newer "$SENTINEL" -name "<glob>" | wc -l` — new files since sentinel = progress. Shell state does not persist across Bash calls, so persist the sentinel path to a file if a later turn needs it.

## Rules

- Never omit the timed-out signal (⏱) — surface partial results always
- Rely on the harness completion notification, not a busy-wait loop
- Canonical reference: CLAUDE.md §6
