---
name: refactor
description: "Test-first refactoring — audit coverage, add characterization tests, apply changes with safety net, run quality stack and review loop. TRIGGER when: user wants to restructure existing Python code without changing behaviour; phrases: \"refactor X\", \"clean up Y\", \"extract Z\", \"restructure this module\", \"improve code quality\". SKIP when: bug fixes (use `/develop:fix`); new features (use `/develop:feature`); mixed refactor+feature — run `/develop:refactor` first, then `/develop:feature`; non-Python projects."
argument-hint: '<target file or directory> <goal> [--repo <owner/repo>] [--plan <path>] [--no-challenge] [--challenge] [--codemap] [--no-codemap] [--accept-no-plan] [--semble] [--team] [--keep "<items>"]'
effort: high
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Test-first refactoring. Audit coverage, add characterization tests if missing, apply changes with safety net.

NOT for:
- bug fixes (use `/develop:fix`)
- new features (use `/develop:feature`)
- `.claude/` config changes (use `/foundry:manage` (requires foundry plugin))
- non-Python projects (JS/TS/Go/Rust) — toolchain assumes pytest; use language-native toolchain instead
- mixed refactor+feature tasks — run /develop:refactor first, then /develop:feature; do not attempt both in single skill run

Quality stack (Branch Safety Guard, Codex Pre-pass, Progressive Review) requires `foundry` plugin; when absent, Step 5 quality stack skipped with a visible warning — output lower quality but workflow still completes.

</objective>

<constants>

- MAX_INNER_CYCLES: 5 (change-test cycles per outer session — Step 4 safety break)

</constants>

<compaction>

Key boundary: end of Step 2 — coverage audit complete, before characterization test writing in Step 3.
Second boundary: end of Step 4 — refactor edits applied, before review stack in Step 5.
Preserve at boundary 1: dev-dir, target path, coverage audit summary, plan-file, --keep items.
Preserve at boundary 2: dev-dir, changed files list, test outcomes.

</compaction>

<workflow>

<!-- Agent Resolution: resolved at runtime via $_DEV_SHARED; source at develop/skills/_shared/agent-resolution.md (installed path) -->

## Agent Resolution

```bash
_PATHS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null)  # timeout: 5000
_DEV_SHARED=$(echo "$_PATHS" | head -1)
_FOUNDRY_SHARED=$(echo "$_PATHS" | tail -1)
[ -z "$_FOUNDRY_SHARED" ] && _FOUNDRY_SHARED="plugins/foundry/skills/_shared"
# loads: compaction-contract.md
cat "$_DEV_SHARED/agent-resolution.md"
```

Contains: foundry check + fallback table. If foundry not installed: substitute each `foundry:X` with `general-purpose` per table. Agents skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/task-hygiene.md"
```

<!-- Reference only — execution-dead at runtime; included for agent behavioral context -->
## Anti-Rationalizations

| Temptation | Reality |
| --- | --- |
| "The code is simple enough — I can skip characterization tests" | No safety net = no proof behavior unchanged. Characterization tests only proof. |
| "I'll fix this adjacent bug while I'm in here" | Scope creep conflates history. Adjacent bugs go in Follow-up, not this session. |
| "The tests are too brittle — I'll refactor them as well" | Refactoring tests + prod code simultaneously makes regressions unattributable. Fix tests first, separate pass. |
| "I know the codebase — no need for coverage audit" | Untested edge cases = most common refactoring breakage. Audit finds what you don't know you don't know. |
| "This is a small change — Step 4's max-5 cycles are overkill" | Simple changes = simple test loops. Guard costs nothing when unneeded; prevents runaway sessions when it is. |

## Project Detection

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/runner-detection.md"
```
Sets `$TEST_CMD` (full suite) and `$PYTEST_CMD` (pytest flags). Run at skill start.

**Optional `--plan <path>`**: if `$ARGUMENTS` contains `--plan <path>` (at any position), read plan file first. Extract `Affected files`, `Risks`, `Suggested approach` — use to inform Step 1 scope analysis. Skip redundant codebase exploration for already-classified files. Store plan path as `PLAN_FILE`.

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/preflight-helpers.md"
```
Execute --plan path extraction; sets `$PLAN_FILE`.

**Checkpoint init**: run `DEV_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_run_dir.py" 2>/dev/null)  # timeout: 5000` to create `.developments/<TS>/` and capture path. Write `checkpoint.md` inside `$DEV_DIR`. After each major step (1, 2, 3, 4, 5), append `step: N — completed` to `$DEV_DIR/checkpoint.md`. On skill start, check for existing `.developments/*/checkpoint.md` — offer resume from last completed step if found.

