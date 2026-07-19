---
name: audit
description: Minimal codex-native audit loop. Use to scan codex configuration/workflow drift and emit ranked gaps with measurable gates.
---

# Audit

Run linear configuration/workflow audit.

## Input Schema

```json
{
  "scope": "config|skills|agents|all",
  "target": "optional path",
  "mode": "upgrade|adversarial",
  "skip_gate": false,
  "done_when": "drift and broken references are ranked with gate result; fix level chosen interactively unless skip_gate=true"
}
```

## Workflow (Exact Commands)

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/audit/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Normalize scope and collect inventory

Scopes:

- `config`: `.codex/config.toml`, instructions, permission/routing.
- `skills`: `.codex/skills/**` plus calibration coverage.
- `agents`: `.codex/agents/*.toml` plus spawn/routing coverage.
- `all`: all above.

```bash
find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/inventory.txt"
```

### 03: Build an audit ledger before running gates

Write `$OUT_DIR/audit-ledger.md` with these sections:

- `Inventory`: configured/present agents/skills.
- `Broken References`: missing files, stale paths, unresolved shared resources.
- `Runtime Leaks`: non-native runner fields/external runtime assumptions.
- `Coverage`: calibration benchmark/behavior.
- `Overlap`: duplicate/fuzzy ownership decisions.
- `Recommendations`: ranked fixes.

For `scope=all`, `mode=adversarial`, or audits crossing skills, agents, CI/config, apply `../../shared/specialist-orchestration.md`. Write `"$OUT_DIR/specialist-audit-plan.md"` packs for:

- `curator`: skill/agent/config drift, duplication, calibration hygiene.
- `linting-expert`: Markdown, Python, shell, ruff/mypy/pre-commit references.
- `cicd-steward`: CI harness, workflow permissions, artifact behavior.
- `challenger`: adversarial check of no-finding or low-risk conclusions.

Stay single-agent for narrow `scope=config`, `scope=skills`, or `scope=agents` audits where same inventory would go to every specialist.

### 04: Run shared quality gates

Follow `../../shared/helper-cli-contract.md` and `run-gates.sh --help`. Default: ruff lint/format `.codex`, explicit no-typed-target reason, calibration tests, clean diff review; project commands may replace.

### 05: Detect drift and broken references

```bash
rg -n "config_file|skills/|quality-gates|run-gates.sh|write-result.py" .codex >"$OUT_DIR/reference-scan.txt"
```

### 06: Audit spawn-pattern coverage and overlap in `AGENTS.md` (instruction-level check)

```bash
rg -n "\[agents\.|description =" .codex/config.toml >"$OUT_DIR/spawn-sections.txt"
rg -n "TRIGGER when|SKIP when|NOT for" .codex/agents >"$OUT_DIR/spawn-policy-sections.txt"
```

### 07: Review native skill and agent contract consistency

Each configured skill has:

- `Input Schema`
- `Workflow`
- `Fail-Fast Rules`
- `Quality Gates`
- `Calibration Hooks`
- `Output Contract`

Each configured agent has:

- `## Scope` or clear role boundary text
- `## Evidence Standard`
- `## Boundaries`
- `## Output Contract` or explicit output format

### 08: Review agent-roster consistency

```bash
rg -n "^(name|description|developer_instructions)" .codex/agents >"$OUT_DIR/agent-roster-scan.txt"
```

Classify overlap as `keep`, `sharpen`, `merge-prune`:

- `keep`: distinct decision surface.
- `sharpen`: role stays; tighten boundary.
- `merge-prune`: no distinct acceptance criterion.

### 09: Classify findings using `../../shared/severity-map.md`

### 10: Write mandatory result artifact

Use shared lifecycle/authoritative help. Write `AUDIT_METADATA`, validate `audit`, promote only validated candidate.

## Fail-fast Rules

1. Missing `.codex` inventory => fail.
2. Shared gate script missing => fail.
3. Critical-path broken config/skill reference => fail.
4. Any configured agent lacks spawn coverage => fail.
5. Unclear/overlapping spawn intent lacks collaboration-team guidance => fail.
6. Agent overlap lacks keep/sharpen/merge-prune decision => fail.
7. Configured entry lacks native skill/agent contract section => fail unless exception recorded.
8. Non-native runtime assumptions in `.codex/skills/*/SKILL.md` or `.codex/agents/*.toml` => fail.
9. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: inventory, contract ledger, reference scan, overlap decisions, `git diff --check`.
- `calibration`: run or justify skipping `.codex/calibration/run.py` with skill/agent behavior change.

Conditional checks:

- `lint`/`format`: when Python/TOML/shell/Markdown formatters available.
- `tests`: with executable probes/behavior-changing fixes.

## Calibration Hooks

Update calibration when audit scope, contract requirements, or routing checks change:

- benchmark patterns: `audit`, every configured skill, every configured agent
- behavioral cases: runtime leak detection, stale reference handling, overlap classification, unsafe sync recommendation

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
