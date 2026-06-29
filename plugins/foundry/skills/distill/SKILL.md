---
name: distill
description: "One-time snapshot extracting patterns from work history and accumulated lessons, distills into concrete improvements — new agent/skill suggestions, roster quality review, memory pruning, consolidating lessons into rules/agent updates, or performing bin/ extraction from /audit --efficiency candidates."
argument-hint: '[review | prune | lessons | executables [<run-dir-or-report-path>] | "external <url-or-path>" | "<recurring task description>"] [--project] [--eager]'
disable-model-invocation: true
allowed-tools: Read, Edit, Bash, Glob, Grep, Write, AskUserQuestion, Agent, WebFetch, TaskCreate, TaskUpdate, TaskList
effort: low
---

<objective>

Analyze how Claude Code is used and surface concrete improvements — new agents/skills to reduce repetition, or consolidate lessons into governance files (rules, agent instructions, skill updates) — without duplicating what exists.

NOT for single-file edits or quality checks — use `/foundry:audit` for config quality checks.
NOT for audit-only scan for extraction candidates (use `/foundry:audit --efficiency` instead of `distill executables` for detection-only).

</objective>

<inputs>

- **$ARGUMENTS**: optional. Modes:
  - Omitted — analyze existing patterns and agents; generate suggestions proactively.
  - `prune [--eager]` — evaluate project memory file for stale, redundant, or verbose entries. Default: advisory diff + apply prompt. `--eager`: score every entry (Usage likelihood × Impact → Tier P0/P1/P2), print full scored table with `#` column, let user select by tier or item numbers, delegate edits to `foundry:curator`.
  - `lessons [--eager]` — read `.notes/lessons.md` and memory feedback files, distill recurring patterns into proposed rule files, agent instruction updates, and skill workflow changes. `--eager`: include Pattern count, Strength, and Tier columns in proposal table; let user select clusters to promote by tier or item numbers; delegate writes to `foundry:curator`.
  - `review [--eager]` — review existing agent/skill roster for quality and gaps without suggesting new additions. `--eager`: lower overlap flag threshold from >50% to >30% scope coverage; surface any shared single capability between agents as boundary issue; add "Sharpen Boundary" section to output.
  - `external <source> [--eager]` — analyse external plugin, skill, or agentic resource and produce structured adoption proposal. `<source>` is URL, file path, or local directory. `--eager`: lower adoption bar — recommend partial adoption even for single useful components.
  - `executables [--eager] [<run-dir-or-report-path>]` — perform bin/ extraction from `/foundry:audit --efficiency` Check 33 candidates. Auto-detects latest run dir under `.reports/audit/`; pass optional path to target a specific run dir or report file. Runs inline Check 33 scan when no report exists. Default gates on HIGH/MEDIUM verdict. `--eager`: also surface LOW verdict clusters as extraction candidates. Spawns `foundry:sw-engineer` per cluster. Skip to **Mode: Executables Extraction** below.
  - `[--eager] <recurring task description>` — use description as context when generating suggestions. `--eager`: lower frequency threshold from 3+ to 2+ occurrences; single high-effort occurrence also qualifies.
  - `--project` — in `prune` and `lessons` modes, show an interactive project picker: enumerate all slugs under `~/.claude/projects/*/memory/` with MEMORY.md size in tokens, then let user select which project(s) to operate on. Omit to operate across **all** projects automatically. Has no effect on other modes.

</inputs>

<workflow>

**Task hygiene**:
```bash
# audit-skip: resilience-replication
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
```
Read `$_FS/task-hygiene.md` — follow task hygiene protocol.

```bash
EAGER=false
[[ "$ARGUMENTS" == *"--eager"* ]] && EAGER=true
ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--eager//g' | xargs)  # timeout: 3000
echo "EAGER=$EAGER"  # shell vars don't persist across Bash calls — read from stdout
echo "ARGUMENTS_STRIPPED=$ARGUMENTS"
```

> **Note**: `EAGER` and stripped `ARGUMENTS` are set by this Bash block, but shell variable state does **not** persist across separate Bash() tool calls. After this block runs, read its stdout (`EAGER=true/false`, `ARGUMENTS_STRIPPED=...`) and carry those values as model-context references for all subsequent mode dispatch and threshold decisions. Do not rely on `$EAGER` as a live shell variable in later steps — substitute the literal boolean value read from stdout.

