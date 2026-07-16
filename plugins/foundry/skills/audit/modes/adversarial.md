# Adversarial Mode — foundry:audit

Triggered by `/audit --adversarial` (alias: `--challenge`). Read+executed by `/audit` when `--adversarial` flag present.

## Mode: adversarial (alias: --challenge)

**Trigger**: `/audit [<scope>...] --adversarial`

Adversarial review of all agents + skills in scope. Runs parallel with or after standard per-file audit (Step 3). Surfaces issues curator pass misses: subtle logic flaws, inconsistent claims, NOT-for gaps, scope leakage, cross-file contradictions, security vulnerabilities in bin/ executables.

**Phase A — Challenger sweep** (parallel with Phase B):

For each file in scope (Step 2 inventory; default all agents + skills if no explicit scope), spawn **foundry:curator** (config-file adversarial review — `foundry:challenger`'s NOT-for excludes config-file review; routes to `foundry:curator`):

> "Adversarially challenge this agent/skill. Do NOT accept claims at face value. Find: (1) unstated assumptions that will fail in edge cases, (2) NOT-for coverage gaps — tasks this agent will wrongly accept because exclusions are incomplete, (3) conflicting instructions that produce non-deterministic or contradictory behavior, (4) workflow steps that would route to the wrong sub-agent for the stated goal, (5) implicit scope that contradicts explicit NOT-for lines. Report every finding with specific evidence from the file."
> Write full findings to `<RUN_DIR>/challenger-<file-slug>.md` where `<file-slug>` = `<plugin>-<skill-dir-name>` for skills or `<plugin>-<agent-name>` for agents (e.g. `foundry-audit`, `oss-review`, `foundry-curator`); `.claude/` files prefix `local`. Never use bare `challenger-SKILL.md`. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"security":N,"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use `ADVERSARIAL_BATCH_SIZE` (default 2) for grouping — smaller batches than Step 3 (`BATCH_SIZE=5`) to maximise per-file attention depth. Same plugin-aware batching algorithm applies; substitute `ADVERSARIAL_BATCH_SIZE` for `BATCH_SIZE`.

**Phase A-prime — Unconstrained curator pass** (parallel with Phase A and Phase B):

For each file in scope, spawn **foundry:curator** with no scope constraint:

> "Audit this file. Run `cat "$AUDIT_TPL/curator-prompt.md"` via the Bash tool and use it as your baseline checklist — apply all those checks. Then go beyond: report ANY additional issue you observe that falls outside the explicit checklist. Look especially for: execution continuing after a confirmed failure path with no `exit 1`; incomplete specifications that would leave an agent uncertain at a branch point; undocumented implicit dependencies (env vars, files, network) not declared in inputs; workflow logic that is self-consistent but would silently produce wrong results on a valid non-happy-path input. No scope constraint — senior-engineer judgment applies."
> Write full findings to `<RUN_DIR>/deep-curator-<file-slug>.md` using same `<file-slug>` convention as Phase A. Return ONLY: `{"status":"done","file":"<path>","findings":N,"severity":{"security":N,"critical":N,"high":N,"medium":N,"low":N},"confidence":0.N}`

Use `ADVERSARIAL_BATCH_SIZE` grouping. Phase C deduplicates Phase A-prime findings against `summary.jsonl` from Steps 3–6 in SAME RUN_DIR only — not against prior runs. In adversarial-only mode (no same-run standard audit), all Phase A-prime findings carried forward.

**Phase B — Codex adversarial pass** (parallel with Phase A):

```bash
CODEX_AVAILABLE=$(command -v codex 2>/dev/null || find ~/.claude/plugins/cache -name "codex*" -type d 2>/dev/null | head -1)  # timeout: 5000
_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
[ -f "$_SHARED/codex-prepass.md" ] || { printf "⚠ WARNING: codex-prepass.md not found at $_SHARED — skipping codex pre-pass\n"; CODEX_AVAILABLE=""; }
[ -n "$CODEX_AVAILABLE" ] && cat "$_SHARED/codex-prepass.md"
```

If `$CODEX_AVAILABLE` non-empty: apply the codex-prepass.md instructions above, run Codex pass on all in-scope files. Focus Codex on: cross-file inconsistencies, circular dispatch chains, agent description ambiguities causing routing failures, workflow steps assuming capabilities declared tools don't provide. Else: `echo "⚠ codex plugin not available — skipping codex adversarial pass"`.

Codex writes per-file findings to `<RUN_DIR>/codex-adversarial-<file-basename>.md`. Return compact JSON envelope per file.

**Phase D — Security & Vulnerability Review** (parallel with Phases A, A-prime, B):

Scope resolution — map audit scope tokens to plugin directories, collect all bin/ scripts:
- Default (full sweep): all `plugins/*/bin/*.py` and `plugins/*/bin/*.sh`
- Named scope (e.g. `foundry`, `oss`, `codemap`): `plugins/<name>/bin/*.py` and `plugins/<name>/bin/*.sh`
- `--local` mode: same paths from `plugins/` source tree; non-local: same paths under `~/.claude/plugins/cache/borda-ai-rig/`
- Zero bin/ scripts found for scope: skip Phase D, note in report

Per-plugin security sweep — for each plugin in scope with bin/ scripts, spawn **foundry:qa-specialist**:

> "Security and vulnerability review of all bin/ scripts in `plugins/<name>/bin/`. You are a black-box security reviewer — focus on executable surface only, not callers. Review every `.py` and `.sh` file in the directory. For Python scripts: check OWASP Top 10 applicability, specifically: (1) injection — `subprocess` calls with `shell=True` or string-concatenated command args; (2) path traversal — unvalidated file paths from argv; (3) insecure deserialization — `pickle.load`, `yaml.load` without `Loader`; (4) hardcoded secrets — API keys, tokens, passwords in source; (5) uncontrolled resource consumption — unbounded loops or file reads without size check. For shell scripts: (1) unquoted variable expansion in command positions; (2) `eval` with external input; (3) `rm -rf` with unvalidated variable path; (4) hardcoded credentials. Write full findings per file to `<RUN_DIR>/security-<plugin-name>.md`. Return ONLY: `{\"status\":\"done\",\"file\":\"<path>\",\"scripts_reviewed\":N,\"findings\":N,\"severity\":{\"critical\":N,\"high\":N,\"medium\":N,\"low\":N},\"confidence\":0.N}`"

Use `BATCH_SIZE` (not `ADVERSARIAL_BATCH_SIZE`) for Phase D — bin/ scripts are shorter and security checks deterministic; BATCH_SIZE=5 fine here. Plugin with ≤5 bin/ scripts: one foundry:qa-specialist spawn covers all; larger sets batch by 5.

Phase D runs parallel with Phases A, A-prime, and B — same async launch pattern.

**Phase C — Aggregate and deduplicate**:

Spawn **foundry:curator** consolidator to merge Phase A + Phase A-prime + Phase B + Phase D findings. Cross-reference against standard audit `summary.jsonl` (same RUN_DIR). Surface only findings NOT already in standard audit — adversarial adds signal, not noise.

In adversarial-only mode (`--adversarial` flag without preceding standard audit in same RUN_DIR), no `summary.jsonl` exists in this RUN_DIR. Skip dedup entirely — surface all adversarial findings without overlap filtering. Do NOT dedup against prior audit runs in `.reports/audit/`; prior runs may have unresolved findings still needing fixing.

Write deduplicated findings to `<RUN_DIR>/adversarial-aggregate.md` and `<RUN_DIR>/adversarial-summary.jsonl` (same JSONL format as Step 5). Return: `{"status":"done","new_findings":N,"overlapping":N,"severity":{"security":N,"critical":N,"high":N,"medium":N,"low":N}}`

**Report format**:

```markdown
## Adversarial Audit — <date> — <scope>

| File | Challenger | Deep-curator | Codex | Security | New Findings | Top Issue |
|------|-----------|--------------|-------|----------|--------------|-----------|
| agents/curator.md | 3 | 1 | 1 | 0 | 2 | NOT-for gap: accepts task X |
```

Adversarial findings feed into standard fix pipeline (Steps 7–10) when user picks fix level from follow-up gate.

**Adversarial-only runs** (no standard audit in same RUN_DIR): skip Steps 3–6; run only Phases A–D above; skip Phase C dedup; report all adversarial findings. Standard findings from prior `.reports/audit/` runs NOT consulted for dedup — user may not have fixed them yet.

**Flag aliases**: `--adversarial` and `--challenge` are identical — either triggers this mode.
