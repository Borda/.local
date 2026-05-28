---
name: topic
description: "Research State of the Art (SOTA) literature for an Artificial Intelligence / Machine Learning (AI/ML) topic, method, or architecture. Finds relevant papers, builds a comparison table, recommends the best implementation strategy for the current codebase, and optionally produces a phased implementation plan mapped to the codebase. Delegates deep analysis to the research:scientist agent and codebase mapping to foundry:solution-architect."
argument-hint: "<topic> [--team] | plan [<output.md>]"
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, WebSearch, WebFetch, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
effort: medium
---

<objective>

Research AI/ML topic literature. Return actionable findings: SOTA methods, best fit, concrete implementation plan. Skill = orchestrator — gathers codebase context, delegates literature search to researcher agent, packages results into structured report.

NOT for deep single-paper analysis or experiment design — use `research:scientist` directly for hypothesis generation, ablation design, experiment validation.

</objective>

<inputs>

- **$ARGUMENTS**: one of:
  - `<topic>` — topic, method name, or problem description (e.g. "object detection for small objects", "efficient transformers", "self-supervised pretraining for medical images")
  - `plan` — produce phased implementation plan from most recent research output (auto-detected from `.temp/`)
  - `plan <path-to-output.md>` — produce plan from specific existing research output file
  - `--team` — multi-agent mode; spawns 2–3 researcher teammates for topics with 3+ competing method families and no SOTA consensus; ~7× token cost vs single-agent mode

</inputs>

<constants>

HARD_CUTOFF: 900   # 15 min — if researcher does not return, surface partial results from .temp/
# Agent calls are synchronous — timeout is handled by Claude Code's native call timeout; no manual extension possible.
# Deviation from §8: Agent tool is synchronous; no file-activity poll available; timeout enforced by HARD_CUTOFF only

</constants>

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
# CLAUDE_PLUGIN_ROOT set by Claude Code to installed cache path; plugins/ fallback = source-tree only
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:solution-architect`.

**Task hygiene**: Before creating tasks, call `TaskList`. For each found task:

- status `completed` if work clearly done
- status `deleted` if orphaned / no longer relevant
- keep `in_progress` only if genuinely continuing

**Task tracking**: per CLAUDE.md, create tasks (TaskCreate) for each major phase — paper collection, researcher analysis, report generation. Mark in_progress/completed throughout.

## Step 1: Understand the codebase context

Read current project before searching, extract constraints:

- Framework (PyTorch, JAX, TensorFlow, scikit-learn)?
- Task (classification, detection, generation, regression)?
- Constraints (latency, memory, dataset size, compute budget)?

**Case-insensitive flag/mode normalization** — normalize before parsing so `--PLAN`, `--Team`, `Plan`, etc. are accepted:

```bash
ARGUMENTS_LOWER=$(echo "$ARGUMENTS" | tr '[:upper:]' '[:lower:]')
```

Use `$ARGUMENTS_LOWER` for all flag/mode dispatch checks (`--team`, `--plan`, leading `plan` token); preserve original `$ARGUMENTS` only where literal substitution into prompts is required (e.g. topic string).

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS_LOWER` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--team\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Early dispatch for `--team` and `plan` modes** — check BEFORE Steps 2-3 to avoid wasted SOTA search compute:

- If `$ARGUMENTS_LOWER` starts with `plan` token (first word is exactly `plan`) → skip Steps 2-3; jump directly to **Plan Mode** section below.
- If `$ARGUMENTS_LOWER` contains `--team` flag → skip Steps 2-3; jump directly to **Team Mode** section below.

Steps 2-3 execute only when neither `--team` nor `plan` mode is detected.

## Step 2: Research & codebase check (run in parallel)

> **Parallelism scope**: 2a (Agent spawn) and 2b (Grep) issue in one response. Any WebSearch/WebFetch calls inside the researcher agent are issued sequentially — invoke all searches before synthesizing results. No mechanism exists to parallelize prose-driven searches across calls.

### 2a: Spawn researcher agent (issue with 2b simultaneously in one response)

Call `Agent(subagent_type="research:scientist", prompt=...)`. Task researcher: find top 5 papers for `$ARGUMENTS`, produce comparison table (method, key idea, benchmark results, compute, code availability), recommend single best method given codebase constraints from Step 1 — with brief implementation plan. Agent's own workflow handles research and experiment design details.

