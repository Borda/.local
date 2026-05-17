---
name: distill
description: "One-time snapshot extracting patterns from work history and accumulated lessons, distills into concrete improvements — new agent/skill suggestions, roster quality review, memory pruning, or consolidating lessons and feedback into rules and agent/skill updates."
argument-hint: '[review | prune | lessons | "external <url-or-path>" | "<recurring task description>"]'
disable-model-invocation: true
allowed-tools: Read, Edit, Bash, Glob, Grep, Write, AskUserQuestion, Agent, WebFetch, TaskCreate, TaskUpdate, TaskList
when_to_use: "Run periodically (e.g., monthly) or after a burst of corrections to extract patterns and distill improvements — new agent/skill suggestions, roster gaps, memory pruning, lesson consolidation. NOT for single-file agent/skill edits (use /foundry:manage) or config quality auditing (use /foundry:audit)."
---

<objective>

Analyze how Claude Code is used and surface concrete improvements — new agents/skills to reduce repetition, or consolidate lessons into governance files (rules, agent instructions, skill updates) — without duplicating what exists.

NOT for single-file edits or quality checks — see `when_to_use`.

</objective>

<inputs>

- **$ARGUMENTS**: optional. Four modes:
  - Omitted — analyze existing patterns and agents; generate suggestions proactively.
  - `review` — review existing agent/skill roster for quality and gaps without suggesting new additions.
  - `prune` — evaluate project memory file for stale, redundant, or verbose entries and apply trimmed version.
  - `lessons` — read `.notes/lessons.md` and memory feedback files, distill recurring patterns into proposed rule files, agent instruction updates, and skill workflow changes.
  - `external <source>` — analyse external plugin, skill, or agentic resource and produce structured adoption proposal. `<source>` is URL, file path, or local directory.
  - Description of recurring task — use description as context when generating suggestions (e.g. "I keep doing X manually").

</inputs>

<workflow>

**Task hygiene**:
```bash
_FS=$("${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/find-foundry-shared.sh" 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
```
Read `$_FS/task-hygiene.md` — follow task hygiene protocol.

## Step 1: Inventory existing agents and skills

Use Glob tool to enumerate agents and skills across all sources — project-local AND plugin-namespaced — to avoid false-gap findings when candidate already exists in plugin:

- **Project-local**: pattern `agents/*.md`, path `.claude/`; pattern `skills/*/SKILL.md`, path `.claude/`
- **Plugin source** (workspace): pattern `*/agents/*.md`, path `plugins/`; pattern `*/skills/*/SKILL.md`, path `plugins/`
- **Installed plugin cache** (if accessible): resolve cache root — `PLUGIN_CACHE=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | sort -Vr | head -1)` — then use Glob tool on `$PLUGIN_CACHE` for pattern `*/agents/*.md` and `*/skills/*/SKILL.md`

For each agent/skill found, extract: name, description, tools, purpose. Tag each entry with plugin namespace (e.g. `foundry:sw-engineer`, `oss:resolve`) — used in Step 3 gap analysis to prevent recommending duplicates of plugin-namespaced agents/skills.

## Step 2: Analyze work patterns

**If `$ARGUMENTS` is `prune`**: skip Steps 2–5 entirely and go to "Mode: Memory Pruning" below.

**If `$ARGUMENTS` is `lessons`**: skip Steps 2–5 entirely and go to "Mode: Lessons Distillation" below.

**If `$ARGUMENTS` is `review`**: skip git analysis below and go directly to Step 3 (Gap analysis). Use agent/skill descriptions from Step 1 as sole input — goal is to assess quality and coverage of existing roster, not look for new patterns in recent work. In Step 5, suppress all "Recommend: New Agent/Skill" sections and output only "Existing Coverage", "Recommend: Enhance Existing", and "No Action Needed" entries.

Otherwise, look for signals of repetitive or specialist work. First three git commands are independent — run in parallel:

```bash
# timeout: 3000
# --- run these three in parallel ---

# Recent git history — what kinds of changes are common?
git log --oneline -50

# What file types are being worked on?
git log --name-only --pretty="" -30 | sort | uniq -c | sort -rn | head -20

# Commit message patterns — what verbs appear most?
git log --oneline -100 | cut -d' ' -f2 | sort | uniq -c | sort -rn | head -15
```

