---
name: fix
description: Reproduce-first bug resolution — capture bug in failing regression test, apply minimal fix, run quality stack and review loop.
argument-hint: '<symptom or issue # (plain 123 or #123)> [--plan <path>] [--diagnosis <path>] [--no-challenge] [--codemap] [--semble] [--team]'
effort: medium
when_to_use: Use when specific bug known and reproducible; NOT for unknown failures without traceback (use debug) or adding new capabilities (use feature).
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Reproduce-first bug resolution. Capture bug in failing regression test, apply minimal fix, verify via quality stack and review loop.

NOT for:
- unknown failures without traceback (use `/foundry:investigate` (requires foundry plugin))
- `.claude/` config issues (use `/foundry:audit` (requires foundry plugin))
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead

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

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:challenger`.

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "I already know root cause from symptom" | Assumptions without verification fix wrong bug. Read code path first. |
| "Regression test can wait — add after fix" | Fix without failing test = unverifiable. Test proves bug existed. |
| "Clean up nearby code while here" | Scope creep produces side effects, obscures fix. Touch only root cause. |
| "Targeted test passes — sufficient" | Targeted test shows bug fixed; full suite shows nothing else broke. Both required. |
| "Fix obvious — Step 1 analysis overkill" | Obvious causes often symptoms. Analysis reveals actual root cause and blast radius. |

Read `$_DEV_SHARED/task-hygiene.md`.

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Optional `--plan <path>`**: if `$ARGUMENTS` ends with `--plan <path>`, read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to populate Step 1 analysis instead of cold codebase exploration. Skip agent feasibility re-check (already done in `/develop:plan`). Store plan path as `PLAN_FILE`.

Read `$_DEV_SHARED/preflight-helpers.md` — execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: create `.developments/<TS>/checkpoint.md` (where `TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)`). After each major step (1, 2, 3, 4), append `step: N — completed`. On skill start, check for existing `.developments/*/checkpoint.md` — offer resume from last completed step if found.

## Fix Mode

**Optional `--diagnosis <path>`**: if provided (from preceding `/develop:debug` session), read diagnosis file first. Skip codebase analysis — root cause, suspect files, and evidence pre-populated. Proceed directly to Step 2 (regression test).

```bash
# Extract --diagnosis path from arguments (supports both --diagnosis <path> and --diagnosis=<path>)
DIAG_FILE=""
set -- $ARGUMENTS
while [ $# -gt 0 ]; do
  case "$1" in
    --diagnosis=*) DIAG_FILE="${1#--diagnosis=}" ;;
    --diagnosis) shift; DIAG_FILE="${1:-}" ;;
  esac
  shift
done
# Existence guard — fail fast if path supplied but missing
if [ -n "$DIAG_FILE" ] && [ ! -f "$DIAG_FILE" ]; then
  echo "! BREAKING — diagnosis file not found: $DIAG_FILE"
  echo "Fix: run /develop:debug first to produce a diagnosis file, or omit --diagnosis"
  exit 1
fi
```

Diagnosis file format: see `/develop:debug` Final Report section for canonical field definitions (Root Cause, Suspect Files, Evidence).

## Flag parsing

**Set `CHALLENGE_ENABLED=true`**. If `--no-challenge` present in `$ARGUMENTS`, set `CHALLENGE_ENABLED=false`.
**Set `CODEMAP_ENABLED=false`**. If `--codemap` present in `$ARGUMENTS`, set `CODEMAP_ENABLED=true`.
**Set `SEMBLE_ENABLED=false`**. If `--semble` present in `$ARGUMENTS`, set `SEMBLE_ENABLED=true`.
**Set `TEAM_MODE=false`**. If `--team` present in `$ARGUMENTS`, set `TEAM_MODE=true`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--diagnosis\`, \`--no-challenge\`, \`--codemap\`, \`--semble\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Preflight** — if `CODEMAP_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute codemap + semble preflight if respective flags set.

## Team Mode Branch

**If `TEAM_MODE=true`**: execute team workflow now — do not proceed to Step 1.

Root cause unclear after initial triage, OR bug spans 3+ modules and user accepted "Proceed anyway" at scope gate: use this path.

**Coordination:**

1. Lead broadcasts current evidence: `{bug: <description>, traceback: <key lines>}`
2. Spawn **foundry:sw-engineer x 2-3 (model=opus)** — each investigates a distinct root-cause hypothesis independently. Read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template — replace `[ROLE_PHRASE]` with `[bug description]`, `[FILE_SLUG]` with `fix-hypothesis`.
3. Each teammate investigates independently — claims hypothesis; returns full output to file (file-based handoff protocol).
4. Lead facilitates cross-challenge between competing analyses.
5. Lead synthesizes consensus root cause, then proceeds with Steps 2-4 (regression test, fix, review loop) alone.

```bash
if [ "$TEAM_MODE" = "true" ]; then
  # Spawn 2-3 sw-engineer teammates — each claims a distinct root-cause hypothesis
  # Health monitoring setup (CLAUDE.md §8)
  FIX_TEAM_LAUNCH=$(date +%s)
  touch /tmp/fix-team-check-1 /tmp/fix-team-check-2  # timeout: 3000
fi
```

```text
# Teammate 1 (foundry:sw-engineer, model=opus) — hypothesis A:
Agent(subagent_type="foundry:sw-engineer", model="opus", prompt="You are a foundry:sw-engineer teammate investigating a bug fix. Read $_DEV_SHARED/preflight-helpers.md §Team Spawn Template.\n\nBug: ${ARGUMENTS}\nEvidence: {bug: <description>, traceback: <key lines>}\n\nYour task: investigate hypothesis A — claim one distinct root-cause hypothesis, gather evidence, propose fix approach.\nTask tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state.\nSignal completion: 'Status: complete | blocked — <reason>'.\nWrite full analysis to .plans/active/fix-hypothesis-A-[timestamp].md using Write tool.\nReturn ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}")

# Teammate 2 (foundry:sw-engineer, model=opus) — hypothesis B:
Agent(subagent_type="foundry:sw-engineer", model="opus", prompt="You are a foundry:sw-engineer teammate investigating a bug fix. Read $_DEV_SHARED/preflight-helpers.md §Team Spawn Template.\n\nBug: ${ARGUMENTS}\nEvidence: {bug: <description>, traceback: <key lines>}\n\nYour task: investigate hypothesis B — claim a DIFFERENT root-cause hypothesis from your teammates, gather evidence, propose fix approach.\nTask tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state.\nSignal completion: 'Status: complete | blocked — <reason>'.\nWrite full analysis to .plans/active/fix-hypothesis-B-[timestamp].md using Write tool.\nReturn ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}")
```

```bash
# Health monitoring — poll every 5 min; hard cutoff 15 min (CLAUDE.md §8)
# After spawning both teammates above, monitor:
# find .plans/active/ -newer /tmp/fix-team-check-1 -name "fix-hypothesis-*.md" | wc -l — new files = alive
# On timeout: read tail -100 of each .plans/active/fix-hypothesis-*.md; surface with ⏱
```

```bash
if [ "$TEAM_MODE" = "true" ]; then
  # After teammates complete: read their output files, synthesize consensus root cause
  # Lead proceeds with Steps 2-4 (regression test, fix, review loop) alone
  exit 0
fi
```

## Step 1: Understand the problem

Gather all available context about bug:

> **Argument type detection**: if `$ARGUMENTS` is positive integer (or prefixed with `#`, e.g. `#123`), treat as GitHub issue number and fetch with `gh issue view`. If text (contains spaces, letters, or special chars), treat as symptom description.

```bash
# Strip leading '#' so both '123' and '#123' work
ARGUMENTS="${ARGUMENTS#\#}"
```

```bash
# If issue number: fetch the full issue with comments
gh issue view <number> --comments
```

If error message or pattern provided: use Grep tool (pattern `<error_pattern>`, path `.`) to search codebase for failing code path.

```bash
# If failing test: run it to capture the exact failure
$PYTEST_CMD --tb=long <test_path> -v 2>&1 >/tmp/pytest-out.txt; PYTEST_EXIT=$?; tail -40 /tmp/pytest-out.txt; [ $PYTEST_EXIT -ne 0 ] && echo "PYTEST FAILED (exit $PYTEST_EXIT)"
```

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**: read `$_DEV_SHARED/codemap-context.md` and follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip entirely if both flags false.

Spawn **foundry:sw-engineer** agent to analyze failing code path and identify:

- Root cause — what wrong and why (not just symptom)
- Entry point to failure — which modules does call cross?
- State mutation — what state changed along way?
- Invariant violated — what condition broke at failure point?
- Minimal code surface needing change — exact files and functions
- Related code possibly affected by fix — blast radius
- Recent commits touching this path (from git log output, if provided)

If root cause not definitively established after analysis, surface assumptions before proceeding:

> ASSUMPTIONS I'M MAKING:
>
> 1. [assumption about root cause]
> 2. [assumption about affected scope] -> Correct me now or I'll proceed with these.

**Scope gate**: if root cause spans 3+ modules, flag complexity smell. Use `AskUserQuestion` to present scope concern before proceeding, with options: "Narrow scope (Recommended)" / "Proceed anyway".

## Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

Spawn `foundry:challenger` with root cause analysis from Step 1 (root cause, blast radius, assumptions, approach):

> "Review root cause analysis and proposed fix approach. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Do not proceed to Step 2 until user resolves each blocker or explicitly accepts risk.
- **Concerns only** → surface as advisory; continue.
- **No findings / all refuted** → proceed.

## Step 2: Reproduce the bug

Create or identify test demonstrating failure:

(Use Glob tool — `pattern: **/test_*.py` — to discover test directories if `<test_dir>` unknown; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` first)