```bash
PROJECT_FLAG=false
if echo "$ARGUMENTS" | grep -qE -- "--project"; then
    PROJECT_FLAG=true
    ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--project//' | xargs)
fi
echo "PROJECT_FLAG=$PROJECT_FLAG"
echo "ARGUMENTS_FINAL=$ARGUMENTS"
```

> **Note**: `PROJECT_FLAG` does not persist across Bash calls. Read its value from the stdout line `PROJECT_FLAG=true/false` and carry as model-context reference. When `true`, the mode must run the interactive picker before operating.

## Step 1: Inventory existing agents and skills

Use Glob tool to enumerate agents and skills across all sources — project-local AND plugin-namespaced — to avoid false-gap findings when candidate already exists in plugin:

- **Project-local**: pattern `agents/*.md`, path `.claude/`; pattern `skills/*/SKILL.md`, path `.claude/`
- **Plugin source** (workspace): pattern `*/agents/*.md`, path `plugins/`; pattern `*/skills/*/SKILL.md`, path `plugins/`
- **Installed plugin cache** (if accessible): resolve cache root — `PLUGIN_CACHE="${CLAUDE_PLUGIN_ROOT:-plugins/foundry}"` — then use Glob tool on `$PLUGIN_CACHE` for pattern `*/agents/*.md` and `*/skills/*/SKILL.md`

For each agent/skill found, extract: name, description, tools, purpose. Tag each entry with plugin namespace (e.g. `foundry:sw-engineer`, `oss:resolve`) — used in Step 3 gap analysis to prevent recommending duplicates of plugin-namespaced agents/skills.

## Step 2: Analyze work patterns

> **Mode-token normalization** — all mode dispatches below compare against the **first whitespace-delimited token** of the stripped `ARGUMENTS` (after `--eager` removal). Use this single rule consistently; do not rely on exact equality of the full `$ARGUMENTS` string, since trailing flags/spaces from prior parsing may differ.

**If first token equals `executables`** (i.e. `executables` alone or `executables <path>`, NOT a path or word that merely starts with the string `executables`): skip Steps 2–5 entirely and go to "Mode: Executables Extraction" below.

**If first token equals `prune`**: skip Steps 2–5 entirely and go to "Mode: Memory Pruning" below.

**If first token equals `lessons`**: skip Steps 2–5 entirely and go to "Mode: Lessons Distillation" below.

**If first token equals `external`** (i.e. `external <source>`, NOT a word that merely starts with the string `external`): skip Steps 2–5 entirely and go to "Mode: External Distillation" below.

**If `$ARGUMENTS` is `review`**: skip git analysis below and go directly to Step 3 (Gap analysis). Use agent/skill descriptions from Step 1 as sole input — goal is to assess quality and coverage of existing roster, not look for new patterns in recent work. In Step 5, suppress all "Recommend: New Agent/Skill" sections and output only "Existing Coverage", "Recommend: Enhance Existing", and "No Action Needed" entries. With `--eager`: apply stricter overlap detection in Step 4 (threshold drops to >30%; any shared single named capability flags as boundary issue); add "Recommend: Sharpen Boundary" section to Step 5 output listing all partial-overlap pairs with specific capability to split.

Otherwise, look for signals of repetitive or specialist work. First three git commands are independent — run in parallel:

```bash
# timeout: 3000
# --- run these three in parallel ---
git log --oneline -50

git log --name-only --pretty="" -30 | sort | uniq -c | sort -rn | head -20

git log --oneline -100 | cut -d' ' -f2 | sort | uniq -c | sort -rn | head -15
```

Then use Glob tool (pattern `todo_*.md`, path `.plans/active/`) to list active task files; read each with Read tool. Also read `.notes/lessons.md` (if exists) for task history and conversation hints.

If `$ARGUMENTS` provided, use as additional context for pattern analysis.

### Frequency Heuristics

- **3+ occurrences** of pattern in recent history → candidate for automation
- **2+ different projects** using same manual process → cross-project skill
- **significant manual effort** per occurrence (subjective — use git history context) → high-value automation target
- **Domain-specific knowledge** required → candidate for specialist agent (not just skill)

