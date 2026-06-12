---
name: topic
description: "Research State of the Art (SOTA) literature for an Artificial Intelligence / Machine Learning (AI/ML) topic, method, or architecture. Finds relevant papers, builds a comparison table, recommends the best implementation strategy for the current codebase, and optionally produces a phased implementation plan mapped to the codebase. Owns broad SOTA search end-to-end via foundry:web-explorer; delegates codebase mapping to foundry:solution-architect."
argument-hint: "<topic> [--team] | plan [<output.md>]"
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, WebSearch, WebFetch, TaskCreate, TaskUpdate, AskUserQuestion, TaskList
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

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
# CLAUDE_PLUGIN_ROOT set by Claude Code to installed cache path; plugins/ fallback = source-tree only
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
[ -z "$_RESEARCH_SHARED" ] && { echo "! Plugin path resolution failed — ensure research plugin installed and CLAUDE_PLUGIN_ROOT set, or invoke from project root."; exit 1; }
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

**Unsupported flag check** (runs BEFORE any mode dispatch to catch unknown flags in all modes): follow `$_RESEARCH_SHARED/unsupported-flag-protocol.md`. Supported flags for this skill: `--team`.

```bash
# timeout: 5000
UNKNOWN_FLAGS=$(echo "$ARGUMENTS_LOWER" | grep -oE -- '--[a-z][a-z0-9-]+' | grep -v -- '--team' || true)
```

**Early dispatch for `--team` and `plan` modes** — check BEFORE Steps 2-3 to avoid wasted SOTA search compute. Priority: `--team` wins over `plan` (invocation `plan --team` → Team Mode, topic string = "plan"):

```bash
# timeout: 5000
FIRST_WORD=$(echo "$ARGUMENTS_LOWER" | awk '{print $1}')
```

- If `$ARGUMENTS_LOWER` contains `--team` flag → skip Steps 2-3; jump directly to **Team Mode** section below.
- Else if `$FIRST_WORD` equals exactly `plan` → skip Steps 2-3; jump directly to **Plan Mode** section below.

Steps 2-3 execute only when neither `--team` nor `plan` mode is detected.

## Step 2: Research & codebase check (run in parallel)

> **Parallelism scope**: 2a (Agent spawn) and 2b (Grep) issue in one response. Any WebSearch/WebFetch calls inside the researcher agent are issued sequentially — invoke all searches before synthesizing results. No mechanism exists to parallelize prose-driven searches across calls.

### 2a: SOTA literature search (issue with 2b simultaneously in one response)

Conduct broad SOTA search directly using `foundry:web-explorer` (or inline WebSearch/WebFetch if web-explorer unavailable) — topic skill owns SOTA end-to-end. Find top 5 papers for `$ARGUMENTS`, produce comparison table (method, key idea, benchmark results, compute, code availability), recommend single best method given codebase constraints from Step 1.

**Note**: do NOT dispatch to `research:scientist` for broad SOTA surveys — scientist is scoped to deep single-paper analysis with a named paper anchor. Use `research:scientist` directly only when: (a) a specific paper is identified and needs deep analysis, (b) hypothesis generation for an identified method, or (c) experiment design for a concrete approach. Broad SOTA = web-explorer territory.

Pre-compute output paths before searching:

```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
DATE=$(date +%Y-%m-%d)  # timeout: 3000
# Anti-overwrite: resolve counter-suffix (quality-gates.md rule)
AGENT_OUT=".temp/output-research-agent-$BRANCH-$DATE.md"
_N=2; while [ -e "$AGENT_OUT" ]; do AGENT_OUT=".temp/output-research-agent-$BRANCH-$DATE-$_N.md"; _N=$((_N+1)); done  # timeout: 5000
mkdir -p .temp  # timeout: 3000
echo "$BRANCH" > "${TMPDIR:-/tmp}/topic-branch"
echo "$DATE" > "${TMPDIR:-/tmp}/topic-date"
echo "$AGENT_OUT" > "${TMPDIR:-/tmp}/topic-agent-out"
```

