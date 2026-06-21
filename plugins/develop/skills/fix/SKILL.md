---
name: fix
description: "Reproduce-first bug resolution — capture bug in failing regression test, apply minimal fix, run quality stack and review loop."
argument-hint: '<symptom or issue # (plain 123 or #123)> [--repo <owner/repo>] [--plan <path>] [--diagnosis <path>] [--no-challenge] [--codemap] [--no-codemap] [--accept-no-plan] [--semble] [--team]'
when_to_use: |
  TRIGGER when: user reports a bug, regression, or unexpected behaviour in Python code with a traceback, failing test, or issue number; phrases: "fix this bug", "repair X", "broken since Y", "test failing".
  SKIP: CI-only failures without local traceback (use `/develop:debug` first); new features (use `/develop:feature`); `.claude/` config issues (use `/foundry:audit`); non-Python projects.
effort: medium
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Reproduce-first bug resolution. Capture bug in failing regression test, apply minimal fix, verify via quality stack and review loop.

NOT for:
- CI-only failures with no local traceback — use `/develop:debug` first (`--ci-run <run-id>` for GitHub Actions logs)
- production incidents without any CI run or traceback (use `/foundry:investigate` (requires foundry plugin))
- `.claude/` config issues (use `/foundry:audit` (requires foundry plugin))
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead
- CSS/JS-only frontend changes (no Python source touched) — use `/develop:feature` for new frontend work or direct editing for surgical CSS/JS fixes; this skill's regression-test gate assumes pytest

</objective>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at plugins/develop/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist` (conditional — outcome C only), `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Language preflight gate**: after runner-detection.md, check project type:

```bash
# timeout: 5000
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ] && [ ! -f "setup.cfg" ]; then
    NON_PY=$(ls package.json Cargo.toml go.mod 2>/dev/null | head -1)
fi
```

If `NON_PY` is non-empty: invoke `AskUserQuestion` — "Non-Python project detected (`$NON_PY` present, no pyproject.toml/setup.py). This toolchain assumes pytest. How to proceed?" · (a) **Abort** — use language-native toolchain · (b) **Continue** — I know what I'm doing (project has Python). On Abort: stop.

**Optional `--plan <path>`**: if `$ARGUMENTS` contains `--plan <path>` (at any position), read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to populate Step 1 analysis instead of cold codebase exploration. Skip agent feasibility re-check (already done in `/develop:plan`). Store plan path as `PLAN_FILE`.

Read `$_DEV_SHARED/preflight-helpers.md` — execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: run `DEV_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_run_dir.py" 2>/dev/null)  # timeout: 5000` to create `.developments/<TS>/` and capture path. Write `checkpoint.md` inside `$DEV_DIR`. After each major step (1, 2, 3, 4), append `step: N — completed` to `$DEV_DIR/checkpoint.md`. On skill start, check for existing `.developments/*/checkpoint.md` — offer resume from last completed step if found.

## Fix Mode

**Optional `--diagnosis <path>`**: if provided (from preceding `/develop:debug` session), read diagnosis file first. Skip Step 1 codebase analysis — root cause, suspect files, and evidence pre-populated from diagnosis file. The Challenger gate still applies: proceed from pre-populated root cause through challenger gate, then to Step 2. Do NOT skip the challenger gate — it reviews the fix approach, not just root cause discovery.

```bash
DIAG_FILE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/diagnosis_parse.py" "$ARGUMENTS" 2>&1) || { echo "$DIAG_FILE"; exit 1; }  # timeout: 5000
```

Diagnosis file format: see `/develop:debug` Final Report section for canonical field definitions (Root Cause, Suspect Files, Evidence).

## Flag parsing

Parse flags into actual shell variables (not prose) so downstream blocks see correct values. Persist to temp files for cross-block access (bash state lost between Bash() calls):

```bash
# timeout: 10000
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" \
    --skill fix --write-files "$ARGUMENTS"
```

Downstream blocks read back, e.g. `TEAM_MODE=$(cat ${TMPDIR:-/tmp}/dev-team-mode 2>/dev/null || echo false)`.

**Codemap resolve** — `CODEMAP_RAW` is already written to `${TMPDIR:-/tmp}/dev-codemap-raw` by the flag-parsing block above (via `dev_parse_args.py --skill fix --write-files`). Read it back, then normalize via `codemap-resolve`:

```bash
# timeout: 5000
CODEMAP_RAW=$(cat ${TMPDIR:-/tmp}/dev-codemap-raw 2>/dev/null || echo auto)
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_RAW" 2>&1)
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    echo "$CODEMAP_ENABLED" >&2  # surface stderr (e.g. strict-mode abort message) to caller
    [ "$CODEMAP_RAW" = "strict" ] && exit 1
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED"   > ${TMPDIR:-/tmp}/dev-codemap-enabled
# codemap: integrated-via-shared
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--diagnosis\`, \`--no-challenge\`, \`--codemap\`, \`--no-codemap\`, \`--accept-no-plan\`, \`--semble\`, \`--repo\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Preflight** — if `CODEMAP_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute codemap + semble preflight if respective flags set.

<!-- Only active when --team flag passed (~10% of invocations) -->
## Team Mode Branch

**If `TEAM_MODE=true`**: execute team workflow now — do not proceed to Step 1.

Root cause unclear after initial triage, OR bug spans 3+ modules and user accepted "Proceed anyway" at scope gate: use this path.

**Coordination:**

1. Lead broadcasts current evidence: `{bug: <description>, traceback: <key lines>}`
2. Spawn **foundry:sw-engineer x 2 (model=opus)** — each investigates a distinct root-cause hypothesis (A, B) independently. Read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template — replace `[ROLE_PHRASE]` with `[bug description]`, `[FILE_SLUG]` with `fix-hypothesis`. If user wants a third independent investigation, re-invoke with a narrower hypothesis spec rather than auto-scaling here.
3. Each teammate investigates independently — claims hypothesis; returns full output to file (file-based handoff protocol).
4. Lead facilitates cross-challenge between competing analyses.
5. Lead synthesizes consensus root cause, then proceeds with Steps 2-4 (regression test, fix, review loop) alone.

Compute run directory and create health sentinel:

```bash
# timeout: 5000
_run_out=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/setup_worktree.py" --sentinel fix-team-check)
TS=$(echo "$_run_out" | head -1)
RUN_DIR=$(echo "$_run_out" | tail -1)
FIX_TEAM_DIR="$RUN_DIR"
RUN_DIR_LITERAL="$RUN_DIR"
echo "$TS" > ${TMPDIR:-/tmp}/dev-fix-team-ts
echo "$RUN_DIR" > ${TMPDIR:-/tmp}/dev-fix-run-dir
trap 'rm -f ${TMPDIR:-/tmp}/fix-team-check-$TS' EXIT
```

Spawn 2 teammates in parallel using Agent() tool:

**IMPORTANT**: before building each spawn prompt below, resolve all shell variables to literal values — embed resolved literals, not variable references, in the prompt strings. `<TS_LITERAL>`, `<_DEV_SHARED_LITERAL>`, and `<ARGUMENTS_LITERAL>` in the prompt text below are placeholders — substitute the actual computed values before constructing the Agent call; the spawned agent cannot expand shell variables from its parent context:

```bash
# timeout: 5000
_SPAWN_DEV_SHARED="$_DEV_SHARED"
_SPAWN_TS="$TS"
_SPAWN_ARGS="$ARGUMENTS"
_SPAWN_RUN_DIR=$(cat ${TMPDIR:-/tmp}/dev-fix-run-dir 2>/dev/null || echo ".temp/develop/$TS")
```

**Teammate 1 — foundry:sw-engineer (model=opus) — hypothesis A**: substitute `$_SPAWN_DEV_SHARED`, `$_SPAWN_TS`, `$_SPAWN_ARGS`, and `$_SPAWN_RUN_DIR` with resolved literals before constructing prompt: "You are a foundry:sw-engineer teammate investigating a bug fix. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Read <_DEV_SHARED_LITERAL>/preflight-helpers.md §Team Spawn Template. Bug: <ARGUMENTS_LITERAL>. Evidence: {bug: <description>, traceback: <key lines>}. Your task: investigate hypothesis A — claim one distinct root-cause hypothesis, gather evidence, propose fix approach. Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. Signal completion: 'Status: complete | blocked — <reason>'. Write full analysis to <RUN_DIR_LITERAL>/fix-hypothesis-A-<TS_LITERAL>.md using Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}"

