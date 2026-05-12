---
name: debug
description: Investigation-first debugging — gather evidence, form confirmed root-cause hypothesis, hand off to fix mode with diagnosis file.
argument-hint: '<symptom or failing test> [--no-challenge] [--team]'
effort: medium
when_to_use: Use when root cause unknown and evidence must be gathered first; NOT for applying known fix (use fix) or environment/tooling failures without code traceback (use foundry:investigate).
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, Skill, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Investigation-first debugging. Gather evidence, trace data flow, form confirmed root-cause hypothesis, hand off to fix mode.

NOT for: production incidents without local reproduction (use `/foundry:investigate` (requires foundry plugin) for triage); `.claude/` config issues (use `/foundry:audit` (requires foundry plugin)); non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead.

</objective>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at plugins/develop/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
# Locate develop plugin shared dir — installed first, local workspace fallback
_DEV_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/develop/*/skills/_shared 2>/dev/null | head -1)
[ -z "$_DEV_SHARED" ] && _DEV_SHARED="plugins/develop/skills/_shared"
```

Read `$_DEV_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:challenger`.

Read `$_DEV_SHARED/task-hygiene.md`.

## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "I already know root cause from traceback" | Tracebacks show where, not why. Unverified assumptions produce fixes for wrong bug. |
| "Fix obvious — Step 2 pattern analysis overkill" | Obvious causes often symptoms. Pattern comparison reveals ordering, timing, or environment differences invisible in traceback. |
| "I'll apply fix here instead of handing off to `/develop:fix`" | Debug = investigation only. Mixing investigation + implementation conflates history, skips regression test gate. |
| "Low confidence fine — I'll try fix and see" | Fix without confirmed hypothesis = guess. Guesses produce fixes that pass tests but don't resolve underlying problem. |

## Project Detection

Read `$_DEV_SHARED/runner-detection.md` — sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Checkpoint**: debug = investigation only — no code changes. `.plans/active/debug_<slug>.md` (written in Step 4) serves as implicit session state. No `.developments/` checkpoint needed.

## Debug Mode

> **Argument type detection**: if `$ARGUMENTS` is positive integer (or prefixed with `#`, e.g. `#123`), treat as GitHub issue number and fetch with `gh issue view`. If text (contains spaces, letters, or special chars), treat as symptom description.

## Flag parsing

**Set `CHALLENGE_ENABLED=true` and `TEAM_MODE=false`**. Parse flags from `$ARGUMENTS`:
- If `--no-challenge` present: set `CHALLENGE_ENABLED=false`.
- If `--team` present: set `TEAM_MODE=true`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--no-challenge\`, \`--team\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**If `TEAM_MODE=true`** — execute team investigation now and exit; skip standard Steps 1-4:

1. Read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template. Confirm `[ROLE_PHRASE]` = symptom text (from `$ARGUMENTS` stripped of flags), `[FILE_SLUG]` = `debug-hypothesis`.
2. Run project detection (read `$_DEV_SHARED/runner-detection.md`) to set `$TEST_CMD` and `$PYTEST_CMD`.
3. Spawn 2-3 `foundry:sw-engineer` agents (model=opus) in parallel — each investigating one independent root-cause hypothesis. Use the Team Spawn Template from preflight-helpers: replace `[ROLE_PHRASE]` with the symptom, `[FILE_SLUG]` with `debug-hypothesis`, assign each agent a distinct hypothesis number N. Each agent writes full output to `.plans/active/debug-hypothesis-N-<timestamp>.md` and returns compact JSON `{"status":"done","file":"<path>","findings":N,"confidence":0.N}`.
4. **Coordination**: lead broadcasts `{symptom: <description>, traceback: <key lines>}` to teammates before spawning. After all return, facilitate cross-challenge between competing analyses. Convergence rule: select hypothesis with most direct evidence (observable in code or logs); if truly tied, invoke `AskUserQuestion` presenting top 2 competing hypotheses.
5. Lead synthesises consensus root cause. Run Steps 3-4 of standard workflow (hypothesis gate + hand off to fix) on the winning hypothesis — execute those steps inline here; do not loop back through Steps 1-2.

Health monitoring (CLAUDE.md §8): for each spawned agent, create sentinel `touch /tmp/debug-team-check-N`; poll every 5 min via `find .plans/active -newer /tmp/debug-team-check-N -type f | wc -l`; hard cutoff 15 min no-file-activity; mark timed-out agents with ⏱ in synthesis.

## Step 1: Understand the symptom

Collect all signals before forming any hypothesis.

**Issue-number mode first** — if `$ARGUMENTS` is issue number, fetch issue body and extract test path BEFORE invoking pytest:

```bash
# Strip leading '#' and fetch issue in one block — ARGUMENTS strip doesn't persist across Bash calls
ISSUE_NUM="${ARGUMENTS#\#}"
ISSUE_BODY=$(gh issue view "$ISSUE_NUM" --comments 2>&1)  # timeout: 6000
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
# Read the full traceback — never just the last line
$PYTEST_CMD --tb=long ${TEST_PATH} -v 2>&1 | tail -60
GATE_EXIT=${PIPESTATUS[0]}
```

```bash
# What changed recently near the failing code?
git log --oneline -20
COMMIT_COUNT=$(git rev-list --count HEAD 2>/dev/null || echo 1)
LOOKBACK=$(( COMMIT_COUNT < 5 ? COMMIT_COUNT : 5 ))
[ "$LOOKBACK" -gt 1 ] && git diff HEAD~${LOOKBACK}..HEAD -- <suspect_file>
```

**Symptom-text mode** — if `$ARGUMENTS` is free-text, skip issue fetch + extraction; locate failing test path from symptom directly, then run:

```bash
$PYTEST_CMD --tb=long <test_path> -v 2>&1 | tail -60
GATE_EXIT=${PIPESTATUS[0]}
```

Use Grep (pattern: failing symbol, class, or error keyword) to trace call path from entry point to failure site. Path hint: use `src/` if exists, else search from project root (`.`).

Spawn **foundry:sw-engineer** agent to map execution path and produce:

- Entry point to failure: which modules does call cross?
- What state mutated along the way?
- What invariant violated at failure point?
- Any recent commit touching this path (from git log output)

**Scope gate**: if root cause spans 3+ modules, flag complexity smell. Use `AskUserQuestion` to present scope concern before proceeding, with options: "Narrow scope (Recommended)" / "Proceed anyway".

Present agent's analysis summary before proceeding.

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

**Gate**: present hypothesis to user, wait for confirmation or challenge before proceeding to Step 4. Wrong hypothesis produces fix that passes tests but doesn't resolve underlying problem.

**Autonomous-mode fallback** (when running as subagent with no direct user interaction):
- Confidence **high**: proceed automatically to Step 4; note "auto-confirmed (subagent mode)" in Final Report
- Confidence **medium**: return hypothesis + evidence to parent agent as structured JSON; let parent decide: `{"hypothesis":"<root cause>","evidence":["<s1>","<s2>"],"confidence":"medium","action_required":"confirm_before_fix"}`
- Confidence **low**: run targeted probe (minimal script, added assertion) to gather more signal before returning to parent

If confidence low: propose targeted probe (minimal script, added log statement, single assertion) to gather missing signal — run before committing to fix.

## Step 4: Hand off to fix

Root cause confirmed. Transition to fix mode with diagnosis as input — fix's Step 1 pre-answered.

Emit handoff block:

```text
Root cause: <confirmed hypothesis from Step 3>
Suspect file(s): <files identified in Steps 1-2>
Evidence: <key signals that confirmed the hypothesis>
```

**Write diagnosis to file** before handing off — enables `/develop:fix` to skip Step 1 analysis via `--diagnosis <path>`:

```bash
SLUG=$(echo "<symptom first 4 words>" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | tr -cd '[:alnum:]-')
[ -z "$SLUG" ] && SLUG="unnamed-$(date +%s)"
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
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**:
- [e.g., unverified alternative hypotheses, hypothesis only — not confirmed via test reproduction]

**Refinements**: N passes.
```

**Follow-up gate (NEVER SKIP)** — Call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "Proceed with fix?"
- (a) label: `/develop:fix --diagnosis $DIAG_FILE` — description: proceed with fix using confirmed diagnosis
- (b) label: `skip` — description: no action

## Team Assignments

<!-- Executed inline in Flag parsing block above when --team flag is set. -->
<!-- This section is reference documentation only — do not execute here. -->

**When to use team mode**: pass `--team` flag. Team logic runs immediately after flag parsing and exits — Steps 1-4 below are skipped.

**Spawn prompt template:** read `$_DEV_SHARED/preflight-helpers.md` §Team Spawn Template — replace `[ROLE_PHRASE]` with `[symptom]`, `[FILE_SLUG]` with `debug-hypothesis`.

</workflow>
