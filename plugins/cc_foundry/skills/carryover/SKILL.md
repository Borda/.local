---
name: carryover
description: 'Session carryover across a context reset — `dump` writes a compact handover doc (goal, decisions + why, lessons, standing instructions, files-touched table, artifacts, next step), then prints `/clear`; the `carryover-restore.js` SessionStart hook re-injects it into the fresh session automatically. TRIGGER when: user says "dump the session", "session dump", "handover before clear", "save state before clearing", "carry this over", "I want to clear but keep the plan", "write down where we are before I reset". SKIP: parking a diverging idea or unanswered question mid-session (that is `foundry:session`, the parking lot); surviving auto-compact at 85% (that is the skill contract in `.temp/state/skill-contract.md` per `compaction.md`, written by the running skill).'
argument-hint: "dump [name] | restore [name] | list"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TaskList, AskUserQuestion
effort: low
model: sonnet
---

<objective>

Carry the *durable* part of a session across `/clear`. `dump` composes a small handover doc from the live conversation, writes it to `.claude/state/carryover/<slug>.md`, and ends by printing `/clear`. The `carryover-restore.js` hook (SessionStart, matcher `clear`) injects that doc into the fresh session, so restore is free. Implementation detail — diffs, tool output, exploration transcript, abandoned approaches — is dropped on purpose; only the decision that settled an approach survives.

Runs **inline, never `context: fork`**. The conversation history *is* the authoritative source for what changed and why; a forked run would see none of it. That constraint is the whole reason this is a separate skill from `foundry:session`.

NOT for: parking open-loop ideas or deferred questions (`foundry:session`); auto-compact survival (`compaction.md` skill contract). Boundary table in the notes section below.

</objective>

<inputs>

- **$ARGUMENTS**: required. Three modes:
  - `dump [name]` — compose and write the carryover doc, set the `LATEST` pointer, print the `/clear` next step. `name` optional; unnamed dumps derive a slug from branch + UTC timestamp.
  - `restore [name]` — print a stored carryover into context and mark it consumed. Named, or `LATEST` when omitted. Manual path for the dumps the hook skips (stale, consumed, or named restore of an older one).
  - `list` — table of stored carryovers: slug, age, consumed.

</inputs>

<constants>

- Carryover dir: `.claude/state/carryover/` (project-local; `.claude/state/` is gitignored, same as `session-context.md`)
- Pointer file: `.claude/state/carryover/LATEST` — plain text, the slug of the most recent unconsumed dump. Blank or missing = nothing pending.
- Doc size cap: ~1.5K tokens (~75 lines). Compress prose, never drop a decision.
- Hook auto-restore window: unconsumed **and** `created` within 30 min. Outside it, `restore` is the manual path.
- Hook truncation threshold: ~8000 chars — above it the hook injects `## Goal` + files table + `## Next step` + a `→ /carryover restore <slug>` pointer instead of the whole doc.
- Stale threshold: 14 days (`⚠ stale` prefix when listing)
- Delete threshold: 30 days (swept during `list`)
- Files-table row cap: 25 (over that, group by directory and state the elided count)

</constants>

<workflow>

**Task hygiene**: load and follow the protocol below.
```bash
# audit-skip: resilience-replication
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_foundry}/bin/load_shared_doc.py" foundry skills/_shared task-hygiene.md  # timeout: 5000
```

## Step 0: Validate and dispatch mode

Extract first word of `$ARGUMENTS` as `MODE`.

If `MODE` matches:
- `dump` (alias: `save`) → **Mode: dump**
- `restore` (alias: `load`) → **Mode: restore**
- `list` → **Mode: list**

