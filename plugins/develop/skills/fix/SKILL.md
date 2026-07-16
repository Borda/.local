---
name: fix
description: "Reproduce-first bug resolution — capture bug in failing regression test, apply minimal fix, run quality stack and review loop. TRIGGER when: user reports a bug, regression, or unexpected behaviour in Python code with a traceback, failing test, or issue number; phrases: \"fix this bug\", \"repair X\", \"broken since Y\", \"test failing\". SKIP when: CI-only failures without local traceback (use `/develop:debug` first); new features (use `/develop:feature`); `.claude/` config issues (use `/foundry:audit`); non-Python projects."
argument-hint: '<symptom or issue # (plain 123 or #123)> [--repo <owner/repo>] [--plan <path>] [--diagnosis <path>] [--no-challenge] [--challenge] [--codemap] [--no-codemap] [--accept-no-plan] [--semble] [--team] [--keep "<items>"]'
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

<compaction>

Key boundary: end of Step 2 — reproduction test written and failing, before Step 3 code edits.
Second boundary: end of Step 3 — fix applied and regression test passing, before Step 4 review stack.
Preserve at boundary 1: dev-dir, regression test path, root cause summary, plan-file, --keep items.
Preserve at boundary 2: dev-dir, changed files list, test outcomes, regression test path.

</compaction>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at plugins/develop/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
# loads: compaction-contract.md
cat "$_DEV_SHARED/agent-resolution.md"
```

Contains: foundry check + fallback table. If foundry not installed: substitute each `foundry:X` with `general-purpose` per table. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist` (conditional — outcome C only), `foundry:challenger`.

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/task-hygiene.md"
```

## Project Detection

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/runner-detection.md"
```
Sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Language preflight gate**: after runner-detection.md, check project type:

```bash
# timeout: 5000
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ] && [ ! -f "setup.cfg" ]; then
    NON_PY=$(ls package.json Cargo.toml go.mod 2>/dev/null | head -1)
fi
```

If `NON_PY` non-empty: invoke `AskUserQuestion` — "Non-Python project detected (`$NON_PY` present, no pyproject.toml/setup.py). This toolchain assumes pytest. How to proceed?" · (a) **Abort** — use language-native toolchain · (b) **Continue** — I know what I'm doing (project has Python). On Abort: stop.

**Optional `--plan <path>`**: if `$ARGUMENTS` contains `--plan <path>` (at any position), read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to populate Step 1 analysis instead of cold codebase exploration. Skip agent feasibility re-check (already done in `/develop:plan`). Store plan path as `PLAN_FILE`.

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/preflight-helpers.md"
```
Execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: run `DEV_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_run_dir.py" 2>/dev/null)  # timeout: 5000` to create `.developments/<TS>/` and capture path. Write `checkpoint.md` inside `$DEV_DIR`. After each major step (1, 2, 3, 4), append `step: N — completed` to `$DEV_DIR/checkpoint.md`. On skill start, check for existing `.developments/*/checkpoint.md` — offer resume from last completed step if found.

```bash
# persist DEV_DIR for compaction recovery — bash state lost between Bash() calls  # timeout: 5000
echo "$DEV_DIR" > "${TMPDIR:-/tmp}/dev-fix-dev-dir"
```

## Fix Mode

**Optional `--diagnosis <path>`**: if provided (from preceding `/develop:debug` session), read diagnosis file first. Skip Step 1 codebase analysis — root cause, suspect files, and evidence pre-populated from diagnosis file. Challenger gate still applies: proceed from pre-populated root cause through challenger gate, then to Step 2. Do NOT skip challenger gate — it reviews fix approach, not just root cause discovery.

```bash
DIAG_FILE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/diagnosis_parse.py" "$ARGUMENTS" 2>&1) || { echo "$DIAG_FILE"; exit 1; }  # timeout: 5000
```

Diagnosis file format: see `/develop:debug` Final Report section for canonical field definitions (Root Cause, Suspect Files, Evidence).

## Flag parsing

Parse flags into actual shell variables (not prose) so downstream blocks see correct values. Persist to temp files for cross-block access (bash state lost between Bash() calls):

