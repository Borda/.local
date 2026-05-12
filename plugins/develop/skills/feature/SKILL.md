---
name: feature
description: TDD-first feature development — crystallise API as a demo test, drive implementation to pass it, run quality stack and progressive review loop.
argument-hint: '<goal> [--plan <path>] [--no-challenge] [--codemap] [--semble] [--team]'
effort: high
when_to_use: Use when adding new capability that doesn't exist yet; NOT for fixing broken existing behaviour (use fix) or restructuring without changing behaviour (use refactor).
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskCreate, TaskUpdate, AskUserQuestion, WebFetch
disable-model-invocation: true
---

<objective>

TDD-first feature development. Crystallise API as demo use-case test, drive implementation to pass it, close quality gaps with review, docs, quality stack.

NOT for:
- bug fixes (use `/develop:fix`)
- `.claude/` config changes (use `/foundry:manage`)
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature

</objective>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at plugins/develop/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
# Locate develop plugin shared dir — installed first, local workspace fallback
_DEV_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/develop/*/skills/_shared 2>/dev/null | head -1)
[ -z "$_DEV_SHARED" ] && _DEV_SHARED="plugins/develop/skills/_shared"
_FOUNDRY_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | head -1)
[ -z "$_FOUNDRY_SHARED" ] && _FOUNDRY_SHARED=".claude/skills/_shared"
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:challenger`.

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The feature is clear — I can skip the demo and go straight to code" | Without crystallized API contract, implementation drifts. Demo = spec. |
| "I know this library — no need to check docs" | Training data contains deprecated patterns. One fetch prevents hours of rework. |
| "I'll write tests after the implementation is stable" | Tests drive design. Writing first reveals API problems before baked in. |
| "The existing suite still passes — the feature is good" | Existing suite doesn't cover new feature. Demo and edge-case tests do. |
| "Step 1 analysis is unnecessary for a small addition" | Scope analysis reveals reuse opportunities and blast radius. Small additions regularly grow. |

Read `$_DEV_SHARED/task-hygiene.md`.

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Optional `--plan <path>`**: if `$ARGUMENTS` ends with `--plan <path>`, read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to populate Step 1 analysis instead of cold codebase exploration. Skip agent feasibility re-check (already done in `/develop:plan`). Store plan path as `PLAN_FILE`.

Read `$_DEV_SHARED/preflight-helpers.md` — execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: create `.developments/<TS>/checkpoint.md` (where `TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)`). After each major step (1, 2, 3, 4, 5), append `step: N — completed` to this file. On skill start, check for existing `.developments/*/checkpoint.md` — if found, offer to resume from last completed step.

## Flag parsing

**Set `CHALLENGE_ENABLED=true`**. If `--no-challenge` present in `$ARGUMENTS`, set `CHALLENGE_ENABLED=false`.
**Set `CODEMAP_ENABLED=false`**. If `--codemap` present in `$ARGUMENTS`, set `CODEMAP_ENABLED=true`.
**Set `SEMBLE_ENABLED=false`**. If `--semble` present in `$ARGUMENTS`, set `SEMBLE_ENABLED=true`.
**Set `TEAM_MODE=false`**. If `--team` present in `$ARGUMENTS`, set `TEAM_MODE=true`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Preflight** — if `CODEMAP_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute codemap + semble preflight if respective flags set.

## Team Mode Branch

**Run immediately after flag parsing when `TEAM_MODE=true` — then `exit 0`; skip Steps 1-5.**