Then use Glob tool (pattern `todo_*.md`, path `.plans/active/`) to list active task files; read each with Read tool. Also read `.notes/lessons.md` (if exists) for task history and conversation hints.

If `$ARGUMENTS` provided, use as additional context for pattern analysis.

### Frequency Heuristics

- **3+ occurrences** of pattern in recent history → candidate for automation
- **2+ different projects** using same manual process → cross-project skill
- **significant manual effort** per occurrence (subjective — use git history context) → high-value automation target
- **Domain-specific knowledge** required → candidate for specialist agent (not just skill)

## Step 3: Gap analysis

> **`review` mode**: focus on agent/skill quality and coverage gaps — skip "Recommend: New Agent/Skill" analysis and focus on "Existing Coverage" and "Recommend: Enhance Existing".

For each identified pattern, check:

1. **Already covered?** — search existing agent/skill descriptions for overlap
2. **Frequent enough?** — recurring ≥ 3 times or clearly domain-specialized (See Step 2 heuristics — combine ≥3 occurrences with effort/frequency signals from Steps 1–2)
3. **Would specialist add quality?** — does it require deep domain knowledge?
4. **Too narrow?** — single-use task doesn't warrant persistent agent

Thresholds for recommendation:

- **New agent**: recurring specialist role, complex decision-making, 5+ distinct capabilities
- **New skill**: workflow orchestration, multi-step process with fixed structure
- **No new file needed**: one-off or already covered by existing agent

## Step 4: Check for duplication

> **`review` mode**: duplication checks still apply — review mode does not skip this step.

Before recommending anything, run overlap check and anti-pattern checklist:

```markdown
For each candidate agent/skill:
- Does any existing agent cover >50% of its scope? → enhance existing instead
- Is the name/description confusingly similar to an existing one? → rename existing
```

Anti-pattern checklist — reject candidate if any apply:

1. **Role vs task confusion**: agents are roles, not tasks. Do not create agent for every different topic.
2. **Near-duplicate**: candidate duplicates existing agent with slightly different name. Enhance existing instead.
3. **Thin wrapper**: candidate skill just calls one agent with fixed args. Not enough value to justify new skill file. Exception: skills that add measure-first/measure-after bookends, multi-mode dispatch across 3+ agents, or safety breaks (retry limits, validation gates) justify wrapper even if only one agent executes for given invocation.

## Step 5: Report

```markdown
## Agent/Skill Suggestions

### Existing Coverage (no gaps found)
- [agent/skill]: covers [pattern] well — no new file needed

### Recommend: New Agent — [name]
**Trigger**: [what recurring pattern or gap justifies this]
**Gap**: [what existing agents don't cover]
**Scope**: [what it would do — 3-5 bullet points]
**Suggested tools**: [Read, Write, Edit, Bash, etc.]
**Draft description**: "[one-line description for frontmatter]"

### Recommend: New Skill — [name]
**Trigger**: [what repetitive workflow justifies this]
**Gap**: [why existing skills don't cover it]
**Scope**: [what workflow steps it would orchestrate]
**Draft description**: "[one-line description for frontmatter]"

### Recommend: Enhance Existing — [agent/skill name]
**Add**: [specific capability missing from current version]
**Why**: [what recurring task would benefit]

### No Action Needed
[pattern]: already handled by [existing agent/skill]

## Confidence
**Score**: [0.N]
**Gaps**: [e.g., git history too shallow, task files not present, descriptions too generic to compare]

**Refinements**: N passes. [Pass 1: <what improved>. Pass 2: <what improved>.] — omit if 0 passes
```

## Mode: Memory Pruning — only when `$ARGUMENTS == "prune"`

Locate, evaluate, and trim project memory file.

**Find memory file:**

<!-- Note: if the auto-memory path convention changes, update this slug derivation. -->

```bash
# timeout: 3000
PROJECT="$(git rev-parse --show-toplevel)"
MEMORY_FILE="$HOME/.claude/projects/$(echo "$PROJECT" | sed 's|[/.]|-|g')/memory/MEMORY.md"
[ -f "$MEMORY_FILE" ] || { echo "MEMORY_FILE not found at $MEMORY_FILE — skipping memory analysis"; exit 0; }
echo "Memory file located."
```

Read memory file with Read tool. Also read `.claude/CLAUDE.md` to identify overlap — anything already covered in CLAUDE.md need not live in memory.

**Evaluate each section against these criteria:**

