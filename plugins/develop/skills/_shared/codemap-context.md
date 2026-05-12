**Structural context (codemap)** — run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent:

```bash
PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename)
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/scan/${PROJ}.json" ]; then
    scan-query central --top 5
fi
```

Results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt with hotspot JSON. `scan-query` not found or index missing: proceed silently — no mention to user.

**Semble companion** — include in agent spawn prompt only when caller sets `SEMBLE_ENABLED=true`; skip if flag absent:

> `mcp__semble__search` available and codemap non-exhaustive (`"exhaustive": false`) or no index found: call `mcp__semble__search` with varied queries (e.g. `"<module> import"`, `"from <module> import"`, `"<module> usage"`) and `repo=<git_root>`, `top_k=20`. Stop when two consecutive queries return no new modules. Merge all results into final rdep set — union of codemap + all semble calls. Codemap exhaustive: skip semble.
