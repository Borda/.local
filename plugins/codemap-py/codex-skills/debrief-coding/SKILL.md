---
name: debrief-coding
description: "Telemetry report: `$codemap-py:debrief-coding [flags]`; skip integration/index/query."
---

# Debrief Coding

Reads `.cache/codemap/logs/` JSONL telemetry, analyses usage patterns, writes a diagnostic report. It discovers legacy flat shards plus recursive `claude/`, `codex/`, and `direct/` runtime trees and keeps unattributed legacy records separate. Codex hooks contribute runtime-scoped CLI and tool shards but no skill-start events, so missing skill telemetry and cross-layer joins remain evidence gaps.

NOT for: validating codemap installation health/integration (use `$codemap-py:integration audit`); building or querying the structural index (use `$codemap-py:scan-codebase` or `$codemap-py:query-code`).

## Runtime note

Codex has no `bin/` PATH entry and no `$CLAUDE_PLUGIN_ROOT`-equivalent environment variable. Resolve this skill's installed plugin-root path once, substitute it for `PLUGIN_ROOT` below, and keep it in reasoning — shell state does not persist across tool calls. Telemetry evidence source is otherwise identical to the Claude sibling: local JSONL files under `.cache/codemap/logs/`, written regardless of which runtime's session produced them.

## Flags

- `--since <YYYY-MM-DD>` — filter to records on or after this date (default: all)
- `--session <id>` — filter to a single session UUID
- `--anonymize` — run `anonymize.py` on the log directory before reading; replaces qualified names with stable pseudonyms, preserves runtime topology, pseudonymizes shard stems, and keeps the salt in `.cache/codemap/logs/.salt` (never included in output)
- `--output <path>` — write the report to this path (default: `.reports/codemap/debrief-<YYYY-MM-DD>.md`)

## Step 0: Verify logs exist

```bash
find .cache/codemap/logs -type f -name '*.jsonl' -print 2>/dev/null
```

No files → stop: "No codemap telemetry found. Run any `$codemap-py:*` skill or `codemap-py query`/`index` command to start collecting logs."

Telemetry is sharded per session below `logs/claude/`, `logs/codex/`, or `logs/direct/`: CLI records use `cli_<session>.jsonl`, skill records use `skills_<session>.jsonl`, and tool-use records use `tools_<session>.jsonl`; older flat shards remain readable as unattributed legacy evidence. Collect every matching shard recursively, not only the legacy root glob. Preserve flat/runtime topology and report overall, per-runtime, and unattributed summaries; `token_measurement` is unavailable because host hooks provide no token usage.

## Step 1: Optionally anonymize

If `--anonymize` is given, anonymize the complete log directory (never assume the legacy unsuffixed files exist — per-session sharding means they usually don't):

```bash
python PLUGIN_ROOT/bin/anonymize.py --input .cache/codemap/logs --out-dir .cache/codemap/export
```

Anonymized copies land in `.cache/codemap/export/` (separated from `.salt` — never target the logs directory itself). Don't mix anonymized and original data in Step 2. No shard present at all → stop: "no CLI or skill logs found — cannot produce an anonymized report." Only one layer present → anonymize it and note the gap.

## Step 2: Read log files

Read every CLI shard, every skill shard, and every tool shard recursively, concatenating records before analysing — reading only one file misses runtime/session shards and reports a near-empty dataset.

Each line is one JSON record. Filter by `--since` (`ts` field) and `--session` if given.

`--session` guard: a session UUID may be absent from one or both log layers (e.g. `skills.jsonl` records only skill events, not all CLI events). An empty filtered result for one file is expected, not a data-loss signal.

CLI record fields: `ts`, `layer`, `runtime`, `v`, `session`, `cmd`, `argv`, `result` (nested: `count`, `query_complete`, `completeness_reason`, `stale`, `method`, `not_covered`, `error`; index records also carry `trigger`, `changed_count`, `incremental`, `stale_before`, and `result_currency`), `timing_ms`, `stderr` (optional), `exit_code` (optional).
Skill record fields: `ts`, `layer`, `runtime`, `v`, `session`, `skill`, `event`, `intent`, `hook_session`.
Tool record fields (`layer: "tool"`): `ts`, `layer`, `runtime`, `v`, `session`, `skill`, `event`, `tool`, `target`. Flat legacy records are `unattributed`; never assign them to Claude based only on tool names.

## Step 3: Analyse

**Pre-filter (both layers)**: drop records with `source: "bench"` and CLI records with an empty `cmd` from all organic-usage stats; report their counts separately as "scripted/polluted records excluded: N". When records carry `v` (plugin version, 0.23+), compute headline stats per distinct `v` as well as overall.

**CLI layer**: total invocations, success vs error rate (`exit_code: 0` = success; non-zero = error; absent = treat as success unless `result.error` is non-empty); completeness reasons (`result.index.completeness_reason`); subcommand distribution; timing (median, p95, max `timing_ms`); coverage (fraction with non-empty `not_covered`); top-5 error patterns by prefix; stale-index warning fraction.

**Skill layer**: total skill starts by name, distinct session count, first/last timestamp in the dataset.

**Cross-layer**: sessions appearing in both layers → linked chains (skill invoked → N CLI calls); average CLI calls per skill session.
Aggregate overall and by runtime; report `unattributed` legacy records separately. Include refresh triggers, changed-count distributions, index-only sessions, incomplete-query reasons, and stale/degraded fractions; legacy provenance remains unknown. Do not present debrief as measured token savings or live fresh-session activation evidence.

**Avoidance join (guard-chain leak rate)**: join the tool layer against the CLI layer — a search/read whose target names a module codemap already answered completely (`query_complete: true`) within the window is an avoidance event, i.e. the model re-derived by hand what the index had already returned exhaustively.

```bash
python PLUGIN_ROOT/bin/join_avoidance.py --logs .cache/codemap/logs --window-min 10 --json
```

A high avoidance rate is a dead-chain signal: guard not firing, injected context not read, or the model ignoring both. Preserve `per_runtime` and `unattributed` metrics, add count and rate to the report Overview, and list flagged modules when non-zero.

## Step 4: Write report

Output path: `--output` if given, else `.reports/codemap/debrief-<YYYY-MM-DD>.md` (today's date). This path is product-level, not runtime-specific — identical to the Claude sibling's default.

```bash
mkdir -p .reports/codemap
```

Write the report with these sections: Overview (2–3 sentence summary), Subcommand distribution, Performance (median/p95/max `timing_ms`), Coverage gaps, Error patterns (top-5 with counts, "none" if clean), Skill invocations, Session timeline (first/last ts, distinct sessions; full chronological event list when `--session` was given).

Print the report path on completion.

## Security note

All logs are local to `.cache/codemap/logs/`. The salt file `.cache/codemap/logs/.salt` must stay local — never share it alongside anonymized output. Anonymized log files themselves are safe to share; without the salt, the pseudonyms are not reversible.
