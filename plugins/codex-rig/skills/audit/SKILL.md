---
name: audit
description: "Audit Codex configuration, workflow, and prompt-efficiency (instruction cost, value-per-token) drift; emit ranked gaps and measurable gates."
---

# Audit

Run linear configuration/workflow audit.

## Input Schema

```json
{
  "scope": "config|skills|roles|all",
  "target": "optional path",
  "mode": "upgrade|adversarial",
  "axis": "standard|value-per-token",
  "min_cost_reduction": "optional fraction; default 0.05 for value-per-token acceptance",
  "skip_gate": false,
  "done_when": "drift and broken references are ranked with gate result; fix level chosen interactively unless skip_gate=true"
}
```

## Workflow (Exact Commands)

### 01: Create run directory

Per `../../shared/helper-cli-contract.md`, run `python PLUGIN_ROOT/shared/create_run.py --skill audit` once; stdout is literal `<run-directory>`; never store it in a shell variable.

### 02: Normalize scope and collect inventory

Scopes:

- `config`: project `.codex/config.toml`, `AGENTS.md` layers, permissions, and routing.
- `skills`: repository/user-authored `.agents/skills/**` plus declared calibration coverage.
- `roles`: role-routing instructions and an explicitly supplied plugin/package role-card root.
- `all`: every applicable surface above. Missing optional local skills or roles is `not-configured`, not drift.

Run `rg --files` with the `AGENTS.md`, `.codex/config.toml`, and `.agents/skills/**` globs as argv. When `target` is
supplied and exists, enumerate regular files under it to depth four with a platform-native filesystem walk. Sort and
deduplicate both result sets into `<run-directory>/inventory.txt`; record unavailable inputs or collection failures.

### 03: Build an audit ledger before running gates

Write `<run-directory>/audit-ledger.md` with these sections:

- `Inventory`: configured/present policy, skills, and role-routing surfaces.
- `Broken References`: missing files, stale paths, unresolved shared resources.
- `Runtime Leaks`: non-native runner fields/external runtime assumptions.
- `Coverage`: calibration benchmark/behavior.
- `Overlap`: duplicate/fuzzy ownership decisions.
- `Prompt Efficiency`: instruction cost, loaded context, obligation preservation, and value-guard evidence.
- `Recommendations`: ranked fixes.

### 04: Audit prompt efficiency without using length as quality

Always write `<run-directory>/prompt-efficiency.md` with `Measurement`, `Cost Baseline`, `Loaded Context`, `Obligation Map`, `Value Guards`, `Adversarial Review`, and `Recommendations` sections. For `scope=config|roles` with no skill target, record `not-applicable` and why. For `scope=skills|all` or `axis=value-per-token`, audit each discovered local skill root independently; an absent optional Codex Rig, Codemap, or Bridge root is `not-configured`, never a cross-plugin dependency or failure.

Measure with matched provider-native token counts; else local `tiktoken` with `o200k_base`; else deterministic UTF-8 bytes and words. Do not install a tokenizer or use network access. Counts are cost evidence, never quality evidence; proxy-only comparison cannot accept a candidate and remains `insufficient-evidence`.

For each baseline/candidate pair, use the same file set and record hashes, measurement source, static cost, loaded referenced instructions, conditional-load decisions, and cost of every reference required by the exercised path. A moved instruction is not a saving when the same run must load it. Map every baseline obligation to its candidate location and evidence, covering safety, ordering, user approval, output/schema, fail-fast, tool-permission, and quality-gate requirements.

Value Guards must record exact package/tests, behavioral and calibration results, contract-marker coverage, tool/check failures, and completion quality. A live comparison must use paired tasks with the same model, effort, task contract, and prompt identity; record native token/cost fields and confidence limits. Treat missing paired live evidence as `insufficient-evidence` for a material behavior claim.

Any candidate that removes, moves, or condenses obligations requires an adversarial review of the obligation map. Accept only when all hard guards pass, no critical behavior regresses, tool/check failures do not increase, and normalized cost falls by `min_cost_reduction`; otherwise reject or mark insufficient evidence. A shorter candidate fails when it loses an obligation, weakens a guard, hides loaded-reference cost, or lacks required evidence. Value-per-token scores may rank already accepted candidates but never override hard gates.

### 05: Route specialists only when triggered

For `scope=all`, `mode=adversarial`, audits crossing skills, agents, CI/config, or material prompt compression, read and apply `../../shared/specialist-orchestration.md`; do not load it for a narrow single-surface audit. Write `<run-directory>/specialist-audit-plan.md` packs for:

- `curator`: skill/agent/config drift, duplication, calibration hygiene.
- `linting-expert`: Markdown, Python, shell, ruff/mypy/pre-commit references.
- `cicd-steward`: CI harness, workflow permissions, artifact behavior.
- `challenger`: adversarial check of no-finding or low-risk conclusions.

Stay single-agent for narrow `scope=config`, `scope=skills`, or `scope=roles` audits where same inventory would go to every specialist.