Use this prompt scaffold (adapt constraints from Step 1):

Note: pre-compute output paths before spawning — orchestrator must extract branch and evaluate date expressions, then substitute concrete paths into all spawn prompts:

```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main') # timeout: 3000
DATE=$(date +%Y-%m-%d)  # timeout: 3000
# Anti-overwrite: resolve counter-suffix before spawn (quality-gates.md rule)
AGENT_OUT=".temp/output-research-agent-$BRANCH-$DATE.md"
_N=2; while [ -e "$AGENT_OUT" ]; do AGENT_OUT=".temp/output-research-agent-$BRANCH-$DATE-$_N.md"; _N=$((_N+1)); done  # timeout: 5000
mkdir -p .temp  # timeout: 3000
```

**Note**: Substitute pre-computed values — do not pass raw $(date) expressions into spawn prompts. Substitute resolved `$AGENT_OUT` path (not template) so agent writes to correct non-conflicting file.

```text
Research the literature on: <$ARGUMENTS>
Codebase constraints: <framework, Python version, compute budget, existing dependencies from Step 1>
Deliver: comparison table (method, key idea, benchmarks, compute, code available), recommendation for best method, a 3-step implementation plan for this codebase, key hyperparameters (name, typical range, what it controls) for the recommended method, and common gotchas (failure modes and how to avoid them).
Write your full findings (comparison table, paper analysis, recommendation, implementation plan, Confidence block) to `<$AGENT_OUT>` using the Write tool.
Then return ONLY a compact JSON envelope on your final line — nothing else after it:
{"status":"done","papers":N,"recommendation":"<method name>","file":"<$AGENT_OUT>","confidence":0.N}
```

**Health monitoring** — Agent tool synchronous; Claude awaits researcher response natively (no Bash checkpoint available). If researcher doesn't return within `$HARD_CUTOFF` seconds (~15 min), use Read tool to surface partial results from `.temp/`, continue with what found; mark timed-out agents with ⏱ in report.
<!-- Deviation from CLAUDE.md §6: Agent(...) calls are synchronous — no Bash checkpoint/poll available; HARD_CUTOFF constant is sole liveness mechanism. Documented in <constants> block. -->

**If Agent tool unavailable** (running as subagent where nested spawning blocked), skip Agent call, conduct research inline: use WebSearch and WebFetch to find top 5 papers, synthesize comparison table yourself. Notify user: "Note: researcher agent could not be spawned in this context — conducting research inline."

### 2b: Check for existing implementations (main context)

Use Grep tool to search codebase for existing related code:

- Pattern: `$ARGUMENTS` (treat as literal string — if `$ARGUMENTS` contains regex metacharacters like `.`, `*`, `+`, `?`, `(`, `)`, `[`, `]`, `\\`, escape them via `grep -F` semantics, OR escape each metachar with `\\` before passing to Grep tool)
- Glob: `**/*.py`
- Output mode: `files_with_matches`
- Limit to 1000 results (per external-data.md — never cap at default 10)

## Step 3: Report

```markdown
---
Research — [topic]
Date:        [YYYY-MM-DD]
Scope:       [topic / research question]
Focus:       SOTA literature research
Agents:      research:scientist (Step 2a), foundry:solution-architect (plan mode P2)
Outcome:     EXPLORATORY | PROMISING | CONSENSUS
Best method: [recommended approach / architecture]
Papers:      [N papers analyzed]
Confidence:  [aggregate score] — [key gaps]
Next steps:  /research:topic plan → /develop:feature (requires `develop` plugin)
Path:        → .reports/research/topic-<branch>-<date>.md
---

## Research: $ARGUMENTS

### SOTA Overview
[2-3 sentence summary of the current state of the field]

### Method Comparison
| Method | Key Idea | SOTA Result | Compute | Code Available |
|--------|----------|-------------|---------|----------------|
| ...    | ...      | ...         | ...     | Yes/No + link  |

### Recommendation
**Use [method]** because [specific reason matching the current codebase constraints].

### Implementation Plan
1. [step with file/component to change]
2. [step]
3. [step]

### Key Hyperparameters
- [param]: [typical range] — [what it controls]

### Gotchas
- [common failure mode and how to avoid it]

### Integration with Current Codebase
- Files to modify: [list with file:line references]
- New dependencies needed: [package versions]
- Estimated effort: [hours/days]
- Risk assessment: [what could go wrong during integration]

### References
- [Paper title] ([year]) — [link]

### Agent Confidence
<!-- One row per spawned agent; team mode: 2–3 rows -->
<!-- Emit only rows for agents actually spawned — omit researcher-2 and researcher-3 rows in single-agent mode -->
| Agent | Score | Gaps |
|---|---|---|
| researcher-1 | [score] | [gaps] |
| researcher-2 | [score] | [gaps] |
| researcher-3 _(team mode only)_ | [score] | [gaps] |
```

