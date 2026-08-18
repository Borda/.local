---
name: debrief-coding
description: Read local codemap telemetry logs and produce a diagnostic/usage report. Supports date filtering, session filtering, and optional anonymization before sharing. TRIGGER when: analyse recent codemap usage, debug query patterns, investigate errors, or prepare a shareable anonymized report of how codemap skills and CLI are being used.
allowed-tools: Read, Write, Bash, Glob
model: haiku
effort: low
---

<objective>

Reads `.cache/codemap/logs/` JSONL telemetry, analyses usage patterns, writes a diagnostic report. It discovers legacy flat shards plus recursive `claude/`, `codex/`, and `direct/` runtime trees and keeps unattributed legacy records separate. Codex hooks contribute runtime-scoped CLI and tool shards but no skill-start events, so missing skill telemetry and cross-layer joins remain evidence gaps.

NOT for: validating codemap installation health/integration (use `/codemap-py:integration audit`); building/querying structural index (use `/codemap-py:scan-codebase` or `/codemap-py:query-code`).

</objective>

<workflow>

## Flags

- `--since <YYYY-MM-DD>` — filter to records on or after this date (default: all)
- `--session <id>` — filter to a single session UUID
- `--anonymize` — run `anonymize.py` on every log shard of all three layers (CLI, skill, tool) before reading; replaces qualified names with stable pseudonyms; keeps salt in `.cache/codemap/logs/.salt` (never included in output). Directory input preserves runtime topology below the export root and pseudonymizes shard session stems.
- `--output <path>` — write report to this path (default: `.reports/codemap/debrief-<YYYY-MM-DD>.md`)

## Step 0: Verify logs exist

```bash
find .cache/codemap/logs -type f -name '*.jsonl' -print 2>/dev/null  # timeout: 5000
```

No files → stop: "No codemap telemetry found. Run any `/codemap-py:*` skill or `codemap-py query`/`index` command to start collecting logs."

Telemetry is sharded per session below `logs/claude/`, `logs/codex/`, or `logs/direct/`: CLI records use `cli_<session>.jsonl`, skill records use `skills_<session>.jsonl`, and tool records use `tools_<session>.jsonl`; older flat shards remain readable as unattributed legacy evidence. Collect every matching shard recursively, not only the legacy root glob. Preserve flat/runtime topology and report overall, per-runtime, and unattributed summaries; `token_measurement` is unavailable because host hooks provide no token usage.

## Step 1: Optionally anonymize

If `--anonymize` flag given:

**Guard**: anonymize every present shard of all three layers — CLI, skill, and tool — by passing the log directory as `--input`; this recurses through flat and runtime-scoped shards. Anonymized copies land in `.cache/codemap/export/` with the same runtime topology (anonymize.py refuses to write next to `.salt` — never target logs dir); don't mix anonymized and original data in Step 2, and don't exempt a layer.

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/anonymize.py" \
    --input .cache/codemap/logs --out-dir .cache/codemap/export  # timeout: 15000
