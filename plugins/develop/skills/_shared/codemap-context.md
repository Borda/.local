**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent:

```bash
PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename)
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ]; then
    scan-query central --top 5
fi
```

Results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt with hotspot JSON. `scan-query` not found or index missing: proceed silently — no mention to user.

## Extended scan — multi-file / API changes

When task touches multiple modules or changes public API surface, run per-affected-module reverse-dependency scan:

```bash
# Diff-mode: auto-derive affected modules from git diff HEAD and run rdeps + coupled in one call
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap_scan.py" --source=diff  # timeout: 15000
# Interpret: any rdeps output = external callers affected; coupled output = co-change pairs
# Fallback (specific known module): scan-query rdeps <mod> --top 10 2>/dev/null || true

# Risk tier based on rdep_count:
# rdep_count >= 5  → HIGH blast radius — flag to user before proceeding
# rdep_count 1–4  → MODERATE — note in plan/report
# rdep_count 0    → LOW — proceed normally
```

**Semble companion** — include in agent spawn prompt only when caller sets `SEMBLE_ENABLED=true`; skip if flag absent:

> `mcp__semble__search` available and codemap non-exhaustive (`"exhaustive": false`) or no index found: call `mcp__semble__search` with varied queries (e.g. `"<module> import"`, `"from <module> import"`, `"<module> usage"`) and `repo=<git_root>`, `top_k=20`. Stop when two consecutive queries return no new modules. Merge all results into final rdep set — union of codemap + all semble calls. Codemap exhaustive: skip semble.
