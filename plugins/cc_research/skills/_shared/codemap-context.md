<!-- file: codemap-context.md — consumers: research/skills/run, verify -->

**Structural context (codemap-py)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent.

Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file — typically module/function the experiment or verification edits. Both empty → only global `central` baseline runs.

```bash
_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)   # `basename ""` exits 0, so `||` never fired
[ -n "$_ROOT" ] || _ROOT="$PWD"
PROJ=$(basename "$_ROOT")   # raw basename — scanner writes it verbatim, never sanitized
_IDX="${CODEMAP_INDEX_DIR:-$_ROOT/.cache/codemap}"   # root-anchored: skill may run from a subdir
if command -v codemap-py >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    codemap-py index --incremental 2>/dev/null || true   # refresh SHA-changed files only; never full-build mid-task
    _CM_N=0 _CM_H=0
    _cq() {
        local out; _CM_N=$((_CM_N+1))
        out=$(codemap-py query --timeout 5 "$@" 2>/dev/null)
        case "$out" in
            *'"error"'*|'') ;;
            *) _CM_H=$((_CM_H+1)); printf '%s\n' "$out" ;;
        esac
    }
    _cq central --top 5
    [ -n "$TARGET_FN" ]     && _cq fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests  # direct callers
    [ -n "$TARGET_MODULE" ] && _cq rdeps "$TARGET_MODULE" --top 10  # importer blast-radius
    [ -n "$TARGET_MODULE" ] && _cq uncovered --top 20 "$TARGET_MODULE"  # test gaps
fi
```

> Query map:
>
> - `central --top 5` — global blast-radius baseline
> - `fn-rdeps --exclude-tests` — direct callers of the edited function (skip redundant caller-walk reads)
> - `rdeps --top 10` — modules importing the edited target; risk tier by count: `>=5` HIGH, `1–4` MODERATE, `0` LOW
> - `uncovered --top 20` — public symbols in the target module with no test coverage

Prepend `## Structural Context (codemap-py)` block with this output to relevant agent spawn prompt, followed by this **codemap-first protocol** (own copy — self-contained, no cross-plugin reference):

1. **Skill-first**: consult the structural context above BEFORE any Grep/Glob/Read aimed at imports, callers, or test coverage for a symbol already listed there — never re-derive what's already answered.
2. **Bounded call budget**: context above insufficient for a symbol not listed → agent may run `codemap-py query` directly, max 3 additional queries this task.
3. **Hard stop on `query_complete: true`**: any codemap-py result carrying `query_complete: true` (or legacy `exhaustive: true`) is final for that query direction — write the answer immediately, no follow-up Grep/Read/query to re-confirm it.

For symbols listed in `fn-rdeps`/`rdeps`/`uncovered` above: trust codemap-py output as-is. Fall back to file reads only when codemap-py output is empty for a symbol you need, or a result shows `query_complete: false`/`degraded` and you must confirm by hand.

`codemap-py` not found, index missing, or block above produced no output (`CODEMAP_ENABLED=false`): omit the protocol paragraph entirely — agent proceeds with normal file-read behaviour.
