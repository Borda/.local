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
               case "$out" in *'"exhaustive":false'*|*'"exhaustive": false'*) _CM_NONEXH=1;; esac ;;
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

Results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt with hotspot JSON and per-query output. `codemap_evidence:` line at end of block reports retrieval reliability — agents may skip re-querying only when `completeness=exhaustive`. `scan-query` not found or index missing: proceed silently — no mention to user.

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
scan-query --timeout 5 fn-blast    "${MODULE}::${FN}"   2>/dev/null  # blast radius (v3)
scan-query --timeout 5 mock-rdeps  "${MODULE}::${FN}"   2>/dev/null  # mock coverage (v4.1)
scan-query --timeout 5 uncovered   --top 20 "$MODULE"   2>/dev/null  # test gaps (v4.2)
scan-query --timeout 5 xrefs --broken      "$MODULE"    2>/dev/null  # stale doc refs (v4.5)
scan-query --timeout 5 undocumented "$MODULE"  2>/dev/null  # doc coverage (v4.4)
```

> Per-agent consumption:
> - `qa-specialist` — read `uncovered` + `mock-rdeps` first; skip manual test-file grep for symbols codemap already classifies; fall back to Read only when codemap context absent or insufficient
> - `doc-scribe` — read `undocumented` + `xrefs --broken` first; skip docstring-scan reads on listed symbols
> - `sw-engineer` — read `fn-blast` first; skip caller-walk reads when blast list complete
> - `challenger` — unchanged; always reads source directly

**Semble companion** — include in agent spawn prompt only when caller sets `SEMBLE_ENABLED=true`; skip if flag absent:

> `mcp__semble__search` available and codemap non-exhaustive (`"exhaustive": false`) or no index found: call `mcp__semble__search` with varied queries (e.g. `"<module> import"`, `"from <module> import"`, `"<module> usage"`) and `repo=<git_root>`, `top_k=20`. Stop when two consecutive queries return no new modules. Merge all results into final rdep set — union of codemap + all semble calls. Codemap exhaustive: skip semble.