```bash
KEEP_ITEMS=""
if [[ "$ARGUMENTS" =~ --keep[[:space:]]\"([^\"]+)\" ]]; then
    KEEP_ITEMS="${BASH_REMATCH[1]}"
fi
echo "$KEEP_ITEMS" > "${TMPDIR:-/tmp}/dev-fix-keep-items"
rm -f .claude/state/skill-contract.md  # timeout: 5000
```

```bash
# timeout: 10000
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" \
    --skill fix --write-files "$ARGUMENTS"
```

Downstream blocks read back, e.g. `TEAM_MODE=$(cat ${TMPDIR:-/tmp}/dev-team-mode 2>/dev/null || echo false)`.

**Codemap resolve** — `CODEMAP_RAW` already written to `${TMPDIR:-/tmp}/dev-codemap-raw` by flag-parsing block above (via `dev_parse_args.py --skill fix --write-files`). Read it back, then normalize via `codemap-resolve`:

```bash
# timeout: 5000
CODEMAP_RAW=$(cat ${TMPDIR:-/tmp}/dev-codemap-raw 2>/dev/null || echo auto)
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_RAW" 2>&1)
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    echo "$CODEMAP_ENABLED" >&2  # surface error msg (e.g. strict-mode abort) to caller
    [ "$CODEMAP_RAW" = "strict" ] && exit 1
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED"   > ${TMPDIR:-/tmp}/dev-codemap-enabled
# codemap: integrated-via-shared
```

> loads: codemap-gates.md

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-gates.md"
```
Follow Gate A and Gate B.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--diagnosis\`, \`--no-challenge\`, \`--challenge\`, \`--codemap\`, \`--no-codemap\`, \`--accept-no-plan\`, \`--semble\`, \`--repo\`, \`--keep\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Preflight** — if `CODEMAP_ENABLED=true`:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/preflight-helpers.md"
```
Execute codemap + semble preflight if respective flags set.

<!-- Only active when --team flag passed (~10% of invocations) -->
## Team Mode Branch

**If `TEAM_MODE=true`**: execute team workflow now — do not proceed to Step 1.

Root cause unclear after initial triage, OR bug spans 3+ modules and user accepted "Proceed anyway" at scope gate: use this path.

**Coordination:**

1. Lead broadcasts current evidence: `{bug: <description>, traceback: <key lines>}`
2. Spawn **foundry:sw-engineer x 2 (model=opus)** — each investigates a distinct root-cause hypothesis (A, B) independently. `_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null); cat "$_DEV_SHARED/preflight-helpers.md"` §Team Spawn Template — replace `[ROLE_PHRASE]` with `[bug description]`, `[FILE_SLUG]` with `fix-hypothesis`. If user wants a third independent investigation, re-invoke with a narrower hypothesis spec rather than auto-scaling here.
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

**IMPORTANT**: before building each spawn prompt below, resolve all shell variables to literal values — embed resolved literals, not variable references, in prompt strings. `<TS_LITERAL>`, `<_DEV_SHARED_LITERAL>`, and `<ARGUMENTS_LITERAL>` in prompt text below are placeholders — substitute actual computed values before constructing Agent call; spawned agent cannot expand shell variables from its parent context:

```bash
# timeout: 5000
TS=$(cat ${TMPDIR:-/tmp}/dev-fix-team-ts 2>/dev/null || echo "")                                        # re-derive — bash state lost between Bash() calls
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null | head -1)
_SPAWN_DEV_SHARED="$_DEV_SHARED"
_SPAWN_TS="$TS"
_SPAWN_ARGS="$ARGUMENTS"
_SPAWN_RUN_DIR=$(cat ${TMPDIR:-/tmp}/dev-fix-run-dir 2>/dev/null || echo ".temp/develop/$TS")
```

**Teammate 1 — foundry:sw-engineer (model=opus) — hypothesis A**: substitute `$_SPAWN_DEV_SHARED`, `$_SPAWN_TS`, `$_SPAWN_ARGS`, and `$_SPAWN_RUN_DIR` with resolved literals before constructing prompt: "You are a foundry:sw-engineer teammate investigating a bug fix. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Read <_DEV_SHARED_LITERAL>/preflight-helpers.md §Team Spawn Template. Bug: <ARGUMENTS_LITERAL>. Evidence: {bug: <description>, traceback: <key lines>}. Your task: investigate hypothesis A — claim one distinct root-cause hypothesis, gather evidence, propose fix approach. Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. Signal completion: 'Status: complete | blocked — <reason>'. Write full analysis to <RUN_DIR_LITERAL>/fix-hypothesis-A-<TS_LITERAL>.md using Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}"