**Teammate 2 — foundry:sw-engineer (model=opus) — hypothesis B**: substitute `$_SPAWN_DEV_SHARED`, `$_SPAWN_TS`, `$_SPAWN_ARGS`, and `$_SPAWN_RUN_DIR` with resolved literals before constructing prompt: "You are a foundry:sw-engineer teammate investigating a bug fix. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Read <_DEV_SHARED_LITERAL>/preflight-helpers.md §Team Spawn Template. Bug: <ARGUMENTS_LITERAL>. Evidence: {bug: <description>, traceback: <key lines>}. Your task: investigate hypothesis B — claim a DIFFERENT root-cause hypothesis from your teammates, gather evidence, propose fix approach. Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. Signal completion: 'Status: complete | blocked — <reason>'. Write full analysis to <RUN_DIR_LITERAL>/fix-hypothesis-B-<TS_LITERAL>.md using Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}"

Health monitoring (CLAUDE.md §6): re-derive `$TS` and `$RUN_DIR` at block start (bash state lost between Bash() calls — read back from temp files the spawn block persisted):

```bash
# timeout: 5000
TS=$(cat ${TMPDIR:-/tmp}/dev-fix-team-ts 2>/dev/null || date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=$(cat ${TMPDIR:-/tmp}/dev-fix-run-dir 2>/dev/null || echo ".temp/develop/$TS")
```

Every 5 min: `find $RUN_DIR -newer ${TMPDIR:-/tmp}/fix-team-check-$TS -name "fix-hypothesis-*.md" | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min no file activity → timed out. One extension (+5 min) if `tail -20` of output file explains delay; second unexplained stall = hard cutoff. On timeout: read `tail -100` of each `$RUN_DIR/fix-hypothesis-*.md`; surface with ⏱; never omit.

After both teammates complete: read their output files from `$RUN_DIR/`, synthesize consensus root cause, facilitate cross-challenge between competing analyses. Lead then proceeds alone with Steps 2-4 (regression test, fix, review loop).

## Step 1: Understand the problem

Gather all available context about bug:

> **Argument type detection**: if `$ARGUMENTS` is positive integer (or prefixed with `#`, e.g. `#123`), treat as GitHub issue number and fetch with `gh issue view`. If text (contains spaces, letters, or special chars), treat as symptom description.

```bash
# timeout: 6000
REPO_NAME=$(cat ${TMPDIR:-/tmp}/dev-upstream 2>/dev/null || echo "")
if [ -n "$REPO_NAME" ]; then
    python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/issue_fetch.py" "$ARGUMENTS" --repo "$REPO_NAME" 2>/dev/null
else
    python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/issue_fetch.py" "$ARGUMENTS" 2>/dev/null
fi
```

**Cross-repo adaptation** (when `REPO_NAME` set) — issue was filed against a different codebase. After fetching issue, the analysis must:
1. Understand the bug's root cause intent from the issue body — not just the symptoms or described fix (which may reference upstream structure)
2. Locate the equivalent bug in LOCAL codebase — run Grep for relevant symbols/patterns; the code paths may differ due to divergence
3. Treat the upstream issue as context, not as a prescription — implement the fix appropriate to local structure

If error message or pattern provided: use Grep tool (pattern `<error_pattern>`, path `.`) to search codebase for failing code path.

```bash
# timeout: 600000
$PYTEST_CMD --tb=long <test_path> -v 2>&1 >"${TMPDIR:-/tmp}/pytest-out.txt"; PYTEST_EXIT=$?; tail -40 "${TMPDIR:-/tmp}/pytest-out.txt"; [ $PYTEST_EXIT -ne 0 ] && echo "PYTEST FAILED (exit $PYTEST_EXIT)"
```

**Codemap target derivation** — set `TARGET_MODULE`/`TARGET_FN` before loading `codemap-context.md` so its caller-impact queries (`fn-rdeps`, `fn-blast`) fire instead of only the `central` baseline. The user may pass an explicit suspect as `module.path::function`:

```bash
# timeout: 5000
if [[ "$ARGUMENTS" == *"::"* ]]; then
    _QNAME=$(printf '%s\n' "$ARGUMENTS" | grep -oE '[A-Za-z_][A-Za-z0-9_.]*::[A-Za-z_][A-Za-z0-9_]*' | head -1)
    TARGET_MODULE="${_QNAME%%::*}"
    TARGET_FN="${_QNAME##*::}"           # bare function name — codemap-context.md builds module::fn itself
else
    TARGET_MODULE=""
    TARGET_FN=""                         # suspect unknown until Step 1 — auto-derive below
fi
export TARGET_MODULE TARGET_FN
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

**Direct-caller impact** — when `CODEMAP_ENABLED=true` and `TARGET_FN` was NOT supplied via `$ARGUMENTS`, derive the suspect qualified name from the sw-engineer Step 1 finding (the module/function it named as the minimal code surface), then run `fn-rdeps` for direct callers benchmarked far cheaper than a plain caller walk (94k vs 1M+ tokens, +40pp accuracy). The shared `codemap-context.md` already ran when `TARGET_FN` was pre-set from args; this block covers the auto-derive case:

```bash
# timeout: 6000
CODEMAP_ENABLED=$(cat ${TMPDIR:-/tmp}/dev-codemap-enabled 2>/dev/null || echo false)
if [ "$CODEMAP_ENABLED" = "true" ] && [ -z "$TARGET_FN" ] && command -v scan-query >/dev/null 2>&1; then
    DERIVED_FN=$(grep -oE '[A-Za-z_][A-Za-z0-9_.]*::[A-Za-z_][A-Za-z0-9_]*' "$DEV_DIR/checkpoint.md" 2>/dev/null | head -1)
    if [ -n "$DERIVED_FN" ]; then
        TARGET_FN="$DERIVED_FN"
        TARGET_MODULE="${DERIVED_FN%%::*}"
        export TARGET_FN TARGET_MODULE
        scan-query --timeout 5 fn-rdeps "$TARGET_FN" --exclude-tests 2>/dev/null \
            | tee "$DEV_DIR/fn-rdeps-output.txt" || true
    fi
fi
```

> The derived qualified name comes from whatever Step 1 recorded in `$DEV_DIR/checkpoint.md` (write the suspect there as `module::function` when you append `step: 1 — completed`). No suspect in `module::function` form recorded → skip silently; the `central` baseline already ran.

**Cannot-reproduce gate**: if sw-engineer was unable to identify root cause, traceback, or any failing test, invoke `AskUserQuestion` — do NOT proceed to Step 2 with no reproduction path:
- question: "Cannot confirm root cause from available information. How to proceed?"
- (a) Use `/develop:debug` — investigate interactively first
- (b) Provide additional context — user pastes traceback, logs, or minimal reproduction; after user replies, re-run Step 1 analysis with the new context in the same session (DMI: cannot wait for next invocation; apply additional context inline)
- (c) Use `/foundry:investigate` (requires foundry plugin) — for production incidents with no CI trace
Stop until user provides option (b) context or selects a redirect.

If root cause not definitively established after analysis, surface assumptions before proceeding:

> ASSUMPTIONS I'M MAKING:
>
> 1. [assumption about root cause]
> 2. [assumption about affected scope] -> Correct me now or I'll proceed with these.

Read `$_DEV_SHARED/premise-grounding.md` §Premise Grounding Gate. Apply using **fix** context from the Skill contexts table.

**Scope gate**: if root cause spans 3+ modules, flag complexity smell. Use `AskUserQuestion` to present scope concern before proceeding, with options: "Narrow scope (Recommended)" / "Proceed anyway".

Read `$_DEV_SHARED/plan-inline.md` §Inline Plan Generation Protocol. Apply using **fix** context from the Skill contexts table. On proceed: set `PLAN_FILE=<path>`; continue to Step 2. On small complexity or `ACCEPT_NO_PLAN=true`: skip and continue to Step 2.

## Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

Spawn `foundry:challenger` with root cause analysis from Step 1 (root cause, blast radius, assumptions, approach):

> "Review root cause analysis and proposed fix approach. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Do not proceed to Step 2 until user resolves each blocker or explicitly accepts risk.
- **Concerns only** → surface as advisory; continue.
- **No findings / all refuted** → proceed.

## Step 2: Reproduce the bug

(Use Glob tool — `pattern: **/test_*.py` — to discover test directories if `<test_dir>` unknown; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` first)

