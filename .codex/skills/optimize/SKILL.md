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
  "mode": "single|campaign",
  "metric_cmd": "required command that emits or validates the target metric",
  "metric_direction": "higher|lower",
  "guard_cmd": "required command that must continue to pass",
  "max_iterations": "optional integer, default 1",
  "min_delta": "optional practical significance threshold",
  "scope_files": [
    "paths the optimization may edit"
  ],
  "done_when": "metric improves without guard regression"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/optimize/$TS"
mkdir -p "$OUT_DIR"
```

### 02: Validate metric and guard commands

Requirements:

- `metric_cmd` is repeatable and produces a comparable value or pass/fail result.
- `metric_direction` is known.
- `guard_cmd` fails on unacceptable regressions.
- `scope_files` is bounded.
- `max_iterations` is explicit for `campaign` mode and remains bounded.
- Files or scripts used by `metric_cmd` and `guard_cmd` are protected unless the user explicitly includes them in scope and accepts the measurement-integrity risk.

Dry-run both commands before editing:

```bash
${METRIC_CMD} >"$OUT_DIR/metric-baseline.txt" 2>&1
${GUARD_CMD} >"$OUT_DIR/guard-baseline.txt" 2>&1
```

### 03: Record baseline and hypothesis

Write `$OUT_DIR/hypothesis.md`:

- metric to improve
- expected mechanism
- files allowed to change
- guard risk
- rollback condition

For `campaign` mode, noisy metrics, GPU/ML performance, or optimization that touches correctness-sensitive code, apply `../_shared/specialist-orchestration.md`. Write `"$OUT_DIR/specialist-optimization-plan.md"` with narrow context packs for:

- `squeezer`: profiling mechanism, bottleneck hypothesis, measurement plan.
- `qa-specialist`: guard coverage and regression risk.
- `data-steward`: data pipeline or reproducibility impact.
- `scientist`: metric validity, ablation design, statistical noise.
- `challenger`: overfitting to the metric or weakening guard checks.

Do not fan out for a single small measured change with a stable metric and guard. Never let a specialist change the metric or guard scripts unless that is explicitly in `scope_files` and measurement-integrity risk is recorded.

Initialize a machine-readable iteration log:

```bash
: >"$OUT_DIR/experiments.jsonl"
```

### 04: Apply one minimal optimization change per iteration

Do not combine independent hypotheses in one iteration. Do not optimize unmeasured paths. Before each iteration, write `$OUT_DIR/iteration-<n>-before.patch` with the current diff for the scoped files. If an iteration fails and only that iteration's patch is present, revert the iteration with `git apply -R` against the iteration diff or mark the run failed when a clean reversal cannot be proven. Never use `git reset --hard`.

### 05: Re-measure

```bash
${METRIC_CMD} >"$OUT_DIR/metric-after.txt" 2>&1
${GUARD_CMD} >"$OUT_DIR/guard-after.txt" 2>&1
```

### 06: Compare baseline and after results in `$OUT_DIR/comparison.md`

Required fields:

- baseline value
- after value
- delta
- guard status
- confidence
- noise caveats

Append one JSON object per iteration to `$OUT_DIR/experiments.jsonl` with:

```json
{
  "iteration": 1,
  "hypothesis": "one-line mechanism",
  "metric_before": 0.0,
  "metric_after": 0.0,
  "delta": 0.0,
  "guard": "pass|fail",
  "decision": "kept|reverted|inconclusive|failed",
  "rollback_evidence": "path or reason"
}
```

### 07: Decide keep/revert

- Keep only when metric moves in the intended direction and guards pass.
- For `min_delta`, keep only when the delta meets or exceeds the practical significance threshold.
- Revert or mark fail when guard regresses.
- If measurement is noisy, require repeated runs or mark inconclusive.
- In `campaign` mode, stop at the first kept result unless the user asked for continued exploration; otherwise continue only while `max_iterations` remains and each rejected iteration has rollback evidence.

### 08: Run shared quality gates

```bash
.codex/skills/_shared/run-gates.sh \
    --out "$OUT_DIR" \
    --tests "${TESTS_CMD:-$GUARD_CMD}"
```

### 09: Write and validate the mandatory result artifact

```bash
.codex/skills/_shared/write-result.py \
    --out "$OUT_DIR/result.candidate.json" \
    --status "$STATUS" \
    --checks-run "lint,format,types,tests,review" \
    --checks-failed "$CHECKS_FAILED" \
    --critical "$CRITICAL" \
    --high "$HIGH" \
    --medium "$MEDIUM" \
    --low "$LOW" \
    --confidence "$CONFIDENCE" \
    --metadata "$OPTIMIZE_METADATA" \
    --artifact-path "$OUT_DIR/result.json"
python3 .codex/skills/_shared/validate-artifacts.py \
    --skill optimize \
    --out "$OUT_DIR" \
    --result "$OUT_DIR/result.candidate.json"
mv "$OUT_DIR/result.candidate.json" "$OUT_DIR/result.json"
```

## Fail-Fast Rules

1. Missing metric or guard command => fail.
2. Baseline cannot be captured => fail.
3. Scope is unbounded => fail.
4. Guard regression after change => fail unless reverted.
5. Metric/guard script changed without explicit scope and measurement-integrity note => fail.
6. Campaign iteration rejected without rollback evidence or unresolved-risk note => fail.
7. Claimed improvement below `min_delta` without explicit inconclusive status => fail.
8. Result artifact validator failure => fail.
9. Result artifact missing => fail.

## Quality Gates

Required checks:

- `tests`: guard command or impacted tests.
- `review`: metric comparison, rollback decision, campaign ledger when relevant, and `git diff --check`.
- `artifact`: shared validator confirms comparison, experiments JSONL, gate logs, and result JSON shape.

Recommended checks:

- `lint`, `format`, `types`: run for any code edits.

## Calibration Hooks

Update calibration when metric/guard policy changes:

- behavioral cases: baseline missing, guard regression, noisy metric overclaim, campaign rollback evidence, below-threshold improvement, artifact validator bypass
- benchmark patterns: `optimize`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
