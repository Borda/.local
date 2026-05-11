---
name: plan
description: Interactive wizard that scans the codebase, proposes a metric/guard/agent config, and writes a program.md run spec. Also runs cProfile on a file path to surface bottlenecks before prompting for optimization goal.
argument-hint: '<goal> | <file.py> [out.md] [--team]'
effort: medium
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Wizard: scans codebase, proposes metric/guard/agent config, writes `program.md` run spec. Also runs cProfile on file path to surface bottlenecks before prompting for optimization goal.

NOT for: running experiments (use `/research:run`); methodology validation (use `/research:judge`); full pipeline from goal to result (use `/research:sweep`).

</objective>

<workflow>

<!-- Agent Resolution: canonical table at plugins/research/skills/_shared/agent-resolution.md -->

## Agent Resolution

```bash
# Locate research plugin shared dir — installed first, local workspace fallback
_RESEARCH_SHARED=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/research/*/skills/_shared 2>/dev/null | head -1)
[ -z "$_RESEARCH_SHARED" ] && _RESEARCH_SHARED="$(git rev-parse --show-toplevel 2>/dev/null)/plugins/research/skills/_shared"
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:solution-architect`, `foundry:perf-optimizer`.

## Plan Mode (Steps P-P0–P-P4)

<!-- P-P prefix = Plan-mode steps; R-prefix = Run-mode steps; these labels appear in task-tracking instructions -->

Triggered by `plan <goal|file>`. Wizard configures run.

**Task tracking**: create tasks for P-P0, P-P1, P-P2, P-P2b, P-P3 at start; add P-P4 only if `--team` detected in arguments.

### Step P-P0: Detect input type

Parse `<input>` from arguments. Determine: **file path** or **goal string**:

1. No spaces AND `test -f <argument>` succeeds → **file path**. Enter profiling flow.
2. Otherwise → **goal string**. Skip to Step P-P1.

**Profiling flow** (file path detected):

Run baseline profiling:

```bash
python3 -m cProfile -s cumtime "$ARGUMENTS" > /tmp/cprofile-out.txt 2>&1  # timeout: 60000
PROFILE_EXIT=$?
[ $PROFILE_EXIT -ne 0 ] && echo "cProfile failed (exit $PROFILE_EXIT)" && exit 1
head -40 /tmp/cprofile-out.txt  # timeout: 5000
time python3 "$ARGUMENTS"  # timeout: 60000
```

Present top 5 bottleneck functions. Ask:

```markdown
Top bottleneck functions:
1. <function> — <cumtime>s (<percentage>%)
2. <function> — <cumtime>s (<percentage>%)
...

What would you like to optimize?
  (a) Overall execution time
  (b) Memory usage
  (c) Specific function: <top function name>
  (d) Custom goal: <describe>
```

Construct goal string from selection:

- (a) → `"Reduce wall-clock execution time of <file>"`
- (b) → `"Reduce peak memory usage of <file>"`
- (c) → `"Optimize <function> in <file> (currently <time>s)"`
- (d) → user's text

Set as `<goal>`, proceed to P-P1.

### Step P-P1: Parse and scan

**Scope guard (first action)**: Before scanning, check `<goal>` is optimization goal. Input clearly not optimization goal (code question, regex/algo explanation, debug question, or any prompt without measurable improvement target) → invoke `AskUserQuestion`:

- question: "This input does not look like an optimization goal (`/research:plan` expects 'Reduce X' / 'Increase Y' / 'Improve Z metric'). How to proceed?"
- (a) label: `rephrase as optimization goal` — description: provide a revised goal with a measurable improvement target
- (b) label: `abort` — description: stop; use `/research` for explanatory questions

Stop if user selects (b). Do not proceed to P-P2 or P-P3 without a valid optimization goal.

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

Dry-run both commands before presenting (add `# timeout: 60000` to any timed bash calls — user commands may run for minutes). Failure → flag error, propose corrections. Do not proceed to P-P3 until user confirms or edits.

### Step P-P2b: Agent validation (pre-write)

After user confirms, run expert agent review before writing `program.md`. Dispatches conditional on goal type — run whichever apply in parallel.

**Pre-spawn — create plan run dir** (review files share single timestamped dir):

```bash
PLAN_RUN_DIR=".experiments/plan-$(date -u +%Y-%m-%dT%H-%M-%SZ)"  # timeout: 5000
mkdir -p "$PLAN_RUN_DIR"  # timeout: 5000
```

**Health monitoring** (CLAUDE.md §8) — create checkpoint before spawning agents:

```bash
LAUNCH_AT=$(date +%s)
CHECKPOINT="/tmp/plan-check-$LAUNCH_AT"
touch "$CHECKPOINT"  # timeout: 3000
```

Poll every 5 min: `find $PLAN_RUN_DIR -newer "$CHECKPOINT" -type f | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min. One extension (+5 min) if partial output visible. On timeout: surface partial results with ⏱, continue to P-P3 with available advisor output.

**Always** — spawn architect to validate scope coverage:

```text
Agent(subagent_type="foundry:solution-architect", prompt="Review a proposed research experiment scope.\n\nGoal: <goal>\nScope files: <scope_files>\nMetric command: <metric_cmd>\n\nCheck: (1) Do scope_files cover the components relevant to the goal? List architectural dependencies outside scope that the ideation agent would need to touch. (2) Are there shared abstractions (base classes, imports, shared state) outside scope required for changes within it?\n\nWrite your full review to `$PLAN_RUN_DIR/plan-review-architect.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"gaps\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"$PLAN_RUN_DIR/plan-review-architect.md\",\"confidence\":0.N}")
```

**If `agent_strategy = ml` or goal contains ML keywords (accuracy, loss, model, training, inference, classification, regression)** — also spawn research:scientist:

```text
Agent(subagent_type="research:scientist", prompt="Review a proposed ML experiment configuration.\n\nGoal: <goal>\nMetric command: <metric_cmd>\nAgent strategy: <agent_strategy>\n\nCheck: (1) Is the goal a well-formed ML hypothesis — falsifiable, with a concrete success criterion? (2) Could metric_cmd improve while the real goal is not achieved (Goodhart's Law)? (3) Is agent_strategy appropriate for this goal type?\n\nWrite your full review to `$PLAN_RUN_DIR/plan-review-scientist.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"issues\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"$PLAN_RUN_DIR/plan-review-scientist.md\",\"confidence\":0.N}")
```

**If `agent_strategy = perf` or goal contains performance keywords (latency, throughput, wall-clock, speed, memory, FPS)** — also spawn perf:

```text
Agent(subagent_type="foundry:perf-optimizer", prompt="Review a proposed performance experiment configuration.\n\nGoal: <goal>\nMetric command: <metric_cmd>\nGuard command: <guard_cmd>\n\nCheck: (1) Does metric_cmd measure the right performance characteristic for this goal? (2) Is guard_cmd comprehensive enough to catch regressions an ideation agent might introduce?\n\nWrite your full review to `$PLAN_RUN_DIR/plan-review-perf.md` using the Write tool.\nReturn ONLY: {\"ok\":true|false,\"issues\":[\"...\"],\"suggestions\":[\"...\"],\"file\":\"$PLAN_RUN_DIR/plan-review-perf.md\",\"confidence\":0.N}")
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
sandbox_network: none | bridge
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

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--team\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

### Step P-P4: --team flag

`--team` detected in `$ARGUMENTS`:
1. Complete Steps P-P0–P-P3 as normal — produce `program.md` with full single-researcher structure.
2. Append a `## Team Mode Notes` section to `program.md`:
   - Number of distinct method families found (used to determine team size at run step)
   - Whether SOTA consensus exists — if clear winner, note team mode may not add value
3. Tell user: "`--team` applies at run step, not plan step. Run: `/research:run <program.md> --team` to execute with parallel researchers."
4. Resolve run-modes dir, read team protocol — include a one-line summary in Team Mode Notes:

   ```bash
   _RESEARCH_RUN_MODES=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/research/*/skills/run/modes 2>/dev/null | head -1)
   [ -d "$_RESEARCH_RUN_MODES" ] || _RESEARCH_RUN_MODES="$(git rev-parse --show-toplevel 2>/dev/null)/plugins/research/skills/run/modes"
   [ -f "$_RESEARCH_RUN_MODES/team.md" ] || { echo "⚠ team.md not found at $_RESEARCH_RUN_MODES"; }
   ```

   Read `$_RESEARCH_RUN_MODES/team.md`.

</workflow>

<notes>

- **Scope boundary**: plan writes `program.md` only — methodology validation = `/research:judge`; execution = `/research:run`; full pipeline = `/research:sweep`.
- **`--team` note**: `--team` applies at the run step, not the plan step. Plan produces a standard `program.md`; the team flag is passed through when invoking `/research:run <program.md> --team`.
- **TTL exemption**: plan run directories (`.experiments/plan-<timestamp>/`) don't write `result.jsonl` — exempt from automated 30-day TTL cleanup per `.claude/rules/artifact-lifecycle.md (installed via /foundry:init)`; remove manually when no longer needed.

</notes>