### Part A — Test archaeology (before writing anything new)

1. Search for existing tests covering the broken behavior:

   ```bash
   # Grep for broken function/class name, error string, or issue number across tests/
   grep -r "<broken_symbol_or_error>" tests/ --include="*.py" -l
   grep -r "#<issue_number>" tests/ --include="*.py" -l
   ```

   Run any candidate tests found to see if they currently pass or fail:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/pytest_gate.py" "$PYTEST_CMD" <candidate_test_file>::<candidate_test_name>  # timeout: 120000
   ```

2. For each candidate test found — critically assess coverage quality:
   - Does it exercise the exact failing path (correct inputs, correct assertions)?
   - Or is it a weak test — broad mocking, trivially happy-path, partial assertion — that deflected the problem rather than caught it?

3. Three outcomes from archaeology:
   - **A: Existing test fails already** → captures bug; use as-is; proceed to Step 3
   - **B: Existing test passes but is weak** (deflected problem) → fix existing test to properly reproduce; do NOT write new test; gate: test must fail after fix
   - **C: No relevant test found** → write new test (proceed to Part B)

Surface archaeology verdict before any writing:

> Found: `[test path or "none"]` — verdict: `[captures / weak-deflected / no test]`

### Part B — Write new reproduction test (only when outcome C)

Spawn **foundry:qa-specialist** agent (outcome C only — no existing tests found) to write two reproduction tests:

Spawn with context:
- Bug description: [symptom from $ARGUMENTS or issue]
- Failing output: [exact error/traceback captured in Step 1]
- Suspect files: [files identified by sw-engineer in Step 1]
- Expected behaviour: [what should happen]
- Actual behaviour: [what currently happens]

**Path 1 — Full user flow (integration demo)**
- Exercises complete user-reported scenario end-to-end
- No mocking of broken subsystem — real execution
- Confirms user-reported problem fully resolved
- Name: `test_<bug>_user_flow` or `test_<bug>_integration`
- Lives in `tests/integration/` or alongside existing integration tests

**Path 2 — Targeted unit test (fast iteration)**
- Minimal scope: isolates root cause directly
- Mock external dependencies; only broken unit under test is real
- Designed for quick re-run during fix iteration (sub-second)
- Name: `test_<bug>_unit` or `test_<bug>_regression`
- Lives next to broken module's existing unit tests
- Use `pytest.mark.parametrize` if bug affects multiple input patterns
- Add brief comment linking to issue if applicable (e.g., `# Regression test for #123`)

**When to skip Path 1**: if bug is purely internal (no user-facing flow exists), document why and proceed with Path 2 only.

Both tests must **fail** against current code before proceeding. Check exit codes for each independently:

```bash
# timeout: 600000
# Path 1 gate
$PYTEST_CMD --tb=short tests/integration/<test_file>::test_<bug>_user_flow -v
GATE_P1=$?
[ $GATE_P1 -eq 0 ] && echo "GATE FAIL (Path 1): test passed — bug not captured" || echo "GATE OK (Path 1): failed as expected (exit $GATE_P1)"

# Path 2 gate
$PYTEST_CMD --tb=short <unit_test_file>::test_<bug>_unit -v
GATE_P2=$?
[ $GATE_P2 -eq 0 ] && echo "GATE FAIL (Path 2): test passed — bug not captured" || echo "GATE OK (Path 2): failed as expected (exit $GATE_P2)"
```

If either gate exit is 0: stop. Bug not reproduced on that path. Do not apply fix. DMI skill — stop enforced via bash gate check:

```bash
# timeout: 3000
if [ "${GATE_P1:-0}" -eq 0 ] || [ "${GATE_P2:-0}" -eq 0 ]; then
    echo "! GATE FAIL: one or more reproduction tests passed — bug not captured; cannot apply fix against unverified bug"
    exit 1
fi
```

**Outcome B gate** (weak test fixed path): after fixing existing test, run it to confirm it now fails:

```bash
$PYTEST_CMD --tb=long <existing_test_file>::<existing_test_name> -v 2>&1 | tail -30; GATE_EXIT=${PIPESTATUS[0]}  # timeout: 30000
[ $GATE_EXIT -eq 0 ] && echo "GATE FAIL: fixed test still passes — weak test not corrected; revisit" || echo "GATE OK: fixed test fails as expected (exit $GATE_EXIT)"
```

