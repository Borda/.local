<!-- file: codemap-gates.md — consumers: research/skills/run, verify -->

**Wrapper** — Gate A / Gate B machinery lives in codemap-shipped gates contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap-py/*/claude-skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap-py/claude-skills/_shared"
[ -f "$_CM_SHARED/codemap-gates.md" ] && cat "$_CM_SHARED/codemap-gates.md" || echo "codemap gates contract absent — use fallback below"
```

Read currency: `IFS= read -r CODEMAP_CURRENCY < "${TMPDIR:-/tmp}/research-codemap-currency-${CSID}" 2>/dev/null || CODEMAP_CURRENCY="no_index"`.

Contract (`v2`) — follow both gates with research's skip flag:

- **Gate A — missing index**: fire when `CODEMAP_ENABLED=false` and `CODEMAP_RAW=auto`.
- **Gate B — stale index**: fire when `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`.

Each gate's `AskUserQuestion` prompt, options, and on-choice actions (continue, abort/skip) in contract — apply as written, no consumer override: the contract's own build/rebuild action is the gated `codemap-py index` dispatcher.

**Fallback when codemap-py plugin absent** (`$_CM_SHARED/codemap-gates.md` missing): skip both gates, proceed with `CODEMAP_ENABLED` as-is — no structural gating, file-read context only. Never break load.
