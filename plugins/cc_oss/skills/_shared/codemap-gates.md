<!-- file: codemap-gates.md — consumers: oss/skills/review, resolve -->

**Wrapper** — the Gate A / Gate B machinery lives in the codemap-shipped gates contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap-py/*/claude-skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap-py/claude-skills/_shared"
[ -f "$_CM_SHARED/codemap-gates.md" ] && cat "$_CM_SHARED/codemap-gates.md" || echo "codemap gates contract absent — use fallback below"
```

`CODEMAP_CURRENCY` is set by the calling skill (`oss:review`, `oss:resolve`) before reading this file.

Contract `v2` (loaded above, when present) — follow both gates with oss's skip flag:
- **Gate A — missing index**: fire when `CODEMAP_ENABLED=false` and `CODEMAP_FORCE_OFF=false`.
- **Gate B — stale index**: fire when `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`.

Each gate's `AskUserQuestion` prompt, options, and on-choice actions (build via the `scan-index` binary, continue, abort/skip) are in the contract — apply verbatim.

**Fallback when the codemap plugin is absent** (`$_CM_SHARED/codemap-gates.md` missing): skip both gates and proceed with `CODEMAP_ENABLED` as-is — no structural gating, file-read context only. Never break the load.
