---
name: debrief-coding
description: Read local codemap telemetry logs and produce a diagnostic/usage report. Supports date filtering, session filtering, and optional anonymization before sharing.
when_to_use: Analyse recent codemap usage, debug query patterns, investigate errors, or prepare a shareable anonymized report of how codemap skills and CLI are being used.
allowed-tools: Read, Write, Bash, Glob
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

Record which log files are present (`cli.jsonl`, `skills.jsonl`).

## Step 1: Optionally anonymize

If `--anonymize` flag given:

**Guard**: check which log files exist before anonymizing — only run `anonymize.py` on files that are present. If one file is missing, anonymize only the present file and note the gap; do not mix anonymized and original data in Step 2 (use original for any file without a corresponding `-anon` variant only when user explicitly confirms, otherwise stop and report the missing file).

```bash
ls .cache/codemap/logs/cli.jsonl 2>/dev/null && CLI_EXISTS="true" || CLI_EXISTS="false"
ls .cache/codemap/logs/skills.jsonl 2>/dev/null && SKILLS_EXISTS="true" || SKILLS_EXISTS="false"
```

If both exist:
```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/anonymize.py" \
    --input .cache/codemap/logs/cli.jsonl \
    --output .cache/codemap/logs/cli-anon.jsonl  # timeout: 15000
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/anonymize.py" \
    --input .cache/codemap/logs/skills.jsonl \
    --output .cache/codemap/logs/skills-anon.jsonl  # timeout: 15000
```

If one file missing: print `⚠ --anonymize: <missing_file> not found — cannot produce fully anonymized report. Proceed with available file only, or stop?` and wait for user decision before continuing.

Use the `-anon` variants as source in Step 2. If anonymize.py not found, warn and proceed with originals.

## Step 2: Read log files

Read `.cache/codemap/logs/cli.jsonl` (or `cli-anon.jsonl`) and `.cache/codemap/logs/skills.jsonl` (or `skills-anon.jsonl`) with the Read tool.

Each line is one JSON record. Filter by `--since` (compare `ts` field) and `--session` if given.

**`--session` guard**: when `--session <id>` given, a session UUID may be absent from one or both log files (e.g., skills.jsonl records only skill events, not all CLI events). Filtering an absent session ID returns an empty set for that file — this is expected, not an error. Report "session not found in <file>" rather than treating empty result as a data loss.

CLI record fields: `ts`, `layer`, `session`, `cmd`, `argv`, `result` (nested: `count`, `exhaustive`, `stale`, `method`, `not_covered`, `error`), `timing_ms`, `stderr` (optional), `exit_code` (optional).

Skill record fields: `ts`, `layer`, `session`, `skill`, `event`, `intent`, `hook_session`.

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
# Basic report of all logs
/codemap:debrief-coding

# Last week only
/codemap:debrief-coding --since 2026-06-15

# Single session trace
/codemap:debrief-coding --session 3f2e1a90-...

# Anonymized (safe to share) — use a project-relative path, not /tmp
/codemap:debrief-coding --anonymize --output .reports/codemap/debrief-anon-$(date +%Y-%m-%d).md
```

## Security note

All logs are local to `.cache/codemap/logs/`. Salt file `.cache/codemap/logs/.salt` must stay local — never share it alongside anonymized output. The anonymized log files themselves are safe to share; without the salt, pseudonyms are not reversible.

</workflow>
