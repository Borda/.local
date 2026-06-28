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

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/manage/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Parse intent and target.

   Supported intents:

   - `create`: scaffold a new skill/agent/rule/config entry.
   - `update`: edit an existing target.
   - `rename`: move target and update references.
   - `delete`: remove target only after dependency scan.
   - `add-permission` / `remove-permission`: modify permission policy with rationale.

   Unknown intent => fail before editing.

3. Resolve owned files and blast radius.

   ```bash
   find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/inventory.txt"
   rg -n "$TARGET" .codex AGENTS.md >"$OUT_DIR/references.txt" 2>/dev/null || true
   ```

   Write `$OUT_DIR/ownership.md` with the exact files to edit and files intentionally not edited.

4. Run safety gates before editing.

   Deletion safety is mandatory for delete and rename operations.

   - Delete/rename requires no unresolved references or an explicit migration plan.
   - Permission changes require reason, use case, and risk note.
   - Public behavior changes require docs/routing/calibration consideration.
   - Home sync is out of scope unless explicitly requested.

5. Apply the smallest reversible edit.

   Keep generated structure local to `.codex/` unless the user explicitly requests another root.

6. Propagate references.

   Update relevant descriptions, mappings, routing text, and calibration notes in the same patch when behavior changes. If a reference is intentionally stale, list it in `$OUT_DIR/unresolved-references.md`.

7. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-true}" \
       --format "${FORMAT_CMD:-true}" \
       --types "${TYPES_CMD:-true}" \
       --tests "${TESTS_CMD:-true}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

8. Write mandatory result artifact.

## Fail-Fast Rules

1. Missing intent or target => fail.
2. Delete/rename with unresolved references => fail.
3. Permission/config change without rationale => fail.
4. Behavior change without routing/docs/calibration decision => fail.
5. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: inventory diff, reference scan, and `git diff --check`.

Conditional checks:

- `lint`/`format`: enabled when generated Python, TOML, shell, or Markdown formatters are available.
- `tests`: calibration or smoke checks for changed skills/agents when behavior changes.

## Calibration Hooks

Any behavior-changing management edit must update or explicitly review:

- `.codex/config.toml`
- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/skills/_shared/native-skill-contract.md`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "review"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "artifact_path": ".reports/codex/manage/<timestamp>/result.json"
}
```
