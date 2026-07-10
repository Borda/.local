<!-- file: codemap-context.md — consumers: plugins/develop/skills/{plan,fix,feature,refactor,review}/SKILL.md, plugins/oss/skills/review/SKILL.md -->

**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent. Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file; both empty → only the global `central` baseline runs.

**Wrapper** — the query mechanics, batch pre-flight bash, evidence-line contract, completeness/staleness semantics, coverage-metadata rules, targeted-edit pattern, and effort tiers live in the codemap-shipped contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap/*/skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap/skills/_shared"
[ -f "$_CM_SHARED/codemap-context.md" ] && echo "$_CM_SHARED/codemap-context.md" || echo "codemap contract absent — use fallback below"
```

Read `$_CM_SHARED/codemap-context.md` (contract `v2`) — follow §Batch pre-flight pattern (run it with `TARGET_MODULE`/`TARGET_FN`), §Evidence-line contract, §Coverage metadata, §Targeted-edit pattern, §Effort-tier guidance.

**Fallback when the codemap plugin is absent** (`$_CM_SHARED/codemap-context.md` missing): run only the baseline `scan-query --timeout 5 central --top 5 2>/dev/null` plus, when a target is known, `scan-query --timeout 5 fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests 2>/dev/null`; treat any non-empty output as usable, skip the evidence-line/completeness logic, and proceed with file reads for the rest. Never break the load.

## Per-agent query map (develop dimension)

Extends the contract core map with develop's dimension queries:
- `central --top 5` — global blast-radius baseline (sw-engineer, architect)
- `fn-rdeps --exclude-tests` — direct callers; benchmarked (94k vs 1M+ tokens, +40pp accuracy); run first (sw-engineer)
- `fn-blast` — transitive caller impact when depth > 1 needed (sw-engineer)
- `uncovered --top 20` — test gaps (qa-specialist)
- `mock-rdeps` — test mock coverage; prevents false "untested" on mocked symbols (qa-specialist)
- `undocumented` — docstring gaps (doc-scribe)
- `symbol --with-imports` — contract reading without re-reading the file (all agents)

Results returned: prepend `## Structural Context (codemap)` block to the foundry:sw-engineer spawn prompt with hotspot JSON and per-query output. `codemap_evidence:` line at the end reports retrieval reliability — agents may skip re-querying only when `completeness=exhaustive`. `scan-query` not found or index missing: emit a ⚠ warning to stderr (` >&2 echo "⚠ codemap: scan-query unavailable or index missing — context reduced to central --top 5" `), then proceed.

## Extended scan — multi-file / API changes (develop batch producer)

Contract §Extended scan defines the risk tiers (`>=5` HIGH, `1–4` MODERATE, `0` LOW). Develop's batch producer:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap_scan.py" --source=diff  # timeout: 15000
```

> Interpret: any `rdeps` output = external callers affected; `coupled` output = co-change pairs.
> Fallback (specific known module): `scan-query rdeps <mod> --top 10 2>/dev/null || true`.

## Review-pipeline injection (oss:review, develop:review)

Review orchestrators run the v4 pre-flight queries **per changed module** before spawning dimension agents, persist structured output, and pass it to each agent as `CODEMAP_CONTEXT` so the agent skips redundant file reads. Pre-flight queries:

```bash
scan-query --timeout 5 fn-rdeps    "${MODULE}::${FN}" --exclude-tests 2>/dev/null  # direct callers (v4.6)
scan-query --timeout 5 fn-blast    "${MODULE}::${FN}"   2>/dev/null  # transitive callers (v3)
scan-query --timeout 5 mock-rdeps  "${MODULE}::${FN}"   2>/dev/null  # mock coverage (v4.1)
scan-query --timeout 5 uncovered   --top 20 "$MODULE"   2>/dev/null  # test gaps (v4.2)
scan-query --timeout 5 xrefs --broken      "$MODULE"    2>/dev/null  # stale doc refs (v4.5)
scan-query --timeout 5 undocumented "$MODULE"  2>/dev/null  # doc coverage (v4.4)
```

> Per-agent consumption:
> - `qa-specialist` — read `uncovered` + `mock-rdeps` first; skip manual test-file grep for symbols codemap already classifies; fall back to Read only when codemap context absent or insufficient
> - `doc-scribe` — read `undocumented` + `xrefs --broken` first; skip docstring-scan reads on listed symbols
> - `sw-engineer` — read `fn-rdeps` first (direct callers), then `fn-blast` for transitive depth; skip caller-walk reads when blast list complete
> - `challenger` — unchanged; always reads source directly

## Review→resolve pre-flight cache (persisted artifact)

Review runs the per-changed-module pre-flight batch once (§Review-pipeline injection). A follow-on skill on the same PR — `oss:resolve` after `/review` — otherwise re-issues the identical `fn-rdeps`/`fn-blast`/`mock-rdeps`/`uncovered`/`xrefs`/`undocumented`/`rdeps` queries for the same modules. The persisted cache lets the follow-on **reuse** those answers instead.

**Artifact shape (report §5.3)** — one file per module at `.temp/<run>/codemap-context/<module>.json`, split into a stable *prefix* (index-derived, content-hashed + git-sha stamped) and a volatile *delta* (touched files, exhausted queries, notes) so a later cross-skill handoff generalizes without rework:

```json
{"module": "pkg.mod",
 "prefix": {"git_sha": "<index git_sha>", "scanned_at": "<index ISO ts>", "content_hash": "<sha256>", "answers": {"rdeps": {...}, "fn-rdeps": {...}}},
 "delta": {"touched_files": [], "exhausted_queries": [], "notes": []}}
```

**Freshness rule**: reusable only when `prefix.git_sha` matches the current index `git_sha` AND `prefix.scanned_at` is not older than the current index `scanned_at` (a rebuilt index — newer `scanned_at` — invalidates every artifact; re-query). Health metric: `reuse_ratio` = reused answers / total persisted.

**Writer/reader contract** (oss plugin ships `bin/codemap_cache.py`; gate on `oss` availability — a consumer without it simply re-queries):

```bash
# write — split a scan-query batch result into per-module artifacts (batch-producer side)
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/codemap_cache.py" write --batch "$BATCH_OUT" --index "$IDX" --cache-dir "$CACHE_DIR"
# read — reuse verdict + cached answers for one module (consumer side)
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/codemap_cache.py" read  --module "$MOD" --index "$IDX" --cache-dir "$CACHE_DIR"
# report — aggregate reuse_ratio for telemetry
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/codemap_cache.py" report --cache-dir "$CACHE_DIR"
```

> Review-side wiring (optional, not yet in review/SKILL.md): review may call `codemap_cache.py write` on its `$RUN_DIR` batch output to seed `$RUN_DIR/codemap-context/` — until then, resolve materializes the cache from review's persisted `$RUN_DIR/codemap-context.md` batch blob on first use, so no review change is required for reuse to work.

**Semble companion** — include in agent spawn prompt only when caller sets `SEMBLE_ENABLED=true`; skip if flag absent:

> `mcp__semble__search` available and codemap direction-incomplete (`"query_complete": false`, or the legacy `"exhaustive": false`) or no index found: call `mcp__semble__search` with varied queries (e.g. `"<module> import"`, `"from <module> import"`, `"<module> usage"`) and `repo=<git_root>`, `top_k=20`. Stop when two consecutive queries return no new modules. Merge all results into final rdep set — union of codemap + all semble calls. Codemap `query_complete: true`: skip semble.
