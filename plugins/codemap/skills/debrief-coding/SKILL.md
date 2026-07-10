---
name: debrief-coding
description: Read local codemap telemetry logs and produce a diagnostic/usage report. Supports date filtering, session filtering, and optional anonymization before sharing. TRIGGER when: analyse recent codemap usage, debug query patterns, investigate errors, or prepare a shareable anonymized report of how codemap skills and CLI are being used.
allowed-tools: Read, Write, Bash, Glob
model: haiku
effort: low
---

<objective>

Reads `.cache/codemap/logs/` JSONL telemetry, analyses usage patterns, and writes a diagnostic report.

NOT for: validating codemap installation health or integration (use `/codemap:integration check`); building or querying the structural index (use `/codemap:scan-codebase` or `/codemap:query-code`).

</objective>

<workflow>

## Flags

- `--since <YYYY-MM-DD>` — filter to records on or after this date (default: all)
- `--session <id>` — filter to a single session UUID
- `--anonymize` — run `anonymize.py` on both log files before reading; replaces qualified names with stable pseudonyms; keeps salt in `.cache/codemap/logs/.salt` (never included in output)
- `--output <path>` — write report to this path (default: `.reports/codemap/debrief-<YYYY-MM-DD>.md`)

## Step 0: Verify logs exist

```bash
ls .cache/codemap/logs/*.jsonl 2>/dev/null  # timeout: 5000
```

No files → stop: "No codemap telemetry found. Run any `/codemap:*` skill or `scan-query` command to start collecting logs."

Telemetry is **sharded per session** (`_telemetry.py` + `log-skill-start.js` + `log-tool-use.js`): CLI records land in `cli_<session>.jsonl`, skill records in `skills_<session>.jsonl`, and Grep/Read/Glob records in `tools_<session>.jsonl`; runs with no seeded session id fall back to unsuffixed `cli.jsonl` / `skills.jsonl` / `tools.jsonl`. Collect **all** matching files, not just the legacy names:

```bash
CLI_LOGS=$(ls .cache/codemap/logs/cli_*.jsonl .cache/codemap/logs/cli.jsonl 2>/dev/null)  # timeout: 5000
SKILLS_LOGS=$(ls .cache/codemap/logs/skills_*.jsonl .cache/codemap/logs/skills.jsonl 2>/dev/null)  # timeout: 5000
TOOLS_LOGS=$(ls .cache/codemap/logs/tools_*.jsonl .cache/codemap/logs/tools.jsonl 2>/dev/null)  # timeout: 5000
```

## Step 1: Optionally anonymize

If `--anonymize` flag given:

**Guard**: anonymize every present shard — never assume the legacy `cli.jsonl` / `skills.jsonl` exist (per-session sharding means they usually don't). Loop over the `$CLI_LOGS` / `$SKILLS_LOGS` sets from Step 0, writing a `-anon` sibling per file; do not mix anonymized and original data in Step 2.

```bash
for f in .cache/codemap/logs/cli_*.jsonl .cache/codemap/logs/cli.jsonl \
         .cache/codemap/logs/skills_*.jsonl .cache/codemap/logs/skills.jsonl \
         .cache/codemap/logs/tools_*.jsonl .cache/codemap/logs/tools.jsonl; do
    [ -f "$f" ] || continue
    python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/anonymize.py" \
        --input "$f" --output "${f%.jsonl}-anon.jsonl"  # timeout: 15000
done
```

If neither set has any file: print `⚠ --anonymize: no CLI or skill logs found — cannot produce anonymized report.` and stop. If only one layer is present, anonymize it and note the gap.

Use the `-anon` variants as source in Step 2. If anonymize.py not found, warn and proceed with originals.

## Step 2: Read log files

Read **every** CLI shard (`cli_*.jsonl` plus legacy `cli.jsonl`), **every** skill shard (`skills_*.jsonl` plus legacy `skills.jsonl`), and **every** tool shard (`tools_*.jsonl` plus legacy `tools.jsonl`) with the Read tool — use the `$CLI_LOGS` / `$SKILLS_LOGS` / `$TOOLS_LOGS` lists from Step 0 (or the `-anon` siblings when anonymized). Concatenate their records before analysing; a single-file read misses all per-session shards and reports a near-empty dataset.

Each line is one JSON record. Filter by `--since` (compare `ts` field) and `--session` if given.

**`--session` guard**: when `--session <id>` given, a session UUID may be absent from one or both log files (e.g., skills.jsonl records only skill events, not all CLI events). Filtering an absent session ID returns an empty set for that file — this is expected, not an error. Report "session not found in <file>" rather than treating empty result as a data loss.

CLI record fields: `ts`, `layer`, `session`, `cmd`, `argv`, `result` (nested: `count`, `exhaustive`, `stale`, `method`, `not_covered`, `error`), `timing_ms`, `stderr` (optional), `exit_code` (optional).

Skill record fields: `ts`, `layer`, `session`, `skill`, `event`, `intent`, `hook_session`.

Tool record fields (`layer: "tool"`, from `log-tool-use.js`): `ts`, `layer`, `session`, `tool` (`Grep`|`Read`|`Glob`), `target` (Grep/Glob pattern or search path, Read file_path). These count raw grep/read volume per session — the signal codemap's context-injection aims to reduce.

## Step 3: Analyse

Compute from filtered records:

**CLI layer:**
- Total invocations, success vs error rate — `exit_code: 0` means the tool ran cleanly (success); `exit_code` present AND non-zero = error; `exit_code` absent = field not logged (treat as success unless `result.error` non-empty)
- Subcommand distribution: count per `cmd` value
- Timing: median, p95, max `timing_ms`; compute p95 as sorted index: `sorted_ms = sorted(r["timing_ms"] for r in cli_records if r.get("timing_ms") is not None); p95 = sorted_ms[int(len(sorted_ms) * 0.95)] if sorted_ms else 0`
- Coverage: fraction of results with `"not_covered": true` or non-empty `not_covered`
- Error patterns: group `result.error` strings by prefix (first 60 chars); list top-5 by count
- Stale-index warnings: fraction of results with `"stale": true`

**Skill layer:**
- Total skill starts by `skill` name
- Session count (distinct `session` values)
- Timeline: first and last `ts` in dataset

**Cross-layer:**
- Sessions appearing in both layers → linked chains (skill invoked → N CLI calls)
- Average CLI calls per skill session

**Avoidance join (guard-chain leak rate):**

Join the tool layer against the CLI layer: a Grep/Read/Glob whose target names a module that codemap already answered completely (`query_complete: true`) within the window is an **avoidance event** — the agent re-derived by hand what the index had already returned exhaustively, so the guard chain leaked. `join_avoidance.py` runs the join (module-match is word-boundary safe, ported from `guard-redundant-scan.js`) and reports the rate per session and per skill:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/join_avoidance.py" --logs .cache/codemap/logs --window-min 10 --json  # timeout: 15000
```

Interpret the `rate` field: a **high avoidance rate is a dead-chain signal** — the guard is not firing, the injected context is not being read, or the model is ignoring both. Feed the count into both the product telemetry (is the index earning its keep?) and stranger self-diagnosis (did I re-grep what I already knew?). Add the count and rate to the report's Overview and, when non-zero, list the flagged modules from the `events` array.

## Step 4: Write report

Output path: `--output` if given, else `.reports/codemap/debrief-<YYYY-MM-DD>.md` where date is today.

```bash
mkdir -p .reports/codemap  # timeout: 5000
```

Use Write tool to create report. Sections:

```markdown
# Codemap Debrief — <date>

**Scope**: <date range> · <total records> records · <anonymized: yes/no>

## Overview

<2–3 sentence summary: total CLI calls, distinct sessions, top subcommand, median timing>

## Subcommand distribution

| cmd | calls | % |
|-----|-------|---|
| ... | ...   |   |

## Performance

| metric | value |
|--------|-------|
| median timing_ms | ... |
| p95 timing_ms | ... |
| max timing_ms | ... |

## Coverage gaps

<fraction with not_covered; list top modules if available>

## Error patterns

<list top-5 error prefixes with counts; "none" if clean run>

## Skill invocations

| skill | starts |
|-------|--------|
| ...   | ...    |

## Session timeline

First: <ts> · Last: <ts> · Distinct sessions: N

<If --session given: full chronological event list for that session>
```

Print report path on completion.

## Example invocations

```bash
/codemap:debrief-coding

/codemap:debrief-coding --since 2026-06-15

/codemap:debrief-coding --session 3f2e1a90-...

# use project-relative path, not /tmp
/codemap:debrief-coding --anonymize --output .reports/codemap/debrief-anon-$(date +%Y-%m-%d).md
```

## Security note

All logs are local to `.cache/codemap/logs/`. Salt file `.cache/codemap/logs/.salt` must stay local — never share it alongside anonymized output. The anonymized log files themselves are safe to share; without the salt, pseudonyms are not reversible.

</workflow>