Search targets: arXiv, Papers With Code, Semantic Scholar, HuggingFace Hub. For each of the top 5 papers found via WebSearch/WebFetch: extract method, key idea, benchmark results, compute cost, code availability. Write full findings (comparison table, paper analysis, recommendation, implementation plan, Confidence block) to `$AGENT_OUT`.

**If `foundry:web-explorer` available** (check `ls ~/.claude/plugins/cache/borda-ai-rig/foundry/*/agents/web-explorer.md 2>/dev/null`): spawn `Agent(subagent_type="foundry:web-explorer", prompt="...")` for parallel deep web research, then merge results into `$AGENT_OUT`. Otherwise conduct research inline using WebSearch and WebFetch directly.

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
Agents:      foundry:web-explorer (Step 2a, if available), foundry:solution-architect (plan mode P2)
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
# Reload from Step 2a bash block (Check 41: fresh shell per call)
BRANCH=$(cat "${TMPDIR:-/tmp}/topic-branch" 2>/dev/null || git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')
DATE=$(cat "${TMPDIR:-/tmp}/topic-date" 2>/dev/null || date +%Y-%m-%d)
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

> loads: modes/team.md  # also loads: modes/plan.md
**Mode-file existence check** — verify before reading:

```bash
_TEAM_MODE="${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/topic/modes/team.md"
[ -f "$_TEAM_MODE" ] || { echo "! MISSING — modes/team.md not found at $_TEAM_MODE. Plugin may not be fully installed. Falling back to single-agent mode."; exit 1; }
```

Also verify `~/.claude/TEAM_PROTOCOL.md` exists (each teammate spawn prompt requires it):

```bash
[ -f "$HOME/.claude/TEAM_PROTOCOL.md" ] || { echo "! MISSING — ~/.claude/TEAM_PROTOCOL.md not found. Run /foundry:setup (requires foundry plugin) to install. Falling back to single-agent mode."; exit 1; }
```

Read `"${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/topic/modes/team.md"` and execute its workflow.

**Mandatory termination gate**: after `modes/team.md` returns (consolidation complete, report written), continue to the `## Follow-up gate` section below — do NOT exit early. The `AskUserQuestion` call in `## Follow-up gate` is the only authorized terminal action for team mode; reaching the end of the team workflow without invoking it is a protocol violation.

## Plan Mode — only when first token of `$ARGUMENTS` is exactly `plan` (not a prefix match — "planning algorithms" must NOT trigger this mode)

> loads: modes/plan.md
**Mode-file existence check** — verify before reading:

```bash
_PLAN_MODE="${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/topic/modes/plan.md"
[ -f "$_PLAN_MODE" ] || { echo "! MISSING — modes/plan.md not found at $_PLAN_MODE. Plugin may not be fully installed."; exit 1; }
```

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

- Skill orchestrates — owns broad SOTA literature search end-to-end via `foundry:web-explorer`, delegates codebase mapping to `foundry:solution-architect` (plan mode). For direct hypothesis/experiment work on a named paper, use `research:scientist` directly.
- **Team Mode dependency**: `--team` requires `~/.claude/TEAM_PROTOCOL.md` to exist — each teammate spawn prompt includes `Read $HOME/.claude/TEAM_PROTOCOL.md and use AgentSpeak v2`; verify file present before launching team mode.
- **Link integrity**: All URLs cited in research report must be fetched and verified before inclusion. Use WebFetch to confirm each URL exists and says what you claim.
- Follow-up chains:
  - Research recommends method → `/research:plan` for sequenced plan (auto-detects latest output), then `/develop:feature` (requires `develop` plugin) for TDD-first implementation
  - Research integrates into existing code → `/develop:refactor` (requires `develop` plugin) first to prepare module, then `/develop:feature` (requires `develop` plugin)
  - Research reveals security concerns with dependency → run `pip-audit` or `uv run pip-audit` for Common Vulnerabilities and Exposures (CVE) scan
  - Plan approved → create `.plans/active/todo_<method>.md` with phases as task groups; start with `/develop:feature <first task from Phase 1>` (requires `develop` plugin)

</notes>
