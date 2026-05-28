---
name: plan
description: "Interactive wizard that scans the codebase, proposes a metric/guard/agent config, and writes a program.md run spec. Also runs cProfile on a file path to surface bottlenecks before prompting for optimization goal."
argument-hint: "<goal> | <file.py> [out.md] [--team]"
effort: medium
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Wizard: scans codebase, proposes metric/guard/agent config, writes `program.md` run spec. Also runs cProfile on file path to surface bottlenecks before prompting for optimization goal.

NOT for: running experiments (use `/research:run`); methodology validation (use `/research:judge`); full pipeline from goal to result (use `/research:sweep`).

</objective>

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:solution-architect`, `foundry:perf-optimizer`.

## Plan Mode (Steps P-P0–P-P4)

<!-- P-P prefix = Plan-mode steps; R-prefix = Run-mode steps; these labels appear in task-tracking instructions -->

Triggered by `plan <goal|file>`. Wizard configures run.

**Task tracking**: create tasks for P-P0, P-P1, P-P2, P-P2b, P-P3 at start; add P-P4 only if `--team` detected in arguments.

**Unsupported flag check** — strip `--team` from `$ARGUMENTS`, scan remaining tokens for any `--<token>`. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--team\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### Step P-P0: Detect input type

Parse `<input>` from arguments. Determine: **file path** or **goal string**:

First, extract first positional token (strip all `--<flag>` tokens from `$ARGUMENTS`, take first remaining token as `FILE_ARG`). Then:

**Disambiguation guard** — only treat `FILE_ARG` as a file path if it actually exists on disk. Multi-token strings ($ARGUMENTS containing spaces beyond `FILE_ARG`) are always goal text — never run `test -f` on the first token of a multi-token goal:

```bash
# Count tokens in $ARGUMENTS (excluding flags). If >1, FILE_ARG is part of a goal string.
NONFLAG_TOKEN_COUNT=$(echo "$ARGUMENTS" | tr ' ' '\n' | grep -v '^--' | grep -v '^$' | wc -l | tr -d ' ')  # timeout: 5000
```

1. `NONFLAG_TOKEN_COUNT == 1` AND `test -f "$FILE_ARG"` succeeds → **file path**. `FILE_ARG` is the script to profile. Enter profiling flow.
2. Otherwise (multi-token, or single token not on disk) → **goal string**. Use full `$ARGUMENTS` (minus flags) as `<goal>`. Skip to Step P-P1.

**Profiling flow** (file path detected):

Run baseline profiling using `FILE_ARG` only — never use raw `$ARGUMENTS` in cProfile command:

```bash
CPROFILE_OUT=$(mktemp -t research-plan-XXXX)  # timeout: 3000
python -m cProfile -s cumtime "$FILE_ARG" > "$CPROFILE_OUT" 2>&1  # timeout: 600000
PROFILE_EXIT=$?
if [ $PROFILE_EXIT -ne 0 ]; then
    echo "⚠ cProfile failed (exit $PROFILE_EXIT) — continuing without profile data."
    echo "  Wizard will prompt for an optimization goal from the goal-string path instead of bottleneck selection."
    PROFILE_AVAILABLE=false
else
    PROFILE_AVAILABLE=true
    head -40 "$CPROFILE_OUT"  # timeout: 5000
    time python "$FILE_ARG"  # timeout: 600000