```bash
# If a failing test already exists — run it to confirm it fails
$PYTEST_CMD --tb=short <test_file>::<test_name> -v

# If no test exists — write a regression test that captures the bug
```

Spawn **foundry:qa-specialist** agent to write regression test if none exists:

- Test must **fail** against current code (proving bug exists)
- Use `pytest.mark.parametrize` if bug affects multiple input patterns
- Keep test minimal — exercise exactly broken behavior
- Add brief comment linking to issue if applicable (e.g., `# Regression test for #123`)

Spawn with context:
- Bug description: [symptom from $ARGUMENTS or issue]
- Failing output: [exact error/traceback captured in Step 1]
- Suspect files: [files identified by sw-engineer in Step 1]
- Expected behaviour: [what should happen]
- Actual behaviour: [what currently happens]
- Regression test must import from `<module>`, name `test_<bug_description>_regression`

**Gate**: regression test must fail before proceeding. Check exit code — do not rely on output text alone:

```bash
GATE_EXIT=$?
if [ $GATE_EXIT -eq 0 ]; then
    echo "GATE FAIL: test passed (exit 0) — bug not captured; revisit Step 1"
    exit 1
fi
echo "GATE OK: test failed as expected (exit $GATE_EXIT)"
```

If `GATE_EXIT -eq 0`: stop. Bug not reproduced. Do not apply fix.