**Teammate 2 — foundry:sw-engineer (model=opus) — hypothesis B**: substitute `$_SPAWN_DEV_SHARED`, `$_SPAWN_TS`, `$_SPAWN_ARGS`, and `$_SPAWN_RUN_DIR` with resolved literals before constructing prompt: "You are a foundry:sw-engineer teammate investigating a bug fix. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Read <_DEV_SHARED_LITERAL>/preflight-helpers.md §Team Spawn Template. Bug: <ARGUMENTS_LITERAL>. Evidence: {bug: <description>, traceback: <key lines>}. Your task: investigate hypothesis B — claim a DIFFERENT root-cause hypothesis from your teammates, gather evidence, propose fix approach. Task tracking: do NOT call TaskCreate or TaskUpdate — lead owns all task state. Signal completion: 'Status: complete | blocked — <reason>'. Write full analysis to <RUN_DIR_LITERAL>/fix-hypothesis-B-<TS_LITERAL>.md using Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<path>\",\"hypothesis\":\"<one-line>\",\"confidence\":0.N}"

Health monitoring (CLAUDE.md §6): re-derive `$TS` and `$RUN_DIR` at block start (bash state lost between Bash() calls — read back from temp files spawn block persisted):

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

**Cross-repo adaptation** (when `REPO_NAME` set) — issue was filed against a different codebase. After fetching issue, analysis must:
1. Understand bug's root cause intent from issue body — not just symptoms or described fix (which may reference upstream structure)
2. Locate equivalent bug in LOCAL codebase — run Grep for relevant symbols/patterns; code paths may differ due to divergence
3. Treat upstream issue as context, not prescription — implement fix appropriate to local structure

If error message or pattern provided: use Grep tool (pattern `<error_pattern>`, path `.`) to search codebase for failing code path.

`<test_path>` is a **substitution token** — resolve failing test file/node (from `$ARGUMENTS` or fetched issue) into `TEST_PATH` before running; bash reads a literal `<...>` as stdin redirect. Redirect order is `>file 2>&1` (stdout to file, then stderr onto stdout) — reverse `2>&1 >file` loses stderr to terminal.

```bash
# timeout: 600000
$PYTEST_CMD --tb=long "$TEST_PATH" -v >"${TMPDIR:-/tmp}/pytest-out.txt" 2>&1; PYTEST_EXIT=$?; tail -40 "${TMPDIR:-/tmp}/pytest-out.txt"; [ $PYTEST_EXIT -ne 0 ] && echo "PYTEST FAILED (exit $PYTEST_EXIT)"
```

**Codemap target derivation** — set `TARGET_MODULE`/`TARGET_FN` before loading `codemap-context.md` so its caller-impact queries (`fn-rdeps`, `fn-blast`) fire instead of only `central` baseline. User may pass explicit suspect as `module.path::function`:

```bash
# timeout: 5000
if [[ "$ARGUMENTS" == *"::"* ]]; then
    _QNAME=$(printf '%s\n' "$ARGUMENTS" | grep -oE '[A-Za-z_][A-Za-z0-9_.]*::[A-Za-z_][A-Za-z0-9_]*' | head -1)
    TARGET_MODULE="${_QNAME%%::*}"
    TARGET_FN="${_QNAME##*::}"           # bare fn — codemap-context.md builds module::fn
else
    TARGET_MODULE=""
    TARGET_FN=""                         # suspect unknown until Step 1 — auto-derive below
fi
export TARGET_MODULE TARGET_FN
```

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-context.md"
```
Follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip entirely if both flags false.

Spawn **foundry:sw-engineer** agent to analyze failing code path and identify:

- Root cause — what wrong and why (not just symptom)
- Entry point to failure — which modules does call cross?
- State mutation — what state changed along way?
- Invariant violated — what condition broke at failure point?
- Minimal code surface needing change — exact files and functions
- Related code possibly affected by fix — blast radius
- Recent commits touching this path (from git log output, if provided)

**Direct-caller impact** — when `CODEMAP_ENABLED=true` and `TARGET_FN` was NOT supplied via `$ARGUMENTS`, derive suspect qualified name from sw-engineer Step 1 finding (module/function it named as minimal code surface), then run `fn-rdeps` for direct callers — benchmarked far cheaper than a plain caller walk (94k vs 1M+ tokens, +40pp accuracy). Shared `codemap-context.md` already ran when `TARGET_FN` was pre-set from args; this block covers the auto-derive case:

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

> Derived qualified name comes from whatever Step 1 recorded in `$DEV_DIR/checkpoint.md` (write suspect there as `module::function` when you append `step: 1 — completed`). No suspect in `module::function` form recorded → skip silently; `central` baseline already ran.

**Cannot-reproduce gate**: if sw-engineer unable to identify root cause, traceback, or any failing test, invoke `AskUserQuestion` — do NOT proceed to Step 2 with no reproduction path:
- question: "Cannot confirm root cause from available information. How to proceed?"
- (a) Use `/develop:debug` — investigate interactively first
- (b) Provide additional context — user pastes traceback, logs, or minimal reproduction; after user replies, re-run Step 1 analysis with new context in same session (DMI: cannot wait for next invocation; apply additional context inline)
- (c) Use `/foundry:investigate` (requires foundry plugin) — for production incidents with no CI trace
Stop until user provides option (b) context or selects a redirect.

If root cause not definitively established after analysis, surface assumptions before proceeding:

> ASSUMPTIONS I'M MAKING:
>
> 1. [assumption about root cause]
> 2. [assumption about affected scope] -> Correct me now or I'll proceed with these.

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/premise-grounding.md"
```
§Premise Grounding Gate. Apply using **fix** context from Skill contexts table.

**Scope gate**: if root cause spans 3+ modules, flag complexity smell. Use `AskUserQuestion` to present scope concern before proceeding, with options: "Narrow scope (Recommended)" / "Proceed anyway".

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/plan-inline.md"
```
§Inline Plan Generation Protocol. Apply using **fix** context from Skill contexts table. On proceed: set `PLAN_FILE=<path>`; continue to Step 2. On small complexity or `ACCEPT_NO_PLAN=true`: skip and continue to Step 2.

## Challenger gate

**Decision — three states** (default is NOT "skip": it runs on substantial fixes and auto-skips only small ones):

1. `--no-challenge` (`CHALLENGE_ENABLED=false`) → **skip gate entirely**, any size.
2. else `--challenge` (`CHALLENGE_FORCED=$(cat ${TMPDIR:-/tmp}/dev-challenge-forced 2>/dev/null || echo false)` = `true`) → **always run**, even on a small fix.
3. else **default** → **run when fix is substantial** (multi-file, ≳50 lines, or touches public API); **auto-skip when small** (single file, ≲50 lines, no API change) — challenger adds little on trivial fixes.

Both flags exist because they cover opposite regimes: `--no-challenge` suppresses gate on substantial fixes where it would otherwise fire; `--challenge` forces it on small fixes where it would otherwise auto-skip.

Spawn `foundry:challenger` with root cause analysis from Step 1 (root cause, blast radius, assumptions, approach):

> "Review root cause analysis and proposed fix approach. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Do not proceed to Step 2 until user resolves each blocker or explicitly accepts risk.
- **Concerns only** → surface as advisory; continue.
- **No findings / all refuted** → proceed.

## Step 2: Reproduce the bug

(Use Glob tool — `pattern: **/test_*.py` — to discover test directories if `<test_dir>` unknown; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` first)

### Part A — Test archaeology (before writing anything new)

1. Search for existing tests covering broken behavior:

   ```bash
   grep -r "<broken_symbol_or_error>" tests/ --include="*.py" -l
   grep -r "#<issue_number>" tests/ --include="*.py" -l
   ```

   Run any candidate tests found to see if they currently pass or fail:

   ```bash
   python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/pytest_gate.py" "$PYTEST_CMD" <candidate_test_file>::<candidate_test_name>  # timeout: 120000
   ```