fi
```

**Fallback path** — if `PROFILE_AVAILABLE=false`: skip the bottleneck selection menu; invoke `AskUserQuestion` with a single open-ended option: "Describe the optimization goal for `<file>` (cProfile data unavailable — provide goal string directly)". Use the user's response as `<goal>` and proceed to P-P1. Never hard-exit on cProfile failure — degraded mode (goal-string only) is always available.

**Profile-available path** — when `PROFILE_AVAILABLE=true`, present top 5 bottleneck functions:

```markdown
Top bottleneck functions:
1. <function> — <cumtime>s (<percentage>%)
2. <function> — <cumtime>s (<percentage>%)
...
```

Invoke `AskUserQuestion` — "What would you like to optimize?", options: (a) Overall execution time · (b) Memory usage · (c) Specific function: `<top function name>` (currently `<time>`s) · (d) Custom goal (describe).

Construct goal string from selection:

- (a) → `"Reduce wall-clock execution time of <file>"`
- (b) → `"Reduce peak memory usage of <file>"`
- (c) → `"Optimize <function> in <file> (currently <time>s)"`
- (d) → user's text

Set as `<goal>`, proceed to P-P1.

### Step P-P1: Parse and scan

**Scope guard (first action)**: Before scanning, check `<goal>` is optimization goal. Input clearly not optimization goal (code question, regex/algo explanation, debug question, any prompt without measurable improvement target) → invoke `AskUserQuestion`:

- question: "This input does not look like an optimization goal (`/research:plan` expects 'Reduce X' / 'Increase Y' / 'Improve Z metric'). How to proceed?"
- (a) label: `rephrase as optimization goal` — description: provide revised goal with measurable improvement target
- (b) label: `abort` — description: stop; use `/research` for explanatory questions

Stop if user selects (b). Do not proceed to P-P2 or P-P3 without valid optimization goal.

Parse `<goal>`. Scan codebase to detect:

- Language and framework (Python, PyTorch, pytest, etc.)
- Available test runners or benchmark scripts
- Candidate metric commands (pytest coverage, benchmark scripts, eval scripts)
- Candidate guard commands (test suite, lint, type check)
- Files relevant to goal (scope files)

### Step P-P2: Present proposed config

Present config as code block for review. Include:

```yaml
metric_cmd:      [command that prints a single numeric result]
metric_direction: higher | lower
guard_cmd:       [command that must pass (exit 0) on every kept commit]
max_iterations:  [default 20]
agent_strategy:  [auto | perf | code | ml | arch]
scope_files:     [files the ideation agent may modify]
compute:         local | colab | docker
```

Dry-run both commands before presenting (add `# timeout: 60000` to timed bash calls — user commands may run for minutes). Failure → flag error, propose corrections. Do not proceed to P-P3 until user confirms or edits.

### Step P-P2b: Agent validation (pre-write)

After user confirms, run expert agent review before writing `program.md`. Dispatch conditional on goal type — run whichever apply in parallel.

**Foundry availability check** — before dispatching any `foundry:*` agent:

```bash
_FOUNDRY_AVAILABLE=$(find ~/.claude/plugins/cache -path "*/foundry*" -name "solution-architect.md" 2>/dev/null | head -1)  # timeout: 5000
```

If `_FOUNDRY_AVAILABLE` empty: skip architecture and perf reviews entirely; print `⚠ foundry plugin not installed — skipping foundry:solution-architect and foundry:perf-optimizer reviews. Continuing without architecture/perf advisory.`; record gap in advisory block as `architect: skipped (foundry absent)`. Proceed to P-P3 with available advisor output (scientist only if ML keywords matched).

**Pre-spawn — create plan run dir** (review files share single timestamped dir):

```bash
PLAN_RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/make_run_dir.py" "plan" ".experiments" 2>/dev/null)  # timeout: 5000
```

**Health monitoring** (CLAUDE.md §6) — create one checkpoint per parallel agent so individual stalls are detectable (ADV-H16). Without per-agent checkpoints a single live agent masks two stalled ones:

```bash
# Plan-mode health constants — ADV-L19 (constants YAML not auto-exported to bash)
PLAN_TIMEOUT_SEC="${PLAN_TIMEOUT_SEC:-600}"
PLAN_MONITOR_INTERVAL="${PLAN_MONITOR_INTERVAL:-300}"
PLAN_HARD_CUTOFF="${PLAN_HARD_CUTOFF:-900}"

# Per-agent checkpoints — TMPDIR-relative, timestamp-suffixed to avoid collisions
_TS=$(date +%s)
ARCH_CHECK="${TMPDIR:-/tmp}/research-plan-arch-${_TS}"
SCI_CHECK="${TMPDIR:-/tmp}/research-plan-sci-${_TS}"
PERF_CHECK="${TMPDIR:-/tmp}/research-plan-perf-${_TS}"
touch "$ARCH_CHECK" "$SCI_CHECK" "$PERF_CHECK"  # timeout: 3000

# Helper checkpoints from health_monitor_start.py — retained for LAUNCH_AT bookkeeping
_HM=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health_monitor_start.py" "plan" 2>/dev/null)  # timeout: 5000
LAUNCH_AT=$(echo "$_HM" | grep '^LAUNCH_AT=' | cut -d= -f2)
```

Poll each checkpoint independently every `$PLAN_MONITOR_INTERVAL` seconds:

- Architect: `find "$PLAN_RUN_DIR" -name "plan-review-architect.md" -newer "$ARCH_CHECK" | wc -l`
- Scientist: `find "$PLAN_RUN_DIR" -name "plan-review-scientist.md" -newer "$SCI_CHECK" | wc -l`
- Perf: `find "$PLAN_RUN_DIR" -name "plan-review-perf.md" -newer "$PERF_CHECK" | wc -l`

Zero hits for any agent = that agent stalled (independent of others). Hard cutoff: `$PLAN_HARD_CUTOFF` (15 min). One extension (+5 min) per agent if partial output visible in its own review file. On per-agent timeout: surface partial results with ⏱, continue to P-P3 with the remaining advisor output.

**Always** — spawn architect to validate scope coverage. Before constructing the Agent() call, substitute the actual computed value of `$PLAN_RUN_DIR` into the prompt string (e.g. `.experiments/plan-2026-05-13T10-00-00Z`):

```text
Agent(subagent_type="foundry:solution-architect", prompt="Review a proposed research experiment scope.\n\nGoal: <goal>\nScope files (newline-separated paths in a markdown code block):\n```\n<scope_files — one path per line>\n```\nMetric command: <metric_cmd>\n\nCheck: (1) Do scope_files cover the components relevant to the goal? List architectural dependencies outside scope that the ideation agent would need to touch. (2) Are there shared abstractions (base classes, imports, shared state) outside scope required for changes within it?\n\nWrite your full review to `<PLAN_RUN_DIR>/plan-review-architect.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"gaps\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"<PLAN_RUN_DIR>/plan-review-architect.md\",\"confidence\":0.N}")
```

**If `agent_strategy = ml` or goal contains ML keywords (accuracy, loss, model, training, inference, classification, regression)** — also spawn research:scientist. Substitute computed `$PLAN_RUN_DIR` before spawning:

```text
Agent(subagent_type="research:scientist", prompt="Review a proposed ML experiment configuration.\n\nGoal: <goal>\nMetric command: <metric_cmd>\nAgent strategy: <agent_strategy>\n\nCheck: (1) Is the goal a well-formed ML hypothesis — falsifiable, with a concrete success criterion? (2) Could metric_cmd improve while the real goal is not achieved (Goodhart's Law)? (3) Is agent_strategy appropriate for this goal type?\n\nWrite your full review to `<PLAN_RUN_DIR>/plan-review-scientist.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"issues\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"<PLAN_RUN_DIR>/plan-review-scientist.md\",\"confidence\":0.N}")
```

**If `agent_strategy = perf` or goal contains performance keywords (latency, throughput, wall-clock, speed, memory, FPS)** — also spawn perf. Substitute computed `$PLAN_RUN_DIR` before spawning:

```text
Agent(subagent_type="foundry:perf-optimizer", prompt="Review a proposed performance experiment configuration.\n\nGoal: <goal>\nMetric command: <metric_cmd>\nGuard command: <guard_cmd>\n\nCheck: (1) Does metric_cmd measure the right performance characteristic for this goal? (2) Is guard_cmd comprehensive enough to catch regressions an ideation agent might introduce?\n\nWrite your full review to `<PLAN_RUN_DIR>/plan-review-perf.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"issues\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"<PLAN_RUN_DIR>/plan-review-perf.md\",\"confidence\":0.N}")
```

Print advisory block below config:

```text
Advisory review:
  architect: <gaps or "scope looks complete">
  scientist:  <issues or "hypothesis is well-formed">   [only if dispatched]
  perf:       <issues or "metric/guard look valid">      [only if dispatched]
