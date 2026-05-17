---
name: refactor
description: "Test-first refactoring — audit coverage, add characterization tests, apply changes with safety net, run quality stack and review loop."
argument-hint: '<target file or directory> <goal> [--plan <path>] [--no-challenge] [--codemap] [--no-codemap] [--accept-no-plan] [--semble] [--team]'
effort: high
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
when_to_use: "Restructure existing code without changing behaviour — NOT for bug fixes (use fix) or new capabilities (use feature)."
---

<objective>

Test-first refactoring. Audit coverage, add characterization tests if missing, apply changes with safety net.

NOT for:
- bug fixes (use `/develop:fix`)
- new features (use `/develop:feature`)
- `.claude/` config changes (use `/foundry:manage` (requires foundry plugin))
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature; do not attempt both in single skill run

</objective>

<constants>

- MAX_INNER_CYCLES: 5 (change-test cycles per outer session — Step 4 safety break)

</constants>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at plugins/develop/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
_PATHS=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev-shared-resolve.sh" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The code is simple enough — I can skip characterization tests" | No safety net = no proof behavior unchanged. Characterization tests only proof. |
| "I'll fix this adjacent bug while I'm in here" | Scope creep conflates history. Adjacent bugs go in Follow-up, not this session. |
| "The tests are too brittle — I'll refactor them as well" | Refactoring tests + prod code simultaneously makes regressions unattributable. Fix tests first, separate pass. |
| "I know the codebase — no need for coverage audit" | Untested edge cases = most common refactoring breakage. Audit finds what you don't know you don't know. |
| "This is a small change — Step 4's max-5 cycles are overkill" | Simple changes = simple test loops. Guard costs nothing when unneeded; prevents runaway sessions when it is. |

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Optional `--plan <path>`**: if `$ARGUMENTS` ends with `--plan <path>`, read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to inform Step 1 scope analysis. Skip redundant codebase exploration for already-classified files. Store plan path as `PLAN_FILE`.

Read `$_DEV_SHARED/preflight-helpers.md` — execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: run `DEV_DIR=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev-run-dir.sh" 2>/dev/null)  # timeout: 5000` to create `.developments/<TS>/` and capture path. Write `checkpoint.md` inside `$DEV_DIR`. After each major step (1, 2, 3, 4, 5), append `step: N — completed` to `$DEV_DIR/checkpoint.md`. On skill start, check for existing `.developments/*/checkpoint.md` — offer resume from last completed step if found.

## Flag parsing

**Set `CHALLENGE_ENABLED=true`**. If `--no-challenge` in `$ARGUMENTS`, set `CHALLENGE_ENABLED=false`.

```bash
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-flags.sh" "$ARGUMENTS" 2>/dev/null)  # timeout: 5000
```

**Set `SEMBLE_ENABLED=false`**. If `--semble` in `$ARGUMENTS`, set `SEMBLE_ENABLED=true`.
**Set `TEAM_MODE=false`**. If `--team` in `$ARGUMENTS`, set `TEAM_MODE=true`.
**Set `ACCEPT_NO_PLAN=false`**. If `--accept-no-plan` in `$ARGUMENTS`, set `ACCEPT_NO_PLAN=true`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--accept-no-plan\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Codemap auto-detection** — run after flag parsing:

```bash
CODEMAP_ENABLED=$(${CLAUDE_PLUGIN_ROOT}/bin/codemap-resolve "$CODEMAP_ENABLED") || exit 1
```