```

If neither set has any file: print `⚠ --anonymize: no CLI or skill logs found — cannot produce anonymized report.` and stop. If only one layer present, anonymize it and note gap.

Use `-anon` variants under `.cache/codemap/export/` as source in Step 2. anonymize.py not found → warn, proceed with originals.

## Step 2: Read log files

Resolve the shard tree with the `Glob` tool, then Read every returned path — do not rely on any variable computed in an earlier Bash block (fresh shell per tool call; Read never expands shell variables regardless). When `--anonymize` ran, glob the mirrored tree under `.cache/codemap/export/` instead of the originals:

- CLI shards: recursive `Glob(".cache/codemap/logs/**/cli*.jsonl")` (or `.cache/codemap/export/**/cli*-anon.jsonl` when anonymized)
- Skill shards: recursive `Glob(".cache/codemap/logs/**/skills*.jsonl")` (or `.cache/codemap/export/**/skills*-anon.jsonl`)
- Tool shards: recursive `Glob(".cache/codemap/logs/**/tools*.jsonl")` (or `.cache/codemap/export/**/tools*-anon.jsonl` when anonymized)

All three layers are anonymized — `anonymize.py --input` is layer-agnostic and Step 1 already loops over the tool shards, so in anonymize mode the tool layer must be read from `.cache/codemap/export/` like the other two. Reading raw `tools_*.jsonl` there would put verbatim Grep/Glob patterns and Read file paths — the `target` field — into an export produced for sharing.

Read **every** path each Glob call returns. Concatenate records before analysing; single-file read misses per-session shards, reports near-empty dataset.

Each line is one JSON record. Filter by `--since` (compare `ts` field) and `--session` if given.

**`--session` guard**: when `--session <id>` given, session UUID may be absent from one or both log files (e.g., skills.jsonl records only skill events, not all CLI events). Filtering absent session ID returns empty set for that file — expected, not error. Report "session not found in <file>" rather than treating empty result as data loss.

CLI record fields: `ts`, `layer`, `runtime`, `v`, `session`, `cmd`, `argv`, `result` (nested: `count`, `query_complete`, `completeness_reason`, `stale`, `method`, `not_covered`, `error`; index records also carry `trigger`, `changed_count`, `incremental`, `stale_before`, and `result_currency`), `timing_ms`, `stderr` (optional), `exit_code` (optional).

Skill record fields: `ts`, `layer`, `runtime`, `v`, `session`, `skill`, `event`, `intent`, `hook_session`.

Tool record fields (`layer: "tool"`, from `log-tool-use.py`): `ts`, `layer`, `runtime`, `v`, `session`, `skill`, `event`, `tool` (`Grep`|`Read`|`Glob`|`Bash`), `target` (Grep/Glob pattern or search path, Read file_path, Bash search command truncated to 200 chars). Count raw grep/read volume by runtime and session; never assign flat legacy records to Claude from tool names.

## Step 3: Analyse

Compute from filtered records:

**Pre-filter (both layers):**
- Drop records with `source: "bench"` (tagged benchmark/demo load) and cli records with empty `cmd` (pre-0.23 test-suite pollution) from all organic-usage stats; report their counts separately as "scripted/polluted records excluded: N"
- When records carry `v` (plugin version, 0.23+): compute headline stats (error rate, stale rate, completeness) per distinct `v` as well as overall — the before/after signal for judging whether a release moved the metrics

**CLI layer:**
- Total invocations, success vs error rate — `exit_code: 0` = tool ran cleanly (success); `exit_code` present AND non-zero = error; `exit_code` absent = field not logged (treat as success unless `result.error` non-empty)
- Completeness reasons: aggregate `result.index.completeness_reason` (0.23+: veto slug — `stale` / `untracked` / `degraded` / `collision` / `root_mismatch` / `module_degraded`; `ok` = complete) — the direct answer to "why is query_complete never true here"
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
- Aggregate overall and by `runtime` (`claude`, `codex`, `direct`); report flat legacy records under `unattributed`.
- Report refresh triggers, changed-file counts, index-only sessions, incomplete-query reasons, and stale/degraded fractions; missing legacy provenance remains `unknown`.
- Do not present debrief as measured token savings or live fresh-session activation evidence.

**Avoidance join (guard-chain leak rate):**

Join tool layer against CLI layer: a Grep/Read/Glob whose target names a module codemap already answered completely (`query_complete: true`) within window is an **avoidance event** — agent re-derived by hand what index had already returned exhaustively, guard chain leaked. `join_avoidance.py` runs the join (module-match word-boundary safe, ported from `guard-redundant-scan.py`), reports rate per session and per skill:

```bash
python3 "${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/join_avoidance.py" --logs .cache/codemap/logs --window-min 10 --json  # timeout: 15000
```

Interpret `rate` and `per_runtime`: **high avoidance rate is a dead-chain signal** — guard not firing, injected context not read, or model ignoring both. Preserve runtime/session grouping and keep `unattributed` separate; never infer a legacy runtime. Feed count into product telemetry and self-diagnosis; when non-zero, list flagged modules from `events`.

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
/codemap-py:debrief-coding

/codemap-py:debrief-coding --since 2026-06-15

/codemap-py:debrief-coding --session 3f2e1a90-...

# use project-relative path, not /tmp
/codemap-py:debrief-coding --anonymize --output .reports/codemap/debrief-anon-$(date +%Y-%m-%d).md
```

## Security note

All logs local to `.cache/codemap/logs/`. Salt file `.cache/codemap/logs/.salt` must stay local — never share alongside anonymized output. Anonymized log files themselves safe to share; without salt, pseudonyms not reversible.

</workflow>
