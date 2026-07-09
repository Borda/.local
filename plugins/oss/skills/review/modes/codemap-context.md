<!-- file: codemap-context.md — consumers: review/SKILL.md -->
<!-- oss:review Step 1 — executed via: > loads: modes/codemap-context.md; gated on CODEMAP_ENABLED=true -->
<!-- fragment — no <workflow> wrapper; executed inline by SKILL.md Step 1 -->
<!-- Input: CODEMAP_ENABLED, CHANGED_FILES, CLEAN_ARGS, _IDX -->
<!-- Output: codemap_available, $CODEMAP_CONTEXT_STAGE; persists both to TMPDIR for Step 2 -->

### Structural context + review pre-flight (codemap — only if `CODEMAP_ENABLED=true`)

**Skip entire section if `CODEMAP_ENABLED=false`** — sets `codemap_available=false` for downstream agent prompts; agents fall back to file reads.

```bash
codemap_available=false
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
# $RUN_DIR created in Step 2; stage to TMPDIR, copied then
CODEMAP_CONTEXT_STAGE="${TMPDIR:-/tmp}/oss-review-codemap-context-${CLEAN_ARGS}.md"
if [ "$CODEMAP_ENABLED" = "true" ] && command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    codemap_available=true
    CHANGED_MODS=$(echo "$CHANGED_FILES" | grep '\.py$' | sed 's|^src/||;s|\.py$||;s|/|.|g' | grep -v '__init__$')
    {
        echo "## Structural Context (codemap)"
        echo
        echo "### Global blast-radius baseline"
        scan-query --timeout 5 central --top 5 2>/dev/null
        echo
        for mod in $CHANGED_MODS; do
            echo "### Module: $mod"
            scan-query --timeout 5 rdeps        "$mod"          2>/dev/null  # importer count → risk tier
            scan-query --timeout 5 fn-rdeps    "$mod" --exclude-tests 2>/dev/null
            scan-query --timeout 5 fn-blast     "$mod"          2>/dev/null  # caller impact (v3)
            scan-query --timeout 5 mock-rdeps   "$mod"          2>/dev/null  # mock coverage (v4.1)
            scan-query --timeout 5 uncovered    --top 20 "$mod" 2>/dev/null  # test gaps (v4.2)
            scan-query --timeout 5 xrefs --broken        "$mod" 2>/dev/null  # stale doc refs (v4.5)
            scan-query --timeout 5 undocumented "$mod" 2>/dev/null  # doc coverage (v4.4)
            echo
        done
    } > "$CODEMAP_CONTEXT_STAGE"
fi
echo "$codemap_available"      > "${TMPDIR:-/tmp}/oss-review-codemap-available-${CLEAN_ARGS}"
echo "$CODEMAP_CONTEXT_STAGE"  > "${TMPDIR:-/tmp}/oss-review-codemap-context-stage-${CLEAN_ARGS}"
```

`codemap_available=true`: Step 2 copies `$CODEMAP_CONTEXT_STAGE` to `$RUN_DIR/codemap-context.md` after `$RUN_DIR` is created. Every dimension-agent spawn prompt in Step 2 must then include a literal block (substituted from `$RUN_DIR/codemap-context.md`):

```text
## Structural Context (codemap, codemap_available=true)
<content of $RUN_DIR/codemap-context.md>

Read this section first. For symbols listed in `uncovered`/`mock-rdeps`/`undocumented`/`xrefs --broken`/`fn-blast`, trust the codemap output; skip redundant Grep/Read on the same data. Fall back to file reads only when codemap output is empty for a symbol you need or when verifying a specific finding.
```

`codemap_available=false`: omit the block; agents proceed with current file-read behaviour.

Tier annotation for Agent 1 (sw-engineer) only: label each module's `imported_by` count — **high risk** (>20), **moderate** (5–20), **low** (<5) — for blast-radius reference.

**Semble companion** (only if `SEMBLE_ENABLED=true`): include in Agent 1 spawn prompt: "If `mcp__semble__search` available and any codemap result is direction-incomplete (`query_complete: false`, or the legacy `exhaustive: false`) or codemap absent: call `mcp__semble__search(query='<module> import', repo=<git_root>, top_k=20)` per module; stop when two consecutive queries return no new importers; merge with codemap; skip if all results `query_complete: true`."
