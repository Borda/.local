---
name: optimize
description: Minimal codex-native optimization loop. Use for metric-driven improvements with guardrails and measurable gates.
---

# Optimize

Run a metric-driven optimization loop with explicit guards, rollback criteria, and experiment logging.

## Input Schema

```json
{
  "goal": "required measurable improvement objective",
  "metric_cmd": "required command that emits or validates the target metric",
  "metric_direction": "higher|lower",
  "guard_cmd": "required command that must continue to pass",
  "scope_files": [
    "paths the optimization may edit"
  ],
  "done_when": "metric improves without guard regression"
}
```

## Workflow

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/optimize/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Validate metric and guard commands.

   Requirements:

   - `metric_cmd` is repeatable and produces a comparable value or pass/fail result.
   - `metric_direction` is known.
   - `guard_cmd` fails on unacceptable regressions.
   - `scope_files` is bounded.

   Dry-run both commands before editing:

   ```bash
   ${METRIC_CMD} >"$OUT_DIR/metric-baseline.txt" 2>&1
   ${GUARD_CMD} >"$OUT_DIR/guard-baseline.txt" 2>&1
   ```

3. Record baseline and hypothesis.

   Write `$OUT_DIR/hypothesis.md`:

   - metric to improve
   - expected mechanism
   - files allowed to change
   - guard risk
   - rollback condition

4. Apply one minimal optimization change.

   Do not combine independent hypotheses in one iteration. Do not optimize unmeasured paths.

5. Re-measure.

   ```bash
   ${METRIC_CMD} >"$OUT_DIR/metric-after.txt" 2>&1
   ${GUARD_CMD} >"$OUT_DIR/guard-after.txt" 2>&1
   ```

6. Compare baseline and after results in `$OUT_DIR/comparison.md`.

   Required fields:

   - baseline value
   - after value
   - delta
   - guard status
   - confidence
   - noise caveats

7. Decide keep/revert.

   - Keep only when metric moves in the intended direction and guards pass.
   - Revert or mark fail when guard regresses.
   - If measurement is noisy, require repeated runs or mark inconclusive.

8. Run shared quality gates.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-${GUARD_CMD:-uv run --no-sync pytest -q}}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

9. Write mandatory result artifact.

## Fail-Fast Rules

1. Missing metric or guard command => fail.
2. Baseline cannot be captured => fail.
3. Scope is unbounded => fail.
4. Guard regression after change => fail unless reverted.
5. Result artifact missing => fail.

## Quality Gates

Required checks:

- `tests`: guard command or impacted tests.
- `review`: metric comparison, rollback decision, and `git diff --check`.

Recommended checks:

- `lint`, `format`, `types`: run for any code edits.

## Calibration Hooks

Update calibration when metric/guard policy changes:

- behavioral cases: baseline missing, guard regression, noisy metric overclaim
- benchmark patterns: `optimize`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
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
  "artifact_path": ".reports/codex/optimize/<timestamp>/result.json"
}
```