**Unsupported flag check** — after extracting the mode token, scan `$ARGUMENTS` for remaining `--<token>` patterns. If found: print `! Unknown flag(s): \`--<token>\`. Supported modes: dump, restore, list.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke correctly) · (b) **Continue ignoring** (skip unknown flags, proceed with recognized mode).

Otherwise (empty, unrecognized, misspelled): use `AskUserQuestion`:

> "Which carryover mode did you want?"
> Options: (a) `dump [name]` — write the handover doc now, (b) `restore [name]` — print a stored carryover back into context, (c) `list` — show stored carryovers

## Step 1 / Mode: dump

### Substep 1a: Derive slug and timestamp

```bash
git branch --show-current 2>/dev/null; date -u +%Y-%m-%dT%H:%M:%SZ; date -u +%Y-%m-%dT%H-%M-%SZ  # timeout: 5000
```

Three lines out: branch, ISO `created` stamp, filesystem-safe stamp. Slug: `<name>` from `$ARGUMENTS` when given (lowercase, non-alphanumerics → `-`); otherwise `<branch with / → ->-<filesystem-safe stamp>`. Empty branch (detached HEAD) → `detached`. Reject a `name` containing `/` or `..` — re-ask via `AskUserQuestion` rather than writing outside the carryover dir.

### Substep 1b: Gather file evidence

```bash
git diff --stat HEAD 2>/dev/null; echo "--- committed since session start ---"; git log --name-only --pretty=format:'%h %s' --since="8 hours ago" 2>/dev/null | head -60  # timeout: 5000
```

> git parses the relative date itself — no BSD/GNU `date` flag split needed.

**Sourcing precedence for the files table** — union of four sources, in this order:

1. **Conversation history — authoritative.** Every `Edit`/`Write` of this session is visible to this skill; that is the touched-file list, and the only source that also knows *what* each change was (`Change`) and whether it landed (`State`).
2. `git diff --stat HEAD` → the `Ref` column (`+N/-M`). A file with no diff entry and no commit is `Ref: uncommitted-new`, or dropped when it was temp scratch.
3. `git log --name-only --since=…` → files already committed this session, which no longer appear in `git diff HEAD`.
4. `.claude/state/session-context.md` → `## Files Modified This Session` — **fallback only**. `task-log.js` writes that section from its PreCompact branch, which fires at the 85% auto-compact threshold; a session dumping before any compaction has no such section, or a stale one from a prior session. Read it only when sources 1–3 come up empty.

**Column rules**: `Change` ≤6 words, what changed, never why (why belongs in `## Decisions`). `State` ∈ `done` / `wip` / `needs-test` / `reverted`. Cap 25 rows — over that, group by directory and state the elided count explicitly, never silently truncate (`quality-gates.md`). Scratchpad and `.temp/` paths are never rows; they belong in `## Artifacts`.

### Substep 1c: Gather artifacts and open tasks

```bash
find .temp .reports .experiments .developments -maxdepth 2 -type d -mtime -1 2>/dev/null | head -20  # timeout: 5000
```

Call `TaskList` for tasks still `in_progress` or `pending` — they feed `## Next step`, not a section of their own (task state survives on its own).

### Substep 1d: Compose the doc

Fill this template. Omit any section with nothing real in it — an empty heading is noise the next session pays for.

```markdown
---
slug: <slug>
created: <ISO8601-UTC>
consumed: false
branch: <git branch>
---

## Goal
<the task/plan in 1–3 lines>

## Decisions
- <decision> — why: <reason>

## Lessons / corrections
- <correction received> — rule going forward: <rule>

## Standing instructions
- <programmatic-level directive that must keep applying>

## Files touched

| File | Change | State | Ref |
| --- | --- | --- | --- |
| `path/to/a.py` | added retry guard | done | +42/-3 |
| `path/to/b.md` | README sync | wip | +8/-0 |

## Artifacts

| Path | Kind | Note |
| --- | --- | --- |
| `.reports/<skill>/<ts>/report.md` | report | consolidated findings |
| `.temp/<skill>/<ts>/` | run-dir | agent handover files |

## Next step
<single concrete next action>

## Dropped deliberately
implementation detail, tool output, exploration transcript
```

**Written in ultra-caveman tier** (`plugins/CLAUDE.md` §Writing Style) — this doc is re-injected into a fresh context on every restore, so every word is a recurring cost. Explicit exclusions: no diffs, no code bodies, no command output, no per-file reasoning, no history of abandoned approaches — only the decision that settled them.

### Substep 1e: Write the doc and the pointer

Use the **Write tool** for both (it creates `.claude/state/carryover/` on demand; no `mkdir` permission gap):

1. `.claude/state/carryover/<slug>.md` — the composed doc. A slug that already exists is overwritten only after `AskUserQuestion` confirms; otherwise append `-2`, `-3`, … .
2. `.claude/state/carryover/LATEST` — the slug alone, one line.

### Substep 1f: Print the next step

Terminal only, short. Confirm the path, the row count of the files table, then:

