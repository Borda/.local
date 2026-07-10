<!-- file: codemap-context.md — consumers: plugins/develop/skills/{plan,fix,feature,refactor,review}/SKILL.md, plugins/oss/skills/review/SKILL.md -->

**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent.

Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file. Both empty → only the global `central` baseline runs.

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    scan-index --incremental 2>/dev/null || true   # refresh SHA-changed files only; never full-build mid-task
    _CM_N=0 _CM_H=0 _CM_STALE=0 _CM_NONEXH=0
    _cq() {
        local out; _CM_N=$((_CM_N+1))
        out=$(scan-query --timeout 5 "$@" 2>/dev/null)
        case "$out" in
            *'"error"'*|'') ;;
            *) _CM_H=$((_CM_H+1)); printf '%s\n' "$out"
               case "$out" in *'"stale":true'*|*'"stale": true'*) _CM_STALE=1;; esac
               # query_complete is the forward field (direction-scoped); exhaustive is its legacy alias for one cycle.
               case "$out" in *'"query_complete":false'*|*'"query_complete": false'*|*'"exhaustive":false'*|*'"exhaustive": false'*) _CM_NONEXH=1;; esac ;;
        esac
    }
    _cq central --top 5
    [ -n "$TARGET_FN" ]     && _cq fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests  # direct callers — benchmarked 94k vs 1M+ tokens, +40pp accuracy
    [ -n "$TARGET_FN" ]     && _cq fn-blast "${TARGET_MODULE}::${TARGET_FN}"  # transitive callers — depth > 1
    [ -n "$TARGET_MODULE" ] && _cq uncovered --top 20 "$TARGET_MODULE"
    [ -n "$TARGET_FN" ]     && _cq mock-rdeps "${TARGET_MODULE}::${TARGET_FN}"
    [ -n "$TARGET_MODULE" ] && _cq undocumented "$TARGET_MODULE"
    [ -n "$TARGET_FN" ]     && _cq symbol --with-imports "$TARGET_FN"
    _IDX_MTIME=$(date -r "${_IDX}/${PROJ}.json" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "?")
    if [ "$_CM_STALE" -eq 1 ]; then _CM_COMPL="stale"
    elif [ "$_CM_NONEXH" -eq 1 ]; then _CM_COMPL="partial"
    elif [ "$_CM_H" -eq 0 ]; then _CM_COMPL="unknown"
    else _CM_COMPL="exhaustive"
    fi
    echo "codemap_evidence: queries_run=${_CM_N} hits=${_CM_H} completeness=${_CM_COMPL} index_mtime=${_IDX_MTIME}"
fi
```

> Query map (per agent dimension):
> - `central --top 5` — global blast-radius baseline (sw-engineer, architect)
> - `fn-rdeps --exclude-tests` — direct callers; benchmarked (94k vs 1M+ tokens, +40pp accuracy); run first (sw-engineer)
> - `fn-blast` — transitive caller impact when depth > 1 needed (sw-engineer)
> - `uncovered --top 20` — test gaps (qa-specialist)
> - `mock-rdeps` — test mock coverage; prevents false "untested" on mocked symbols (qa-specialist)
> - `undocumented` — docstring gaps (doc-scribe)
> - `symbol --with-imports` — contract reading without re-reading the file (all agents)
>
> Targeted edit (known symbol, file >~300 lines): `symbol <mod::name>` → take line span → `Read(offset=span_start−10, limit=span_len+20)` → Edit. Slice Read suffices — Edit needs only a slice containing the target, not the whole file. Spans come from the index; file changed since scan → spans may drift (self-heal usually covers it). Edit errors "Found N matches" (`old_string` not file-wide unique) or no-match (drifted) → full `Read`, then Edit with a larger unique `old_string`.

Results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt with hotspot JSON and per-query output. `codemap_evidence:` line at end of block reports retrieval reliability — agents may skip re-querying only when `completeness=exhaustive`. `scan-query` not found or index missing: emit ⚠ warning to stderr (` >&2 echo "⚠ codemap: scan-query unavailable or index missing — context reduced to central --top 5" `), then proceed.

**Coverage metadata in output** — each `scan-query` result includes an `index` block with per-command coverage fields:
- `index.method` — analysis technique used (`static-ast`, `import-graph`, `index-lookup`, `ast-flags`)
- `index.not_covered` — what the method structurally misses (list); when non-empty, surface as a scope caveat in the response; do NOT run grep to fill the gap — gaps are structurally unresolvable by static analysis
- `index.hint` — actionable alternative if user needs deeper coverage (e.g. grep pattern for hook-registered callers)
- `index.confidence: "exact"` — result is authoritative; omit verification caveats

**Codemap = primary codebase navigation tool.** Do NOT grep/bash to re-verify what codemap already returned. When `not_covered` non-empty: (1) include one-line caveat in response — "Note: callers via [not_covered items] not included — structurally invisible to static AST"; (2) log gap:
```bash
mkdir -p .cache/codemap
printf '{"ts":"%s","cmd":"%s","target":"%s","not_covered":%s,"hint":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<subcommand>" "<target>" '<not_covered_json>' "<hint_or_empty>" \
    >> .cache/codemap/gaps.jsonl 2>/dev/null || true
```
(3) Continue achieving goal — do NOT abandon task because of structural gap.

When `method=index-lookup` + `confidence=exact`: result authoritative, skip verification caveats.

## Extended scan — multi-file / API changes

When task touches multiple modules or changes public API surface, run per-affected-module reverse-dependency scan:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap_scan.py" --source=diff  # timeout: 15000
```

> Interpret: any `rdeps` output = external callers affected; `coupled` output = co-change pairs.
> Fallback (specific known module): `scan-query rdeps <mod> --top 10 2>/dev/null || true`.
>
> Risk tier based on rdep_count:
> - `>= 5` → HIGH blast radius — flag before proceeding
> - `1–4` → MODERATE — note in plan/report
> - `0` → LOW — proceed normally

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