With `--eager` (lower thresholds):
- **2+ occurrences** → candidate for automation
- **1 occurrence** with significant manual effort → qualifies as high-value candidate
- Domain-specific threshold unchanged

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
  (with --eager: lower to >30%; any shared single named capability → flag as boundary issue)
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
<!-- Slug-divergence guard: `resolve_memory_dir.py` is the single source of truth for the memory directory and `MEMORY.md` filename. Any consumer that reads or writes session/project memory (e.g. `foundry:session`, lessons mode below) MUST resolve the same path via this script — do NOT hardcode an alternate slug or filename here or elsewhere; divergence causes silent split-brain between writer and reader. -->

```bash
# timeout: 5000
FOUND=$(find "$HOME/.claude/projects" -maxdepth 3 -name "MEMORY.md" -path "*/memory/MEMORY.md" 2>/dev/null | sort)
if [ -z "$FOUND" ]; then
    echo "PRUNE_ABORT"
    echo "PRUNE_ABORT_REASON: no memory files found under ~/.claude/projects/"
else
    echo "PRUNE_FOUND"
    echo "$FOUND" | while IFS= read -r f; do
        slug=$(echo "$f" | sed 's|.*/projects/||;s|/memory/MEMORY.md||')
        tokens=$(( $(wc -c < "$f" 2>/dev/null || echo 0) / 4 ))
        echo "PRUNE_ENTRY: $slug | ${tokens}k tokens | $f"
    done
fi
```

 **Short-circuit**: After the block runs, scan for `PRUNE_ABORT` (exact-line match). If present, stop prune mode and end with Confidence block. Otherwise, collect all `PRUNE_ENTRY:` lines — each has format `<slug> | <N>k tokens | <path>`.

**If `PROJECT_FLAG == true`** (interactive picker): call `AskUserQuestion` with `multiSelect: true`. Build options from `PRUNE_ENTRY` lines — label = `<slug> (tokens=<N>k)`, description = `prune this project's memory`. Max 4 options: if more than 4 projects found, take the 4 largest by token count and note in the question text that remaining projects were omitted (user can re-run). Always add a final option with label `Skip` and description `exit without changes`. Checked slugs → extract matching `<path>` fields as the working set.

**If `PROJECT_FLAG == false`**: use all `<path>` fields from PRUNE_ENTRY lines as the working set.

Run P1–P3 once per file in the working set. Label each section with its slug. Print consolidated summary at the end.

Read memory file with Read tool. Also read `.claude/CLAUDE.md` to identify overlap — anything already covered in CLAUDE.md need not live in memory.

**If `$EAGER == true`** — skip P1–P3 below; execute P-eager steps:

**P-eager-1**: Score every MEMORY.md section against two dimensions:

- **Usage likelihood**: High = needed every session · Moderate = occasional · Low = rare/one-off
- **Impact if missing**: High = wrong behavior without it · Moderate = degraded output · Low = no effect
- **Tier** (derived): P0 = keep · P1 = trim candidate · P2 = drop/convert candidate
  - P0: High×High or High×Moderate
  - P1: any Moderate×Moderate or mixed High/Low signal
  - P2: Low usage OR Low impact (especially both)
- **Action**: entries whose content could live in `rules/*.md` or an agent file → mark `→ rule` in Action column

Print scored table:

```text
| #  | Section | Usage likelihood | Impact if missing | Tier | Action      |
|----|---------|-----------------|-------------------|------|-------------|
| 1  | ...     | High            | High              | P0   | Keep        |
| 2  | ...     | Low             | Low               | P2   | Drop        |
| 3  | ...     | Moderate        | High              | P1   | Trim        |
| 4  | ...     | Low             | High              | P2   | → rule      |

Legend:
  Usage likelihood — High: every session · Moderate: occasional · Low: rare/one-off
  Impact if missing — High: wrong behavior · Moderate: degraded · Low: no effect
  Tier — P0: keep · P1: trim candidate · P2: drop/convert candidate
  Action — "→ rule" entries can be promoted to rules/*.md then dropped from memory
```

