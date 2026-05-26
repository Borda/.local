---
name: investigate
description: Minimal codex-native investigation loop. Use for unknown failures and root-cause narrowing with measurable gates.
---

# Investigate

Run a linear diagnosis loop for unclear failures.

## Workflow

1. Capture symptom, scope, and reproduction context.
2. Gather evidence from logs, errors, and changed files.
3. Rank top hypotheses and map them to validation checks.
4. Run the anti-rationalization gate: each root-cause claim needs supporting evidence, a falsification check, and at least one rejected alternative. If confidence is low, run a targeted probe before proposing a fix.
5. Run required checks from `../_shared/quality-gates.md`.
6. Decide most likely root cause and gate result.
7. Write artifact to `.reports/codex/investigate/<timestamp>/result.json`.

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
  "artifact_path": ".reports/codex/investigate/<timestamp>/result.json"
}
```