```bash
if [ "$TEAM_MODE" = "true" ]; then
  # Step 1 scope analysis still required — teammates need it to orient
  # (run inline before spawning; same analysis as solo Step 1)
  # After scope analysis, broadcast to teammates:
  # {feature: <desc>, scope: <modules>, API: <proposed signature>}

  # Spawn teammate 1: foundry:sw-engineer — implements feature (Steps 2-3)
  # Spawn teammate 2: foundry:qa-specialist — TDD tests + security checks (parallel)
  # Spawn teammate 3: foundry:doc-scribe — documentation structure (parallel, Step 5 prep)
  #
  # Coordination order:
  #   1. QA challenges SW API design — lead routes challenge back to SW before implementation starts
  #   2. SW shares implementation details with QA so tests stay accurate
  #   3. Lead synthesizes outputs in Step 5 onward as normal
  #
  # Spawn prompt template (from $_DEV_SHARED/preflight-helpers.md ## Team Spawn Template):
  # Replace [ROLE_PHRASE] with feature description, [FILE_SLUG] with "feature"
  #
  # Teammate 1 (sw-engineer):
  #   "You are a foundry:sw-engineer teammate implementing: [feature description].
  #    Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
  #    Your task: implement the feature (Steps 2-3: demo test, TDD loop).
  #    Compact Instructions: preserve file paths, test results, API signatures. Discard verbose tool output.
  #    Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state.
  #    Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'.
  #    Write your full analysis to .plans/active/feature-sw-engineer-[timestamp].md using the Write tool.
  #    Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}."
  #
  # Teammate 2 (qa-specialist, model=opus):
  #   "You are a foundry:qa-specialist teammate implementing: [feature description].
  #    Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
  #    Your task: write TDD tests in parallel with SW implementation; include security checks for any
  #    auth/payment/data-handling code.
  #    Compact Instructions: preserve file paths, test results, API signatures. Discard verbose tool output.
  #    Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state.
  #    Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'.
  #    Write your full analysis to .plans/active/feature-qa-specialist-[timestamp].md using the Write tool.
  #    Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}."
  #
  # Teammate 3 (doc-scribe, model=sonnet):
  #   "You are a foundry:doc-scribe teammate implementing: [feature description].
  #    Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
  #    Your task: prepare documentation structure in parallel (Step 5 prep — docstrings, CHANGELOG, README).
  #    Compact Instructions: preserve file paths, doc locations, API signatures. Discard verbose tool output.
  #    Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state.
  #    Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'.
  #    Write your full analysis to .plans/active/feature-doc-scribe-[timestamp].md using the Write tool.
  #    Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N}."
  #
  # After all teammates complete: read their output files, synthesize, run quality stack, produce Final Report.
  exit 0
fi
```

## Step 1: Understand purpose and scope

Gather full context before writing any code:

> **Argument type detection**: if `$ARGUMENTS` is positive integer (or prefixed with `#`, e.g. `#123`), treat as GitHub issue number and fetch with `gh issue view`. If text, treat as feature description.

```bash
# Strip leading '#' and fetch in one block — ARGUMENTS strip doesn't persist across Bash calls
ISSUE_NUM="${ARGUMENTS#\#}"
gh issue view "$ISSUE_NUM" --comments  # timeout: 6000
```

If free-text description provided: use Grep tool (pattern `<keyword>`, glob `**/*.py`) to search related code. Path hint: use `src/` if that directory exists, otherwise search from project root (`.`).

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**: read `$_DEV_SHARED/codemap-context.md` and follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip entirely if both flags false.

Spawn **foundry:sw-engineer** agent to analyse codebase and produce:

- **Purpose**: what problem does feature solve, and for which users?
- **Scope**: which files and modules likely change (entry points, data models, tests)?
- **Compatibility**: does feature touch public API? Require deprecation? Need backward-compat shims?
- **Reuse opportunities**: existing utilities, base classes, patterns, abstractions new code can extend instead of duplicate
- **Risks**: edge cases, performance implications, integration points needing careful handling
- **Scope challenge**: Right problem? Simpler alternatives? What already exists that could extend instead of build from scratch?
- **Complexity smell**: if proposed change touches 8+ files or introduces 2+ new classes/modules, flag explicitly — scope may need narrowing before proceeding

**Gate**: if complexity smell flagged, present scope concern to user before proceeding to Step 2.

Present analysis summary before proceeding.

## Optional Step: Source Verification (when using external APIs or version-sensitive libraries)

Skip if feature calls no external library APIs — no new framework features, no third-party SDK methods, no stdlib functions changed in recent Python version.

**Trigger**: feature calls external library API — new framework feature, third-party SDK method, or stdlib function changed in recent Python version.

**DETECT → FETCH → CITE pipeline:**

1. **DETECT** — read `pyproject.toml` or `requirements*.txt` for exact version and output:

   ```markdown
   STACK DETECTED:
   - <library> <exact-version> (from pyproject.toml)
   → Fetching official docs for the relevant API.
   ```