**Preflight** — if `CODEMAP_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute codemap + semble preflight if respective flags set.

## Step 1: Scope and understand

Read target code, build mental model before touching anything.

If `<target>` is directory: use Glob tool (pattern `**/*.py`, path `<target>`) to enumerate Python files.

```bash
# Measure current state
find <target> -name '*.py' -exec wc -l {} + 2>/dev/null | tail -1
```

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**: read `$_DEV_SHARED/codemap-context.md` and follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip if both false.

**Multi-file / API-change scope — extended codemap scan** (only when `CODEMAP_ENABLED=true`): if target is directory, spans multiple files, or goal mentions renaming/restructuring public API (i.e., refactoring NOT limited to internals of single function or class with unchanged public interface):

```bash
# Derive project name and affected modules
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")  # timeout: 3000
# Affected modules from <target> path: strip src/ prefix, drop .py, slash→dot
REFACTOR_FILES=$(find <target> -name '*.py' -type f 2>/dev/null)
AFFECTED_MODULES=$(echo "$REFACTOR_FILES" | sed 's|^\./||;s|^src/||;s|\.py$||;s|/|.|g' | grep . || echo "")
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/scan/${PROJ}.json" ] && [ -n "$AFFECTED_MODULES" ]; then
    # Reusability: who calls each affected module outside the refactoring scope
    while IFS= read -r mod; do
        scan-query rdeps "$mod" 2>/dev/null
    done <<< "$AFFECTED_MODULES"
    # Tightest coupling pairs — determines refactor sequence and what must change together
    scan-query coupled --top 10
fi
```

Include `## Scope & Reusability (codemap)` block in foundry:sw-engineer spawn prompt. If `rdeps` returns callers **outside** refactoring scope: flag explicitly — those callers must update or refactoring silently breaks public contract. If `CODEMAP_ENABLED=false` and scope is multi-file: skip silently.

Spawn **foundry:sw-engineer** agent to analyze code and identify:

- Public API surface (functions, classes, methods external code calls)
- Internal complexity hotspots (cyclomatic complexity, deep nesting, long functions)
- Code smells relevant to stated goal
- Dependencies and coupling between modules
- **Complexity smell**: directory or cross-module scope — flag it; consider team mode

**Scope gate**: if target is directory-wide scope (10+ files) regardless of goal, flag complexity smell. Use `AskUserQuestion`: "Narrow scope (Recommended)" / "Proceed anyway".

Read `$_DEV_SHARED/plan-inline.md` §Inline Plan Generation Protocol. Apply using **refactor** context from the Skill contexts table. On proceed: set `PLAN_FILE=<path>`; continue to Step 2. On small complexity or `ACCEPT_NO_PLAN=true`: skip and continue to Step 2.

## Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

Spawn `foundry:challenger` with scope analysis from Step 1 (affected files, dependencies, coupling, risks):

> "Review the refactoring scope and approach. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Don't proceed to Step 2 until user resolves each blocker or explicitly accepts risk.
- **Concerns only** → surface as advisory before coverage audit; continue.
- **No findings / all refuted** → proceed.

## Step 2: Audit test coverage

Find existing tests for target code:

Use Glob tool (pattern `**/test_*.py` or `**/*_test.py`), then Grep tool (pattern `<module_name>`, output mode `files_with_matches`) to narrow to those referencing target.

> (Use Glob tool — `pattern: **/test_*.py` — to discover test files; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` for configured paths)

```bash
# Check pytest available
$PYTEST_CMD --co -q 2>&1 | head -5

# Check pytest-cov available
SKIP_COV=0
if $PYTEST_CMD --co -q --cov=. 2>&1 | grep -q "ModuleNotFoundError\|No module named.*cov"; then
    echo "WARNING: pytest-cov not installed — coverage data unavailable; classifying all public functions as UNCOVERED (conservative)"
    SKIP_COV=1
fi

# Collect tests for target module
$PYTEST_CMD --co -q 2>&1 | grep -i "<module_name>" || echo "No tests found for <module_name>"

# Run coverage (only if pytest-cov available)
[ "${SKIP_COV}" -eq 0 ] && $PYTEST_CMD --cov=<target_module> -q --cov-report=term-missing
```

Classify each public function/method:

- **Covered**: at least one test for happy path + one edge case
- **Partially covered**: test exists but missing edge cases or failure paths
- **Uncovered**: no test

### Review: Validate the coverage audit

Before writing characterization tests, evaluate audit output critically:

1. **Completeness**: all public functions, methods, classes identified — including complex call paths?
2. **Classification accuracy**: each item correctly classified? Partial-covered often misclassified as covered.
3. **Refactor relevance**: uncovered/partial items in code paths refactoring will touch?
4. **Hidden dependencies**: integration points or cross-module calls audit may have missed?

If audit incomplete: re-examine before Step 3. Gaps found mid-refactoring (Step 4) costly.

<!-- Only active when --team flag passed (~10% of invocations) -->
**Team mode branch** — if `TEAM_MODE=true`: Steps 1–2 complete solo (teammates need scope + coverage context). Spawn both teammates now; skip Steps 3–5, proceed to Final Report after results received.

When `TEAM_MODE=true`:

Compute run directory and create health sentinel:

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".temp/develop/${TS}"
mkdir -p "$RUN_DIR"
touch /tmp/refactor-team-check-$TS
```

Spawn 2 teammates in parallel using Agent() tool:

**Teammate 1 — foundry:sw-engineer (model=opus)**: performs refactoring (Steps 4–5). Prompt: "You are a foundry:sw-engineer teammate refactoring: [target]. Read ~/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Your task: apply the refactoring steps (Steps 4–5: change with safety net, review). Scope constraint: only edit source files (not under `tests/`). Broadcast context: {target: <path>, coverage: <summary>, goal: <stated goal>}. Compact Instructions: preserve file paths, test results, coverage numbers. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal completion in final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to $RUN_DIR/refactor-sw-engineer.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N,\"summary\":\"<one-line>\"}."

**Teammate 2 — foundry:qa-specialist (model=opus)**: writes characterization tests (Step 3) in parallel. Prompt: "You are a foundry:qa-specialist teammate refactoring: [target]. Read ~/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Your task: write characterization tests (Step 3) to build a safety net for the refactor. Scope constraint: only create/edit files under `tests/`. Do NOT edit source files. Broadcast context: {target: <path>, coverage: <summary>, goal: <stated goal>}. Compact Instructions: preserve file paths, test results, coverage numbers. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal completion in final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to $RUN_DIR/refactor-qa-specialist.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N,\"summary\":\"<one-line>\"}."

Health monitoring (CLAUDE.md §8): create sentinel `touch /tmp/refactor-team-check-$TS`; every 5 min: `find $RUN_DIR -newer /tmp/refactor-team-check-$TS -type f | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min no file activity → timed out. One extension (+5 min) if `tail -20` of output file explains delay; second unexplained stall = hard cutoff. On timeout: read `tail -100` of stalled file; surface partial results with ⏱; never omit.

