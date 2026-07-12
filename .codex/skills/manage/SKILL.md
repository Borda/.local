---
name: manage
description: Minimal codex-native management loop. Use to create, update, or remove Codex agents/skills/config entries with guardrails.
---

# Manage

Run a guarded Codex configuration management loop for agents, skills, rules, and local config entries.

## Input Schema

```json
{
  "intent": "create|update|delete|rename|add-permission|remove-permission",
  "target": "required agent, skill, rule, config key, or path",
  "change": "required description or spec path",
  "done_when": "target and all references are updated or explicitly left unchanged"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/manage/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Parse intent and target

Supported intents:

- `create`: scaffold a new skill/agent/rule/config entry.
- `update`: edit an existing target.
- `rename`: move target and update references.
- `delete`: remove target only after dependency scan.
- `add-permission` / `remove-permission`: modify permission policy with rationale.

Unknown intent => fail before editing.

### 03: Resolve owned files and blast radius

```bash
find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/inventory.txt"
rg -n "$TARGET" .codex AGENTS.md >"$OUT_DIR/references.txt" 2>/dev/null || true
```

Write `$OUT_DIR/ownership.md` with the exact files to edit and files intentionally not edited.

### 04: Run safety gates before editing

Deletion safety is mandatory for delete and rename operations.

- Delete/rename requires no unresolved references or an explicit migration plan.
- Permission changes require reason, use case, and risk note.
- Public behavior changes require docs/routing/calibration consideration.
- Versioned calibration fixtures are committed-history markers: compare their current value with `git show HEAD:<path>` and do not advance more than one version step from the last committed value while the change is still uncommitted.
- Home sync is out of scope unless explicitly requested.

### 05: Apply the smallest reversible edit

Keep generated structure local to `.codex/` unless the user explicitly requests another root.

### 06: Propagate references

Update relevant descriptions, mappings, routing text, and calibration notes in the same patch when behavior changes. If a reference is intentionally stale, list it in `$OUT_DIR/unresolved-references.md`.

For broad management changes with separable config, docs, calibration, or verification workstreams, route through `delegation-lead` and the shared specialist orchestration policy. Use the lowest-cost capable registered specialist for each bounded workstream. Accept a delegated change only after the handover gate proves ownership, objective evidence, applicable checks, visible unresolved limits, and parent-owned final acceptance.

### 07: Run shared quality gates

Inspect `run-gates.sh --help`. Supply real commands for affected surfaces and explicit reasons for every not-applicable gate; never use `true` as a substitute for a skip reason. Review must include a clean diff check.

### 08: Write mandatory result artifact

For manage artifacts, include `ownership.md` and follow `../_shared/helper-cli-contract.md`. Write with `MANAGE_METADATA`, validate as skill `manage`, and promote only the validated candidate.

## Fail-Fast Rules

1. Missing intent or target => fail.
2. Delete/rename with unresolved references => fail.
3. Permission/config change without rationale => fail.
4. Behavior change without routing/docs/calibration decision => fail.
5. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: inventory diff, reference scan, and `git diff --check`.
- `artifact`: `ownership.md`, gate logs, and result JSON pass the shared validator.

Conditional checks:

- `lint`/`format`: enabled when generated Python, TOML, shell, or Markdown formatters are available.
- `tests`: calibration or smoke checks for changed skills/agents when behavior changes.

## Calibration Hooks

Any behavior-changing management edit must update or explicitly review:

- `.codex/config.toml`
- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/skills/_shared/native-skill-contract.md`

When a management edit changes a versioned calibration artifact, calculate the version from the last commit, not from the dirty working tree. If `HEAD` has `1.3`, all uncommitted edits for the next commit should stay at either `1.3` or `1.4`; do not keep bumping to `1.5`, `1.6`, and so on before a commit exists.

Commit-output management must also keep `.codex/skills/_shared/commit-response-template.md` aligned with the mandatory message shape:

```text
<type>(<scope>): <title>

Co-authored-by: Codex <codex@openai.com>
```

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
