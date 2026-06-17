<!-- file: codemap-context.md — consumers: plugins/develop/skills/{plan,fix,feature,refactor,review}/SKILL.md, plugins/oss/skills/review/SKILL.md -->

**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent.

Callers may pre-set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare function name) before reading this file. Both empty → only the global `central` baseline runs.

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    scan-index --incremental 2>/dev/null || true   # refresh SHA-changed files only; never full-build mid-task
    scan-query --timeout 5 central --top 5 2>/dev/null
    [ -n "$TARGET_FN" ] && scan-query --timeout 5 fn-blast "${TARGET_MODULE}::${TARGET_FN}" 2>/dev/null
    [ -n "$TARGET_MODULE" ] && scan-query --timeout 5 uncovered --top 20 "$TARGET_MODULE" 2>/dev/null
    [ -n "$TARGET_FN" ] && scan-query --timeout 5 mock-rdeps "${TARGET_MODULE}::${TARGET_FN}" 2>/dev/null
    [ -n "$TARGET_MODULE" ] && scan-query --timeout 5 undocumented "$TARGET_MODULE" 2>/dev/null
    [ -n "$TARGET_FN" ] && scan-query --timeout 5 symbol --with-imports "$TARGET_FN" 2>/dev/null
fi
```

> Query map (per agent dimension):
> - `central --top 5` — global blast-radius baseline (sw-engineer, architect)
> - `fn-blast` — caller impact before editing (sw-engineer)
> - `uncovered --top 20` — test gaps (qa-specialist)
> - `mock-rdeps` — test mock coverage; prevents false "untested" on mocked symbols (qa-specialist)
> - `undocumented` — docstring gaps (doc-scribe)
> - `symbol --with-imports` — contract reading without re-reading the file (all agents)

Results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt with hotspot JSON and per-query output. `scan-query` not found or index missing: proceed silently — no mention to user.

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