- **Drop**: content no longer accurate (removed features, resolved one-time issues, superseded decisions), or fully duplicated in CLAUDE.md
- **Trim**: sections still accurate but containing implementation history or rationale no longer needed day-to-day — keep operational facts (what/where), drop why-it-was-built backstory
- **Keep**: rules actively applied every session; project-specific facts absent from CLAUDE.md; anything model needs to act correctly

**Memory-write gate** — project CLAUDE.md `Memory Policy` prohibits auto-writes to MEMORY.md. Prune mode runs read-only by default and produces advisory diff/report rather than applying edits silently:

**P1**: Read memory file and analyse for stale, redundant, and verbose entries.

**P2**: Print proposed prune report to terminal (sections to drop + sections to trim, with line ranges and reasoning):

   ```text
   Prune proposals (apply manually unless explicitly approved below):
     Drop  — <section name>: <reason>
     Trim  — <section name>: <what to remove vs keep>
     ...
   ```

**P3**: Call `AskUserQuestion` — do NOT write question as plain text. Map options directly into tool call:
   - question: "Apply prune edits to MEMORY.md?"
   - (a) label: `Apply now` — description: use Edit tool to apply all proposals to memory file
   - (b) label: `Show diff first` — description: print line-by-line preview before applying any change
   - (c) label: `Skip` — description: leave MEMORY.md untouched; user will edit manually

Only after user picks (a) (or (b) followed by approval) may Edit be invoked on memory file. **Never apply prune edits silently.**

Print compact summary after applying (or after user declines):

```text
Pruned MEMORY.md — <date>
  Dropped: N sections — [names]
  Trimmed: N sections — [names]
  Kept:    N sections unchanged
  Saved:   ~N lines
```

End response with `## Confidence` block per CLAUDE.md output standards.

## Mode: Lessons Distillation — only when `$ARGUMENTS == "lessons"`

Read accumulated lessons and feedback, identify patterns to promote into durable governance — rule files, agent instruction updates, or skill workflow changes.

**Step L1: Collect raw material**

Find and read all source material in parallel:

Use Read tool on `.notes/lessons.md` (skip if file not found). Derive MEMORY_DIR via canonical snippet:
```bash
PROJECT="$(git rev-parse --show-toplevel)"  # timeout: 3000
MEMORY_DIR="$HOME/.claude/projects/$(echo "$PROJECT" | sed 's|[/.]|-|g')/memory"
```
Then use Glob tool with pattern `feedback_*.md` in `$MEMORY_DIR` to list feedback files; read each with Read tool. Also read `.claude/rules/` (Glob `rules/*.md`, path `.claude/`) to understand what's already captured as rule.

**Step L2: Cluster and classify**

Group all lessons/feedback entries by domain. Use model reasoning to identify clusters of related items:

- **Git & commit discipline** (staging, branching, commit messages, push safety)
- **Testing & QA** (test patterns, mocking rules, coverage gaps)
- **Task management** (TaskCreate/TaskUpdate lifecycle, when to create tasks, when to mark complete, orchestrator vs. teammate task ownership)
- **Agent & skill config** (agent instructions, skill workflow, CLAUDE.md additions — excluding task tracking)
- **Communication & output** (tone, format, reporting)
- **Tool & permission use** (Bash vs native tools, settings.json)
- **Other** (project-specific, one-off)

For each lesson entry, classify disposition:

| Disposition | Meaning |
| --- | --- |
| `→ rule` | Recurring enough to warrant standalone `.claude/rules/<name>.md` file |
| `→ agent update` | Specific to one agent's instructions — edit that agent's `.md` file |
| `→ skill update` | Specific to one skill's workflow — edit that skill's `SKILL.md` |
| `→ already covered` | Already present verbatim (or near-verbatim) in existing rule, agent, or CLAUDE.md |
| `→ too narrow` | One-off, project-specific, or not generalizable — keep in memory only |

Thresholds:

- **`→ rule`**: 2+ distinct lessons on same topic, or single lesson applying across ≥3 agents/skills
- **`→ agent/skill update`**: lesson applies specifically to one file's behavior and not yet there
- **`→ already covered`**: exact principle including scope already in target file — mark and skip. Before marking, verify scope matches: same terminology does not imply same scope. If the lesson adds conditions not in the existing rule (new agent population, new trigger context, new edge case), classify as `→ rule` or `→ agent/skill update` instead.