**Outcome B failure-mode verification**: scan the traceback output above for the expected error string from the reported symptom. If traceback does NOT contain a recognizable match to the reported bug symptom, surface: `⚠ Test fails but failure mode may differ from reported symptom — verify the test captures the actual bug before proceeding.`

### Review: Validate the reproduction

Before applying fix, critically evaluate reproduction test(s):

1. **Correct failure mode**: fails for right reason (actual bug), not setup issue?
2. **Isolation**: exercises exactly broken behavior, not too broadly?
3. **Minimal reproduction**: smallest test demonstrating failure?
4. **Parametrization**: key variants covered if bug spans multiple input patterns?
5. **Archaeology honesty**: if outcome B (weak test fixed), is test now harder to pass? Does it catch actual failure mode?

If issue found: revise test(s) before applying fix. Flawed reproduction = fix validated against wrong criteria.

## Step 3: Apply the fix

**Breaking change gate**: before applying fix, assess whether fix introduces a breaking change.

```bash
# Resolve oss plugin shared dir (undefined if oss plugin absent)
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED=$(ls -d plugins/oss/skills/_shared 2>/dev/null | head -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED=""  # oss plugin absent — semver-rules.md unavailable
```

If `oss` plugin available (i.e., `$_OSS_SHARED` non-empty), read `$_OSS_SHARED/semver-rules.md` for semver classification guidance; otherwise use standard SemVer rules (BREAKING = major bump, new feature = minor, fix = patch). Breaking change definition: worked before → fails/behaves differently now → no prior warning/shim. If yes — stop, call `AskUserQuestion` before any edit. State: what worked before, what will break, why this fix approach needed. Proceed only on explicit user confirmation. One question per breaking change; group only when logically one atomic change. Prose question does NOT count — `AskUserQuestion` mandatory.

Make minimal change to fix root cause:

1. Edit only code necessary to resolve bug
2. Run regression test to confirm now passes:
   ```bash
   # timeout: 600000
   $PYTEST_CMD --tb=short <test_file>::<test_name> -v
   ```
3. Run affected tests (prefer targeted over full suite):

   **Test impact (codemap)** — derive the minimal test set before running anything:
   ```bash
   scan-query test-impact "<changed_module::function or bare module>" 2>/dev/null
   ```
   - Result non-empty `pytest_cmd` → use it instead of full `<test_dir>` run; surface `not_covered` caveat if present
   - Result empty or `scan-query` absent → fall back to full directory below

   **Full suite fallback** (only when impact query returns empty or is unavailable):
   ```bash
   # timeout: 600000
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
   python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/run_pytest_short.py" "$PYTEST_CMD" <test_dir>; PYTEST_EXIT=$?; [ $PYTEST_EXIT -ne 0 ] && echo "PYTEST FAILED (exit $PYTEST_EXIT)"  # timeout: 600000
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
- [if no test runner: `rm <test_file>` — no test suite will re-execute it; it served the gate, now expendable. **Exception**: if test was introduced in this session and is definitively wrong, delete it. Never delete pre-existing regression tests — they represent captured behavior that predates this session.]

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [e.g., could not reproduce locally, partial traceback only, fix not runtime-tested]

**Refinements**: N passes.
```

<!-- Team branching logic is inline above at ## Team Mode Branch — executed immediately when TEAM_MODE=true, before Step 1. When to use: root cause unclear after initial triage, OR bug spans 3+ modules AND user accepted "Proceed anyway" at scope gate. Set via --team flag. -->

</workflow>

<notes>

<!-- Reference only — execution-dead at runtime; included for agent behavioral context -->

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "I already know root cause from symptom" | Assumptions without verification fix wrong bug. Read code path first. |
| "Regression test can wait — add after fix" | Fix without failing test = unverifiable. Test proves bug existed. |
| "Clean up nearby code while here" | Scope creep produces side effects, obscures fix. Touch only root cause. |
| "Targeted test passes — sufficient" | Targeted test shows bug fixed; full suite shows nothing else broke. Both required. |
| "Fix obvious — Step 1 analysis overkill" | Obvious causes often symptoms. Analysis reveals actual root cause and blast radius. |

</notes>