For material prompt compression, `challenger` must independently inspect the obligation map and cost/quality decision. Specialist disagreement is evidence to reconcile, not a vote.

### 06: Run shared quality gates

Follow `../../shared/helper-cli-contract.md` and `python PLUGIN_ROOT/shared/run_gates.py --help`. Use project-configured lint, format, type, and test commands for the discovered surfaces, explicit reasons for inapplicable gates, and clean diff review.

### 07: Detect drift and broken references

Run `rg -n` for `config_file|skills/|roles/|quality-gates|run_gates.py|write-result.py` over existing `AGENTS.md`,
`.codex`, `.agents`, and the optional target. Write results to `<run-directory>/reference-scan.txt`; record missing
inputs or command failure explicitly.

**Structural context (optional)**: when the audited scope contains a Python package, also probe codemap-py once for
undocumented public surface and externally-uncalled modules: `python PLUGIN_ROOT/shared/codemap_adapter.py context
--category audit --out <run-directory>/codemap-context.json`. Per `../../shared/codemap-contract.md`,
absence/incompatibility is non-fatal — continue with the reference scan above, using the persisted evidence as an
additional signal, never a replacement for it.

### 08: Audit spawn-pattern coverage and overlap in `AGENTS.md` (instruction-level check)

Run two separate `rg -n` argv scans: `delegat|specialist|spawn|role|\[agents\.` over existing `AGENTS.md` and
`.codex/config.toml`, writing `<run-directory>/spawn-sections.txt`; then
`Trigger and skip boundaries|TRIGGER when|SKIP when|NOT for` over the supplied target or `AGENTS.md`, writing
`<run-directory>/spawn-policy-sections.txt`. Record missing inputs or command failure explicitly.

### 09: Review native skill and agent contract consistency

Each configured skill has:

- `Input Schema`
- `Workflow`
- `Fail-Fast Rules`
- `Quality Gates`
- `Calibration Hooks`
- `Output Contract`

Each configured role or agent has:

- `## Scope` or clear role boundary text
- `## Evidence Standard`
- `## Boundaries`
- `## Output Contract` or explicit output format

### 10: Review role-roster consistency when a role-card target is supplied

When a target is supplied, run `rg -n` for `^(role_id|name|model|description|developer_instructions)` over that exact
target and write `<run-directory>/role-roster-scan.txt`; record scan failure. Without a target, create that artifact as
an empty file and classify the role roster as not configured.

Classify overlap as `keep`, `sharpen`, `merge-prune`:

- `keep`: distinct decision surface.
- `sharpen`: role stays; tighten boundary.
- `merge-prune`: no distinct acceptance criterion.

### 11: Classify findings using `../../shared/severity-map.md`

### 12: Write mandatory result artifact

Use shared lifecycle/authoritative help. Write `AUDIT_METADATA`, validate `audit`, promote only validated candidate.

## Fail-fast Rules

1. Requested target missing or escaping the consuming project/approved external scope => fail.
2. Shared gate script missing => fail.
3. Critical-path broken config/skill reference => fail.
4. Any configured role/agent lacks routing coverage => fail.
5. Unclear/overlapping spawn intent lacks collaboration-team guidance => fail.
6. Agent overlap lacks keep/sharpen/merge-prune decision => fail.
7. Configured entry lacks its declared skill/role contract section => fail unless exception recorded.
8. Non-native runtime assumptions in an audited skill or role card => fail.
9. Result artifact missing => fail.
10. `prompt-efficiency.md` or its required evidence sections missing => fail.
11. Prompt candidate accepted from raw length/proxy alone, without obligation mapping, hard value guards, loaded-reference cost, required adversarial review, matched live identity, or declared material reduction => fail.
12. `axis=value-per-token` requested without `scope=skills|all` or a supplied target containing a skill root => fail.

## Quality Gates

Required checks:

- `review`: inventory, contract ledger, prompt-efficiency evidence, reference scan, overlap decisions, `git diff --check`.
- `calibration`: run the owning project's declared calibration command when audited workflow behavior changes; for Codex Rig source, use `runtime/calibration/run.py --layout plugin`.

Conditional checks:

- `lint`/`format`: when Python/TOML/shell/Markdown formatters available.
- `tests`: with executable probes/behavior-changing fixes.

## Calibration Hooks

Update calibration when audit scope, contract requirements, or routing checks change:

- benchmark patterns: `audit`, every configured skill, every configured agent
- behavioral cases: runtime leak detection, stale reference handling, overlap classification, unsafe sync recommendation, length-only compression, missing loaded-reference cost, missing paired evidence, critical behavior regression, and below-threshold cost reduction

## Output Contract

Use `../../shared/quality-gates.md`.

`AUDIT_METADATA.value_per_token` records schema version, status (`not-run|insufficient-evidence|rejected|accepted`), scope roots, baseline/candidate hashes, static measurements, conditional-load trace, obligation-map path, static gates, behavioral/live comparisons, decision, and residual limits.

Minimum artifact payload template: `result-template.json`.
