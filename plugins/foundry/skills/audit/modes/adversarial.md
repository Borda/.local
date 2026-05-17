# Adversarial Mode — foundry:audit

Triggered by `/audit --adversarial` (alias: `--challenge`). Read+executed by `/audit` when `--adversarial` flag present.

## Mode: adversarial (alias: --challenge)

**Trigger**: `/audit [<scope>...] --adversarial`

Adversarial review of all agents + skills in scope. Runs parallel with or after standard per-file audit (Step 3). Surfaces issues curator pass misses: subtle logic flaws, inconsistent claims, NOT-for gaps, scope leakage, cross-file contradictions.

**Phase A — Challenger sweep** (parallel with Phase B):

For each file in scope (Step 2 inventory; default all agents + skills if no explicit scope), spawn **foundry:challenger**:

> "Adversarially challenge this agent/skill. Do NOT accept claims at face value. Find: (1) unstated assumptions that will fail in edge cases, (2) NOT-for coverage gaps — tasks this agent will wrongly accept because exclusions are incomplete, (3) conflicting instructions that produce non-deterministic or contradictory behavior, (4) workflow steps that would route to the wrong sub-agent for the stated goal, (5) implicit scope that contradicts explicit NOT-for lines. Report every finding with specific evidence from the file."
> Write full findings to `<RUN_DIR>/challenger-<file-slug>.md` where `<file-slug>` = `<plugin>-<skill-dir-name>` for skills or `<plugin>-<agent-name>` for agents (e.g. `foundry-audit`, `oss-review`, `foundry-curator`); `.claude/` files prefix `local`. Never use bare `challenger-SKILL.md`. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use same `BATCH_SIZE` grouping as Step 3 — same plugin-aware batching applies.

**Phase A-prime — Unconstrained curator pass** (parallel with Phase A and Phase B):

For each file in scope, spawn **foundry:curator** with no scope constraint:

> "Audit this file. Read `$AUDIT_TPL/curator-prompt.md` as your baseline checklist — apply all those checks. Then go beyond: report ANY additional issue you observe that falls outside the explicit checklist. Look especially for: execution continuing after a confirmed failure path with no `exit 1`; incomplete specifications that would leave an agent uncertain at a branch point; undocumented implicit dependencies (env vars, files, network) not declared in inputs; workflow logic that is self-consistent but would silently produce wrong results on a valid non-happy-path input. No scope constraint — senior-engineer judgment applies."
> Write full findings to `<RUN_DIR>/deep-curator-<file-slug>.md` using same `<file-slug>` convention as Phase A. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use same `BATCH_SIZE` grouping. Phase C deduplicates against standard audit findings — only net-new deep-curator findings carried forward.

**Phase B — Codex adversarial pass** (parallel with Phase A):

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$("${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/find-foundry-shared.sh" 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
```

If `[ -n "$CODEX_AVAILABLE" ]`: read `$_SHARED/codex-prepass.md`, run Codex pass on all in-scope files. Focus Codex on: cross-file inconsistencies, circular dispatch chains, agent description ambiguities causing routing failures, workflow steps assuming capabilities declared tools don't provide. Else: `echo "⚠ codex plugin not available — skipping codex adversarial pass"`.

Codex writes per-file findings to `<RUN_DIR>/codex-adversarial-<file-basename>.md`. Return compact JSON envelope per file.

**Phase C — Aggregate and deduplicate**:

Spawn **foundry:curator** consolidator to merge Phase A + Phase A-prime + Phase B findings. Cross-reference against standard audit `summary.jsonl` (same RUN_DIR). Surface only findings NOT already in standard audit — adversarial adds signal, not noise.

In adversarial-only mode (`--adversarial` flag without preceding standard audit), Steps 3–6 are skipped so no `summary.jsonl` exists in RUN_DIR. Dedup against most recent standard audit `summary.jsonl` within the same RUN_DIR or from any run within the last 24h (check `.reports/audit/` for recent dirs). If no standard audit found within 24h, skip dedup and surface all adversarial findings without overlap filtering.

Write deduplicated findings to `<RUN_DIR>/adversarial-aggregate.md` and `<RUN_DIR>/adversarial-summary.jsonl` (same JSONL format as Step 5). Return: `{"status":"done","new_findings":N,"overlapping":N,"severity":{"critical":N,"high":N,"medium":N,"low":N}}`

**Report format**:

```markdown
## Adversarial Audit — <date> — <scope>

| File | Challenger | Deep-curator | Codex | New Findings | Top Issue |
|------|-----------|--------------|-------|--------------|-----------|
| agents/curator.md | 3 | 1 | 1 | 2 | NOT-for gap: accepts task X |
```

Adversarial findings feed into standard fix pipeline (Steps 7–10) when user picks fix level from follow-up gate.

**Adversarial-only runs** (no standard audit): skip Steps 3–6; run only Phases A–C above; report adversarial findings only.

**Flag aliases**: `--adversarial` and `--challenge` are identical — either triggers this mode.