2. **FETCH** — use WebFetch to retrieve **specific relevant docs page** (not homepage). Source priority: official docs > official changelog/migration guide > web standards (MDN). Never cite Stack Overflow, blog posts, or AI training data.

   If WebFetch fails (network unavailable, site down): skip source verification entirely. Proceed to Step 2. Note in Final Report: "Source verification skipped — WebFetch unavailable."

3. **CITE** — when implementing, embed comment with source URL and key quoted passage:

   ```python
   # Docs: https://docs.example.com/v2/api/method
   # "The recommended pattern for X is Y" (v2.1 docs)
   ```

4. **Conflict** — if docs describe pattern conflicting with how codebase currently uses library:

   ```text
   CONFLICT DETECTED:
   Existing code uses <old pattern>.
   <library> <version> docs recommend <new pattern> for this use case.
   Options:
   A) Use the documented pattern (may require updating existing call sites)
   B) Match existing code (works but not idiomatic for this version)
   → Which approach?
   ```

## Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

Spawn `foundry:challenger` with scope analysis from Step 1 (purpose, scope, risks, approach):

> "Review implementation approach and scope identified in Step 1. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Don't proceed to Step 2 until user resolves each blocker or explicitly accepts risk.
- **Concerns only** → surface as advisory section before demo test; continue.
- **No findings / all refuted** → proceed.

## Step 2: Write a demo use-case

Before crystallising API, surface non-obvious design decisions:

> ASSUMPTIONS I'M MAKING:
>
> 1. [assumption about API shape, e.g. "returning a list not a generator"]
> 2. [assumption about caller context, e.g. "called once per batch, not per item"] → Correct me now or I'll proceed with these.

Don't proceed to demo if any assumption would materially change API shape.

Crystallise intended API contract before any implementation. Choose form based on scope:

> **Choosing demo form**: use inline doctest for simple functions/methods with minimal setup; use example script for features requiring external state, multiple steps, or side effects.

**Unit function / simple API** -> inline doctest:

```python
def predict(self, x: Tensor) -> Tensor:
    """
    >>> model = Classifier()
    >>> model.predict(torch.zeros(1, 3))
    tensor([0])
    """
```

**Complex feature** (setup required, side effects, multi-step flow) -> minimal example script:

```bash
mkdir -p examples/
```

```python
# examples/demo_<feature>.py  — throwaway script, run manually
from mypackage import Classifier

model = Classifier.from_pretrained("tiny")
result = model.predict_batch(["hello", "world"])
print(result)  # expected: [label, label]
```

Example script captures what feature should feel like to use. Becomes formal pytest test once implementation complete and API stable (end of Step 3).

Both forms must:

- Use **exact API** feature will expose (function name, signature, return type)
- Show happy-path end-to-end flow user would first reach for
- **Fail or error** against current code (feature doesn't exist yet)

**Gate**: demo must fail or error.

```bash
# Run demo and capture exit code in same Bash call — PIPESTATUS lost across separate calls
# Doctest form:
$PYTEST_CMD --doctest-modules <module>.py -v 2>&1 | tail -10; GATE_EXIT=${PIPESTATUS[0]}

# Script form (use instead of doctest when applicable):
# python examples/demo_<feature>.py 2>&1 | tail -5; GATE_EXIT=$?

if [ "${GATE_EXIT:-0}" -eq 0 ]; then
    echo "⚠ GATE FAIL: demo passed (exit 0) — feature may already exist; revisit Step 1"
elif [ "${GATE_EXIT}" -eq 5 ]; then
    # exit 5 = no tests collected = demo file missing = GATE FAIL
    echo "⚠ GATE FAIL: no demo tests collected (exit 5) — demo file missing or doctest not detected"
else
    echo "✓ GATE OK: demo failed as expected (exit $GATE_EXIT)"
fi
```

If `GATE_EXIT -eq 0` or `GATE_EXIT -eq 5`: stop. Don't proceed. Revisit Step 2 — demo is missing or feature already implemented.

### Review: Validate the demo

Before proceeding to implementation, critically evaluate demo:

1. **Goal alignment**: does demo address user's stated goal, or slightly different problem?
2. **API design**: is proposed API minimal? Follows existing codebase conventions (naming, parameter order, return types)?
3. **Missing scenarios**: obvious happy-path variants or important failure modes demo doesn't cover?
4. **Testability**: can demo be automatically verified — not just `print`-and-inspect?

If issue found: revise demo and re-run gate. Don't proceed to Step 3 with flawed API contract — entire TDD loop anchored to this.

## Step 3: TDD implementation loop

Drive implementation by making tests pass, one cycle at a time:

```bash
# Baseline: confirm existing suite is green before adding any new code
$PYTEST_CMD --tb=short <target_test_dir> -v 2>&1 | tail -20
GATE_EXIT=${PIPESTATUS[0]}
```

**Gate**: all existing tests must pass before proceeding. If any fail, stop — don't add new code on broken baseline. Use `/develop:fix` to address pre-existing failures first, then return here.

> **Note on exit code 5**: `pytest` returns exit code 5 when no tests collected. Exit code 5 acceptable here — means no pre-existing tests exist yet, valid baseline for new feature. Proceed with TDD loop. Only exit codes 1, 2, 3, 4 indicate actual test failures.

(Use Glob tool — `pattern: **/test_*.py` — to discover test directories if `<target_test_dir>` unknown; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` first)

Start from Step 2 demo — already failing, becomes first target. For each piece of functionality:

1. **Target demo or write next focused test** — first iteration uses Step 2 demo directly; subsequent iterations add one new test per piece of new behaviour
2. **Run existing suite — confirm all pass**:
   ```bash
   $PYTEST_CMD --tb=short <target_test_dir> -v 2>&1 | tail -20
   GATE_EXIT=${PIPESTATUS[0]}
   ```
3. **Run new demo/test — confirm it fails**:
   ```bash
   # doctest form
   $PYTEST_CMD --doctest-modules <module>.py -v --tb=short 2>&1 | tail -10
   GATE_EXIT=${PIPESTATUS[0]}
   # pytest form
   $PYTEST_CMD --tb=short <test_file>::<test_name> -v
   # script form
   python examples/demo_<feature>.py 2>&1 | tail -5
   ```
4. **Implement minimal code** (spawn **foundry:sw-engineer** agent for non-trivial logic):
   - Reuse or extend existing code identified in Step 1 — prefer subclassing or composing over parallel reimplementation
   - Match project's existing patterns (naming, error handling, type annotations)
5. **Run demo/test — confirm it passes**
6. **Run full suite** to catch regressions:
   ```bash
   $PYTEST_CMD --tb=short <target_test_dir> -v
   ```
7. If regressions appear: fix before moving on — never carry forward broken suite

Repeat until all feature tests pass and Step 2 demo passes.

If Step 2 produced example script: promote into formal pytest test now that API is stable. Delete script once test in place.

## Step 4: Review and close gaps

Full review of implementation. **Loop** — review -> fix -> re-review until only nits remain. Maximum 3 cycles.

**Each cycle:**

**5-axis quality scan** — before full criteria evaluation, assess implementation on each axis:

- **Correctness**: matches exact API from Step 2? Edge cases and error paths covered?
- **Readability**: can another engineer understand feature without reading issue or demo?
- **Architecture**: fits established patterns? Abstraction level appropriate?
- **Security**: if feature touches input handling, auth, or data storage — are those paths hardened?
- **Performance**: N+1 patterns, unbounded collections, unnecessary computation introduced?

Use scan to prioritize which criteria below get deepest scrutiny.

1. Evaluate against all criteria:

   - **API match**: implementation matches exact API from Step 2 (name, signature, return type)
   - **Scope discipline**: only Step-1-identified files changed; no drive-by fixes or unrelated edits
   - **Edge cases**: error paths, boundary inputs, None/empty handling exercised by tests
   - **Test quality**: tests verify behavior (not implementation internals); parametrized where inputs vary
   - **Simplicity**: no dead code, unnecessary abstractions, over-engineering

2. For every gap found: implement fix immediately — add missing tests, remove dead code, revert out-of-scope edits. Return to Step 3 for substantive implementation gap needing new TDD cycle.

3. Re-run full suite to confirm nothing regressed:

   ```bash
   $PYTEST_CMD --tb=short <target_test_dir> -v 2>&1 | tail -20
   GATE_EXIT=${PIPESTATUS[0]}
   ```

   > **Objective convergence check**: if findings in this cycle identical to previous cycle (same locations, same issues), declare convergence and exit loop — further cycles won't resolve; surface to user.

4. **If only nits remain** (style, cosmetic naming, minor formatting): document in Follow-up and exit loop.

5. **If substantive gaps remain**: start next cycle (max 3 total).

**After 3 cycles**: if substantive issues remain, stop — surface to user before proceeding to Step 5.

When stopping with unresolved issues, use this report variant instead of standard Final Report:

```markdown
## Feature Report: <feature name> [INCOMPLETE]

### Status
Implementation incomplete — stopped after 3 review cycles.

### Remaining Issues
- [list each unresolved substantive gap]

### What Works
- [completed parts, passing tests]

### Recommended Next Steps
1. [most actionable next step to unblock]
2. [second step]
```

## Step 5: Documentation

Spawn **foundry:doc-scribe** agent to update all affected docs:

- Add or update **docstrings** on new/modified functions and classes (Google style — Napoleon)
- Update module-level docstring if feature adds significant capability
- Add demo from Step 2 as doctest if not already embedded
- Update `CHANGELOG.md` with one-line entry under `Unreleased`
- If feature changes public API: update `README.md` usage examples

Spawn with context:
- Affected files: [list from Step 1 scope analysis]
- New/modified public API: [function names, signatures from Step 3]
- Demo location: [Step 2 demo file path and function name]
- CHANGELOG entry: [one-line description of feature]

Agent must Read each affected source file before writing docstrings — do not write placeholder content.

```bash
# Verify doctests pass after doc updates
$PYTEST_CMD --doctest-modules <target_module> -v 2>&1 | tail -20
GATE_EXIT=${PIPESTATUS[0]}
```

Read `$_FOUNDRY_SHARED/quality-stack.md` (if file not found → skip quality stack entirely, note "foundry quality-stack not found at installed path — stack skipped" in Final Report) and execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

## Final Report

```markdown
## Feature Report: <feature name>

### Purpose
[1-2 sentence description of what was built and why]

### Codebase Analysis
- Reused: [list of existing utilities/patterns leveraged]
- Modified: [files changed and why]
- New files: [list]

### Demo Use-Case
- Location: <file>::<test or doctest>
- API: [the function/class signature exposed]

### TDD Cycle
- Tests written: N
- Tests passing: N/N
- Regressions introduced: 0

### Quality
- Lint: clean / N issues fixed
- Types: clean / N issues fixed
- Doctests: passing
- Review: pass / N issues fixed (N cycles)

### Follow-up
- [any deferred items, known limitations, or suggested next steps]

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**:
- [e.g., review cycle incomplete, edge cases not fully explored]

**Refinements**: N passes.
```

## Team Assignments

**Reference documentation** — execution is in `## Team Mode Branch` above. When `--team` flag set, that branch runs and exits before Step 1.

**When to use team mode**: feature spans 3+ modules, OR changes public API, OR involves auth/payment/data scope.

- **Teammate 1 (foundry:sw-engineer, model=opus)**: implements feature (Steps 2-3)
- **Teammate 2 (foundry:qa-specialist, model=opus)**: writes TDD tests in parallel + security checks for auth/payment/data scope
- **Teammate 3 (foundry:doc-scribe, model=sonnet)**: prepares documentation structure in parallel (Step 5)

**Coordination:**

1. Lead broadcasts Step 1 analysis: `{feature: <desc>, scope: <modules>, API: <proposed signature>}`
2. QA challenges SW's API design first — lead routes challenge back to SW before implementation starts
3. SW shares implementation details with QA so tests stay accurate
4. Lead synthesizes outputs in Steps 5 onward as normal

**Spawn prompt template:**

```markdown
You are a [role] teammate implementing: [feature].
Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages.
Your task: [specific responsibility].
[If QA]: include security checks for any auth/payment/data-handling code.
Compact Instructions: preserve file paths, test results, API signatures. Discard verbose tool output.
Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal your completion in your final delta message: "Status: complete | blocked — <reason>".
Write your full analysis to .plans/active/feature-[role]-[timestamp].md using the Write tool. Return ONLY compact JSON: {"status":"done","file":"<path>","findings":N,"confidence":0.N}.
```

</workflow>