After both complete: read their output files from `$RUN_DIR/`, synthesize outputs, run quality stack, produce Final Report. Exit — do not continue to Steps 3–5.

Continue to Step 3 only when `TEAM_MODE=false`.

## Step 3: Add characterization tests (if needed)

For every **uncovered** or **partially covered** public API, spawn **foundry:qa-specialist** to generate characterization tests:

- Import function, call with representative inputs, assert **current** output
- Use `pytest.mark.parametrize` for multiple input/output pairs
- Name tests `test_<function>_characterization_*`

Spawn with context:
- Target module: `<module_path>`
- Coverage audit results: [paste coverage-audit output showing uncovered/partial functions]
- Uncovered public APIs to test: [list from audit]
- Current code (read target file before writing tests — tests must assert CURRENT behaviour, not desired)
- Test file target: `tests/test_<module>_characterization.py`
- Test naming: `test_<function>_characterization_<scenario>`

```bash
# Run to confirm they pass against current code
$PYTEST_CMD <test_file> -v
```

**Gate**: all characterization tests must pass before proceeding. Check exit code:

```bash
GATE_EXIT=$?
if [ "${GATE_EXIT:-0}" -eq 5 ]; then
    echo "GATE WARN: no tests collected (exit 5) — characterization test file missing or not detected by pytest; fix collection, not the code"
elif [ $GATE_EXIT -ne 0 ]; then
    echo "GATE FAIL: characterization test(s) failed (exit $GATE_EXIT) — fix the test, not the code"
    # The test is wrong if it fails on unmodified code
fi
echo "GATE OK: all characterization tests pass on unmodified code"
```

If `GATE_EXIT -ne 0`: characterization test is wrong — must document *current* behavior, not desired. Fix test to match what code actually does, then re-run.

## Step 4: Refactor with safety net

For each change:

1. One focused change (single responsibility per edit)
2. Run test suite:
   ```bash
   $PYTEST_CMD --tb=short <test_files> -v
   ```
3. Tests pass: proceed to next change
4. Tests fail: revert, try different approach

**Safety break**: track cycle count in scratch (`INNER_CYCLE=0`; increment after each change-test pair). After `MAX_INNER_CYCLES` cycles, stop — report what succeeded, what broke, what remains.

**Refactoring categories:**

- **Logic simplification**: replace complex conditionals, flatten nesting, extract helpers
- **API cleanup**: rename for clarity, consolidate parameters, add type annotations
- **Structural**: extract classes/modules, reduce coupling, apply design patterns
- **Performance**: replace loops with vectorized ops, reduce allocations, batch I/O
- **Dead code removal**: remove unused imports, unreachable branches, commented-out code; scan `_`-prefixed functions with no call sites; flag public methods absent from `__init__.py` exports

## Step 5: Review and close gaps

Full review of refactored code. **Loop** — review -> targeted refactoring (return to Step 4) -> re-review until only nits remain. Max 3 outer cycles. (Step 4's "max 5 change-test cycles" bound applies within each pass through Step 4, independent of outer loop.)

**Each cycle:**

1. Evaluate against all criteria:

   - **Behavior preservation**: all characterization tests and pre-existing tests pass with identical outputs
   - **Goal achieved**: stated refactoring goal actually accomplished (not just partial)
   - **No new smells**: no new coupling, complexity, or duplication introduced
   - **API surface**: no unintended public API changes (signature, return type, raised exceptions)
   - **Dead code**: unreachable code after refactor was removed

2. For every gap: return to Step 4, apply targeted fix — one focused change per gap.

3. Re-run full test suite:

   ```bash
   $PYTEST_CMD --tb=short <test_files> -v 2>&1 | tail -20
   GATE_EXIT=${PIPESTATUS[0]}
   ```

4. **Objective convergence check**: if findings this cycle identical to previous cycle (same locations, same issues), declare convergence and exit — further cycles won't resolve; surface to user.

5. **Only nits remain** (variable naming, comment clarity, minor formatting): document in Follow-up, exit loop.

6. **Substantive gaps remain**: start next cycle (max 3 total).

**After 3 cycles**: substantive issues remain → stop, surface to user.

Read `$_FOUNDRY_SHARED/quality-stack.md` (if not found → skip quality stack entirely, note "foundry quality-stack not found at installed path — stack skipped" in Final Report) and execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

## Final Report

```markdown
## Refactor Report: <target>

### Goal
[stated goal or "general quality pass"]

### Test Coverage Before
- Covered: N functions | Partially: N | Uncovered: N
- Characterization tests added: N

### Changes Made
| File | Change | Lines |
|------|--------|-------|
| path/to/file.py | extracted helper function | -12/+8 |

### Test Results
- All tests passing: yes/no
- Coverage: before% -> after%

### Follow-up
- [any remaining items that need manual review]

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**:
- [e.g., coverage tool unavailable, some tests skipped]

**Refinements**: N passes.
```

</workflow>
