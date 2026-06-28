---
name: develop
description: Minimal codex-native develop loop. Use for implementation tasks with linear plan-build-verify flow and measurable quality gates.
---

# Develop

Run a linear implementation loop with strict gates.

## Input Schema

```json
{
  "goal": "required implementation objective",
  "constraints": [
    "optional constraints"
  ],
  "done_when": "required acceptance statement"
}
```

## Workflow (Exact Commands)

01. Create run directory.

    ```bash
    TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
    OUT_DIR=".reports/codex/develop/$TS"
    mkdir -p "$OUT_DIR"
    ```

02. Record baseline diff and branch.

    ```bash
    git rev-parse --abbrev-ref HEAD >"$OUT_DIR/branch.txt"
    git diff --stat >"$OUT_DIR/before.diffstat"
    ```

03. Route the change type and define ownership.

    Modes:

    - `feature`: define public behavior, acceptance checks, docs impact, and tests before implementation.
    - `fix`: reproduce or cite the failing behavior before editing.
    - `refactor`: preserve behavior with characterization tests or an equivalent safety net.
    - `config`: inventory references and calibration/routing impact before editing.
    - `spike`: read-only or disposable probe; do not present as completed implementation.

    Define the narrowest reversible change, owned files, and acceptance criteria. If the task is 3+ steps or has design tradeoffs, update the plan before editing.

04. Run the anti-rationalization gate before editing.

    - Existing code and tests for the target surface have been read.
    - Failure mode or new behavior is captured by a failing doctest, pytest, or explicit acceptance check.
    - If the task starts from a symptom, failing test, failing CI, flaky behavior, regression, tool/environment error, or unexplained metric shift, run `investigate` first or document equivalent root-cause evidence before editing.
    - Root-cause evidence includes the claim, supporting logs/code, a falsification check, and at least one rejected alternative. A workaround-only change is a temporary mitigation, not completion, unless explicitly requested by the user.
    - Behavior-preserving refactors have characterization tests or an equivalent current-behavior safety net.
    - The next edit is the smallest reversible step, not a speculative refactor.

05. Implement minimal change.

06. Apply specialist policy when the change crosses a domain boundary.

    - public API or architecture: use or simulate `solution-architect` review before committing to the design.
    - bug fix or test behavior: use or simulate `qa-specialist` review for the verification matrix.
    - CI/tooling: use or simulate `cicd-steward` and `linting-expert` review.
    - security-sensitive code: use or simulate read-only `security-auditor` review.
    - ML/data/research behavior: use or simulate `data-steward`, `scientist`, or `squeezer` as appropriate.

    If specialist fan-out is unavailable, record the in-main substitute in `$OUT_DIR/specialist-notes.md`.

07. Run shared quality gates.

    ```bash
    .codex/skills/_shared/run-gates.sh \
        --out "$OUT_DIR" \
        --lint "${LINT_CMD:-uv run --no-sync ruff check .}" \
        --format "${FORMAT_CMD:-uv run --no-sync ruff format --check .}" \
        --types "${TYPES_CMD:-uv run --no-sync mypy src/}" \
        --tests "${TESTS_CMD:-uv run --no-sync pytest -q}" \
        --review "${REVIEW_CMD:-git diff --check}"
    ```

08. Review the changed files and the gate output before deciding pass/fail.

09. Classify findings using `../_shared/severity-map.md`.

10. Write mandatory result artifact.

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

01. Missing `goal` or `done_when` => fail.
02. Shared gate script missing => fail.
03. Any critical finding => fail.
04. Ambiguous scope or missing ownership => fail.
05. Missing failing doctest, pytest, or explicit acceptance check for changed behavior => fail.
06. Symptom-first task edited without `investigate` output or equivalent root-cause evidence => fail.
07. Workaround-only fix presented as completion without explicit temporary-mitigation instruction => fail.
08. Behavior-changing config/agent/skill edit without calibration/routing decision => fail.
09. Specialist-required domain change without specialist output or labeled substitute => fail.
10. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: `git diff --check`, changed-file inspection, and acceptance criteria trace.
- `tests`: failing-then-passing check or explicit acceptance probe for changed behavior.

Conditional checks:

- `lint`/`format`/`types`: run project-configured commands when code or typed config changed.
- `calibration`: run when `.codex/skills`, `.codex/agents`, `.codex/config.toml`, or calibration files changed.

## Calibration Hooks

Update calibration when implementation routing or output expectations change:

- benchmark patterns: `develop`
- behavioral cases: symptom-first routing, specialist substitution, config behavior changes, missing acceptance probe

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
  "artifact_path": ".reports/codex/develop/<timestamp>/result.json"
}
```