### Review: Validate the reproduction

Before applying fix, critically evaluate regression test:

1. **Correct failure mode**: fails for right reason (actual bug), not setup issue?
2. **Isolation**: exercises exactly broken behavior, not too broadly?
3. **Minimal reproduction**: smallest test demonstrating failure?
4. **Parametrization**: key variants covered if bug spans multiple input patterns?

If issue found: revise regression test before applying fix. Flawed reproduction = fix validated against wrong criteria.

## Step 3: Apply the fix

Make minimal change to fix root cause:

1. Edit only code necessary to resolve bug
2. Run regression test to confirm now passes:
   ```bash
   $PYTEST_CMD --tb=short <test_file>::<test_name> -v
   ```
3. Run full test suite for affected module:
   ```bash
   $PYTEST_CMD --tb=short <test_dir> -v
   ```
   **If `<test_dir>` does not exist or has no tests beyond regression test**: run only regression test (already verified in Step 2). Note in Final Report: "No pre-existing test suite found — regression test is sole verification."

4. If existing tests break: fix has side effects — reconsider approach

## Step 4: Review and close gaps

Full review of fix. **Loop** — review -> fix -> re-review until only nits remain. Max 3 cycles.

**Each cycle:**

**5-axis quality scan** — before full criteria evaluation, assess fix on each axis:

- **Correctness**: addresses root cause (not symptom)? Edge cases covered?
- **Readability**: comprehensible without surrounding bug context?
- **Architecture**: fits existing patterns? New coupling introduced?
- **Security**: bug path touch input handling, auth, or data? If yes, addressed?
- **Performance**: fix introduce loops, queries, or calls in hot path?

Use scan to prioritize which criteria below get deepest scrutiny.

1. Evaluate against all criteria:

   - **Root cause**: fix addresses actual root cause, not just symptom
   - **Minimality**: smallest change resolving bug; no collateral edits
   - **Regression test quality**: test precisely isolates bug (fails before fix, passes after)
   - **Side effects**: full suite passes without new failures or unexpected warnings

2. For every gap found: implement fix immediately — tighten patch, remove collateral edits, adjust test. Return to Step 3 for gap requiring re-examining fix approach.

3. Re-run test suite:

   ```bash
   $PYTEST_CMD --tb=short <test_dir> -v 2>&1 >/tmp/pytest-out.txt; PYTEST_EXIT=$?; tail -20 /tmp/pytest-out.txt; [ $PYTEST_EXIT -ne 0 ] && echo "PYTEST FAILED (exit $PYTEST_EXIT)"
   ```

4. **Adjacent bugs** (observation only): scan for similar patterns; document in Follow-up — do not fix here, avoids scope creep.

5. **Objective convergence check**: if findings this cycle identical to previous cycle (same locations, same issues), declare convergence and exit — further cycles won't resolve; surface to user instead.

6. **Only nits remain**: document in Follow-up, exit loop.

7. **Substantive gaps remain**: start next cycle (max 3 total).

**After 3 cycles**: if substantive issues remain, stop — surface to user before proceeding.

Read `$_FOUNDRY_SHARED/quality-stack.md` (if file not found → skip quality stack entirely, note "foundry quality-stack not found at installed path — stack skipped" in Final Report) and execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

## Final Report

```markdown
## Fix Report: <bug summary>

### Root Cause
[1-2 sentence explanation of what was wrong and why]

### Regression Test
- File: <test_file>
- Test: <test_name>
- Confirms: [what behavior the test locks in]
- Disposition: keep if a test runner auto-discovers this file; otherwise add to Follow-up as a cleanup candidate

### Changes Made
| File | Change | Lines |
| --- | --- | --- |
| path/to/file.py | description of fix | -N/+M |

### Test Results
- Regression test: PASS
- Full suite: PASS (N tests)
- Lint: clean

### Follow-up
- [any related issues or code that should be reviewed]
- [if no test runner: `rm <test_file>` — no test suite will re-execute it; it served the gate, now expendable]

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**:
- [e.g., could not reproduce locally, partial traceback only, fix not runtime-tested]

**Refinements**: N passes.
```

## Team Assignments

<!-- Team branching logic is inline above at ## Team Mode Branch — executed immediately when TEAM_MODE=true, before Step 1. -->

**When to use**: root cause unclear after initial triage, OR bug spans 3+ modules AND user accepted "Proceed anyway" at scope gate. Set via `--team` flag.

See `## Team Mode Branch` above for spawn instructions, coordination protocol, and file-handoff pattern.

</workflow>
