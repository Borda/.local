<!-- file: codemap-context.md — consumers: codemap-py `integrate apply` (managed-block host, CONSUMER_MANAGED_FILE["foundry"]); foundry agents run the equivalent pre-flight inline in their own <codemap_context> block and do not read this file yet -->

**Structural context (codemap-py) — foundry wrapper.** Provider ships the shared mechanics; this file adds only the foundry-specific dimension. Run only when caller sets `CODEMAP_ENABLED=true`; skip if flag absent.

**Wrapper** — target derivation, query mechanics, evidence-line contract, completeness/staleness semantics, effort tiers all live in the codemap-shipped contract. Resolve and read it:

```bash
_CM_SHARED="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap-py/*/claude-skills/_shared 2>/dev/null | head -1)"
[ -z "$_CM_SHARED" ] && _CM_SHARED="plugins/codemap-py/claude-skills/_shared"
[ -f "$_CM_SHARED/codemap-context.md" ] && cat "$_CM_SHARED/codemap-context.md" || echo "codemap contract absent — use fallback below"
```

Contract (`v3`) — follow §Target derivation, §Core query map, §Evidence-line contract, §Effort-tier guidance.

## Per-agent query map (foundry dimension)

Extends the contract core map. Each entry is the dimension that agent's own pre-flight already runs — keep the two in sync when either changes:

- `foundry:sw-engineer` — `central --top 5`, `rdeps`, `fn-rdeps`, `fn-blast`, `symbol`
- `foundry:qa-specialist` — `uncovered --top 20`, `coverage-gap --threshold 0.8`, `mock-rdeps`, `fixture-rdeps`, `fixture-graph`
- `foundry:doc-scribe` — `undocumented`, `xrefs --broken`
- `foundry:solution-architect` — `central --top 5`, `rdeps` (fan-in), `deps` (fan-out), `xrefs`
- `foundry:perf-optimizer` — `central --top 5`, `subprocess-deps`, `fn-blast`, `fixture-rdeps`, `fixture-graph`
- `foundry:challenger` — `central --top 5`, `rdeps`, `fn-blast`

**Bounded call budget + hard stop** — symbol not covered by the pre-flight above → up to 3 additional `codemap-py query` calls this task. Any result carrying `query_complete: true` (or legacy `exhaustive: true`) is final for that direction: no follow-up Grep/Read/query to re-confirm it.

**Fallback when the codemap plugin is absent** (`$_CM_SHARED/codemap-context.md` missing): run only `codemap-py query --timeout 5 central --top 5 2>/dev/null`; treat any non-empty output as usable, skip evidence-line/completeness logic, proceed with file reads. Never break the load.

## Managed-block host

This file is `CONSUMER_MANAGED_FILE["foundry"]` — the consumer-owned host for the `codemap-py.integration.v2` managed-block body. It ships **without** one: `codemap-py integrate plan` records a first-time insert and `integrate apply` appends the `<!-- codemap-py:integration:begin v1 sha256=... -->` … `end` block at EOF, per install. The sentinel schema remains `v1`; the body declares protocol `codemap-py.integration.v2`. Never hand-author that block — the engine refuses any block whose body hash does not match its marker.