**Duplicate detection**: Before finalizing proposals, scan all lessons for identical insights expressed with different wording. When two or more lessons reduce to the same principle, consolidate into one entry — do not propose separate changes for duplicate lessons. Flag the consolidation explicitly in the proposals table.

**Contradiction detection**: If two lessons make mutually exclusive claims about the same topic, flag both with ⚠ CONTRADICTION and do not classify either as → rule or → agent/skill update. Surface to user for resolution.

**Step L3: Generate proposals**

Produce structured proposal table. Do not apply anything yet — report first.

````markdown
## Lessons Distillation Proposals

### Summary
- Source files read: N (.notes/lessons.md + N feedback files)
- Total lessons: N
- Clusters: N domains

### Proposals

| # | Cluster | Lesson (condensed) | Disposition | Target |
|---|---------|-------------------|-------------|--------|
| 1 | Git | Never use git add -A; stage specific files | → already covered | rules/git-commit.md |
| 2 | Agent config | Agent description must include NOT-for clause | → rule | add to existing rule: rules/foundry-config.md |
| 3 | Communication | Flag blockers before starting, not mid-task | → already covered | rules/communication.md |

### New Rule Files Proposed (N)

#### rules/<name>.md
**Cluster**: [domain]
**Lessons consolidated**: [list lesson IDs, e.g., L1, L3, L7]
**Draft content**:
```markdown

## description: [one-line]

## [Rule heading]

[content distilled from the lessons]

```
**Why a rule file**: [applies broadly across agents/skills, not specific to one]

### Agent Instruction Updates Proposed (N)