```bash
# persist DEV_DIR for compaction recovery — bash state lost between Bash() calls  # timeout: 5000
echo "$DEV_DIR" > "${TMPDIR:-/tmp}/dev-refactor-dev-dir"
```

## Flag parsing

Parse flags into actual shell variables (not prose) so downstream blocks see correct values. Persist to temp files for cross-block access (bash state lost between Bash() calls):

```bash
KEEP_ITEMS=""
if [[ "$ARGUMENTS" =~ --keep[[:space:]]\"([^\"]+)\" ]]; then
    KEEP_ITEMS="${BASH_REMATCH[1]}"
fi
echo "$KEEP_ITEMS" > "${TMPDIR:-/tmp}/dev-refactor-keep-items"
rm -f .claude/state/skill-contract.md  # timeout: 5000
```

```bash
# timeout: 10000
python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" \
    --skill refactor --write-files "$ARGUMENTS"
```

Downstream blocks read back, e.g. `TEAM_MODE=$(cat ${TMPDIR:-/tmp}/dev-team-mode 2>/dev/null || echo false)`.

**Codemap flag parsing** — derive raw flag into a real shell variable, then normalize via `codemap-resolve`. Uses skill-specific temp file (`dev-refactor-codemap-raw`) to avoid reading stale values from prior feature/debug runs:

```bash
# timeout: 5000
CODEMAP_RAW=auto
[[ " $ARGUMENTS " == *" --no-codemap "* ]] && CODEMAP_RAW=off
[[ " $ARGUMENTS " == *" --codemap "* ]] && [[ " $ARGUMENTS " != *" --no-codemap "* ]] && CODEMAP_RAW=strict
echo "$CODEMAP_RAW" > ${TMPDIR:-/tmp}/dev-refactor-codemap-raw
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--plan\`, \`--team\`, \`--no-challenge\`, \`--challenge\`, \`--codemap\`, \`--no-codemap\`, \`--accept-no-plan\`, \`--semble\`, \`--repo\`, \`--keep\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Codemap auto-detection** — run after flag parsing. Behaviour differs by mode: `strict` (user explicitly passed `--codemap`) hard-fails when codemap unavailable; `auto` and `off` soft-degrade to `false` (do not abort skill):

```bash
# timeout: 5000
CODEMAP_RAW=$(cat ${TMPDIR:-/tmp}/dev-refactor-codemap-raw 2>/dev/null || echo auto)
CODEMAP_ENABLED=$("${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/codemap-resolve" "$CODEMAP_RAW")
RESOLVE_EXIT=$?
if [ "$RESOLVE_EXIT" -ne 0 ]; then
    if [ "$CODEMAP_RAW" = "strict" ]; then
        echo "! codemap unavailable but --codemap (strict) passed — aborting"
        exit 1
    fi
    # auto/off: soft degrade — continues without codemap
    echo "⚠ codemap unavailable in '$CODEMAP_RAW' mode — proceeding with CODEMAP_ENABLED=false"
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED" > ${TMPDIR:-/tmp}/dev-refactor-codemap-enabled
# codemap: integrated-via-shared
```

> loads: codemap-gates.md

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-gates.md"
```
Follow Gate A and Gate B.

