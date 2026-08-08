# debugging/ — session cost analysis

Read-only scripts that answer "where did the money go" from Claude Code transcripts in `~/.claude/projects/<project-slug>/<session-id>.jsonl`. They touch nothing but those files, take no credentials, and print to stdout.

Built while investigating a `/oss:review` that cost ~$45. Findings and follow-ups live in [`.plans/active/todo_efficiency-audit-remainder.md`](../.plans/active/todo_efficiency-audit-remainder.md).

## The trap these scripts exist to avoid

Claude Code writes **one JSONL row per content block**, and every row of the same assistant message repeats that message's `usage` object. Summing rows therefore multiplies the answer by the average block count — on a real session that read **$61.21 where the truth was $20.56**, a 3× inflation.

`_usage.parse()` deduplicates by `message.id`. Any new analysis must do the same.

## Scripts

| Script                       | Question it answers                                                                        |
| ---------------------------- | ------------------------------------------------------------------------------------------ |
| `fanout_scan.py`             | Which sessions and which skills actually drive spend? Start here.                          |
| `session_cost.py`            | Where did one session's money go — main vs subagent, by model tier?                        |
| `turn_profile.py`            | Within one session: context re-sent per call, cache rebuilds, growth curve.                |
| `classify_resolver_sites.py` | Of the real resolver-script call sites in a plugin, which are safely cat-only extractable? |
| `_usage.py`                  | Shared parsing, deduplication and pricing. Not a CLI.                                      |

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

# 5. classify resolver-script call sites in a plugin (unrelated question, same directory)
python debugging/classify_resolver_sites.py plugins/cc_foundry --list-extractable
```

Run from the repo root; the scripts import `_usage` from their own directory.

## Two limits to state before quoting any number

**Subagent spend is absent from the flat `<session-id>.jsonl` only.** It contains zero `isSidechain` rows, so a total read from that file alone is a **main-loop floor**. `session_cost.py` prints a warning whenever it sees spawns but no sidechain rows. The real per-agent data does exist, one directory over: `<session-id>/subagents/<agent-id>.jsonl`, one file per spawn, parseable by `_usage.parse()` unchanged. Read 2026-08-08 across 116 subagent transcripts in 3 sessions: minimum total tokens for one agent's full run was 114,855–536,700 depending on session (the floor when an agent's task was trivial corroborates the earlier ~120,851 tok/agent estimate rather than overturning it); first-call boot size (system prompt + rules + tool schemas, before any task work) held to a tighter 27,332–58,603 band, median ~40,000–50,000 across all three. Measured subagent share for one session was ~56% of that session's total spend ($792 subagent vs $610 main-loop) — matching the earlier arithmetic-inferred ~55%, now sourced instead of inferred.

**Prices are public list rates**, hard-coded in `_usage.PRICES`. The transcript records tokens only. Effective plan rates may differ, so treat dollar figures as proportional truth — the *shares* are solid, the absolute totals are an assumption.

## What the numbers showed

- **Cache read is ~50% of main-loop cost** — context size × turn count. Halving turns is worth as much as halving context.
- **Cache writes concentrate in cold starts.** Two calls — session open and one mid-run `/clear` — carried 74% of all rebuild tokens. Writes price at 12.5× reads, which is why the guidance is `/compact`, never `/clear`: compaction pays the same rebuild once and then shrinks every later turn, while clearing rebuilds the same size and returns nothing.
- **Usage ranking beat intuition.** `/oss:resolve` had run 102 times to `/oss:review`'s 70, while the research plugin — queued for the same optimisation — had been invoked once.
- **`/compact` breaks even fast, not at ~14 turns.** Measured across 41 real compactions in 5 sessions (drop-detection: a compaction is any call whose post-call context falls below 70% of the prior call's): median rebuild cost $0.87, median break-even ~2 turns, worst observed 14. All 41 repaid before their session ended.

## Tests

Pure functions carry doctests; there is no separate suite yet.

```bash
cd debugging && python -m doctest _usage.py session_cost.py turn_profile.py fanout_scan.py classify_resolver_sites.py
```

Silence means pass.