```

Any agent returns `ok: false` → surface suggestions, ask user: revise config (re-enter P-P2) or proceed. Do not block — user decides.

### Step P-P3: Write program.md

Output path: second argument after `<goal>` if provided, else `program.md` at project root.

**Overwrite check**: path exists → print one-line warning, `AskUserQuestion`: (a) Overwrite — proceed; (b) Abort — stop. No silent overwrite.

Write file using canonical template, pre-populated from wizard findings:

````markdown
# Program: <title from goal>

## Goal
<one-paragraph description of what to improve and why>

## Metric
```yaml
command: <metric_cmd from wizard>
direction: higher | lower
target: <optional numeric goal — campaign stops when crossed>
```

## Guard
```yaml
command: <guard_cmd from wizard>
```

## Config
```yaml
max_iterations: 20
agent_strategy: auto | perf | code | ml | arch
scope_files:
  - <path or glob>
compute: local | colab | docker
colab_hw: # optional: H100 | L4 | T4 | A100 (used when compute: colab)
sandbox_network: none | bridge  # ⚠ not validated by judge.md C-checks — manually verify before running
```

## Notes
<optional free-form text — strategy hints, context, known constraints — ignored by the skill>
````

Print:

```text
✓ Program saved to <OUTPUT_PATH>

Next steps:
  /research:judge <OUTPUT_PATH>   ← validate plan before running (recommended)
  /research:run <OUTPUT_PATH>     ← start iteration loop directly
```

### Step P-P4: --team flag

`--team` detected in `$ARGUMENTS`:
1. Complete Steps P-P0–P-P3 as normal — produce `program.md` with full single-researcher structure.
2. Append `## Team Mode Notes` section to `program.md`:
   - Number of distinct method families found (determines team size at run step)
   - Whether SOTA consensus exists — if clear winner, note team mode may not add value
3. Tell user: "`--team` applies at run step, not plan step. Run: `/research:run <program.md> --team` to execute with parallel researchers."
4. Resolve run-modes dir, read team protocol — include one-line summary in Team Mode Notes:

   ```bash
   _RESEARCH_RUN_MODES=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/research/*/skills/run/modes 2>/dev/null | head -1)
   [ -d "$_RESEARCH_RUN_MODES" ] || _RESEARCH_RUN_MODES="$(git rev-parse --show-toplevel 2>/dev/null)/plugins/research/skills/run/modes"
   [ -f "$_RESEARCH_RUN_MODES/team.md" ] || { echo "⚠ team.md not found at $_RESEARCH_RUN_MODES"; }
   ```

   Read `$_RESEARCH_RUN_MODES/team.md`.

</workflow>

<notes>

- **Scope boundary**: plan writes `program.md` only — methodology validation = `/research:judge`; execution = `/research:run`; full pipeline = `/research:sweep`.
- **`--team` note**: `--team` applies at run step, not plan step. Plan produces standard `program.md`; pass flag when invoking `/research:run <program.md> --team`.
- **TTL exemption**: plan run dirs (`.experiments/plan-<timestamp>/`) don't write `result.jsonl` — exempt from 30-day TTL cleanup per `.claude/rules/artifact-lifecycle.md` (installed via `/foundry:setup` — requires `foundry` plugin); remove manually when no longer needed.

</notes>