```bash
mkdir -p .reports/research  # timeout: 3000
# Anti-overwrite counter-suffix loop (per quality-gates.md output routing rule)
BASE=".reports/research/topic-$BRANCH-$DATE.md"; REPORT_OUT="$BASE"; COUNT=2
while [ -f "$REPORT_OUT" ]; do REPORT_OUT="${BASE%.md}-${COUNT}.md"; COUNT=$((COUNT+1)); done  # timeout: 5000
```

Write full report to `$REPORT_OUT` using Write tool (resolved by counter-suffix loop above) — **do not print full report to terminal**.

Print compact terminal summary:

```text
---
Research — [topic]
SOTA:        [1–2 sentence summary of current landscape]
Best method: [recommended approach / architecture]
Key papers:  [top 2–3 papers with year]
Gaps:        [what the research couldn't cover or needs runtime validation]
Confidence:  [aggregate score] — [key gaps]
→ saved to .reports/research/topic-$BRANCH-$DATE.md
---
```

End response with `## Confidence` block per CLAUDE.md output standards.

## Team Mode — only when `--team` flag present

# loads: modes/team.md
Read `"${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/topic/modes/team.md"` and execute its workflow.

**Mandatory termination gate**: after `modes/team.md` returns (consolidation complete, report written), continue to the `## Follow-up gate` section below — do NOT exit early. The `AskUserQuestion` call in `## Follow-up gate` is the only authorized terminal action for team mode; reaching the end of the team workflow without invoking it is a protocol violation.

## Plan Mode — only when first token of `$ARGUMENTS` is exactly `plan` (not a prefix match — "planning algorithms" must NOT trigger this mode)

# loads: modes/plan.md
Read `"${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/topic/modes/plan.md"` and execute its workflow.

**Mandatory termination gate**: after `modes/plan.md` returns (phased plan emitted, report written), continue to the `## Follow-up gate` section below — do NOT exit early. The `AskUserQuestion` call in `## Follow-up gate` is the only authorized terminal action for plan mode; reaching the end of the plan workflow without invoking it is a protocol violation.

## Follow-up gate

Call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "What next?"
- (a) label: `/research:plan` — description: design a research program from these findings
- (b) label: `/develop:feature` — description: implement based on findings (requires `develop` plugin)
- (c) label: `skip` — description: no action

</workflow>

<notes>

- Skill orchestrates — gathers context, delegates research to `research:scientist` and codebase mapping to `foundry:solution-architect` (plan mode). For direct hypothesis/experiment work, use `research:scientist` directly.
- **Team Mode dependency**: `--team` requires `~/.claude/TEAM_PROTOCOL.md` to exist — each teammate spawn prompt includes `Read $HOME/.claude/TEAM_PROTOCOL.md and use AgentSpeak v2`; verify file present before launching team mode.
- **Link integrity**: All URLs cited in research report must be fetched and verified before inclusion. Use WebFetch to confirm each URL exists and says what you claim.
- Follow-up chains:
  - Research recommends method → `/research:plan` for sequenced plan (auto-detects latest output), then `/develop:feature` (requires `develop` plugin) for TDD-first implementation
  - Research integrates into existing code → `/develop:refactor` (requires `develop` plugin) first to prepare module, then `/develop:feature` (requires `develop` plugin)
  - Research reveals security concerns with dependency → run `pip-audit` or `uv run pip-audit` for Common Vulnerabilities and Exposures (CVE) scan
  - Plan approved → create `.plans/active/todo_<method>.md` with phases as task groups; start with `/develop:feature <first task from Phase 1>` (requires `develop` plugin)

</notes>
