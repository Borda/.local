---
name: audit
description: Minimal codex-native audit loop. Use to scan codex configuration/workflow drift and emit ranked gaps with measurable gates.
---

# Audit

Run linear configuration/workflow audit.

## Input Schema

```json
{
  "scope": "config|skills|roles|all",
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

In each later Bash block, replace `<run-directory-created-in-step-01>` with the exact path created in step 01.

### 02: Normalize scope and collect inventory

Scopes:

- `config`: project `.codex/config.toml`, `AGENTS.md` layers, permissions, and routing.
- `skills`: repository/user-authored `.agents/skills/**` plus declared calibration coverage.
- `roles`: role-routing instructions and an explicitly supplied plugin/package role-card root.
- `all`: every applicable surface above. Missing optional local skills or roles is `not-configured`, not drift.

```bash
OUT_DIR="<run-directory-created-in-step-01>"
{
  rg --files -g 'AGENTS.md' -g '.codex/config.toml' -g '.agents/skills/**' 2>/dev/null || true
  if [[ -n "${TARGET:-}" && -e "$TARGET" ]]; then find "$TARGET" -maxdepth 4 -type f; fi
} | sort -u >"$OUT_DIR/inventory.txt"
```

### 03: Build an audit ledger before running gates

Write `$OUT_DIR/audit-ledger.md` with these sections:

- `Inventory`: configured/present policy, skills, and role-routing surfaces.
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

Follow `../../shared/helper-cli-contract.md` and `run-gates.sh --help`. Use project-configured lint, format, type, and test commands for the discovered surfaces, explicit reasons for inapplicable gates, and clean diff review.

### 05: Detect drift and broken references

```bash
OUT_DIR="<run-directory-created-in-step-01>"
rg -n "config_file|skills/|roles/|quality-gates|run-gates.sh|write-result.py" \
  AGENTS.md .codex .agents "${TARGET:-}" >"$OUT_DIR/reference-scan.txt" 2>/dev/null || true
```

### 06: Audit spawn-pattern coverage and overlap in `AGENTS.md` (instruction-level check)

```bash
OUT_DIR="<run-directory-created-in-step-01>"
rg -n "delegat|specialist|spawn|role|\[agents\." AGENTS.md .codex/config.toml \
  >"$OUT_DIR/spawn-sections.txt" 2>/dev/null || true
rg -n "Trigger and skip boundaries|TRIGGER when|SKIP when|NOT for" "${TARGET:-AGENTS.md}" \
  >"$OUT_DIR/spawn-policy-sections.txt" 2>/dev/null || true
```

### 07: Review native skill and agent contract consistency

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

### 08: Review role-roster consistency when a role-card target is supplied

```bash
OUT_DIR="<run-directory-created-in-step-01>"
if [[ -n "${TARGET:-}" ]]; then
  rg -n "^(role_id|name|model|description|developer_instructions)" "$TARGET" \
    >"$OUT_DIR/role-roster-scan.txt" 2>/dev/null || true
else
  : >"$OUT_DIR/role-roster-scan.txt"
fi
```

Classify overlap as `keep`, `sharpen`, `merge-prune`:

- `keep`: distinct decision surface.
- `sharpen`: role stays; tighten boundary.
- `merge-prune`: no distinct acceptance criterion.

### 09: Classify findings using `../../shared/severity-map.md`

### 10: Write mandatory result artifact

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

## Quality Gates

Required checks:

- `review`: inventory, contract ledger, reference scan, overlap decisions, `git diff --check`.
- `calibration`: run the owning project's declared calibration command when audited workflow behavior changes; for Codex Rig source, use `runtime/calibration/run.py --layout plugin`.

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
