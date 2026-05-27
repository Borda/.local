---
name: feature
description: "TDD-first feature development — crystallise API as a demo test, drive implementation to pass it, run quality stack and progressive review loop."
argument-hint: "<goal> [--plan <path>] [--no-challenge] [--no-codemap] [--codemap] [--semble] [--team] [--accept-no-plan]"
effort: high
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion, WebFetch
disable-model-invocation: true
---

<objective>

TDD-first feature development. Crystallise API as demo use-case test, drive implementation to pass it, close quality gaps with review, docs, quality stack.

NOT for:
- bug fixes (use `/develop:fix`)
- `.claude/` config changes (use `/foundry:manage` (requires foundry plugin))
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature

</objective>

<workflow>

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (mounted by develop plugin init) -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:doc-scribe`, `foundry:linting-expert`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Language preflight gate**: after runner-detection.md, check project type:

```bash
# Abort early on non-Python repos — toolchain assumes pytest  # timeout: 5000
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ] && [ ! -f "setup.cfg" ]; then
    NON_PY=$(ls package.json Cargo.toml go.mod 2>/dev/null | head -1)
fi
```

If `NON_PY` is non-empty: invoke `AskUserQuestion` — "Non-Python project detected (`$NON_PY` present, no pyproject.toml/setup.py). This toolchain assumes pytest. How to proceed?" · (a) **Abort** — use language-native toolchain · (b) **Continue** — I know what I'm doing (project has Python). On Abort: stop.

**Optional `--plan <path>`**: if `$ARGUMENTS` contains `--plan <path>` (at any position), read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to populate Step 1 analysis instead of cold codebase exploration. Skip agent feasibility re-check (already done in `/develop:plan`). Store plan path as `PLAN_FILE`.

Read `$_DEV_SHARED/preflight-helpers.md` — execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: run `DEV_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_run_dir.py" 2>/dev/null)  # timeout: 5000` to create `.developments/<TS>/` and capture path. Write `checkpoint.md` inside `$DEV_DIR`. After each major step (1, 2, 3, 4, 5), append `step: N — completed` to `$DEV_DIR/checkpoint.md`. On skill start, check for existing `.developments/*/checkpoint.md` — if found, offer to resume from last completed step.

## Flag parsing

Parse flags into actual shell variables (not prose) so downstream blocks see correct values. Persist to temp files for cross-block access (bash state lost between Bash() calls):

```bash
# timeout: 5000
CHALLENGE_ENABLED=true
CODEMAP_ENABLED=auto
SEMBLE_ENABLED=false
TEAM_MODE=false
ACCEPT_NO_PLAN=false
[[ " $ARGUMENTS " == *" --no-challenge "* ]] && CHALLENGE_ENABLED=false
[[ " $ARGUMENTS " == *" --no-codemap "* ]] && CODEMAP_ENABLED=off
[[ " $ARGUMENTS " == *" --codemap "* ]] && CODEMAP_ENABLED=strict
[[ " $ARGUMENTS " == *" --semble "* ]] && SEMBLE_ENABLED=true
[[ " $ARGUMENTS " == *" --team "* ]] && TEAM_MODE=true
[[ " $ARGUMENTS " == *" --accept-no-plan "* ]] && ACCEPT_NO_PLAN=true
echo "$CHALLENGE_ENABLED" > ${TMPDIR:-/tmp}/dev-challenge-enabled
echo "$CODEMAP_ENABLED"   > ${TMPDIR:-/tmp}/dev-codemap-enabled
echo "$SEMBLE_ENABLED"    > ${TMPDIR:-/tmp}/dev-semble-enabled
echo "$TEAM_MODE"         > ${TMPDIR:-/tmp}/dev-team-mode
echo "$ACCEPT_NO_PLAN"    > ${TMPDIR:-/tmp}/dev-accept-no-plan
```

Downstream blocks read back, e.g. `TEAM_MODE=$(cat ${TMPDIR:-/tmp}/dev-team-mode 2>/dev/null || echo false)`.