2. For each candidate test found — critically assess coverage quality:
   - Does it exercise exact failing path (correct inputs, correct assertions)?
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

**When to skip Path 1**: if bug purely internal (no user-facing flow exists), document why and proceed with Path 2 only.

Both tests must **fail** against current code before proceeding. Check exit codes for each independently:

```bash
# timeout: 600000
$PYTEST_CMD --tb=short tests/integration/<test_file>::test_<bug>_user_flow -v
GATE_P1=$?
[ $GATE_P1 -eq 0 ] && echo "GATE FAIL (Path 1): test passed — bug not captured" || echo "GATE OK (Path 1): failed as expected (exit $GATE_P1)"

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

**Outcome B failure-mode verification**: scan traceback output above for expected error string from reported symptom. If traceback does NOT contain a recognizable match to reported bug symptom, surface: `⚠ Test fails but failure mode may differ from reported symptom — verify the test captures the actual bug before proceeding.`

### Review: Validate the reproduction

Before applying fix, critically evaluate reproduction test(s):

1. **Correct failure mode**: fails for right reason (actual bug), not setup issue?
2. **Isolation**: exercises exactly broken behavior, not too broadly?
3. **Minimal reproduction**: smallest test demonstrating failure?
4. **Parametrization**: key variants covered if bug spans multiple input patterns?
5. **Archaeology honesty**: if outcome B (weak test fixed), is test now harder to pass? Does it catch actual failure mode?

If issue found: revise test(s) before applying fix. Flawed reproduction = fix validated against wrong criteria.

```bash
# Compaction contract — boundary 1: after reproduction, before edit (compaction-contract.md §Lifecycle)
_DEV_DIR=$(cat "${TMPDIR:-/tmp}/dev-fix-dev-dir" 2>/dev/null || echo "")
_PLAN_FILE=$(cat "${TMPDIR:-/tmp}/dev-plan-file" 2>/dev/null || echo "")
_KEEP=$(cat "${TMPDIR:-/tmp}/dev-fix-keep-items" 2>/dev/null || echo "")
_PYTEST_CMD=$(cat "${TMPDIR:-/tmp}/dev-pytest-cmd" 2>/dev/null || echo "")
_PRESERVE="dev-dir=$_DEV_DIR, plan-file=${_PLAN_FILE:-none}, pytest-cmd=$_PYTEST_CMD"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: develop:fix · phase: edit (after reproduction test written)"
    echo "- run-dir: $_DEV_DIR"
    echo "- preserve: $_PRESERVE"
    echo "- next: apply minimal fix (Step 3) → review+quality stack (Step 4)"
} > .claude/state/skill-contract.md
```

## Step 3: Apply the fix

**Breaking change gate**: before applying fix, assess whether fix introduces a breaking change.

```bash
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED=$(ls -d plugins/oss/skills/_shared 2>/dev/null | head -1)
[ -n "$_OSS_SHARED" ] && cat "$_OSS_SHARED/semver-rules.md" || echo "oss plugin absent — semver-rules.md unavailable, use standard SemVer rules"
```

If `oss` plugin available (i.e., `$_OSS_SHARED` non-empty), use `semver-rules.md` above for semver classification guidance; otherwise use standard SemVer rules (BREAKING = major bump, new feature = minor, fix = patch). Breaking change definition: worked before → fails/behaves differently now → no prior warning/shim. If yes — stop, call `AskUserQuestion` before any edit. State: what worked before, what will break, why this fix approach needed. Proceed only on explicit user confirmation. One question per breaking change; group only when logically one atomic change. Prose question does NOT count — `AskUserQuestion` mandatory.

Make minimal change to fix root cause:

1. Edit only code necessary to resolve bug
2. Run regression test to confirm now passes:
   ```bash
   # timeout: 600000
   $PYTEST_CMD --tb=short <test_file>::<test_name> -v
   ```
3. Run affected tests (prefer targeted over full suite):

   **Test impact (codemap)** — derive minimal test set before running anything.

   **Reuse from diagnosis handoff first** — when invoked with `--diagnosis`, `/develop:debug` may have already run this query and written it into diagnosis file under `## Test Impact (codemap)`. Reuse it (one query total across debug→fix) only when still fresh — not `stale` and not older than current index:

   ```bash
   # timeout: 6000
   DIAG_FILE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/diagnosis_parse.py" "$ARGUMENTS" 2>/dev/null)  # re-derive — bash state lost between Bash() calls
   REUSED_PYTEST_CMD=""
   if [ -n "$DIAG_FILE" ] && grep -q '^## Test Impact (codemap)' "$DIAG_FILE" 2>/dev/null; then
       # extract the fenced JSON block that follows the marker heading
       _TI_JSON=$(awk '/^## Test Impact \(codemap\)/{f=1} f&&/^```json/{g=1;next} f&&/^```/{g=0} g' "$DIAG_FILE")
       _HANDOFF_AT=$(grep -m1 'index_scanned_at:' "$DIAG_FILE" | sed 's/.*index_scanned_at:[[:space:]]*//')
       PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null || basename "$PWD")
       _LIVE_AT=$(grep -o '"scanned_at"[[:space:]]*:[[:space:]]*"[^"]*"' "${CODEMAP_INDEX_DIR:-.cache/codemap}/${PROJ}.json" 2>/dev/null | head -1 | sed 's/.*"\([^"]*\)"$/\1/')
       case "$_TI_JSON" in *'"stale": true'*|*'"stale":true'*) _TI_STALE=1;; *) _TI_STALE=0;; esac
       if [ "$_TI_STALE" -eq 0 ] && [ -n "$_HANDOFF_AT" ] && [ "$_HANDOFF_AT" = "$_LIVE_AT" ]; then
           REUSED_PYTEST_CMD=$(printf '%s' "$_TI_JSON" | grep -o '"pytest_cmd"[[:space:]]*:[[:space:]]*"[^"]*"' | sed 's/.*"\([^"]*\)"$/\1/')
           echo "→ reusing test-impact from diagnosis handoff (index unchanged): $REUSED_PYTEST_CMD"
       else
           echo "→ diagnosis test-impact stale or index moved — re-querying live"
       fi
   fi
   ```

   **Live query** — run only when no fresh handoff result was reused (`REUSED_PYTEST_CMD` empty):
   ```bash
   scan-query test-impact "<changed_module::function or bare module>" 2>/dev/null
   ```
   - Reused `REUSED_PYTEST_CMD` non-empty, OR live result non-empty `pytest_cmd` → use it instead of full `<test_dir>` run; surface `not_covered` caveat if present
   - Result empty or `scan-query` absent → fall back to full directory below

   **Full suite fallback** (only when impact query returns empty or unavailable):
   ```bash
   # timeout: 600000
   $PYTEST_CMD --tb=short <test_dir> -v
   ```
   **If `<test_dir>` does not exist or has no tests beyond regression test**: run only regression test (already verified in Step 2). Note in Final Report: "No pre-existing test suite found — regression test is sole verification."

