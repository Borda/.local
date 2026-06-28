---
name: investigate
description: Minimal codex-native investigation loop. Use for unknown failures and root-cause narrowing with measurable gates.
---

# Investigate

Run a diagnosis-first loop for unclear failures. This skill produces a root-cause claim with evidence, falsification checks, and rejected alternatives before any fix is attempted.

## Input Schema

```json
{
  "symptom": "required failing command, traceback, CI failure, flaky behavior, or tool anomaly",
  "scope": "optional path/module/tool/CI run",
  "pace": "fast|full",
  "done_when": "one root cause is confirmed or the remaining uncertainty is explicit"
}
```

## Workflow

1. Create run directory.

   ```bash
   TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
   OUT_DIR=".reports/codex/investigate/$TS"
   mkdir -p "$OUT_DIR"
   ```

2. Capture symptom and reproduction context.

   Write `$OUT_DIR/symptom.md` with:

   - failing command or observed behavior
   - expected behavior
   - local vs CI vs external context
   - first known bad time or commit, if known
   - whether the failure is deterministic, flaky, or unknown

3. Gather signals before forming hypotheses.

   ```bash
   git status --short >"$OUT_DIR/status.txt" 2>/dev/null || true
   git log --oneline -10 >"$OUT_DIR/recent-commits.txt" 2>/dev/null || true
   git diff --stat >"$OUT_DIR/diffstat.txt" 2>/dev/null || true
   python --version >"$OUT_DIR/python-version.txt" 2>&1 || true
   ```

   Add tool-specific logs, CI excerpts, traceback snippets, config files, and changed source files as needed. Never treat absence of evidence as evidence of absence.

4. Rank hypotheses in `$OUT_DIR/hypotheses.md`.

   ```markdown
   | Rank | Hypothesis | Supporting evidence | Falsification check | Status |
   | --- | --- | --- | --- | --- |
   ```

   Include at least three plausible hypotheses unless the root cause is directly proven by a failing command and code/log evidence.

5. Probe the top hypotheses.

   Use targeted probes that can confirm, rule out, or narrow one hypothesis at a time.

   Each probe must have a clear outcome:

   - `confirmed`
   - `ruled_out`
   - `inconclusive`

   Persist probe commands and outputs under `$OUT_DIR/probes/` or inline in `$OUT_DIR/probes.md`.

6. Run the anti-rationalization gate.

   A root-cause claim requires:

   - supporting evidence from logs/code/commands
   - one falsification check
   - at least one rejected alternative
   - explicit confidence

   If confidence is low, continue probing instead of proposing a fix.

7. Run shared quality gates or targeted checks relevant to the failure.

   ```bash
   .codex/skills/_shared/run-gates.sh \
       --out "$OUT_DIR" \
       --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
       --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
       --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
       --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
       --review "${REVIEW_CMD:-git diff --check}"
   ```

8. Decide gate result and write `.reports/codex/investigate/<timestamp>/result.json`.

## Fail-Fast Rules

1. Missing symptom => fail.
2. No evidence collected before hypotheses => fail.
3. Root cause stated without falsification check => fail.
4. Workaround presented as root cause => fail.
5. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: hypothesis table, probe outcomes, rejected alternatives, and `git diff --check`.

Conditional checks:

- `tests`: failing or confirming reproduction command when available.
- `lint`, `format`, `types`: only when code/config changes are made as part of a probe.

## Calibration Hooks

Update calibration when root-cause routing or workaround rejection changes:

- behavioral cases: symptom-first routing, rejected alternatives, low-confidence probe escalation
- benchmark patterns: `investigate`

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
