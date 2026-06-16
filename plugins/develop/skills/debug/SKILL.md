---
name: debug
description: "Investigation-first debugging — gather evidence, form confirmed root-cause hypothesis, hand off to fix mode with diagnosis file."
when_to_use: |
  TRIGGER when: user reports a symptom or failing test with Python traceback, or asks to investigate a runtime/CI failure with reproducible evidence; phrases: "debug this failure", "why is X broken", "find the root cause of <error>", "investigate this CI failure".
  SKIP: pure config quality issues (use `/foundry:audit`); broad system-wide diagnosis without traceback (use `/foundry:investigate`); user already knows the fix (use `/develop:fix`); non-Python project.
argument-hint: "<symptom or issue # (plain 123 or #123)> [--repo <owner/repo>] [--no-challenge] [--team] [--ci-run <run-id-or-url>] [--codemap] [--no-codemap]"
effort: high
allowed-tools: Read, Write, Bash, Grep, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Investigation-first debugging. Gather evidence, trace data flow, form confirmed root-cause hypothesis, hand off to fix mode.

NOT for: production incidents without any CI run ID or local traceback (use `/foundry:investigate` (requires foundry plugin) for triage); `.claude/` config issues (use `/foundry:audit` (requires foundry plugin)); non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead. CI-only failures ARE supported — pass `--ci-run <run-id or URL>` to use GitHub Actions logs as evidence source.

**Issue ID routing note**: bare numbers ≥1000 are treated as issue IDs only when `--issue` flag is present (same rule as `/develop:feature`). Pass `--issue <N>` for high-numbered issues to avoid ambiguity.

</objective>

<workflow>

<!-- Agent resolution: see _DEV_SHARED/agent-resolution.md (mounted by develop plugin init) -->

## Agent Resolution

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Language preflight gate**: detect project language; adjust test runner accordingly.

```bash
# timeout: 5000
LANG_HINT="python"
if [ ! -f "pyproject.toml" ] && [ ! -f "setup.py" ] && [ ! -f "setup.cfg" ] && [ ! -f "Pipfile" ]; then
    if [ -f "package.json" ]; then LANG_HINT="node"
    elif [ -f "go.mod" ]; then LANG_HINT="go"
    elif [ -f "Cargo.toml" ]; then LANG_HINT="rust"
    fi
fi
```

If `LANG_HINT` not `python`: invoke `AskUserQuestion` — "Non-Python project detected (`$LANG_HINT`). Toolchain assumes pytest. How to proceed?" · (a) **Abort** — use language-native runner · (b) **Continue** — repo also has Python sources. On Abort: stop.

**Checkpoint**: debug = investigation only — no code changes. `.plans/active/debug_<slug>.md` (written in Step 4) serves as implicit session state. No `.developments/` checkpoint needed.

## Flag parsing

Parse flags into actual shell variables (not prose) so downstream blocks see correct values:

```bash
# timeout: 10000
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" \
    --skill debug --write-files "$ARGUMENTS"
# URL normalization and log fetching: see §URL Normalization in ci-log-extract.md below
```

**Codemap resolve** — `CODEMAP_RAW` is already written to `${TMPDIR:-/tmp}/dev-debug-codemap` (per-skill) and `${TMPDIR:-/tmp}/dev-codemap-raw` (legacy) by the flag-parsing block above (via `dev_parse_args.py --skill debug --write-files`). Read the per-skill path, then normalize via `codemap-resolve`:

```bash
# timeout: 5000
CODEMAP_RAW=$(cat ${TMPDIR:-/tmp}/dev-debug-codemap 2>/dev/null || echo auto)
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_RAW")
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    [ "$CODEMAP_RAW" = "strict" ] && exit 1
    CODEMAP_ENABLED=false
fi
# Skill-specific namespace — avoids reading stale true from prior feature --codemap run
echo "$CODEMAP_ENABLED" > ${TMPDIR:-/tmp}/dev-debug-codemap-enabled
```

Downstream blocks read back: `CHALLENGE_ENABLED=$(cat ${TMPDIR:-/tmp}/dev-challenge-enabled 2>/dev/null || echo true)`, `TEAM_MODE=$(cat ${TMPDIR:-/tmp}/dev-team-mode 2>/dev/null || echo false)`, `CI_RUN_ID=$(cat ${TMPDIR:-/tmp}/dev-ci-run-id 2>/dev/null || echo "")`.