```bash
# Parse --issue flag for issue-linked feature scaffolding  # timeout: 6000
ISSUE_REF=$(echo "$ARGUMENTS" | grep -oP '(?<=--issue )[^ ]+' || echo "")
echo "$ISSUE_REF" > ${TMPDIR:-/tmp}/dev-issue-ref
if [ -n "$ISSUE_REF" ]; then
    gh issue view "$ISSUE_REF" 2>/dev/null || echo "⚠ Could not fetch issue $ISSUE_REF — proceeding without issue context"
fi
```

If `ISSUE_REF` non-empty and issue fetch succeeded: include issue title, body, and labels in Step 1 scope analysis as pre-populated requirements context.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--no-challenge\`, \`--no-codemap\`, \`--codemap\`, \`--semble\`, \`--accept-no-plan\`, \`--issue\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Codemap auto-detection** — run after flag parsing:

```bash
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_ENABLED") || exit 1
```

**Semble preflight** — if `SEMBLE_ENABLED=true`:

Read `$_DEV_SHARED/preflight-helpers.md` — execute semble preflight if flag set.

<!-- Only active when --team flag passed (~10% of invocations) -->
## Team Mode Branch

**Run immediately after flag parsing when `TEAM_MODE=true`. Runs Step 1 inline (teammates need scope context), then spawns parallel teammates for Steps 2-4. Exit after synthesis.**

When `TEAM_MODE=true`:

Guard: `[ -f "${HOME}/.claude/TEAM_PROTOCOL.md" ] || echo "TEAM_PROTOCOL_ABSENT"` — if output contains `TEAM_PROTOCOL_ABSENT`: invoke `AskUserQuestion` — question: "foundry plugin not installed (TEAM_PROTOCOL.md absent) — cannot run team mode. Continue solo instead?" · (a) Continue solo — fall back to Steps 1–5 solo workflow · (b) Abort — stop and run `/foundry:init` first. On (b): stop. On (a): set `TEAM_MODE=false` and continue.

Run Step 1 scope analysis inline (same analysis as solo Step 1) — teammates need orientation context. After Step 1 completes, broadcast to teammates: `{feature: <desc>, scope: <modules>, API: <proposed signature>}`.

Read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template to get spawn prompt template. Replace `[ROLE_PHRASE]` with feature description, `[FILE_SLUG]` with `feature`.

Compute run directory:

```bash
# timeout: 5000
mapfile -t _run < <(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/setup_worktree.py")
TS="${_run[0]}"
TEAM_DIR="${_run[1]}"
echo "$TS" > ${TMPDIR:-/tmp}/dev-feature-team-ts
```

**IMPORTANT**: in spawn prompts below, replace `$TS` and `$TEAM_DIR` with the actual computed values from the bash block above — literal resolved strings, not shell variable references.

```bash
# Resolve variables to literals for spawn prompt embedding (matches fix/refactor pattern)  # timeout: 5000
_SPAWN_TS="$TS"
_SPAWN_TEAM_DIR="$TEAM_DIR"
```

Use `$_SPAWN_TS` (or the literal resolved value) inside spawn prompt strings, not bare `$TS`.

Spawn 3 teammates in parallel using Agent() tool:

**Teammate 1 — foundry:sw-engineer (model=opus)**: implements the feature (Steps 2-3: demo test, TDD loop). Prompt: "You are a foundry:sw-engineer teammate implementing: [feature description]. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages. Your task: implement the feature (Steps 2-3: demo test, TDD loop). Scope constraint: only edit files in `src/`, the target module directory, and non-test Python files. Do NOT edit files under `tests/`. Compact Instructions: preserve file paths, test results, API signatures. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to .temp/develop/$TS/feature-sw-engineer-$TS.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"summary\":\"<one-line>\",\"findings\":N,\"confidence\":0.N}."

**Teammate 2 — foundry:qa-specialist (model=sonnet)**: audits test coverage, adds edge-case and regression tests in parallel + security checks for auth/payment/data scope (TDD demo/red-green tests stay with sw-engineer per qa-specialist NOT-for). Prompt: "You are a foundry:qa-specialist teammate implementing: [feature description]. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages. Your task: audit test coverage and add edge-case, boundary, and regression tests around the SW implementation; include security checks for any auth/payment/data-handling code. Do NOT write the primary TDD demo/red-green tests — those stay with sw-engineer (Teammate 1) as part of the TDD loop. Scope constraint: only create or edit files under `tests/`. Do NOT edit source files under `src/` or the target module. Compact Instructions: preserve file paths, test results, API signatures. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to .temp/develop/$TS/feature-qa-specialist-$TS.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"summary\":\"<one-line>\",\"findings\":N,\"confidence\":0.N}."

**Teammate 3 — foundry:doc-scribe (model=sonnet)**: prepares documentation structure in parallel (Step 5 prep — docstrings and README only; CHANGELOG handled by lead via foundry:sw-engineer after synthesis). Prompt: "You are a foundry:doc-scribe teammate implementing: [feature description]. Read ${HOME}/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2 for inter-agent messages. Your task: prepare documentation structure in parallel (Step 5 prep — docstrings and README only; do NOT write to CHANGELOG.md — that is handled separately). Compact Instructions: preserve file paths, doc locations, API signatures. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal your completion in your final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to .temp/develop/$TS/feature-doc-scribe-$TS.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"summary\":\"<one-line>\",\"findings\":N,\"confidence\":0.N}."

**Path verification**: after team spawns, verify agents received correct paths — check expected output files exist:

```bash
# timeout: 5000
for agent in sw-engineer qa-specialist doc-scribe; do
    expected=".temp/develop/$TS/feature-${agent}-$TS.md"
    [ -f "$expected" ] && echo "✓ $agent wrote $expected" || echo "⚠ $agent missing expected output $expected"
done
```

**Coordination order**: QA challenges SW API design — lead routes challenge back to SW before implementation starts. SW shares implementation details with QA so tests stay accurate. Lead synthesizes outputs in Step 5 onward as normal.

Health monitoring (CLAUDE.md §8): re-derive `$TS` at block start (bash state lost between Bash() calls — read back from temp file the spawn block persisted):

```bash
# timeout: 5000
TS=$(cat ${TMPDIR:-/tmp}/dev-feature-team-ts 2>/dev/null || date -u +%Y-%m-%dT%H-%M-%SZ)
```

Create sentinel `touch ${TMPDIR:-/tmp}/feature-team-check-$TS`; every 5 min: `find .temp/develop/$TS -newer ${TMPDIR:-/tmp}/feature-team-check-$TS -type f | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min no file activity → timed out. One extension (+5 min) if `tail -20` of output file explains delay; second unexplained stall = hard cutoff. On timeout: read `tail -100` of stalled file; surface with ⏱; never omit timed-out teammates.

After all teammates complete: read their output files from `.temp/develop/$TS/`, synthesize, run quality stack, produce Final Report. Exit — do not continue to solo Steps 1-5.

## Step 1: Understand purpose and scope

Gather full context before writing any code:

> **Argument type detection**: if `$ARGUMENTS` is positive integer (or prefixed with `#`, e.g. `#123`), treat as GitHub issue number and fetch with `gh issue view`. If text, treat as feature description.
>
> **Issue ID parsing rule**: Issue IDs must be prefixed with `#`; bare numbers ≥1000 are treated as issue IDs only if the `--issue` flag is present. Bare numbers <1000 without `#` prefix are treated as issue IDs unconditionally (legacy behavior). To avoid ambiguity when numeric goals appear, prefer descriptive text arguments or use `#<N>` prefix for issue references.

```bash
# Strip leading '#' so both '123' and '#123' work; only fetch if numeric
ISSUE_NUM="${ARGUMENTS#\#}"
if [[ "$ISSUE_NUM" =~ ^[0-9]+$ ]]; then
  python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/issue_fetch.py" "$ARGUMENTS" 2>/dev/null  # timeout: 6000
fi
```

If free-text description provided: use Grep tool (pattern `<keyword>`, glob `**/*.py`) to search related code. Path hint: use `src/` if that directory exists, otherwise search from project root (`.`).

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`** (values normalized by `bin/codemap-resolve` and `bin/semble-resolve`): read `$_DEV_SHARED/codemap-context.md` and follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip entirely if both flags false.

Spawn **foundry:sw-engineer** agent to analyse codebase and produce:

- **Purpose**: what problem does feature solve, and for which users?
- **Scope**: which files and modules likely change (entry points, data models, tests)?
- **Compatibility**: does feature touch public API? Require deprecation? Need backward-compat shims?
- **Reuse opportunities**: existing utilities, base classes, patterns, abstractions new code can extend instead of duplicate
- **Risks**: edge cases, performance implications, integration points needing careful handling
- **Scope challenge**: Right problem? Simpler alternatives? What already exists that could extend instead of build from scratch?
- **Complexity smell**: if proposed change touches 8+ files or introduces 2+ new classes/modules, flag explicitly — scope may need narrowing before proceeding

**Complexity classification**: classify as `small` (≤3 files, single concern), `medium` (4–7 files, or 1 new module), or `large` (8+ files, 2+ new modules, or public API change).

Read `$_DEV_SHARED/plan-inline.md` §Inline Plan Generation Protocol. Apply using **feature** context from the Skill contexts table. On proceed: set `PLAN_FILE=<path>`; continue to Step 2. On small complexity or `ACCEPT_NO_PLAN=true`: skip and continue to Step 2.

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

**Unit function / simple API** -> inline doctest (doctest in method docstring; must fail against current code).

**Complex feature** (setup required, side effects, multi-step flow) -> minimal example script `examples/demo_<feature>.py`; shows intended API end-to-end; becomes formal pytest test once implementation complete and API stable (end of Step 3).

Both forms must:

- Use **exact API** feature will expose (function name, signature, return type)
- Show happy-path end-to-end flow user would first reach for
- **Fail or error** against current code (feature doesn't exist yet)

**Gate**: demo must fail or error.

```bash
# Step 1: collect-only — verify ≥1 doctest exists before running full gate  # timeout: 30000
$PYTEST_CMD --collect-only --doctest-modules <module>.py -q 2>&1 | tail -5; COLLECT_EXIT=${PIPESTATUS[0]}
if [ "$COLLECT_EXIT" -eq 5 ]; then
    echo "⚠ GATE FAIL: no demo tests collected — demo file missing or doctest malformed"
    GATE_EXIT=1  # collection failed — skip full run, treat as gate failure
elif [ "$COLLECT_EXIT" -ne 0 ]; then
    echo "⚠ Cannot collect doctests — check module for import errors (collect exit $COLLECT_EXIT)"
    GATE_EXIT=1  # collection failed — skip full run, treat as gate failure
fi
```

```bash
# Step 2: run full gate only when collection succeeded (COLLECT_EXIT=0)  # timeout: 600000
# Doctest form:
if [ "${COLLECT_EXIT:-1}" -eq 0 ]; then
    $PYTEST_CMD --doctest-modules <module>.py -v 2>&1 | tail -10; GATE_EXIT=${PIPESTATUS[0]}
    if [ "${GATE_EXIT:-0}" -eq 0 ]; then
        echo "⚠ GATE FAIL: demo passed (exit 0) — feature may already exist; revisit Step 1"
    else
        echo "✓ GATE OK: demo failed as expected (exit $GATE_EXIT)"
    fi
fi

# Script form (use instead of doctest when applicable):
# python examples/demo_<feature>.py 2>&1 | tail -5; GATE_EXIT=$?
```

If `COLLECT_EXIT -ne 0`: stop — collection failed, gate skipped (GATE_EXIT=1). If `GATE_EXIT -eq 0`: invoke `AskUserQuestion` — do not silently proceed past a gate failure with prose alone: "Demo passed against current code — feature may already exist. How to proceed?" · (a) **Stop** — revisit Step 1 scope (recommended; feature likely already implemented) · (b) **Continue anyway** — proceed with TDD loop (gate explicitly overridden). On Stop: exit; do not advance to Step 3.

### Review: Validate the demo

Before proceeding to implementation, critically evaluate demo:

1. **Goal alignment**: does demo address user's stated goal, or slightly different problem?
2. **API design**: is proposed API minimal? Follows existing codebase conventions (naming, parameter order, return types)?
3. **Missing scenarios**: obvious happy-path variants or important failure modes demo doesn't cover?
4. **Testability**: can demo be automatically verified — not just `print`-and-inspect?

If issue found: revise demo and re-run gate. Don't proceed to Step 3 with flawed API contract — entire TDD loop anchored to this.

## Step 3: TDD implementation loop

**TDD test ownership**: lead (or foundry:sw-engineer if delegated) writes all red-green demo and TDD tests in Steps 2–3. foundry:qa-specialist must NOT write the primary demo or red-green tests in any mode — qa-specialist adds edge-case, boundary, and regression tests after implementation is complete (Step 4). This rule applies in both solo and team mode.

Drive implementation by making tests pass, one cycle at a time:

```bash
# Baseline: confirm existing suite is green before adding any new code
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/run_pytest_short.py" "$PYTEST_CMD" <target_test_dir>  # timeout: 600000
GATE_EXIT=$?
```

**Gate**: all existing tests must pass before proceeding. If any fail, stop — don't add new code on broken baseline. Use `/develop:fix` to address pre-existing failures first, then return here.

> **Note on exit code 5**: `pytest` returns exit code 5 when no tests collected. Exit code 5 acceptable here — means no pre-existing tests exist yet, valid baseline for new feature. Proceed with TDD loop. Only exit codes 1, 2, 3, 4 indicate actual test failures.

(Use Glob tool — `pattern: **/test_*.py` — to discover test directories if `<target_test_dir>` unknown; check `pyproject.toml` `[tool.pytest.ini_options] testpaths` first)

Start from Step 2 demo — already failing, becomes first target. For each piece of functionality:

1. **Target demo or write next focused test** — first iteration uses Step 2 demo directly; subsequent iterations add one new test per piece of new behaviour
2. **Run existing suite — confirm all pass**:
   ```bash
   # timeout: 600000
   $PYTEST_CMD --tb=short <target_test_dir> -v 2>&1 | tail -20
   GATE_EXIT=${PIPESTATUS[0]}
   ```
3. **Run new demo/test — confirm it fails**:
   ```bash
   # timeout: 600000
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
   # timeout: 600000
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
   # timeout: 600000
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

Spawn **foundry:doc-scribe** agent to update docstrings and README only (doc-scribe NOT-for: CHANGELOG — route separately):

- Add or update **docstrings** on new/modified functions and classes (Google style — Napoleon)
- Update module-level docstring if feature adds significant capability
- Add demo from Step 2 as doctest if not already embedded
- If feature changes public API: update `README.md` usage examples

Spawn doc-scribe with context:
- Affected files: [list from Step 1 scope analysis]
- New/modified public API: [function names, signatures from Step 3]
- Demo location: [Step 2 demo file path and function name]

Agent must Read each affected source file before writing docstrings — do not write placeholder content.

**CHANGELOG update** (separate from doc-scribe): after doc-scribe completes, spawn **foundry:sw-engineer** to append one-line entry to `CHANGELOG.md` under `Unreleased` section. Context: feature name and one-line description of new capability.

```bash
# Verify doctests pass after doc updates  # timeout: 600000
$PYTEST_CMD --doctest-modules <target_module> -v 2>&1 | tail -20
GATE_EXIT=${PIPESTATUS[0]}
```

Read `$_FOUNDRY_SHARED/quality-stack.md` (if file not found → skip quality stack entirely, note "foundry quality-stack not found at installed path — stack skipped" in Final Report) and execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

**Branch Safety Guard — no test suite**: if no test suite found (pytest collects 0 tests or `$TEST_CMD` not set), log `⚠ No test suite detected — Branch Safety Guard weakened` and require explicit user confirmation before proceeding past the guard.

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
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [e.g., review cycle incomplete, edge cases not fully explored]

**Refinements**: N passes.
```

<!-- Team spawn logic: see ## Team Mode Branch above -->

</workflow>

<notes>

<!-- Reference only — execution-dead at runtime; included for agent behavioral context -->

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The feature is clear — I can skip the demo and go straight to code" | Without crystallized API contract, implementation drifts. Demo = spec. |
| "I know this library — no need to check docs" | Training data contains deprecated patterns. One fetch prevents hours of rework. |
| "I'll write tests after the implementation is stable" | Tests drive design. Writing first reveals API problems before baked in. |
| "The existing suite still passes — the feature is good" | Existing suite doesn't cover new feature. Demo and edge-case tests do. |
| "Step 1 analysis is unnecessary for a small addition" | Scope analysis reveals reuse opportunities and blast radius. Small additions regularly grow. |

</notes>