**P-eager-2**: Call `AskUserQuestion` tool — do NOT write question as plain text:
- question: "Which entries to prune? Select tier or type item numbers (e.g. 2, 4, 7)."
- (a) label: `All P2` — description: drop all tier-P2 entries; apply `→ rule` conversions as proposals
- (b) label: `All P1 + P2` — description: trim P1 entries and drop P2 entries
- (c) label: `Specific items` — description: enter item numbers in next message; applies only those
- (d) label: `Skip` — description: leave MEMORY.md untouched; user edits manually

If user picks (c): print "Enter item numbers (e.g. 2, 4, 7):" and wait for next message; resolve item numbers against # column before proceeding.

**P-eager-3**: Spawn **foundry:curator** to apply selected edits. Substitute absolute memory file path (resolved from `PRUNE_FOUND_PATH`) inline before issuing the Agent call:

```text
Read MEMORY.md at <absolute-path>.
Apply these prune actions (sections identified by # from scored table):
  <list: # — section name — action (Drop | Trim | Convert to rule)>
Rules:
- Drop: remove entire section including heading
- Trim: keep operational directive only (1 line max per entry); remove rationale/backstory
- Convert to rule: remove section from MEMORY.md; print proposed rule file content inline in response for user review before writing — do NOT write the rule file
Write MEMORY.md changes using the Edit tool.
Return ONLY: {"status":"done","sections_dropped":N,"sections_trimmed":N,"rule_conversions":N,"confidence":0.N}
```

Print compact summary after curator completes:

```text
Pruned MEMORY.md — <date>
  Dropped: N sections — [names]
  Trimmed: N sections — [names]
  Rule conversions proposed: N — [names] (review and write manually or via /manage)
  Kept:    N sections unchanged
  Saved:   ~N lines
```

End response with `## Confidence` block per CLAUDE.md output standards.

**Otherwise** (`$EAGER == false`) — standard read-only advisory flow:

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

Read and execute `${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/skills/distill/modes/lessons.md`.

## Mode: External Distillation — only when `$ARGUMENTS` begins with `external`

Read and execute `${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/skills/distill/modes/external.md`.

## Mode: Executables Extraction — only when `$ARGUMENTS` begins with `executables`

Read and execute `${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/skills/distill/modes/executables.md`.

</workflow>

<notes>

- Skill is introspective: looks at tooling itself, not just code

- Invoke periodically (e.g., monthly) or after burst of correction/feedback; one-time snapshot, not continuous monitor

- Suggestions are proposals — always review before creating new files

- After creating new agent/skill based on suggestion, re-run skill once to confirm gap resolved, then stop

- **`lessons` mode is primary consolidation path** — run after any session with significant corrections to prevent lesson drift back into MEMORY.md noise

- **Agent Teams signal tracking**: when reviewing patterns, also look for:

  - Skills using `--team` or team-mode heuristics more/less than expected → flag over/under-use relative to decision matrix in `CLAUDE.md § Agent Teams`
  - Security findings appearing in reviews for non-auth code → suggests foundry:qa-specialist teammate scope too broad; narrow it
  - Model tier mismatches (e.g., heavy analysis assigned to `sonnet` teammates) → flag for tier adjustment

- **`external` mode calibration**: two concrete GT fixture cases defined in calibrate skills mode file — find via `find "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}" -maxdepth 5 -path "*/calibrate/modes/skills.md" 2>/dev/null | head -1` with fallback to `plugins/foundry/skills/calibrate/modes/skills.md`:
  - **caveman plugin** — narrow, self-contained communication mode, no local structural overlap → GT: install-as-is recommended, Group A empty or thin
  - **Karpathy autoresearch** — research automation tool, strong overlap with `research:` plugin structure → GT: Group A candidates map to research plugin, digest recommended, install-as-is not triggered
  - Ground truth = static snapshot of each tool's agent/skill/rule files (no live fetch needed); score adoption-table lane assignments against GT outcomes

- Follow-up chains:

  - Suggestion accepted for new agent/skill → `/foundry:manage create` to scaffold and register it
  - Suggestion to enhance existing → edit agent/skill directly, then `/foundry:setup`
  - `lessons` proposals applied → `/foundry:setup` to propagate; `/foundry:audit rules` to verify new rule files structurally sound
  - `executables` extraction complete → `/foundry:setup` to propagate bin/ scripts; run `/foundry:audit --efficiency` to confirm `clusters == 0`

</notes>