#### agents/<name>.md
**Change**: [what to add/modify in the agent's instructions]
**Lesson source**: [which lesson(s) justify this]

### Skill Workflow Updates Proposed (N)

#### skills/<name>/SKILL.md
**Change**: [what step/note to add or modify]
**Lesson source**: [which lesson(s) justify this]

### Already Covered (N) — no action needed
- L2: [lesson] → already in [file]

### Too Narrow (N) — keep in memory
- L5: [lesson] → one-off, not generalizable
````

**Agent/skill name verification**: For each → agent update and → skill update row, verify: (1) proposed target file/agent name matches the lesson content — if lesson mentions foundry:qa-specialist, target must be qa-specialist.md, not a different agent; (2) agent name is plugin-prefixed and exists in the roster from Step 1.

**Step L4: Apply (with confirmation)**

Set up run directory before conflict checks:

```bash
RUN_DIR=".reports/distill/$(date -u +%Y-%m-%dT%H-%M-%SZ)"
mkdir -p "$RUN_DIR"  # timeout: 5000
```

**Conflict pre-check** — before presenting question, run in parallel for every `→ rule` and `→ agent/skill update` proposal:

1. **Existing content grep**: use Grep to search target file (if already exists) for section heading or key phrase delta would insert near. Hit = potential collision with existing content.
2. **Cross-proposal collision**: if two proposals both target same file and same section heading, mark both ⚠ CONFLICT.

Annotate each conflicting proposal row with ⚠. If conflicts found, print above question:

```text
⚠ Conflicts detected:
  - Proposal #N conflicts with existing content in <file>:<section> — both modify <topic>
  - Proposals #N and #M both target <file>:<section>
Review conflicts manually or select (b) to inspect each change before writing.
```

Print (annotated) proposal table. Then call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "Apply proposals?"
- (a) label: `Apply non-conflicting` — description: write all `→ rule` and `→ agent/skill update` changes except ⚠ flagged proposals
- (b) label: `Review first` — description: show diff of each proposed change before writing
- (c) label: `Skip` — description: discard proposals and exit without changes

If user selects (a), apply changes:

- **New rule files**: Write tool to create `.claude/rules/<name>.md` with drafted content
- **Agent updates**: Edit tool to insert new instruction into appropriate section of agent file
- **Skill updates**: Edit tool to insert new step/note in skill file

After applying:

1. Run cross-reference checks — use Grep to verify new rule files are referenced from `CLAUDE.md` or agent files that govern them (rule with project-wide applicability should appear as `See .claude/rules/<name>.md` reference in `CLAUDE.md`; agent-scoped rules should appear in relevant agent file)
2. Print compact apply summary:

```text
Applied N changes — <date>
  New rules:      N files — [names]
  Agent updates:  N files — [names]
  Skill updates:  N files — [names]
  Skipped:        N (already covered or too narrow)
```

3. Remind user: "Run `/foundry:init` to propagate rule changes to `~/.claude/`"

4. **Git diff gate** — run after all writes complete:

```bash
git diff HEAD -- <space-separated list of changed files>  # timeout: 5000
```

Print diff. If anything unexpected appears, revert individual files before proceeding: `git checkout HEAD -- <file>`. Final safety net — changes recoverable until committed.

**Quality gate**: After edits in L4, proceed to L5 (`foundry:curator` review) before considering the lesson applied. For agent or skill file edits specifically (not rule files), treat L5 curator findings as advisory — address any structural issues found before finalizing.

**Step L5: curator review** — after applying changes, dispatch curator to audit created and modified config files:

```text
Agent(subagent_type="foundry:curator", prompt="Review the following Claude config files just created or modified by /distill:lessons: <list new rule files and updated agent/skill files from Step L4>. Check: (1) quality — rules are concrete, not vague; (2) duplication — no overlap with existing files; (3) NOT-for boundary clarity; (4) structural consistency. Write your full findings to $RUN_DIR/curator-review.md using the Write tool. Return ONLY a compact JSON envelope: {\"status\":\"done\",\"file\":\"$RUN_DIR/curator-review.md\",\"issues\":N,\"confidence\":0.N}")
```

Surface curator findings as advisory block in terminal output. Do not block on curator findings — quality recommendations, not release gates.

End response with `## Confidence` block per CLAUDE.md output standards.

## Mode: External Distillation — only when `$ARGUMENTS` begins with `external`

Analyse external plugin, skill, or agentic resource and produce structured adoption proposal for local Claude Code setup.

```bash
EXT_RUN_DIR=".reports/distill/$(date -u +%Y-%m-%dT%H-%M-%SZ)"
mkdir -p "$EXT_RUN_DIR"  # timeout: 5000
```

**E1: Classify and plan**

Identify source type:
- URL → `WebFetch` (skim landing page + follow key links: README, docs, manifests, agent/skill files)
- File path → `Read`
- Directory → `Glob` `*.md`, `*.js`, `*.json` then prioritise: manifests, README, agent/skill/rule/hook files

**E2: Fast read — structure and intent**

Skim headings, frontmatter, filenames, top-level examples. Extract: purpose, target user, top-level architecture, routing logic. ≤ 2 reads per top-level file.

**E3: Slow read — full content**

Read all agent/skill/rule/hook files end to end. For large sources prioritise: prompts, rules, validation gates, templates, docs. Use Glob + Read in parallel.

**E4: Extract mental model**

Record in working notes: source intent, architecture, routing, safety model, expected outputs, key design decisions.

**E5: Identify standout implementation details**

Use Grep for: hooks, validation gates, must/never constraints, fallback paths, scoring rubrics, unusual prompt patterns. Flag anything absent in local setup.

**E6: Source report**

Produce inline:

```text
## Source Report — <source>
Intent:       [one line]
Architecture: [one line]
Notable hacks: [bullets]
Risks / unclear assumptions: [bullets]
Candidate artifacts: [comma list]
```

**E7: Read live local setup**

Run in parallel:
- Glob + Read on `.claude/agents/*.md`, `.claude/skills/**/SKILL.md`, `.claude/rules/*.md`
- Glob on `plugins/*/` for installed plugins

**E8: Build local capability map**

Group local agents/skills/rules by responsibility, trigger conditions, gates, output formats. Note coverage gaps.

**E9–E10: Compare and split**

For each candidate from E6, compare against local capability map. Assign to group:

- **Group A — Align + improve**: maps onto existing local agent/skill/rule, improves without structural change
- **Group B — Differentiated highlights**: novel pattern or design philosophy, doesn't map natively — interesting but requires larger structural work or conflicts with existing design

**E11: Score candidates**

Rate each on: impact (H/M/L) · fit (H/M/L) · duplication risk (none/low/high) · effort (S/M/L) · safety risk.

**E12: Adoption brainstorm table**

Exactly one of Adopt/Tweak/Discuss/Skip per item. "Local target" = specific file or directory.

- `source/hooks/task-log.js` — Group A · **Adopt as-is** · Local target: `.claude/hooks/task-log.js` · No local equivalent; identical purpose
- `source/skills/audit/SKILL.md` — Group A · **Tweak** · Local target: `.claude/skills/audit/SKILL.md` · Adapt trigger keyword to local naming
- `source/agents/doc-scribe.md` — Group B · **Discuss** · Local target: — · Overlaps existing agent; scope TBD
- `source/skills/old-util/SKILL.md` — Group B · **Skip** · Local target: — · Covered by local equivalent

**Install-as-is recommendation**

After scoring, apply this judgement:

- **Recommend install-as-is** when: (a) Group A has ≤ 2 candidates AND source has coherent standalone design, OR (b) cumulative edit effort is L (large) for ≥ 3 candidates
- If recommending: state justification — what source provides that local setup lacks, why cherry-picking would dilute value
- Present as explicit option in E13 (option b); omit if not recommended

**E13: Gate — AskUserQuestion**

Present source report + adoption table + install-as-is recommendation (when applicable). Then call `AskUserQuestion` tool — do NOT write options as plain text first. Map options directly into tool call arguments:
- question: "Apply external source candidates?"
- (a) label: `Apply Group A candidates` — description: adopt-as-is and tweak items only
- (b) label: `Install as standalone plugin` — description: install external source as standalone plugin (include only when install-as-is recommended)
- (c) label: `Review first` — description: walk through each candidate interactively
- (d) label: `Skip` — description: exit without changes

**E14: Apply**

- Option (a): reuse existing distill apply path — conflict pre-check + AskUserQuestion gate + Edit + git diff safety net (per Step L4). Limit edits to confirmed Group A targets only.
- Option (b): print install command or path; do not apply automatically — plugin installation requires user action.

**E15: Verify and report**

Print changed files. Run `git diff HEAD -- <files>` and show output. Surface unresolved Group B items as open questions for future distill runs. End with `## Confidence` block per CLAUDE.md output standards.

**E16: curator quality review**

Spawn `foundry:curator` to review applied External Distillation changes for config quality:

```text
Agent(subagent_type="foundry:curator", prompt="Review Claude config files modified by /distill external mode: <list files changed in E14>. Check: (1) structural integrity — XML tag balance, step numbering; (2) cross-ref validity — no broken agent/skill references; (3) content quality — no duplication of existing canonical content. Write your full findings to $EXT_RUN_DIR/curator-external-review.md using the Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"$EXT_RUN_DIR/curator-external-review.md\",\"issues\":N,\"confidence\":0.N}")
```

If critical findings returned: surface to user before marking complete. Non-critical findings: advisory only.

</workflow>

<notes>

- Skill is introspective: looks at tooling itself, not just code

- Invoke periodically (e.g., monthly) or after burst of correction/feedback; one-time snapshot, not continuous monitor

- Suggestions are proposals — always review before creating new files

- After creating new agent/skill based on suggestion, re-run skill once to confirm gap resolved, then stop

- **`lessons` mode is primary consolidation path** — run after any session with significant corrections to prevent lesson drift back into MEMORY.md noise

- **Agent Teams signal tracking**: when reviewing patterns, also look for:

  - Skills using `--team` or team-mode heuristics more/less than expected → flag over/under-use relative to decision matrix in `CLAUDE.md § Agent Teams`
  - Security findings appearing in reviews for non-auth code → suggests qa-specialist teammate scope too broad; narrow it
  - Model tier mismatches (e.g., heavy analysis assigned to `sonnet` teammates) → flag for tier adjustment

- **`external` mode calibration**: two concrete GT fixture cases defined in calibrate skills mode file — find via `find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry/"* -maxdepth 5 -path "*/calibrate/modes/skills.md" 2>/dev/null | sort -Vr | head -1` with fallback to `plugins/foundry/skills/calibrate/modes/skills.md`:
  - **caveman plugin** — narrow, self-contained communication mode, no local structural overlap → GT: install-as-is recommended, Group A empty or thin
  - **Karpathy autoresearch** — research automation tool, strong overlap with `research:` plugin structure → GT: Group A candidates map to research plugin, digest recommended, install-as-is not triggered
  - Ground truth = static snapshot of each tool's agent/skill/rule files (no live fetch needed); score adoption-table lane assignments against GT outcomes

- Follow-up chains:

  - Suggestion accepted for new agent/skill → `/foundry:manage create` to scaffold and register it
  - Suggestion to enhance existing → edit agent/skill directly, then `/foundry:init`
  - `lessons` proposals applied → `/foundry:init` to propagate; `/audit rules` to verify new rule files structurally sound

</notes>
