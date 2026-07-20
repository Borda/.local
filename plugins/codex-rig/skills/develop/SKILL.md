---
name: develop
description: Minimal codex-native develop loop. Use for implementation tasks with linear plan-build-verify flow and measurable quality gates.
---

# Develop

Run linear implementation with strict gates.

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

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/develop/$TS"
mkdir -p "$OUT_DIR"
```

In each later Bash block, replace `<run-directory-created-in-step-01>` with the exact path created in step 01.

### 02: Record baseline diff and branch

```bash
OUT_DIR="<run-directory-created-in-step-01>"
git rev-parse --abbrev-ref HEAD >"$OUT_DIR/branch.txt"
```

Inspect `collect-diff.sh --help`; collect `working-tree` into `$OUT_DIR/baseline`.

### 03: Route the change type and define ownership

Modes:

- `feature`: define public behavior, acceptance checks, docs impact, and tests before implementation.
- `fix`: reproduce or cite the failing behavior before editing.
- `refactor`: preserve behavior with characterization tests or an equivalent safety net.
- `config`: inventory references and calibration/routing impact before editing.
- `spike`: read-only or disposable probe; do not present as completed implementation.

Define narrowest reversible change, owners, acceptance. For 3+ steps/design tradeoffs, update plan before edit.

### 04: Run the anti-rationalization gate before editing

- Existing code and tests for the target surface have been read.
- Failure mode or new behavior is captured by a failing doctest, pytest, or explicit acceptance check.
- Coding changes have a project coding-principles plan from the applicable `AGENTS.md` layers: simple/readable/reproducible structure first, short reusable units without low-value argument-remapping wrappers, guard clauses or early `return`/`yield`/`continue` for invalid or terminal cases, project docstring-style detection, concise purpose docstrings, and inline comments only for non-trivial implementation blocks.
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

### 05: Implement minimal change

While implementing, keep the code understandable from the code itself:

- Apply the consolidated project coding principles from the applicable `AGENTS.md` layers.
- Refactor long, dense, or deeply nested blocks into named helpers/classes before adding explanatory text.
- Avoid tiny rarely used helpers that only remap arguments; keep the logic inline, use a local helper, or use `functools.partial` when only binding arguments.
- Match the project's configured or established docstring style, and keep function/class purpose in docstrings rather than comments directly above definitions.
- Refactor instead of writing long docstrings or comments when a block needs a long explanation to be understandable.

### 06: Orchestrate specialists when the change crosses a domain boundary

Apply `../../shared/specialist-orchestration.md`. Stay single-agent for narrow implementation that fits in one to three files and one domain. Use specialist orchestration when the task crosses domains, benefits from independent verification, or can split into parallel context packs.

Before spawning or substituting specialists, write `"$OUT_DIR/specialist-plan.md"` with one row per planned pass:

| role | trigger | context pack | expected output | mode |
| --- | --- | --- | --- | --- |

Required orchestration patterns:

- public API or architecture: `solution-architect` for API contract/migration shape, `sw-engineer` for implementation, `qa-specialist` for acceptance matrix, and `doc-scribe` for public docs/docstrings when applicable.
- bug fix or regression: `investigate` or equivalent root-cause evidence first, then `sw-engineer` for the fix and `qa-specialist` for failure-before/pass-after proof.
- CI/tooling: `cicd-steward` for workflow behavior and `linting-expert` for ruff/mypy/pre-commit or suppression policy.
- security-sensitive code: read-only `security-auditor` before implementation; pair with `sw-engineer` and `qa-specialist` only after risk is scoped.
- ML/data/research behavior: `data-steward` for data contracts, `scientist` for method/metric validity, `squeezer` for performance claims, plus `qa-specialist` for tensor boundary tests.
- docs-impacting behavior: `doc-scribe` gets only the verified public behavior, API signatures, examples, and migration notes; do not send unrelated implementation details.
- high-risk or broad changes: `challenger` runs after the draft plan or diff to stress-test assumptions and residual risk.

Each specialist context pack must include only relevant files, hunks, logs, and questions. Do not give every specialist the full task history. If specialist fan-out is unavailable, record the in-main substitute in `$OUT_DIR/specialist-notes.md` and lower confidence when independence mattered.

### 07: Write `$OUT_DIR/development-notes.md` before running gates

Required sections:

- `Scope`
- `Acceptance Criteria`
- `Evidence`
- `Specialist Policy`
- `Gates`

### 08: Run shared quality gates

Inspect `run-gates.sh --help`, then run all project-relevant gates with explicit commands or skip reasons.

### 09: Review the changed files and the gate output before deciding pass/fail

### 10: Classify findings using `../../shared/severity-map.md`

### 11: Run confidence calibration and recovery before any user-facing output

Write `"$OUT_DIR/confidence-calibration.md"` with these sections:

- `Initial Confidence`: starting score and the concrete uncertainty sources.
- `Objective Evidence`: code paths read, tests/checks run, reproduction or acceptance evidence, and artifacts inspected.
- `Confidence Gaps`: missing evidence, unverified assumptions, risky substitutions, or unavailable checks.
- `Recovery Actions`: internal loops already performed to increase confidence, such as reading more source, running focused checks, adding/adjusting tests, consulting specialist policy, or reducing scope.
- `Recomputed Confidence`: final score after recovery, with why it is objectively supported.
- `Remaining Limits`: residual uncertainty and why it is acceptable or blocking.

Shared confidence policy:

Apply the shared confidence band policy from `../../shared/quality-gates.md`. This skill records the required evidence in `confidence-calibration.md` and mirrors it in `DEVELOP_METADATA.confidence_recovery` before output.

Confidence must be honest and objectively verifiable. Do not inflate it to pass a gate; if the evidence is missing, keep the lower score and fail or time out with the missing evidence named.

### 12: Write and validate the mandatory result artifact

Follow `../../shared/helper-cli-contract.md` and authoritative help. Write with `DEVELOP_METADATA`, validate as skill `develop`, and promote only the validated candidate.

`DEVELOP_METADATA.confidence_recovery` must mirror `confidence-calibration.md` and include `initial_confidence`, `final_confidence`, `status`, `evidence`, `recovery_actions`, and `remaining_limits`. `DEVELOP_METADATA.confidence_gap_closures` must include one closure record per non-empty `confidence_gaps` entry, with `status=closed|unresolved|deferred` and matching evidence or rationale.

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
15. New or materially changed function/method without a purpose docstring in the configured, established, or fallback project style => fail unless it is generated or third-party code explicitly outside the edited ownership.
16. Non-trivial new or changed code block without an explanatory inline comment => fail unless the code was refactored until the rationale is obvious from names and structure.
17. Explanatory inline comment immediately before a new or changed function/class definition => fail; move that explanation into the docstring.
18. Long, dense, or deeply nested new/changed code block that could be split into clear helpers/classes or simplified with guard clauses => fail unless the local project pattern requires the structure.
19. Low-value tiny function/class that only remaps arguments, wraps one call without a semantic purpose, or is rarely used => fail unless it materially improves readability, testability, or API stability.
20. Missing `confidence-calibration.md` sections => fail.
21. Shared confidence policy violation from `../../shared/quality-gates.md` => fail.

## Quality Gates

Required checks:

- `review`: `git diff --check`, changed-file inspection, acceptance criteria trace, simplicity/readability/reproducibility inspection, project docstring-style detection, and docstring/comment policy inspection for changed code.
- `tests`: failing-then-passing check or explicit acceptance probe for changed behavior; `feature` mode must include the demo failure before edits and demo pass after implementation.
- `artifact`: shared validator confirms `development-notes.md`, gate logs, and result JSON shape.
- `confidence`: `confidence-calibration.md` and `DEVELOP_METADATA.confidence_recovery` satisfy the shared confidence band policy from `../../shared/quality-gates.md`.

Conditional checks:

- `lint`/`format`/`types`: run project-configured commands when code or typed config changed.
- `calibration`: run when workflow skills, role/agent routing, `.codex/config.toml`, or calibration fixtures changed; Codex Rig source uses `runtime/calibration/run.py --layout plugin`.

## Calibration Hooks

Update calibration when implementation routing or output expectations change:

- benchmark patterns: `develop`
- behavioral cases: symptom-first routing, specialist substitution, config behavior changes, missing acceptance probe, feature demo gate bypass, missing project docstring-style detection, missing function docstrings, overlong docstrings masking complex code, long code blocks not factored, deep branching without guard clauses, low-value argument-remapping wrappers, pre-definition comments that should be docstrings, missing explanatory inline comments, low-confidence recovery loop, objective confidence evidence, artifact validator bypass

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Final chat output must include the confidence score, confidence band status, recovery actions, remaining limits, and the concrete confidence gaps or degradation reasons plus closure status from `metadata.confidence_gaps` and `metadata.confidence_gap_closures`.

Minimum artifact payload template: `result-template.json`.
