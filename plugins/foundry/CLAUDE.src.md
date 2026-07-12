<!-- source: plugins/foundry/CLAUDE.src.md → ~/.claude/CLAUDE.md via /foundry:setup Step 10 | NOT auto-loaded from cache (non-CLAUDE.md name intentional) -->

## Workflow Orchestration

### 1. Plan Mode Default

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- Use plan mode for verification steps, not just building
- Goes sideways → STOP, re-plan immediately
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy

- Use sub-agents liberally to keep main context clean
- Prefer specialised agents over general-purpose; offload research and exploration
- Run independent subtasks in parallel, not serially; one tack per sub-agent
- **Context discipline**: spawn prompt = task inputs + instructions only. Include: working dir · input paths/vars · output target · return envelope format. Exclude: session history · prior-phase reasoning · inline file contents (pass path instead)
- Complex problems → throw more compute via sub-agents
- **File-based handoff**: 2+ analysis agents each write full output to file, return only compact JSON envelope — see `.claude/skills/_shared/file-handoff-protocol.md`

### 3. Self-Improvement Loop

- After ANY correction: update `.notes/lessons.md` with preventative rule
- Write rules that prevent same mistake; iterate until mistake rate drops

### 4. Verification Before Done

- Never mark complete without proving it works — run tests, check logs, diff against main
- Ask "would staff engineer approve this?"
- **Diff against ask**: before done, diff output against literal request — every constraint honored, nothing silently dropped
- **Confidence scores**: request `## Confidence` block from every analysis agent (protocol in Output Standards); surface low confidence — never drop uncertain findings

### 5. Autonomous Bug Fixing

Trivial/mechanical (typo, single-file): just fix it — logs, errors, failing tests; no hand-holding. Multi-file or behaviour-changing: follow Root Cause protocol (`rules/debugging.md`).

### 6. Background Agent Health Monitoring

The harness runs one Bash call at a time (foreground `sleep` blocked, ~10 min per-call cap) — a skill **cannot** busy-wait in a poll loop for a background agent. Monitoring is event-driven and post-hoc.

**Protocol**:

- **Background spawn** (`run_in_background=true`): rely on the harness **completion notification** as the primary liveness signal — act when it arrives, don't block. Optional between-turn liveness: the `Monitor` tool, or a single `find <run-dir> -newer <sentinel>` probe per turn (no sleep loop).
- **Synchronous spawn** (blocking `Agent()`): returns only when done — read the output file afterwards.
- **On completion / return**: read the agent's output file; empty or missing → mark `timed_out`, record `{"verdict":"timed_out"}`, surface with ⏱ — never omit a stalled agent.

Canonical helper: `_FOUNDRY_SHARED/agent-spawn-protocol.md`. Skills may tighten timeouts in their own `<constants>` block.

### 7. Context Cost Discipline

- Cache-read cost = live context size × turn count — dominant cost line; keep both small
- Multi-phase skill runs (e.g. review → resolve): after phase report file written, prefer fresh session or `/clear` for next phase; resume from report file, not transcript
- Live context >200K tokens = smell — wrap up phase, persist state to file, restart lean
- Batch tool calls: create all tasks in ONE response (parallel calls); pair `TaskUpdate` with next substantive tool call — never emit a response containing only task bookkeeping

## Pre-Authorized Operations

Operations in `settings.json` pre-approved — execute directly. Operation not covered → restructure to match existing allow entry before requesting new permission; batch missing permissions into one ask.

**Tool efficiency rule** — native Claude tools (Read, Grep, Glob, Write, Edit, and others) always available, never need `settings.json` approval; use first:

- Native tools purpose-built and auditable; Bash for operations they cannot do (run tests, git, system commands)
- Prefer N sequential native tool calls over one script; loop of 10 Reads beats heredoc needing approval
- Avoid `python << 'EOF' ... EOF` heredocs; use `python -c "..."` one-liners only when native tools cannot write back (e.g. JSON transforms)

