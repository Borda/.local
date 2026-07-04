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
  "mode": "feature|fix|refactor|config|spike",
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
    .codex/skills/_shared/collect-diff.sh --scope working-tree --out "$OUT_DIR/baseline"
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
    - `feature` mode has a feature demo contract before production edits:
      - simple public API: inline doctest or focused pytest that shows the intended call and result
      - multi-step behavior: minimal example or pytest exercising the user-visible workflow end to end
      - the demo must be automatically executable and must fail against current code for the intended missing behavior
      - if the demo passes before implementation, stop and re-scope; do not silently proceed unless the user explicitly overrides the gate
    - Review the demo contract for goal alignment, API shape, missing scenarios, and automatic verifiability before implementation.
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

07. Write `$OUT_DIR/development-notes.md` before running gates.

    Required sections:

    - `Scope`
    - `Acceptance Criteria`
    - `Evidence`
    - `Specialist Policy`
    - `Gates`

08. Run shared quality gates.

    ```bash
    .codex/skills/_shared/run-gates.sh --out "$OUT_DIR"
    ```

09. Review the changed files and the gate output before deciding pass/fail.

10. Classify findings using `../_shared/severity-map.md`.

11. Write and validate the mandatory result artifact.

```bash
.codex/skills/_shared/write-result.sh \
    --out "$OUT_DIR/result.candidate.json" \
    --status "$STATUS" \
    --checks-run "lint,format,types,tests,review" \
    --checks-failed "$CHECKS_FAILED" \
    --critical "$CRITICAL" \
    --high "$HIGH" \
    --medium "$MEDIUM" \
    --low "$LOW" \
    --confidence "$CONFIDENCE" \
    --artifact-path "$OUT_DIR/result.json"
python3 .codex/skills/_shared/validate-artifacts.py \
    --skill develop \
    --out "$OUT_DIR" \
    --result "$OUT_DIR/result.candidate.json"
mv "$OUT_DIR/result.candidate.json" "$OUT_DIR/result.json"
```

## Fail-fast Rules

01. Missing `goal` or `done_when` => fail.
02. Shared gate script missing => fail.
03. Any critical finding => fail.
04. Ambiguous scope or missing ownership => fail.
05. Missing failing doctest, pytest, or explicit acceptance check for changed behavior => fail.
06. `feature` mode without an executable failing demo contract before production edits => fail.
07. Feature demo passes before implementation without explicit user override and re-scope note => fail.
08. Symptom-first task edited without `investigate` output or equivalent root-cause evidence => fail.
09. Workaround-only fix presented as completion without explicit temporary-mitigation instruction => fail.
10. Behavior-changing config/agent/skill edit without calibration/routing decision => fail.
11. Specialist-required domain change without specialist output or labeled substitute => fail.
12. Missing `development-notes.md` sections => fail.
13. Result artifact validator failure => fail.
14. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: `git diff --check`, changed-file inspection, and acceptance criteria trace.
- `tests`: failing-then-passing check or explicit acceptance probe for changed behavior; `feature` mode must include the demo failure before edits and demo pass after implementation.
- `artifact`: shared validator confirms `development-notes.md`, gate logs, and result JSON shape.

Conditional checks:

- `lint`/`format`/`types`: run project-configured commands when code or typed config changed.
- `calibration`: run when `.codex/skills`, `.codex/agents`, `.codex/config.toml`, or calibration files changed.

## Calibration Hooks

Update calibration when implementation routing or output expectations change:

- benchmark patterns: `develop`
- behavioral cases: symptom-first routing, specialist substitution, config behavior changes, missing acceptance probe, feature demo gate bypass, artifact validator bypass

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