4. If existing tests break: fix has side effects — reconsider approach

```bash
# Compaction contract — boundary 2: after fix applied, before review stack (compaction-contract.md §Lifecycle)
_DEV_DIR=$(cat "${TMPDIR:-/tmp}/dev-fix-dev-dir" 2>/dev/null || echo "")
_PYTEST_CMD=$(cat "${TMPDIR:-/tmp}/dev-pytest-cmd" 2>/dev/null || echo "")
_CHANGED=$(git diff --name-only HEAD 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: develop:fix · phase: review+quality (after fix applied)"
    echo "- run-dir: $_DEV_DIR"
    echo "- preserve: dev-dir=$_DEV_DIR, changed-files=$_CHANGED, pytest-cmd=$_PYTEST_CMD"
    echo "- next: review and close gaps (Step 4) → Final Report"
} > .claude/state/skill-contract.md
```

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

```bash
_FOUNDRY_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null | tail -1)
[ -f "$_FOUNDRY_SHARED/quality-stack.md" ] && cat "$_FOUNDRY_SHARED/quality-stack.md" || echo "foundry quality-stack not found at installed path — stack skipped"
```
If file not found → skip quality stack entirely, note "foundry quality-stack not found at installed path — stack skipped" in Final Report. Otherwise execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

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

```bash
rm -f .claude/state/skill-contract.md  # clear contract — skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
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
