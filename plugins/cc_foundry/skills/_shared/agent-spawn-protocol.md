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

## Resume vs fresh spawn — context cost discipline

`SendMessage({to: <agentId>})` resumes an agent from its **full prior transcript** — every follow-up round re-sends everything the agent ever read/wrote, so cost grows with the transcript, not the new task (observed: a 4th follow-up round on an accumulated agent cost ~650K subagent tokens vs ~200K for the same-scope task run as a fresh spawn). It also risks the agent reasoning off stale context from earlier rounds instead of current on-disk state.

**Default: one task, one spawn.** When a spawned agent finishes and reports its result, treat it as done — do not keep it around "in case." A new, independent follow-up task (even on the same files, even moments later) gets a **fresh** `Agent()` call with a self-contained prompt: current file paths + the specific task, not a reference to "what you just did." The fresh agent re-reads current on-disk state itself, which is also strictly more correct than trusting a stale in-context copy.

**When resume is actually right**: genuinely sequential/incremental work where the agent's own accumulated reasoning state is the point (e.g. an iterative refinement loop the agent is mid-way through, or a multi-part task deliberately split into hand-offs to keep each turn's prompt small). Even then, each hand-off must compact hard — send only the delta/new instruction, never re-paste prior findings the agent already has in its transcript — so the resumed context doesn't balloon with repeated, increasingly outdated material across rounds.

- If unsure whether a follow-up is "the same task continuing" or "a new independent task" — default to fresh. A fresh spawn that re-derives something the old agent already knew is far cheaper than an old agent quietly reasoning off page-3 assumptions that page-40 already invalidated.

## Rules

- Never omit the timed-out signal (⏱) — surface partial results always
- Rely on the harness completion notification, not a busy-wait loop
- New independent follow-up task → fresh `Agent()` spawn, not `SendMessage`-resume (see above)
- Canonical reference: CLAUDE.md §6
