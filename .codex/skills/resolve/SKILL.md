---
name: resolve
description: Minimal codex-native resolve loop. Use to apply review findings, rerun checks, and publish unresolved gaps with measurable gates.
---

# Resolve

Run a linear resolve loop for findings closure.

## Input Schema

```json
{
  "findings_source": "required path or explicit list",
  "target_scope": "required path/module",
  "done_when": "critical/high findings are either fixed or explicitly unresolved"
}
```

## Workflow (Exact Commands)

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/resolve/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Validate and copy findings source.

   ```bash
   cp "$FINDINGS_SOURCE" "$OUT_DIR/findings-input.txt"
   ```

3. Normalize findings before editing.

   Write `$OUT_DIR/action-items.md` with:

   - finding id or source location
   - severity
   - exact affected files
   - expected closure evidence
   - owner/status: `todo|fixed|unresolved`
   - unresolved rationale, when applicable

   If a finding is ambiguous, inspect the referenced code and either sharpen it into an action item or mark it `unresolved-needs-clarification` before editing.

4. Apply fixes in priority order: `critical` -> `high` -> `medium`.

   Fix one finding cluster at a time. After each cluster, record the changed files and evidence in `$OUT_DIR/closure-log.md`.

5. Challenge the closure before running full gates.

   For each fixed finding, answer:

   - Does the original failure still reproduce?
   - Could the finding pass review while remaining functionally wrong?
   - Which regression check now protects it?
   - What risk remains?

   Missing closure evidence keeps the item unresolved.

6. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

7. Write unresolved findings to `$OUT_DIR/unresolved.txt`.

8. Write mandatory result artifact.

   ```bash
   .codex/skills/_shared/write-result.sh \
       --out "$OUT_DIR/result.json" \
       --status "$STATUS" \
       --checks-run "lint,format,types,tests,review" \
       --checks-failed "$CHECKS_FAILED" \
       --critical "$CRITICAL" \
       --high "$HIGH" \
       --medium "$MEDIUM" \
       --low "$LOW" \
       --confidence "$CONFIDENCE" \
       --artifact-path "$OUT_DIR/result.json"
   ```

## Fail-fast Rules

1. Missing findings source => fail.
2. Shared gate script missing => fail.
3. Critical unresolved findings => fail.
4. Finding marked fixed without closure evidence => fail.
5. Gate failure caused by the resolution patch => fail unless explicitly listed as unresolved.
6. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: action-item ledger, closure log, unresolved list, and `git diff --check`.
- `tests`: the smallest checks that prove closure for fixed findings.

Conditional checks:

- `lint`/`format`/`types`: run project-configured checks for changed code/config.
- `calibration`: run when findings affect `.codex/skills`, `.codex/agents`, routing, or gate policy.

## Calibration Hooks

Update calibration when resolution policy or output shape changes:

- benchmark patterns: `resolve`
- behavioral cases: ambiguous findings, false closure, unresolved critical/high handling, gate failure disclosure

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "lint",
    "format",
    "types",
    "tests",
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
  "artifact_path": ".reports/codex/resolve/<timestamp>/result.json"
}
```
