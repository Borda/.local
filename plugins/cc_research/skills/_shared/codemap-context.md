<!-- file: codemap-context.md — consumers: research/skills/run, verify -->

**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent.

Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file — typically module/function the experiment or verification edits. Both empty → only global `central` baseline runs.

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    scan-index --incremental 2>/dev/null || true   # refresh SHA-changed files only; never full-build mid-task
    _CM_N=0 _CM_H=0
    _cq() {
        local out; _CM_N=$((_CM_N+1))
        out=$(scan-query --timeout 5 "$@" 2>/dev/null)
        case "$out" in
            *'"error"'*|'') ;;
            *) _CM_H=$((_CM_H+1)); printf '%s\n' "$out" ;;
        esac
    }
    _cq central --top 5
    [ -n "$TARGET_FN" ]     && _cq fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests  # direct callers
    [ -n "$TARGET_MODULE" ] && _cq rdeps "$TARGET_MODULE" --top 10  # importer blast-radius
    [ -n "$TARGET_MODULE" ] && _cq uncovered --top 20 "$TARGET_MODULE"  # test gaps
    echo "codemap_evidence: queries_run=${_CM_N} hits=${_CM_H}"
fi
```

> Query map:
> - `central --top 5` — global blast-radius baseline
> - `fn-rdeps --exclude-tests` — direct callers of the edited function (skip redundant caller-walk reads)
> - `rdeps --top 10` — modules importing the edited target; risk tier by count: `>=5` HIGH, `1–4` MODERATE, `0` LOW
> - `uncovered --top 20` — public symbols in the target module with no test coverage

Prepend `## Structural Context (codemap)` block with this output to relevant agent spawn prompt. `scan-query` not found or index missing: emit ⚠ stderr warning, proceed with file-read context. Codemap is primary navigation tool — don't grep/Read to re-verify what it already returned.