```text
→ .claude/state/carryover/<slug>.md (N files, M decisions)
Next: clear the context. I cannot run it for you — Claude Code exposes no programmatic slash invocation, so the line below is yours to send. The SessionStart hook re-injects this doc automatically on the other side.

/clear
```

The literal `/clear` is the **last line of the reply** — nothing after it, so it is one copy away.

End with a `## Confidence` block per `quality-gates.md` — score on: files table backed by conversation evidence (not guessed), decisions captured with their reasons, next step concrete enough to act on cold.

## Step 2 / Mode: restore

### Substep 2a: Resolve the target

Named → `.claude/state/carryover/<name>.md`. Unnamed → read `.claude/state/carryover/LATEST` (Read tool) and use the slug it holds; blank or missing → print `No pending carryover. → /carryover list` and stop.

Missing target file → print the miss and fall through to a `list` render so the user sees what does exist.

### Substep 2b: Print it into context

Read the doc and print its body verbatim, frontmatter stripped, under a one-line banner naming the slug and its age. **Terminal only — never route this to a file**: landing it in context *is* the mechanism, and output-routing to `.temp/` would defeat it.

### Substep 2c: Mark consumed

1. Edit tool on the doc: `consumed: false` → `consumed: true` (frontmatter only).
2. Write tool on `.claude/state/carryover/LATEST`: empty content. The hook treats blank and missing alike, so nothing re-injects on the next `/clear`.

End with a `## Confidence` block per `quality-gates.md` — score on: target resolved unambiguously, doc printed intact, consumed marker written.

## Step 3 / Mode: list

### Substep 3a: Sweep expired carryovers (≥ 30 days)

```bash
find .claude/state/carryover -name '*.md' -mtime +30 -delete 2>/dev/null; echo "sweep done"  # timeout: 5000
```

### Substep 3b: Collect and render

Glob `.claude/state/carryover/*.md`, Read each one's frontmatter for `slug`, `created`, `consumed`, `branch`. Age comes from `created`, not file mtime — marking a doc consumed rewrites the file and would reset mtime.

```markdown
## Carryovers — <today's date>

| Slug | Age | Branch | Consumed |
| --- | --- | --- | --- |
| `plan-x` | 12 min | main | no |
| `⚠ stale refactor-auth` | 16 d | feat/auth | yes |

→ /carryover restore <slug> to print one back into context
→ /carryover dump <name> to write a new one
```

`⚠ stale` prefix at ≥ 14 days. No files → `No stored carryovers.`

End with a `## Confidence` block per `quality-gates.md` — score on: glob returned a result (even empty), every frontmatter parsed, ages computed from `created`.

</workflow>

<notes>

**Why not one command.** A skill cannot invoke `/clear` — Claude Code exposes no programmatic slash invocation (that is Agent SDK `query()` only), and neither keybindings, `UserPromptSubmit`, nor `UserPromptExpansion` can trigger one either. So `dump` + `/clear` stays two steps; the mechanism buys its keep by making the *third* step (restore) automatic.

**Why inline, not forked.** `context: fork` skills cannot read conversation history. The files table's `Change` and `State` columns, the decisions, and the lessons all come from that history — a forked carryover would have nothing to write. `foundry:session` stays forked because its modes only touch files.

**Three state mechanisms — they do not overlap.**

| Mechanism | Survives | Trigger | Store |
| --- | --- | --- | --- |
| Parked items (`session`) | open loops, deferred ideas | automatic, behavioral | `session-context.md` `## Parked items` |
| Skill contract (`compaction.md`) | in-flight skill phase state | auto-compact at 85% | `.temp/state/skill-contract.md` |
| Carryover (`carryover`) | plan, decisions, lessons, files table | explicit `dump` before `/clear` | `.claude/state/carryover/` |

**Restore is best-effort, dump is not.** The hook injects only when the pointer exists, the doc is unconsumed, and it is under 30 minutes old — a deliberately narrow window, so an old dump never ambushes an unrelated session. Everything outside it is reachable by `/carryover restore <slug>`, which has no age gate.

**Not a mode of `/foundry:session`.** `dump`/`restore` were never dispatched there — `session` is `context: fork` and cannot read conversation history, so it could never compose a carryover. Its fallback "which mode?" question mentions this skill by name for anyone who guesses `session dump`; that is the only cross-reference, not a redirect branch.

**Scope**: carryovers are project-local — `.claude/state/carryover/` lives inside the working tree, so nothing leaks across projects.

</notes>