## Agent Teams

Teams always user-invoked:

- **Models**: lead = session model; reasoning (foundry:sw-engineer, foundry:perf-optimizer, research:scientist) = `opus`; execution (foundry:qa-specialist, foundry:doc-scribe, foundry:linting-expert, oss:cicd-steward, research:data-steward, foundry:web-explorer) = `sonnet`; max 3–5
- **Protocol**: every spawn prompt must include `Read ~/.claude/TEAM_PROTOCOL.md and use AgentSpeak v2`; preserve file paths, errors, test results, task IDs; discard verbose output
- **Security**: `foundry:qa-specialist` auto-includes OWASP Top 10 — no separate security agent
- **File-based handoff in teams**: teammates writing parallel analysis follow §2 file-handoff protocol — compact JSON envelope back to lead, full output to file

## Task Management

### File-based tracking

1. Plan in `.plans/active/todo_<name>.md`; check in before starting
2. On approval → TaskCreate each phase; mark complete as you go
3. Document results in `.plans/closed/results_<name>.md`; capture lessons → see §3 Self-Improvement Loop

### Session-start hygiene

**First action every interaction**: call `TaskList`, triage all found tasks before any work:

- Work clearly done → `TaskUpdate` status `completed`
- Orphaned / no longer relevant → `TaskUpdate` status `deleted`
- Genuinely continuing from prior session → keep, mark `in_progress`

Prevents zombie tasks accumulating across sessions and showing false progress.

### In-session task tracking

- **Skills with predefined workflow**: TaskCreate all steps at start — before any tool calls; keep list current as work evolves
- **Multi-step work** (3+ tool calls or 2+ distinct instructions) → TaskCreate before first tool call, including on plan-mode exit
- On pivot → new task for new work; TaskUpdate existing if scope changed
- Mark complete before final output; keep statuses current — live feed
- Skip for: single-task actions, simple skills (sync, distill), transient subagents

### Safety breaks for loops

- Default max 3 iterations
- At limit: stop, report progress, ask user continue or re-scope
- Skill-declared bounds take precedence

## Self-Setup Maintenance

See `.claude/rules/foundry-config.md` for `.claude/` editing checklist (plan mode gate, post-edit steps, XML conventions, sync). See `.claude/rules/claude-config.md` for universal Bash timeout and directory navigation rules.

## Compact Instructions

When context compacted, preserve in summary:

1. Active decisions and constraints — design choices, user directives, "DO NOT" rules
2. Current task state — phase/step active, what remains
3. File modification history — which files changed and why
4. Pending follow-ups — deferred items, open questions, next steps

After compaction, re-read `.claude/state/session-context.md` if exists. If a `## Skill Compaction Contract` section is present in that file, it is a verbatim skill hand-off from the PreCompact hook — treat its `preserve:`, `run-dir`, and `next` fields as authoritative for resuming the active skill, not to be paraphrased or summarized away.

## Core Principles

- **Simplicity First**: touch only what's necessary; smallest change that works
- **No Laziness**: find root causes; no temp fixes; senior developer standards
- **Root Cause**: post-fix verify all symptoms resolved; if remain → root cause incomplete; loop (max 3, then AskUser); invoke `foundry:challenger` post-fix (non-trivial changes) to confirm resolution + no new regressions. Protocol: `rules/debugging.md`.
- **Proportionality**: reasoning depth, length, tool count scale to stakes — over-delivery = failure mode equal to under-delivery (buries signal, wastes tokens); trivial ask → direct answer, zero ceremony
- **Legible deviation**: every filled assumption, bent instruction, corrected error stated explicitly — user never discovers changes by diffing output against request
- **Reversibility check**: before any action that cannot restore pre-session state (deleting pre-existing files, pushing, dropping tables, external messages), pause — confirm scope matches what was asked; prefer reversible alternatives
- **Tool-first**: use declared tools fully and creatively — if tool can do job indirectly, use it
