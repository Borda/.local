<!-- file: codemap-context.md — consumers: bin/_injection_block.py injection block; develop/oss wrappers (plugins/{develop,oss}/skills/_shared/codemap-context.md) reference this contract by installed-plugin cache path -->

# Codemap context contract — v2

Plugin-agnostic structural-context contract. Consumer plugins (develop, oss, any) reference this file — never copy it. Wrappers add only per-agent query maps + flag surfaces + plugin-local batch/cache paths; the query mechanics, evidence-line contract, completeness/staleness semantics, batch pre-flight, and effort tiers live here once.

> Contract version `v2` feeds the injection version check. Keep in sync with `BLOCK_VERSION` in `bin/_injection_block.py` — bump both together when the query set or evidence contract changes.

## Target derivation — pluggable (consumer supplies)

`TARGET_MODULE` (dotted) + `TARGET_FN` (bare name) are **consumer-supplied inputs** — this contract does not derive them. The consumer wrapper/SKILL sets them from `$ARGUMENTS`, a review diff, or a finding before reading this file:

- explicit `module.path` or `module.path::function` in args → split into `TARGET_MODULE` / `TARGET_FN`
- module-only known → set `TARGET_MODULE`, leave `TARGET_FN` empty
- both empty → only the global `central` baseline runs (correct when the affected surface is unknown until the agent searches)

Normalize a file path to a dotted module: strip leading `./` and `src/`, strip trailing `.py`, replace `/` with `.`.

## Core query map

- `central --top 5` — global blast-radius baseline; always safe, runs with no target.
- `fn-rdeps <mod>::<fn> --exclude-tests` — direct callers of a function; benchmarked 94k vs 1M+ tokens, +40pp accuracy; run first when a symbol is known.
- `fn-blast <mod>::<fn>` — transitive caller impact (depth > 1).
- `rdeps <mod>` — reverse module dependencies; run when only a module (no function) is known.
- `symbol --with-imports <fn>` — read a symbol's contract without re-reading the file (all agents).

> Consumer wrappers extend this map with per-agent dimensions (test gaps, doc gaps, mock coverage, etc.). Keep additions in the wrapper — not here.

## Batch pre-flight pattern

Reference bash for a single-target run. Consumers may inline it or call a plugin-local batch producer; the completeness/evidence logic below is invariant.

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
    [ -n "$TARGET_FN" ]     && _cq fn-rdeps "${TARGET_MODULE}::${TARGET_FN}" --exclude-tests
    [ -n "$TARGET_FN" ]     && _cq fn-blast "${TARGET_MODULE}::${TARGET_FN}"
    [ -z "$TARGET_FN" ] && [ -n "$TARGET_MODULE" ] && _cq rdeps "$TARGET_MODULE"
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

> The injected loader block (`bin/_injection_block.py`) runs a shorter inline variant (`central --top 3` + one derived query) and points here for the full map. `scan-query` not found or index missing → the block emits nothing and callers fall back to their normal exploration path.

## Evidence-line contract

Every run emits one `codemap_evidence:` line summarising retrieval reliability:

```
codemap_evidence: queries_run=<n> hits=<h> completeness=<exhaustive|partial|stale|unknown> index_mtime=<iso|?>
```

Completeness semantics:
- `exhaustive` — all queries hit, none stale, none direction-incomplete → consumers may **skip** re-querying (grep/read) for what codemap returned.
- `partial` — at least one result `query_complete:false` (direction-incomplete) → fill gaps via the consumer's fallback (semble, grep), not by re-running codemap.
- `stale` — index older than source (`stale:true`) → rebuild or accept reduced currency; see the gates contract.
- `unknown` — no query hit → index empty or target absent; fall back to file reads.

Consumers may skip re-querying **only** when `completeness=exhaustive`.

## Coverage metadata in output

Each `scan-query` result carries an `index` block with per-command coverage fields:
- `index.method` — analysis technique used (`static-ast`, `import-graph`, `index-lookup`, `ast-flags`).
- `index.not_covered` — what the method structurally misses (list); non-empty → surface as a scope caveat in the response; do NOT grep to fill the gap — gaps are structurally unresolvable by static analysis.
- `index.hint` — actionable alternative if deeper coverage is needed (e.g. grep pattern for hook-registered callers).
- `index.confidence: "exact"` — result is authoritative; omit verification caveats.

**Codemap = primary codebase navigation tool.** Do NOT grep/bash to re-verify what codemap already returned. When `not_covered` non-empty: (1) include a one-line caveat — "Note: callers via [not_covered items] not included — structurally invisible to static AST"; (2) log the gap:
```bash
mkdir -p .cache/codemap
printf '{"ts":"%s","cmd":"%s","target":"%s","not_covered":%s,"hint":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "<subcommand>" "<target>" '<not_covered_json>' "<hint_or_empty>" \
    >> .cache/codemap/gaps.jsonl 2>/dev/null || true
```
(3) Continue achieving the goal — do NOT abandon the task because of a structural gap.

When `method=index-lookup` + `confidence=exact`: result authoritative, skip verification caveats.

## Effort-tier guidance

Scale the query set to the task blast-radius; more queries cost more tokens.

- **quick** (single-symbol edit, known target): `central --top 3` + `fn-rdeps`. Skip the transitive walk.
- **standard** (feature/fix touching one module): add `fn-blast` + `symbol --with-imports`; add the wrapper's per-agent dimensions.
- **deep** (multi-module / public-API change): run the per-affected-module reverse-dependency batch (below) and tier the blast radius.

## Extended scan — multi-file / API changes

When a task touches multiple modules or changes public-API surface, run a per-affected-module reverse-dependency scan. Interpret: any `rdeps` output = external callers affected; `coupled` output = co-change pairs. Fallback for one known module: `scan-query rdeps <mod> --top 10 2>/dev/null || true`.

Risk tier by `rdep_count`:
- `>= 5` → HIGH blast radius — flag before proceeding.
- `1–4` → MODERATE — note in plan/report.
- `0` → LOW — proceed normally.

> The batch producer (a plugin `bin/` script or an inline per-module loop) and any persisted-cache artifact are plugin-local — those paths live in the wrapper, not here.

## Targeted-edit pattern (known symbol, large file)

Known symbol + file >~300 lines: `symbol <mod::name>` → take the line span → `Read(offset=span_start−10, limit=span_len+20)` → Edit. A slice Read suffices — Edit needs only a slice containing the target, not the whole file. Spans come from the index; file changed since scan → spans may drift (self-heal usually covers it). Edit errors "Found N matches" (`old_string` not file-wide unique) or no-match (drifted) → full `Read`, then Edit with a larger unique `old_string`.

## Result-prepend contract

Prepend returned results as a `## Structural Context (codemap)` section to any agent spawn prompt, with hotspot JSON + per-query output. The `codemap_evidence:` line at the end of the block reports retrieval reliability; agents may skip re-querying only when `completeness=exhaustive`. `scan-query` unavailable or index missing → emit a one-line ⚠ to stderr and proceed with file-read context.
