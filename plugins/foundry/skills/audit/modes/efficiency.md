# Efficiency Mode — foundry:audit

Triggered by `/audit --efficiency`. Read+executed by `/audit` when `--efficiency` flag present.

## Mode: efficiency

**Trigger**: `/audit [<scope>...] --efficiency`

Sweeps agents and skills for cost inefficiency signals. Does NOT run standard per-file quality audit (Steps 3–6) — efficiency-only analysis. Generates prioritized cost-reduction plan with estimated savings.

**Scope resolution**: same as standard audit. No scope = all agents + skills across plugins + `.claude/`. Named scope = union of resolved file sets.

**Phase A — Per-file efficiency audit** (parallel foundry:curator spawns, same BATCH_SIZE):

Spawn **foundry:curator** per file with efficiency-specific prompt:

> Audit `<file>` for cost and efficiency signals only. Do NOT run general quality checks. Check:
> 1. **Model tier**: is `model:` declared? If `model: opus` or `model: opusplan`, does task genuinely require reasoning depth — adversarial multi-step analysis, architectural design, complex implementation? Flag if task is primarily: template fill, pattern matching, structured summarization, orchestrator-only dispatch, or single-pass structured write.
>    **Performance-safety sub-check (mandatory before any downgrade recommendation)**: does the agent produce quality-sensitive output? Quality-sensitive signals: public-facing text (contributor replies, blog posts), security analysis (OWASP, exploit reasoning), adversarial reasoning, complex multi-file code design, creative original content. If any signal present, add `performance_risk: medium|high` to the finding and require empirical validation note — do NOT recommend downgrade as P1/P2 without this caveat. A lower-cost model that degrades output quality is not an efficiency gain.
> 2. **Effort level**: is `effort: xhigh` declared? Flag if agent is read-only, single-pass, or executes a fixed decision tree — xhigh planning budget has nowhere to spend. Exception: `xhigh` on a quality-sensitive sonnet agent is acceptable as a compensating signal — Claude Code docs note "available levels depend on the model" so runtime behaviour may cap at `high`, but the combination is valid and signals intent; do not flag as waste.
> 3. **Missing model declaration**: no `model:` AND no `disable-model-invocation: true` → session model inherited; flag with recommended tier (opus/sonnet/haiku based on role complexity).
> 4. **Dead model spec**: `model:` declared + `disable-model-invocation: true` → model never runs; spec is vestigial and misleading.
> 5. **Token bloat**: identify inline reference blocks >40 lines that load unconditionally but apply only to a subset of invocations (e.g., ML-specific patterns for non-ML projects, hook authoring for non-hook tasks, domain CI blocks always loaded). Flag with estimated line count and suggested gate/extraction.
> 6. **Tool grant scope**: does `tools:` or `allowed-tools:` include `*` or tools not referenced anywhere in workflow body? Flag unused grants as cleanup candidates.
> Write findings to `<RUN_DIR>/efficiency-<file-basename>.md`.
> Return ONLY: `{"status":"done","file":"<path>","issues":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"top_issue":"<one-line>","cheapest_viable_model":"<model or unchanged>","confidence":0.N}`

**Phase B — System-wide spawn pattern + duplication scan** (parallel with Phase A):

```bash
# Unbounded per-item agent spawns (no cap near spawn site)
echo "=== Unbounded spawn patterns ==="
grep -rn "Agent(" plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null \
  | grep -i "per.*finding\|per.*item\|per.*action\|each.*finding\|each.*item\|each.*action" \
  | grep -v "cap\|MAX_\|CAP_\|max_\|# max\|# Cap\|# limit\|LIMIT_" \
  || echo "none found"

# Dead model specs: model: declared + disable-model-invocation: true
echo "=== Dead model specs ==="
for f in plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  grep -q "^model:" "$f" && grep -q "disable-model-invocation: true" "$f" && echo "DEAD_SPEC: $f"
done

# Skills missing model declaration (and not disable-model-invocation)
echo "=== Missing model declarations ==="
for f in plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md; do
  [ -f "$f" ] || continue
  grep -q "disable-model-invocation: true" "$f" && continue
  grep -q "^model:" "$f" || echo "NO_MODEL: $f"
done

# Agents missing model declaration
for f in plugins/*/agents/*.md .claude/agents/*.md; do
  [ -f "$f" ] || continue
  grep -q "^model:" "$f" || echo "NO_MODEL: $f"
done

# Boilerplate duplication counts
echo "=== Boilerplate duplication ==="
AGENT_RES=$(grep -rl "_SHARED=\$(ls -td.*plugins/cache" plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null | wc -l | tr -d ' ')
FLAG_CHECK=$(grep -rl "Unknown flag" plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null | wc -l | tr -d ' ')
HEALTH_MON=$(grep -rl "MONITOR_INTERVAL=" plugins/*/skills/*/SKILL.md .claude/skills/*/SKILL.md 2>/dev/null | wc -l | tr -d ' ')
echo "agent-resolution boilerplate: $AGENT_RES files"
echo "unsupported-flag-check boilerplate: $FLAG_CHECK files"
echo "health-monitoring constants: $HEALTH_MON files"
```

**Phase C — Aggregate, score, and plan** (after A+B complete):

Spawn **foundry:curator** consolidator to merge all findings:

> Read all per-file reports from `<RUN_DIR>/efficiency-*.md`. Also read Phase B bash output passed as context.
> Produce a cost-reduction report with these sections:
> 1. **Cheapest Viable Model table** — one row per agent/skill with cost issue: `| file | current model+effort | minimum viable | rationale | estimated saving |`; saving = opus→sonnet ≈70%, opusplan→sonnet ≈70%, xhigh→high ≈25%, xhigh→medium ≈35%
> 2. **Dead Model Specs** — list files with contradictory model+disable-model-invocation; exact fix (remove `model:` line)
> 3. **Unbounded Spawn Patterns** — list files with uncapped per-item agent dispatch; recommended cap and batch strategy
> 4. **Token Bloat Hotspots** — top 5 files by redundant inline content; section name, line count, suggested action
> 5. **Boilerplate Duplication** — pattern name × occurrence count × total redundant lines × extraction target
> 6. **Missing Model Declarations** — list files inheriting session model; recommended tier per file
> 7. **Prioritized Improvement Plan** — P1 (critical: correctness/highest cost), P2 (high: model downgrades), P3 (medium: hygiene/dedup), P4 (low: compression); each item: file + exact change + estimated saving + `performance_risk: low|medium|high`. Items with `performance_risk: high` are automatically downgraded to P-HOLD (do not apply without empirical benchmarking). Items with `performance_risk: medium` stay in plan but carry a `⚠ validate first` marker.
> 8. **Estimated Combined Savings** — rough % reduction for most common workflows if all P1+P2 applied
> Write full report to `<RUN_DIR>/efficiency-report.md`.
> Return ONLY: `{"status":"done","file":"<RUN_DIR>/efficiency-report.md","critical":N,"high":N,"medium":N,"low":N,"total_issues":N,"top_saving":"<description>","confidence":0.N}`

**Report format** (terminal summary):

```
verdict: EFFICIENCY_ISSUES · critical: N · high: N · medium: N · low: N · confidence: 0.N
→ <RUN_DIR>/efficiency-report.md

Critical: [list each]
Estimated savings (P1+P2): ~X%
```

Efficiency findings feed into standard fix pipeline (Steps 7–10) when user picks fix level from follow-up gate.

**Flag aliases**: `--efficiency` only (no alias).
