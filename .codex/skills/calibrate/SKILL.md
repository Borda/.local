---
name: calibrate
description: Codex-native calibration loop. Use to detect leaks or major gaps across mirrored skills and agents with fixed checks plus behavioral recall, precision, and confidence-accuracy scoring.
---

# Calibrate

Run a linear calibration loop for codex workflow integrity and behavioral scoring.

## Input Schema

```json
{
  "scope": "skills|agents|routing|all",
  "pace": "fast|full",
  "mode": "ab-test|apply",
  "skip_gate": false,
  "done_when": "recall and bias scores emitted; proposals written if mode=apply; gate skipped if skip_gate=true"
}
```

## Workflow

### 01: Load calibration task set from `.codex/calibration/tasks.json`

### 02: Load behavioral cases from `.codex/calibration/behavioral-cases.json`

### 03: Load behavioral observations from `.codex/calibration/behavioral-observations.jsonl`

- Require `source`, `run_id`, and `observed_at` on each observation where available.

### 04: Run `.codex/calibration/run.sh`

### 05: Inspect `checks_failed`, `leaks_found`, and `behavioral`

### 06: Review behavioral metrics:

- `recall`: expected finding IDs recovered from known cases.
- `precision`: reported finding IDs that match expected finding IDs.
- `confidence_accuracy`: `1 - mean(abs(confidence - per-case F1))`.
- `mean_overconfidence`: average positive confidence bias over per-case F1.
- `gate_metrics_raw`: unrounded overall values used for pass/fail thresholds.
- `by_source`: recall, precision, and confidence calibration grouped by observation source.
- `observation_freshness`: latest `observed_at`, missing timestamp count, and live-vs-fixture observation counts.

### 07: Classify gaps as blocking or non-blocking

### 08: Emit measured recommendations for what should be fixed or improved next

- Failed checks and leaks come first.
- Behavioral recommendations must name the metric gap and the affected cases when available.
- Fixture-only caveats must be separate from live-quality claims.

### 09: Write artifacts to `.reports/codex/calibration/<timestamp>/result.json` and `.reports/codex/calibration/<timestamp>/recommendations.md`

### 10: Write the skill-level artifact to `.reports/codex/calibrate/<timestamp>/result.json` when this skill wraps the runner

## Native Contract Checks

Calibration must verify the configured native surface, not only the runner internals.

Skill checks:

- each configured skill file exists
- skill frontmatter uses unindented `---` markers with `name:` and `description:`
- required contract sections are present
- artifact path uses `.reports/codex/<skill>/`
- output examples include `status`, `checks_run`, `checks_failed`, `findings`, `confidence`, and `artifact_path`
- native skill files do not depend on external runner-only metadata or cache paths
- shared helper checks cover `run-gates.sh`, `write-result.sh`, `collect-diff.sh`, `collect-pr.sh`, `find-review-report.py`, and `validate-artifacts.py`
- offline CI harness checks cover `.github/codex-harness.sh`, the `CODEX_OFFLINE_HARNESS` marker, blocked LLM/network command shims, `GITHUB_STEP_SUMMARY`, `.github/codex-harness-results/`, upload-artifact wiring, and the `offline-ci-harness` check id

Agent checks:

- each configured agent file exists and is registered
- active `model` and `review_model` pins use supported model strings for the current Codex runtime
- `model_reasoning_effort` follows the agent-effort-policy: bounded support roles use `medium`, implementation and verification roles use `high`, and architecture/security/research/challenger roles use `xhigh`
- high-stakes specialist roles use the high-capability model tier, while bounded support roles may use the lower-cost support tier
- deprecated model strings are absent from active project config and agent TOML files
- role has a clear `Scope` or equivalent boundary
- counterpart mapping, evidence standard, boundaries, output format, and output contract are present or explicitly waived
- sensitive agents keep their sandbox constraints, especially read-only security audit
- no external runtime tool names or external path variables are required by native agents

## Usage Notes

- Use after any meaningful agent or skill instruction change to confirm routing and output shape still match the configured stack.
- Treat `leaks_found` as the primary drift signal and `checks_failed` as the mechanical gate signal.
- Treat behavioral metrics as measurement of supplied observations only. `fixture-selftest` observations validate the scoring contract; live Codex quality requires replacing or appending observations generated from live calibration prompts.
- Treat `live_observations = 0` as a reporting caveat, not proof that live Codex quality is acceptable.
- Compare behavioral thresholds against `gate_metrics_raw`, not rounded display metrics.
- Use `source=live-*`, a stable `run_id`, and UTC `observed_at` timestamps for live behavioral calibration rows.
- If the run surfaces missing registration or pattern mismatches, prefer a minimal config fix and rerun before widening the change.

## Fail-Fast Rules

1. Missing calibration files => fail.
2. Missing configured skill or agent file => fail.
3. Native skill/agent contract mismatch => fail unless explicitly waived in the result.
4. Runtime leakage in native skill or agent files => fail.
5. Behavioral gate below threshold => fail.
6. Result artifact missing => fail.
7. Offline CI harness missing, not executable, or able to invoke LLM/network commands => fail.

## Quality Gates

Required checks:

- `calibration`: `.codex/calibration/run.sh`.
- `offline-ci-harness`: `.github/codex-harness.sh` must run the calibration harness without Codex/OpenAI/LLM credentials or network-capable helper CLIs, print the result summary, save artifacts under `.github/codex-harness-results/`, and wire that folder to the GitHub artifact upload step.
- `review`: inspect failed patterns, leakage, behavioral gaps, and stale fixtures before recommending changes.

Conditional checks:

- `tests`: run focused tests when calibration code changes.
- `format`: validate JSON and shell syntax when calibration fixtures change.

## Calibration Hooks

When calibration expectations change, update together:

- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/calibration/behavioral-observations.jsonl`
- `.codex/calibration/run.sh`
- `.github/codex-harness.sh`
- `.github/workflows/ci-harness.yml`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "calibration"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "behavioral": {
    "status": "pass|fail",
    "overall": {
      "recall": 0.0,
      "precision": 0.0,
      "f1": 0.0,
      "confidence_accuracy": 0.0,
      "mean_overconfidence": 0.0
    }
  },
  "by_source": {
    "fixture-selftest": {
      "recall": 0.0,
      "precision": 0.0,
      "confidence_accuracy": 0.0
    }
  },
  "observation_freshness": {
    "latest_observed_at": "2026-06-02T00:00:00Z",
    "missing_observed_at": 0,
    "fixture_observations": 0,
    "live_observations": 0
  },
  "recommendations": [
    "measured fix or improvement recommendation"
  ],
  "follow_up": [
    "non-blocking next check"
  ],
  "artifacts": {
    "recommendations": ".reports/codex/calibration/<timestamp>/recommendations.md"
  },
  "artifact_path": ".reports/codex/calibrate/<timestamp>/result.json"
}
```
