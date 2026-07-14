<!-- file: codemap-gates.md — consumers: develop/skills/fix, feature, refactor, debug, plan, review -->

**Wrapper** — Gate A / Gate B machinery lives in codemap-shipped gates contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap/*/skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap/skills/_shared"
[ -f "$_CM_SHARED/codemap-gates.md" ] && echo "$_CM_SHARED/codemap-gates.md" || echo "codemap gates contract absent — use fallback below"
```

Read currency: `CODEMAP_CURRENCY=$(cat "${TMPDIR:-/tmp}/dev-codemap-currency" 2>/dev/null || echo "no_index")`.

Read `$_CM_SHARED/codemap-gates.md` (contract `v2`) and follow both gates with develop's skip flag:
- **Gate A — missing index**: fire when `CODEMAP_ENABLED=false` and `CODEMAP_RAW=auto`.
- **Gate B — stale index**: fire when `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`.

Each gate's `AskUserQuestion` prompt, options, and on-choice actions (build via `codemap:scan-codebase`, continue, abort/skip) in contract — apply verbatim.

**Fallback when codemap plugin absent** (`$_CM_SHARED/codemap-gates.md` missing): skip both gates, proceed with `CODEMAP_ENABLED` as-is — no structural gating, file-read context only. Never break load.
