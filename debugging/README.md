# debugging/ — session cost analysis

Read-only scripts that answer "where did the money go" from Claude Code transcripts in `~/.claude/projects/<project-slug>/<session-id>.jsonl`. They touch nothing but those files, take no credentials, and print to stdout.

Built while investigating a `/oss:review` that cost ~$45. Findings and follow-ups live in [`.plans/active/todo_efficiency-audit-remainder.md`](../.plans/active/todo_efficiency-audit-remainder.md).

## The trap these scripts exist to avoid

Claude Code writes **one JSONL row per content block**, and every row of the same assistant message repeats that message's `usage` object. Summing rows therefore multiplies the answer by the average block count — on a real session that read **$61.21 where the truth was $20.56**, a 3× inflation.

`_usage.parse()` deduplicates by `message.id`. Any new analysis must do the same.

## Scripts

| Script            | Question it answers                                                         |
| ----------------- | --------------------------------------------------------------------------- |
| `fanout_scan.py`  | Which sessions and which skills actually drive spend? Start here.           |
| `session_cost.py` | Where did one session's money go — main vs subagent, by model tier?         |
| `turn_profile.py` | Within one session: context re-sent per call, cache rebuilds, growth curve. |
| `_usage.py`       | Shared parsing, deduplication and pricing. Not a CLI.                       |

## Usage

```bash
# 1. find the expensive sessions across every project
python debugging/fanout_scan.py ~/.claude/projects --sort cost --limit 15

# 2. rank skills by how often they run and what they spawn
python debugging/fanout_scan.py ~/.claude/projects --commands

# 3. break down one session
python debugging/session_cost.py ~/.claude/projects/<slug>/<session-id>.jsonl

# 4. profile it call by call — finds cache rebuilds and context growth
python debugging/turn_profile.py ~/.claude/projects/<slug>/<session-id>.jsonl --top 15
```

Run from the repo root; the scripts import `_usage` from their own directory.

## Two limits to state before quoting any number

**Subagent spend is not in the transcript.** Sessions that spawned 11 agents contain zero `isSidechain` rows, so every total here is a **main-loop floor**. On the measured review the missing subagent share was ~55% of the true bill, inferred by arithmetic ($45 reported − $20.56 measured ≈ $2.2 per agent) and cross-checked against an independently measured ~120,851 tok/agent. `session_cost.py` prints a warning whenever it sees spawns but no sidechain rows.

**Prices are public list rates**, hard-coded in `_usage.PRICES`. The transcript records tokens only. Effective plan rates may differ, so treat dollar figures as proportional truth — the *shares* are solid, the absolute totals are an assumption.

## What the numbers showed

- **Cache read is ~50% of main-loop cost** — context size × turn count. Halving turns is worth as much as halving context.
- **Cache writes concentrate in cold starts.** Two calls — session open and one mid-run `/clear` — carried 74% of all rebuild tokens. Writes price at 12.5× reads, which is why the guidance is `/compact`, never `/clear`: compaction pays the same rebuild once and then shrinks every later turn, while clearing rebuilds the same size and returns nothing.
- **Usage ranking beat intuition.** `/oss:resolve` had run 102 times to `/oss:review`'s 70, while the research plugin — queued for the same optimisation — had been invoked once.

## Tests

Pure functions carry doctests; there is no separate suite yet.

```bash
cd debugging && python -m doctest _usage.py session_cost.py turn_profile.py fanout_scan.py
```

Silence means pass.
