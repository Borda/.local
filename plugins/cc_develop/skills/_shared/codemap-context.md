<!-- file: codemap-context.md — consumers: plugins/cc_develop/skills/{plan,fix,feature,refactor,review}/SKILL.md, plugins/cc_oss/skills/review/SKILL.md -->

**Structural context (codemap-py)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent. Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file; both empty → only global `central` baseline runs.

**Wrapper** — query mechanics, batch pre-flight bash, evidence-line contract, completeness/staleness semantics, coverage-metadata rules, targeted-edit pattern, and effort tiers live in codemap-shipped contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap-py/*/claude-skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap-py/claude-skills/_shared"
[ -f "$_CM_SHARED/codemap-context.md" ] && cat "$_CM_SHARED/codemap-context.md" || echo "codemap contract absent — use fallback below"
```

Contract (`v2`) — follow §Batch pre-flight pattern (run with `TARGET_MODULE`/`TARGET_FN`), §Evidence-line contract, §Coverage metadata, §Targeted-edit pattern, §Effort-tier guidance.

**Fallback when codemap plugin absent** (`$_CM_SHARED/codemap-context.md` missing): run only baseline `codemap-py query --timeout 5 central --top 5 2>/dev/null` plus, when target known, `codemap-py query --timeout 5 fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests 2>/dev/null`; treat any non-empty output as usable, skip evidence-line/completeness logic, proceed with file reads for rest. Never break load.

## Per-agent query map (develop dimension)

Extends contract core map with develop's dimension queries:
- `central --top 5` — global blast-radius baseline (sw-engineer, architect)
- `fn-rdeps --exclude-tests` — direct callers; benchmarked (94k vs 1M+ tokens, +40pp accuracy); run first (sw-engineer)
- `fn-blast` — transitive caller impact when depth > 1 needed (sw-engineer)
- `uncovered --top 20` — test gaps (qa-specialist)
- `mock-rdeps` — test mock coverage; prevents false "untested" on mocked symbols (qa-specialist)
- `undocumented` — docstring gaps (doc-scribe)
- `symbol --with-imports` — contract reading without re-reading file (all agents)

Results returned: prepend `## Structural Context (codemap-py)` block to foundry:sw-engineer spawn prompt with hotspot JSON and per-query output. `codemap-py` not found or index missing: emit ⚠ warning to stderr (` >&2 echo "⚠ codemap-py: codemap-py unavailable or index missing — context reduced to central --top 5" `), then proceed.

## Extended scan — multi-file / API changes (develop batch producer)

Contract §Extended scan defines risk tiers (`>=5` HIGH, `1–4` MODERATE, `0` LOW). Develop's batch producer:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_develop}/bin/codemap_scan.py" --source=diff  # timeout: 15000
```

> Interpret: any `rdeps` output = external callers affected; `coupled` output = co-change pairs.
> Fallback (specific known module): `codemap-py query rdeps <mod> --top 10 2>/dev/null || true`.

## Review-pipeline injection (oss:review, develop:review)

Review orchestrators run v4 pre-flight queries **per changed module** before spawning dimension agents, persist structured output, pass to each agent as `CODEMAP_CONTEXT` so agent skips redundant file reads. Pre-flight queries (module-level only — a name-only changed-files list cannot supply the `module::fn` qnames `fn-rdeps`/`fn-blast` require; bare-module fn-* calls failed 100% in production, 2026-07 usage audit F1; fn-level returns once diff-hunk qname derivation lands — audit plan P1.2b):

```bash
codemap-py query --timeout 5 rdeps       "$MODULE"            2>/dev/null  # importer count → risk tier
codemap-py query --timeout 5 mock-rdeps  "$MODULE"            2>/dev/null  # mock coverage (v4.1)
codemap-py query --timeout 5 uncovered   --top 20 "$MODULE"   2>/dev/null  # test gaps (v4.2)
codemap-py query --timeout 5 xrefs --broken      "$MODULE"    2>/dev/null  # stale doc refs (v4.5)
codemap-py query --timeout 5 undocumented "$MODULE"  2>/dev/null  # doc coverage (v4.4)
```

> Per-agent consumption:
> - `qa-specialist` — read `uncovered` + `mock-rdeps` first; skip manual test-file grep for symbols codemap already classifies; fall back to Read only when codemap context absent or insufficient
> - `doc-scribe` — read `undocumented` + `xrefs --broken` first; skip docstring-scan reads on listed symbols
> - `sw-engineer` — read `rdeps` first (importers per changed module); `fn-rdeps`/`fn-blast` only when a concrete `module::fn` qname is known (dimension queries above)
> - `challenger` — unchanged; always reads source directly

## Review→resolve pre-flight cache (persisted artifact)

Review runs per-changed-module pre-flight batch once (§Review-pipeline injection). Follow-on skill on same PR — `oss:resolve` after `/review` — otherwise re-issues identical `rdeps`/`mock-rdeps`/`uncovered`/`xrefs`/`undocumented` queries for same modules. Persisted cache lets follow-on **reuse** those answers instead.

**Artifact shape (report §5.3)** — one file per module at `.temp/<run>/codemap-context/<module>.json`, split into stable *prefix* (index-derived, content-hashed + git-sha stamped) and volatile *delta* (touched files, exhausted queries, notes) so a later cross-skill handoff generalizes without rework:

```json
{"module": "pkg.mod",
 "prefix": {"git_sha": "<index git_sha>", "scanned_at": "<index ISO ts>", "content_hash": "<sha256>", "answers": {"rdeps": {...}, "fn-rdeps": {...}}},
 "delta": {"touched_files": [], "exhausted_queries": [], "notes": []}}
```

**Freshness rule**: reusable only when `prefix.git_sha` matches current index `git_sha` AND `prefix.scanned_at` not older than current index `scanned_at` (rebuilt index — newer `scanned_at` — invalidates every artifact; re-query). Health metric: `reuse_ratio` = reused answers / total persisted.

**Writer/reader contract** (oss plugin ships `bin/codemap_cache.py`; gate on `oss` availability — consumer without it simply re-queries):

```bash
# write — split a codemap-py query batch result into per-module artifacts (batch-producer side)
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/codemap_cache.py" write --batch "$BATCH_OUT" --index "$IDX" --cache-dir "$CACHE_DIR"
# read — reuse verdict + cached answers for one module (consumer side)
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/codemap_cache.py" read  --module "$MOD" --index "$IDX" --cache-dir "$CACHE_DIR"
# report — aggregate reuse_ratio for telemetry
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/codemap_cache.py" report --cache-dir "$CACHE_DIR"
```

> Review-side wiring (optional, not yet in review/SKILL.md): review may call `codemap_cache.py write` on its `$RUN_DIR` batch output to seed `$RUN_DIR/codemap-context/` — until then, resolve materializes cache from review's persisted `$RUN_DIR/codemap-context.md` batch blob on first use, so no review change required for reuse to work.

**Semble companion** — include in agent spawn prompt only when caller sets `SEMBLE_ENABLED=true`; skip if flag absent:

> `mcp__semble__search` available and codemap direction-incomplete (`"query_complete": false`, or legacy `"exhaustive": false`) or no index found: call `mcp__semble__search` with varied queries (e.g. `"<module> import"`, `"from <module> import"`, `"<module> usage"`) and `repo=<git_root>`, `top_k=20`. Stop when two consecutive queries return no new modules. Merge all results into final rdep set — union of codemap + all semble calls. Codemap `query_complete: true`: skip semble.
