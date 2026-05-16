# Campaign Report Format — run/SKILL.md sidecar

Loaded by Step R6 at end of campaign run.
Report structure and terminal summary format.

## Report structure

```markdown
---
Run — [goal]
Date:        [YYYY-MM-DD]
Scope:       [program.md path] / [N] iterations planned
Focus:       ML optimization run
Agents:      research:scientist (per iteration)
Outcome:     GOAL_ACHIEVED | IMPROVED | STALLED | DIVERGED
Best:        [metric_key] = [best] ([delta]% improvement)
Confidence:  [score] — [key gaps]
Next steps:  /research:retro | /research:fortify | /research:run --resume
Path:        → .reports/research/run-<branch>-<date>.md
---

## Run: <goal>

**Run ID**: <run-id>
**Date**: <date>
**Iterations**: <total> (<kept> kept, <reverted> reverted, <other> other)
**Baseline**: <metric> = <baseline value>
**Best**: <metric> = <best value> (<delta>% improvement)
**Best commit**: <sha>
**Diary**: ".experiments/state/<run-id>/diary.md"
**Codex co-pilot**: active (ran every iteration) — <N> Codex passes run (omit line if --codex not used)
**Codex wins**: <N> Codex proposals kept vs <N> Claude proposals kept

### Experiment History

| #   | Metric | Delta  | Status   | Description | Agent | Confidence |
| --- | ------ | ------ | -------- | ----------- | ----- | ---------- |
| N   | value  | +X.X%  | status   | desc        | agent | 0.N        |

### Summary
[2-3 sentences on what strategies worked, what didn't, what to try next]

### Recommended Follow-ups
- [next action]
```

## Terminal summary format

```text
---
Run — <goal>
Iterations: <total>  Kept: <kept>  Reverted: <reverted>
Baseline:   <metric_key> = <baseline>
Best:       <metric_key> = <best> (<delta>% improvement, commit <sha>)
Agent:      <agent type used>
→ saved to .reports/research/run-<branch>-<date>.md
→ diary: .experiments/state/<run-id>/diary.md
---
```