Read `$_DEV_SHARED/ci-log-extract.md`. Follow §URL Normalization to set `CI_RUN_ID`. If `CI_RUN_ID` set, follow §Log Fetching and §Log Parsing to set `CI_LOG_EVIDENCE`; use it as evidence source in Step 1 instead of local pytest.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--team\`, \`--ci-run\`, \`--issue\`, \`--repo\`, \`--codemap\`, \`--no-codemap\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Mode selection** — debug runs in one of two mutually-exclusive modes; set explicitly before any Step:

```bash
# timeout: 5000
# Strip flags before integer detection so "123 --no-challenge" correctly detects issue mode
ARGUMENTS_FOR_MODE_DETECT=$(echo "$ARGUMENTS" | sed -E 's/--no-challenge|--team|--ci-run[= ]?[^ ]+|--issue|--repo[= ]?[^ ]+|--no-codemap|--codemap//g' | xargs)
if [[ " $ARGUMENTS " == *" --issue "* ]] || [[ "$ARGUMENTS_FOR_MODE_DETECT" =~ ^#?[0-9]+$ ]]; then
    DEBUG_MODE="issue"
else
    DEBUG_MODE="symptom"
fi
echo "$DEBUG_MODE" > ${TMPDIR:-/tmp}/dev-debug-mode
```

Subsequent steps branch by `DEBUG_MODE`:
- **Issue mode**: Step 1 fetches issue body and extracts test path before invoking pytest; skip the symptom-text pytest block. Stop after Step 4 (handoff) — do not run symptom-text branches.
- **Symptom mode**: Step 1 skips issue fetch; uses free-text symptom directly. Skip the issue-mode pytest block entirely.

**If `TEAM_MODE=true`** — execute team investigation now in place of standard Steps 1-2. After team synthesis completes, run Steps 3-4 inline (hypothesis gate + handoff to fix) on the winning hypothesis — do not return to standard Steps 1-2. Authoritative reading: team mode **replaces** Steps 1-2 (parallel hypothesis investigation supplants serial evidence gathering); Steps 3-4 still execute (inline within this block, not by looping back to the standard workflow):

1. Read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template. Confirm `[ROLE_PHRASE]` = symptom text (from `$ARGUMENTS` stripped of flags), `[FILE_SLUG]` = `debug-hypothesis`.
2. Run project detection (read `$_DEV_SHARED/runner-detection.md`) to set `$TEST_CMD` and `$PYTEST_CMD`.
3. Compute `TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)` and `mkdir -p ".temp/develop/$TS"`. Spawn 2-3 `foundry:sw-engineer` agents (model=opus) in parallel — each investigating one independent root-cause hypothesis. Use the Team Spawn Template from preflight-helpers: replace `[ROLE_PHRASE]` with the symptom, `[FILE_SLUG]` with `debug-hypothesis`, assign each agent a distinct hypothesis number N. Each agent writes full output to `.temp/develop/$TS/debug-hypothesis-N.md` and returns compact JSON `{"status":"done","file":"<path>","findings":N,"confidence":0.N,"summary":"<one-line description of hypothesis>"}`.
4. **Coordination**: lead broadcasts `{symptom: <description>, traceback: <key lines>}` to teammates before spawning. After all return, facilitate cross-challenge between competing analyses. Convergence rule: select hypothesis with most direct evidence (observable in code or logs); if truly tied, invoke `AskUserQuestion` presenting top 2 competing hypotheses.
5. **Synthesis trace agent**: spawn one `foundry:sw-engineer` synthesis agent after individual teammate reports — read all teammate findings from `.temp/develop/$TS/debug-hypothesis-*.md`, produce unified cross-cutting trace map (entry point, modules crossed, state mutations, invariant violations across hypotheses). Write to `.temp/develop/$TS/debug-trace-synthesis.md`.
6. Lead synthesises consensus root cause from synthesis trace + competing hypotheses. Run Steps 3-4 of standard workflow (hypothesis gate + hand off to fix) on the winning hypothesis — execute those steps inline here; do not loop back through Steps 1-2. **Step 3 gate in team mode**: if convergence was reached by synthesis agent (all hypotheses point to same root cause with high confidence), present the converged hypothesis without a new user confirmation prompt — state "Team converged on root cause (no ambiguity)" and proceed directly to Step 4 handoff. Only invoke `AskUserQuestion` at Step 3 if competing hypotheses remain or convergence was declared by default (tied evidence).

Health monitoring (CLAUDE.md §6): for each spawned agent, use a **per-agent sentinel** keyed on the loop counter `$N` (not the literal `N`). Loop over agent indices in actual bash:

```bash
# timeout: 5000
for N in 1 2 3; do
    touch "${TMPDIR:-/tmp}/debug-team-check-${N}"
done
```

Poll each independently every 5 min via `find .temp/develop/$TS -newer ${TMPDIR:-/tmp}/debug-team-check-${N} -type f | wc -l` where `$N` is the actual agent index in the loop variable. A single shared sentinel collapses health isolation — stalled agent N=2 cannot be distinguished from active agent N=1. Hard cutoff 15 min no-file-activity per agent; mark timed-out agents with ⏱ in synthesis.

## Step 1: Understand the symptom

Collect all signals before forming any hypothesis.

**Structural context (codemap — only if `CODEMAP_ENABLED=true`)**: if index available, run before codebase exploration to pre-load blast-radius context for the failing module:

```bash
# timeout: 10000
CODEMAP_ENABLED=$(cat ${TMPDIR:-/tmp}/dev-debug-codemap-enabled 2>/dev/null || echo false)
if [ "$CODEMAP_ENABLED" = "true" ]; then
    scan-query central --top 5 2>/dev/null
fi
```

After reading traceback or `$ARGUMENTS`, derive `TARGET_MODULE`: strip `src/`, `.py` suffix, replace `/` with `.` (e.g. `src/mypackage/auth.py` → `mypackage.auth`). Then run:

```bash
# timeout: 10000
scan-query rdeps <TARGET_MODULE> 2>/dev/null
scan-query fn-blast <TARGET_MODULE::failing_fn> 2>/dev/null  # v3 index only
```

If codemap results returned: prepend `## Structural Context (codemap)` block to foundry:sw-engineer spawn prompt (Step 1). Callers of the failing module = likely affected paths to verify after fix. fn-blast shows transitive callers — high-depth callers are regression risk.

**Issue-number mode first** — if `$ARGUMENTS` is issue number, fetch issue body and extract test path BEFORE invoking pytest:

```bash
# timeout: 6000
REPO_NAME=$(cat ${TMPDIR:-/tmp}/dev-upstream 2>/dev/null || echo "")
if [ -n "$REPO_NAME" ]; then
    ISSUE_BODY=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/issue_fetch.py" "$ARGUMENTS" --repo "$REPO_NAME" 2>/dev/null)
else
    ISSUE_BODY=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/issue_fetch.py" "$ARGUMENTS" 2>/dev/null)
fi
echo "$ISSUE_BODY"
```

```bash
# Extract a test path (e.g., tests/foo.py or test_foo.py) from the issue body
TEST_PATH=$(echo "$ISSUE_BODY" | grep -oE '(tests?/[^[:space:]]+\.py|test_[^[:space:]]+\.py)' | head -1)
if [ -z "$TEST_PATH" ]; then
  echo "→ No test file found in issue; running full test suite"
elif [ ! -f "$TEST_PATH" ]; then
  echo "⚠ test path from issue not found on disk: $TEST_PATH — running full suite"
  TEST_PATH=""
fi
```

Run pytest with extracted path (empty `$TEST_PATH` → full suite):

```bash
# timeout: 600000
$PYTEST_CMD --tb=long ${TEST_PATH} -v 2>&1 | tail -60
GATE_EXIT=${PIPESTATUS[0]}
echo "$GATE_EXIT" > ${TMPDIR:-/tmp}/dev-gate-exit
if [ "$GATE_EXIT" -ne 0 ]; then
    echo "Bug reproduced — tests fail. Proceed to fix."
else
    echo "Tests pass — bug may not be reproducible via pytest; check symptom directly."
fi
```

```bash
# timeout: 3000
git log --oneline -20
COMMIT_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo 1)
LOOKBACK=$(( COMMIT_COUNT < 5 ? COMMIT_COUNT : 5 ))
SUSPECT_FILE="${TEST_PATH:-}"  # derive from TEST_PATH resolved above; empty -> full-repo diff (acceptable for small repos)
[ "$LOOKBACK" -gt 1 ] && git diff HEAD~${LOOKBACK}..HEAD -- "${SUSPECT_FILE:-}"
```

**Cross-repo adaptation** (when `REPO_NAME` set) — issue from different codebase. After fetching issue:
1. Extract bug's root cause intent — what invariant is violated, not just described symptoms (which may reference upstream structure or code paths)
2. Search LOCAL codebase for the equivalent failure site — grep for related symbols; code paths may differ from upstream due to divergence
3. Treat upstream issue as debugging context, not as a map — trace the actual failure in local code

**Symptom-text mode** — if `$ARGUMENTS` is free-text, skip issue fetch + extraction; locate failing test path from symptom directly. `<test_path>` is a **substitution token** — resolve it into the shell variable `$TEST_PATH` first (via Grep against symptom keywords or heuristic file search), then use `$TEST_PATH` in the pytest call. Do NOT execute with the literal `<test_path>` string — bash would interpret `<` as a stdin redirect from a file named `test_path`:

```bash
# Resolve TEST_PATH before this block — e.g.:
# TEST_PATH=$(grep -rE '<symptom keyword>' tests/ --include='*.py' -l | head -1)
# timeout: 600000
$PYTEST_CMD --tb=long ${TEST_PATH} -v 2>&1 | tail -60
GATE_EXIT=${PIPESTATUS[0]}
echo "$GATE_EXIT" > ${TMPDIR:-/tmp}/dev-gate-exit
if [ "$GATE_EXIT" -ne 0 ]; then
    echo "Bug reproduced — tests fail. Proceed to fix."
else
    echo "Tests pass — bug may not be reproducible via pytest; check symptom directly."
fi
```

Use Grep (pattern: failing symbol, class, or error keyword) to trace call path from entry point to failure site. Path hint: use `src/` if exists, else search from project root (`.`).

Spawn **foundry:sw-engineer** agent to map execution path and produce:

- Entry point to failure: which modules does call cross?
- What state mutated along the way?
- What invariant violated at failure point?
- Any recent commit touching this path (from git log output)

**Scope gate**: if root cause spans 3+ modules, flag complexity smell. Use `AskUserQuestion` to present scope concern before proceeding, with options: "Narrow scope (Recommended)" / "Proceed anyway".

Present agent's analysis summary before proceeding.

**Flaky-test branch** — if symptom is intermittent (passes alone, fails in full suite): run binary-search isolation. `<failing-test-node-id>` is a **substitution token** — before executing this block, resolve the failing test node ID from `$ARGUMENTS` or from prior pytest output (captured in a shell variable, e.g. `FAILING_TEST_NODE=tests/foo.py::test_bar`), then substitute the literal node ID into the command. Do NOT execute with the literal `<failing-test-node-id>` string — bash would interpret `<` as a stdin redirect:

```bash
# Resolve FAILING_TEST_NODE before this block (bash would interpret literal `<...>` as redirect):
# FAILING_TEST_NODE=$(echo "$ARGUMENTS" | grep -oE 'tests?/[^[:space:]]+::test_[^[:space:]]+' | head -1)
_FOUNDRY_BIN=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry-bin 2>/dev/null || ls -td ~/.claude/plugins/cache/*/foundry/*/bin 2>/dev/null | head -1 || echo "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin")  # timeout: 5000
if [ -z "$FAILING_TEST_NODE" ]; then
    echo "⚠ FAILING_TEST_NODE not resolved — cannot run polluter isolation; surface failing test node ID first"
elif [ -f "$_FOUNDRY_BIN/find-polluter.py" ]; then
    python "$_FOUNDRY_BIN/find-polluter.py" "$FAILING_TEST_NODE"  # timeout: 60000
else
    echo "⚠ foundry plugin absent — skipping flaky-test isolation; proceed with standard rerun"
fi
```

Output names the polluting upstream test. Cross-plugin call — `find-polluter.py` ships in `foundry/bin/`. Run only when CI shows non-deterministic failure pattern. If foundry plugin absent: skip flaky-test isolation step; proceed with standard rerun.

## Step 2: Pattern analysis

Find nearest similar working code path, compare exhaustively:

1. Locate 2-3 code paths handling similar input or similar work *successfully*
2. List **every** difference between working path and broken one — not just obvious one
3. Check across axes:
   - Same input, different environment (versions, config, data shape)?
   - Same logic, different call order or timing?
   - Conditionals taking different branches on different inputs?
   - None/empty guards present in working path but absent in broken one?

Step catches non-obvious causes — ordering dependency, environment-specific state, type coercion silently changing behaviour.

## Challenger gate

**Skip if `CHALLENGE_ENABLED=false`.**

Spawn `foundry:challenger` with pattern analysis from Step 2 (differences between working/broken paths, candidate causes):

> "Review pattern analysis and candidate root causes. Challenge across all 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply mandatory refutation step."

Parse result:
- **Blockers found** → STOP. Present findings. Incorporate challenger's surviving challenges into hypothesis list before Step 3 gate.
- **Concerns only** → add as alternative hypotheses in Step 3; continue.
- **No findings / all refuted** → proceed.

## Step 3: Hypothesis and gate

State root cause hypothesis explicitly before writing any code:

```text
Root cause: <one sentence — what is wrong and why>
Evidence for: [signals that support this]
Evidence against: [anything that contradicts or remains unexplained]
Confidence: high / medium / low
```

Read `$_DEV_SHARED/premise-grounding.md` §Premise Grounding Gate. Apply using **debug** context from the Skill contexts table. Run before presenting hypothesis — any ungrounded premise in the hypothesis produces a fix that addresses the wrong mechanism.

**Gate**: present hypothesis to user, wait for confirmation or challenge before proceeding to Step 4. Wrong hypothesis produces fix that passes tests but doesn't resolve underlying problem.

If confidence low: propose targeted probe (minimal script, added log statement, single assertion) to gather missing signal — run before committing to fix.

## Step 4: Hand off to fix

Root cause confirmed. Transition to fix mode with diagnosis as input — fix's Step 1 pre-answered.

```bash
# timeout: 5000
if [ ! -f "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/skills/fix/SKILL.md" ]; then
    echo "⚠ /develop:fix not found — partial install detected; diagnosis file will be written but handoff cannot be invoked automatically"
fi
```

Emit handoff block:

```text
Root cause: <confirmed hypothesis from Step 3>
Suspect file(s): <files identified in Steps 1-2>
Evidence: <key signals that confirmed the hypothesis>
```

**Write diagnosis to file** before handing off — enables `/develop:fix` to skip Step 1 analysis via `--diagnosis <path>`:

```bash
SLUG=$(echo "$ARGUMENTS" | tr ' ' '\n' | grep -v '^--' | grep -v '^[0-9]\+$' | head -4 | tr '\n' '-' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-' | sed 's/-$//'); [ -z "$SLUG" ] && SLUG="unnamed-$(date +%s)"
# Note: grep -v '^[0-9]\+$' strips bare numeric tokens (e.g. CI run IDs) from the slug to avoid confusing filenames like debug_12345678.md
DIAG_FILE=".plans/active/debug_${SLUG}.md"
mkdir -p .plans/active
```

Write `$DIAG_FILE` with this structure:
```markdown
# Debug Diagnosis: <symptom>

## Root Cause
<one sentence — confirmed hypothesis>

## Suspect Files
- path/to/file.py — <reason>

## Evidence
- <signal 1 that confirmed hypothesis>
- <signal 2>

## Confidence
<high|medium|low>
```

Hand off: `-> /develop:fix --diagnosis $DIAG_FILE`. Root cause already known — fix's Step 1 analysis complete.

## Final Report

After root cause confirmed and handoff to `/develop:fix` complete, emit terminal summary:

```markdown
Root Cause: <one sentence>
File(s): <suspect files>
Evidence: <key signals>
→ Handed off to /develop:fix --diagnosis $DIAG_FILE

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [e.g., unverified alternative hypotheses, hypothesis only — not confirmed via test reproduction]

**Refinements**: N passes.
```

**Follow-up gate (NEVER SKIP)** — Call `AskUserQuestion` tool — do NOT write options as plain text first. Substitute actual `$DIAG_FILE` path (from bash block above) into option (a) label before calling tool. Map options directly into tool call arguments:
- question: "Proceed with fix?"
- (a) label: `/develop:fix --diagnosis <DIAG_FILE>` (substitute resolved path, e.g. `/develop:fix --diagnosis .plans/active/debug_<slug>.md`) — description: proceed with fix using confirmed diagnosis
- (b) label: `skip` — description: no action

</workflow>

<notes>

## Anti-Rationalizations

<!-- Reference only — execution-dead at runtime; included for agent behavioral context -->

| Temptation | Reality |
| --- | --- |
| "I already know root cause from traceback" | Tracebacks show where, not why. Unverified assumptions produce fixes for wrong bug. |
| "Fix obvious — Step 2 pattern analysis overkill" | Obvious causes often symptoms. Pattern comparison reveals ordering, timing, or environment differences invisible in traceback. |
| "I'll apply fix here instead of handing off to `/develop:fix`" | Debug = investigation only. Mixing investigation + implementation conflates history, skips regression test gate. |
| "Low confidence fine — I'll try fix and see" | Fix without confirmed hypothesis = guess. Guesses produce fixes that pass tests but don't resolve underlying problem. |

<!-- Team spawn logic: see Flag parsing block above for team mode branch -->

</notes>
