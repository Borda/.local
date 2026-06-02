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

1. Load calibration task set from `.codex/calibration/tasks.json`.
2. Load behavioral cases from `.codex/calibration/behavioral-cases.json`.
3. Load behavioral observations from `.codex/calibration/behavioral-observations.jsonl`.
   - Require `source`, `run_id`, and `observed_at` on each observation where available.
4. Run `.codex/calibration/run.sh`.
5. Inspect `checks_failed`, `leaks_found`, and `behavioral`.
6. Review behavioral metrics:
   - `recall`: expected finding IDs recovered from known cases.
   - `precision`: reported finding IDs that match expected finding IDs.
   - `confidence_accuracy`: `1 - mean(abs(confidence - per-case F1))`.
   - `mean_overconfidence`: average positive confidence bias over per-case F1.
   - `gate_metrics_raw`: unrounded overall values used for pass/fail thresholds.
   - `by_source`: recall, precision, and confidence calibration grouped by observation source.
   - `observation_freshness`: latest `observed_at`, missing timestamp count, and live-vs-fixture observation counts.
7. Classify gaps as blocking or non-blocking.
8. Recommend minimal fixes for blocking gaps.
9. Write artifact to `.reports/codex/calibrate/<timestamp>/result.json`.

## Usage Notes

- Use after any meaningful agent or skill instruction change to confirm routing and output shape still match the configured stack.
- Treat `leaks_found` as the primary drift signal and `checks_failed` as the mechanical gate signal.
- Treat behavioral metrics as measurement of supplied observations only. `fixture-selftest` observations validate the scoring contract; live Codex quality requires replacing or appending observations generated from live calibration prompts.
- Treat `live_observations = 0` as a reporting caveat, not proof that live Codex quality is acceptable.
- Compare behavioral thresholds against `gate_metrics_raw`, not rounded display metrics.
- Use `source=live-*`, a stable `run_id`, and UTC `observed_at` timestamps for live behavioral calibration rows.
- If the run surfaces missing registration or pattern mismatches, prefer a minimal config fix and rerun before widening the change.

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
  "artifact_path": ".reports/codex/calibrate/<timestamp>/result.json"
}
```