**Preflight** — if `CODEMAP_ENABLED=true`:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/preflight-helpers.md"
```
Execute codemap + semble preflight if respective flags set.

## Step 1: Scope and understand

Read target code, build mental model before touching anything.

If `<target>` is directory: use Glob tool (pattern `**/*.py`, path `<target>`) to enumerate Python files.

```bash
find <target> -name '*.py' -exec wc -l {} + 2>/dev/null | tail -1
```

**If `CODEMAP_ENABLED=true` or `SEMBLE_ENABLED=true`**:

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/codemap-context.md"
```
Follow enabled sections (codemap block if `CODEMAP_ENABLED`, semble companion if `SEMBLE_ENABLED`). Skip if both false.

**Multi-file / API-change scope — extended codemap scan** (only when `CODEMAP_ENABLED=true`): if target is directory, spans multiple files, or goal mentions renaming/restructuring public API (i.e., refactoring NOT limited to internals of single function or class with unchanged public interface):

```bash
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)")  # timeout: 3000
REFACTOR_FILES=$(find <target> -name '*.py' -type f 2>/dev/null)
AFFECTED_MODULES=$(echo "$REFACTOR_FILES" | sed 's|^\./||;s|^src/||;s|\.py$||;s|/|.|g' | grep . || echo "")
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${PROJ}.json" ] && [ -n "$AFFECTED_MODULES" ]; then
    while IFS= read -r mod; do
        scan-query rdeps "$mod" 2>/dev/null
    done <<< "$AFFECTED_MODULES"
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

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/premise-grounding.md"
```
§Premise Grounding Gate. Apply using **refactor** context from Skill contexts table.

**Goal classification gate**: after sw-engineer analysis completes, scan goal text for mixed signals — if goal contains both refactor keywords (rename, extract, restructure, decouple, consolidate) AND feature keywords (add, implement, new, support), invoke `AskUserQuestion`: "Goal mixes refactoring and feature work — split into two runs." · (a) Abort — run refactor first, then feature · (b) Continue as refactor-only — treat feature additions as out of scope.

**Scope gate**: if target spans 3+ modules OR 5+ files OR goal mentions any public-API rename — flag complexity smell. Use `AskUserQuestion`: "Narrow scope (Recommended)" / "Proceed anyway".

```bash
_DEV_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" 2>/dev/null)  # timeout: 5000
cat "$_DEV_SHARED/plan-inline.md"
```
§Inline Plan Generation Protocol. Apply using **refactor** context from Skill contexts table. On proceed: set `PLAN_FILE=<path>`; continue to Step 2. On small complexity or `ACCEPT_NO_PLAN=true`: skip and continue to Step 2.

## Challenger gate

**Decision — three states** (default is NOT "skip": it runs on substantial refactors and auto-skips only small contained ones):

1. `--no-challenge` (`CHALLENGE_ENABLED=false`) → **skip gate entirely**, any size.
2. else `--challenge` (`CHALLENGE_FORCED=$(cat ${TMPDIR:-/tmp}/dev-challenge-forced 2>/dev/null || echo false)` = `true`) → **always run**, even on a small change.
3. else **default** → **run when refactor is substantial** (spans multiple files, ≳50 lines, or changes public API / an exported symbol); **auto-skip when small** (single file, ≲50 lines, no API change) — a contained refactor has little design surface to challenge.

Two flags are opposites for two regimes, which is why both exist: `--no-challenge` suppresses gate on *substantial* changes where it would otherwise fire; `--challenge` forces it on *small* changes where it would otherwise auto-skip.

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
# timeout: 600000
$PYTEST_CMD --co -q 2>&1 | head -5

SKIP_COV=0
if $PYTEST_CMD --co -q --cov=. 2>&1 | grep -q "ModuleNotFoundError\|No module named.*cov"; then
    echo "⚠ coverage tool not found — coverage gate skipped"
    SKIP_COV=1
fi

$PYTEST_CMD --co -q 2>&1 | grep -i "<module_name>" || echo "No tests found for <module_name>"

[ "${SKIP_COV}" -eq 0 ] && { $PYTEST_CMD --cov=<target_module> -q --cov-report=term-missing || true; }
```

If `SKIP_COV=1`: skip coverage classification entirely — do not classify any function as UNCOVERED; note "coverage tool absent — coverage audit skipped" in audit output. **Step 3 qa-specialist spawn behavior when `SKIP_COV=1`**: spawn qa-specialist with all public functions listed as `coverage: unknown` and instruction to write characterization tests for every public function (cannot prioritize uncovered functions when coverage unknown — test all to ensure safety net). Proceed to Step 3 with unknown coverage state.

Classify each public function/method (only when `SKIP_COV=0`):

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
# timeout: 5000
_run=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/setup_worktree.py" --sentinel refactor-team-check)
TS=$(echo "$_run" | head -1)
RUN_DIR=$(echo "$_run" | tail -1)
RUN_DIR_LITERAL="$RUN_DIR"
echo "$TS" > ${TMPDIR:-/tmp}/dev-refactor-team-ts
echo "$RUN_DIR" > ${TMPDIR:-/tmp}/dev-refactor-run-dir
trap 'rm -f ${TMPDIR:-/tmp}/refactor-team-check-$TS' EXIT
```

**IMPORTANT**: in spawn prompts below, substitute `$RUN_DIR_LITERAL` with actual resolved path before constructing each Agent call — agents receive literal resolved strings, not shell variable references. Same applies to `$TS` substitution.

**Note on `model=` assignments**: `model=opus`/`model=sonnet` in spawn prompts below are advisory hints — effective only when actual foundry agents installed. When falling back to `general-purpose` (foundry absent), prompt-prepend `model=` does not reliably override agent-resolution fallback tier; effective model set by `agent-resolution.md`'s fallback table, not spawn prompt. Intentional — sonnet sufficient for qa-specialist characterization-test task and opus for sw-engineer refactor implementation; on fallback, expect tier degradation noted in Final Report.

Serialize teammates — qa-specialist writes and gates characterization tests against **pre-refactor** source first, then sw-engineer applies refactor. Spawning sw-engineer first inverts safety net: characterization tests would be written against already-mutated code, so any behaviour change refactor introduces becomes undetectable (tests pin new behaviour instead of original). Mirrors solo Step 3 gate (`GATE OK: all characterization tests pass on unmodified code`).

**Step T1 — Spawn foundry:qa-specialist (model=sonnet) against the pre-refactor source and wait for completion**. Prompt: "You are a foundry:qa-specialist teammate refactoring: [target]. Read ~/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Your task: write characterization tests (Step 3) to build a safety net BEFORE any refactor — test the CURRENT (unmodified, pre-refactor) source and assert its existing behaviour. Scope constraint: only create/edit files under `tests/`. Do NOT edit source files. Broadcast context: {target: <path>, coverage: <summary>, goal: <stated goal>}. Compact Instructions: preserve file paths, test results, coverage numbers. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal completion in final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to $RUN_DIR_LITERAL/refactor-qa-specialist.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N,\"summary\":\"<one-line>\"}."

**Gate T1 — characterization tests must pass on unmodified code before spawning sw-engineer**. Run qa-specialist's tests (`$PYTEST_CMD <char_test_file> -v`; check exit via persisted-exit pattern in Step 3). Exit 0 → safety net green; proceed to T2. Exit ≠ 0 (including 5 — no tests collected) → no valid safety net; do NOT refactor. Invoke `AskUserQuestion` — (a) re-spawn qa-specialist with corrected assertions/path (recommended) · (b) proceed without safety net (record acceptance in `checkpoint.md`) · (c) abort.

**Step T2 — Only after Gate T1 is green, spawn foundry:sw-engineer (model=opus) to apply the refactor**. Prompt: "You are a foundry:sw-engineer teammate refactoring: [target]. Read ~/.claude/TEAM_PROTOCOL.md — use AgentSpeak v2. Your task: apply the refactoring steps (Steps 4–5: change with safety net, review). Scope constraint: only edit source files (not under `tests/`) — do NOT modify the characterization tests in `$RUN_DIR_LITERAL/refactor-qa-specialist.md`'s test file. Broadcast context: {target: <path>, coverage: <summary>, goal: <stated goal>, safety_net: $RUN_DIR_LITERAL/refactor-qa-specialist.md}. Compact Instructions: preserve file paths, test results, coverage numbers. Discard verbose tool output. Task tracking: do NOT call TaskCreate or TaskUpdate — the lead owns all task state. Signal completion in final delta message: 'Status: complete | blocked — <reason>'. Write your full analysis to $RUN_DIR_LITERAL/refactor-sw-engineer.md using the Write tool. Return ONLY compact JSON: {\"status\":\"done\",\"file\":\"<path>\",\"findings\":N,\"confidence\":0.N,\"summary\":\"<one-line>\"}."

**Gate T2 — re-run the same characterization tests against the post-refactor source**. Green→green proves refactor preserved behaviour. Any test now failing means refactor changed observable behaviour — surface with ⚠ and do NOT accept refactor until reconciled (fix source, or confirm behaviour change intended and update test deliberately).

Health monitoring (CLAUDE.md §6): re-derive `$TS` and `$RUN_DIR` at block start (bash state lost between Bash() calls — read back from temp files the spawn block persisted):

```bash
# timeout: 5000
TS=$(cat ${TMPDIR:-/tmp}/dev-refactor-team-ts 2>/dev/null || date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=$(cat ${TMPDIR:-/tmp}/dev-refactor-run-dir 2>/dev/null || echo ".temp/develop/$TS")
```

Apply to each teammate independently — create sentinel `touch ${TMPDIR:-/tmp}/refactor-team-check-$TS` before each spawn; every 5 min: `find $RUN_DIR -newer ${TMPDIR:-/tmp}/refactor-team-check-$TS -type f | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min no file activity → timed out. One extension (+5 min) if `tail -20` of output file explains delay; second unexplained stall = hard cutoff. On timeout: read `tail -100` of stalled file; surface partial results with ⏱; never omit.

After both complete: read their output files from `$RUN_DIR/`, synthesize outputs, run quality stack, produce Final Report. Exit — do not continue to Steps 3–5.

Continue to Step 3 only when `TEAM_MODE=false`.

```bash
# Compaction contract — boundary 1: after coverage audit, before characterization tests (compaction-contract.md §Lifecycle)
_DEV_DIR=$(cat "${TMPDIR:-/tmp}/dev-refactor-dev-dir" 2>/dev/null || echo "")
_PLAN_FILE=$(cat "${TMPDIR:-/tmp}/dev-plan-file" 2>/dev/null || echo "")
_KEEP=$(cat "${TMPDIR:-/tmp}/dev-refactor-keep-items" 2>/dev/null || echo "")
_PYTEST_CMD=$(cat "${TMPDIR:-/tmp}/dev-pytest-cmd" 2>/dev/null || echo "")
_PRESERVE="dev-dir=$_DEV_DIR, plan-file=${_PLAN_FILE:-none}, pytest-cmd=$_PYTEST_CMD"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: develop:refactor · phase: characterize+edit (after coverage audit)"
    echo "- run-dir: $_DEV_DIR"
    echo "- preserve: $_PRESERVE"
    echo "- next: add characterization tests (Step 3) → refactor with safety net (Step 4)"
} > .claude/state/skill-contract.md
```

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
# timeout: 600000
$PYTEST_CMD <test_file> -v; GATE_EXIT=$?
echo "$GATE_EXIT" > ${TMPDIR:-/tmp}/dev-gate-exit
```

**Gate**: all characterization tests must pass before proceeding. Check exit code from persisted file (`$?` in a fresh shell is unrelated to prior pytest run):

```bash
GATE_EXIT=$(cat ${TMPDIR:-/tmp}/dev-gate-exit 2>/dev/null || echo 1)
if [ "${GATE_EXIT}" -eq 5 ]; then
    echo "GATE FAIL: no tests collected (exit 5) — characterization test file missing or not detected by pytest; cannot proceed to Step 4 without a safety net"
elif [ "$GATE_EXIT" -ne 0 ]; then
    echo "GATE FAIL: characterization test(s) failed (exit $GATE_EXIT) — fix the test, not the code"
else
    echo "GATE OK: all characterization tests pass on unmodified code"
fi
```

If `GATE_EXIT -ne 0` (including exit 5): characterization tests missing or wrong — **cannot proceed to Step 4 without a passing safety net**. Invoke `AskUserQuestion` — "Characterization test gate failed (exit `$GATE_EXIT`). How to proceed?" · (a) **Fix test collection path / fix test assertions** (recommended — re-spawn qa-specialist with corrected path or assertions) · (b) **Proceed without safety net** (accept risk — record decision in `$DEV_DIR/checkpoint.md`) · (c) **Abort**. On (b): document explicit acceptance in `checkpoint.md` (`step: 3 — gate exit $GATE_EXIT — proceed without safety net (user accepted)`) before continuing.

## Step 4: Refactor with safety net

For each change:

1. One focused change (single responsibility per edit)
2. Run affected tests (prefer targeted over full characterization suite):
   ```bash
   scan-query test-impact "<changed_module>" 2>/dev/null
   ```
   - Non-empty `pytest_cmd` → run those tests; surface `not_covered` caveat if present; fall back to full suite if all tests pass but feel incomplete
   - Empty or unavailable → full suite:
   ```bash
   # timeout: 600000
   $PYTEST_CMD --tb=short <test_files> -v
   ```
3. Tests pass: proceed to next change
4. Tests fail: revert, try different approach

**Safety break**: track cycle count and wall time via temp files (bash state lost between Bash() calls — `$INNER_CYCLE` and `$START_TIME` declared inline are unavailable in subsequent Bash blocks; persistence is mandatory):

```bash
# timeout: 3000
echo "0"             > ${TMPDIR:-/tmp}/dev-inner-cycle
echo "$(date +%s)"   > ${TMPDIR:-/tmp}/dev-start-time
MAX_WALL_SECONDS=1800  # 30 min cap (5 outer × MAX_INNER_CYCLES worst case)
```

At each inner iteration start, read back, increment, check:

```bash
# timeout: 3000
INNER_CYCLE=$(cat ${TMPDIR:-/tmp}/dev-inner-cycle 2>/dev/null || echo 0)
START_TIME=$(cat ${TMPDIR:-/tmp}/dev-start-time 2>/dev/null || echo $(date +%s))
INNER_CYCLE=$((INNER_CYCLE+1))
echo "$INNER_CYCLE" > ${TMPDIR:-/tmp}/dev-inner-cycle
MAX_INNER_CYCLES=5  # must match constants block — bash can't ref it directly
if [ "$INNER_CYCLE" -gt $MAX_INNER_CYCLES ]; then
    echo "⚠ MAX_INNER_CYCLES ($MAX_INNER_CYCLES) reached — stopping refactor loop; report what succeeded, what broke, what remains"
fi
ELAPSED=$(( $(date +%s) - START_TIME ))
if [ "$ELAPSED" -ge 1800 ]; then
    echo "⚠ wall-time cap reached (30 min) — stopping refactor loop"
fi
```

After each change-test pair: re-read counter from temp file, increment, write back. Stop when `INNER_CYCLE > MAX_INNER_CYCLES` or elapsed ≥ `MAX_WALL_SECONDS`.

**Refactoring categories:**

- **Logic simplification**: replace complex conditionals, flatten nesting, extract helpers
- **API cleanup**: rename for clarity, consolidate parameters, add type annotations
- **Structural**: extract classes/modules, reduce coupling, apply design patterns
- **Performance**: replace loops with vectorized ops, reduce allocations, batch I/O
- **Dead code removal**: remove unused imports, unreachable branches, commented-out code; scan `_`-prefixed functions with no call sites; flag public methods absent from `__init__.py` exports

```bash
# Compaction contract — boundary 2: after refactor edits, before review stack (compaction-contract.md §Lifecycle)
_DEV_DIR=$(cat "${TMPDIR:-/tmp}/dev-refactor-dev-dir" 2>/dev/null || echo "")
_PYTEST_CMD=$(cat "${TMPDIR:-/tmp}/dev-pytest-cmd" 2>/dev/null || echo "")
_CHANGED=$(git diff --name-only HEAD 2>/dev/null | tr '\n' ' ' | sed 's/ *$//')
mkdir -p .claude/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: develop:refactor · phase: review+quality (after refactor edits applied)"
    echo "- run-dir: $_DEV_DIR"
    echo "- preserve: dev-dir=$_DEV_DIR, changed-files=$_CHANGED, pytest-cmd=$_PYTEST_CMD"
    echo "- next: review and close gaps (Step 5) → Final Report"
} > .claude/state/skill-contract.md
```

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
   # timeout: 600000
   $PYTEST_CMD --tb=short <test_files> -v 2>&1 | tail -20
   GATE_EXIT=${PIPESTATUS[0]}
   ```

4. **Objective convergence check**: if findings this cycle identical to previous cycle (same locations, same issues), declare convergence and exit — further cycles won't resolve; surface to user.

5. **Only nits remain** (variable naming, comment clarity, minor formatting): document in Follow-up, exit loop.

6. **Substantive gaps remain**: start next cycle (max 3 total).

**After 3 cycles**: substantive issues remain → stop, surface to user.

**Foundry availability check** before quality stack:

```bash
# timeout: 5000
_FOUNDRY_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null | tail -1)   # re-derive — bash state lost between Bash() calls
[ -z "$_FOUNDRY_SHARED" ] && _FOUNDRY_SHARED="plugins/foundry/skills/_shared"
[ ! -d "$_FOUNDRY_SHARED" ] || [ ! -f "$_FOUNDRY_SHARED/quality-stack.md" ] && echo "⚠ foundry plugin not installed — quality stack skipped (Branch Safety Guard, Codex Pre-pass, Progressive Review Loop, Codex Mechanical Delegation)"
```

```bash
_FOUNDRY_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_shared_resolve.py" --foundry 2>/dev/null | tail -1)
[ -z "$_FOUNDRY_SHARED" ] && _FOUNDRY_SHARED="plugins/foundry/skills/_shared"
[ -f "$_FOUNDRY_SHARED/quality-stack.md" ] && cat "$_FOUNDRY_SHARED/quality-stack.md" || echo "foundry plugin absent — quality stack skipped (Branch Safety Guard, Codex Pre-pass, Progressive Review, Codex Mechanical Delegation)"
```
If not found → skip quality stack entirely, note the message above in Final Report. Otherwise execute Branch Safety Guard, Quality Stack, Codex Pre-pass, Progressive Review Loop, and Codex Mechanical Delegation steps.

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
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [e.g., coverage tool unavailable, some tests skipped]

**Refinements**: N passes.
```

```bash
rm -f .claude/state/skill-contract.md  # clear contract — skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

</workflow>
