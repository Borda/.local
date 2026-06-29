---
name: session
description: 'Session parking lot — automatically parks diverging ideas and unanswered questions to project-scoped memory; /session resume shows pending items, /session archive closes them, /session summary gives a session digest TRIGGER when: user asks "what was I working on", "any pending items", "what''s in the parking lot", "remind me where we left off", "what did we defer"; resume intent clear from context. SKIP: new topic or explicit new task; user providing new context rather than resuming; archive mode requires user-supplied text (user-initiated only).'
argument-hint: "resume | archive <text> | summary"
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, TaskList, TaskCreate, TaskUpdate, AskUserQuestion
effort: low
model: sonnet
context: fork
---

<objective>

Track open-loop ideas, deferred questions, diverging threads — no loss to context compaction or session end. Three on-demand commands (`resume`, `archive`, `summary`) plus behavioral parking rule that writes `session-open-*.md` memory files as items arise.

NOT for: general persistent notes or diary entries (use .notes/ directly); managing task lists (use TaskCreate/TaskUpdate tools).

</objective>

<inputs>

- **$ARGUMENTS**: required. Three modes:
  - `resume` (alias: `pending`) — list all open `session-open-*.md` memory files for this project, grouped by age; items ≥ 14 days get `⚠ stale` prefix; items ≥ 30 days deleted silently before listing
  - `archive <partial-text>` — fuzzy-match parked item by name or content, delete memory file, append audit entry to `.claude/logs/session-archive.jsonl`
  - `summary` — compact session digest: completed tasks, parked items, recent git commits since session start; follows output-routing rule (≤10 lines → terminal; longer → `.temp/output-session-summary-<date>.md`)

</inputs>

<constants>

- Memory dir: resolved via `resolve_memory_dir.py` (canonical; see snippet below)
- Canonical MEMORY_DIR snippet (use in every bash block that needs the path):
  ```bash
  MEMORY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_memory_dir.py" 2>/dev/null)
  [ -n "$MEMORY_DIR" ] || { echo "! resolve_memory_dir.py returned empty — aborting; check Python availability and plugin installation"; exit 1; }
  ```
- File pattern: `session-open-*.md`
- Resolution log: `.claude/logs/session-archive.jsonl`
- Stale threshold: 14 days (add `⚠ stale` prefix when listing)
- Delete threshold: 30 days (silently remove before listing)
- Max open items: 10 (surface list and ask to archive before parking new ones)

</constants>

<workflow>

**Task hygiene**:
```bash
# audit-skip: resilience-replication
_FS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_shared_path.py" foundry skills/_shared 2>/dev/null || echo "plugins/foundry/skills/_shared")  # timeout: 5000
```
Read `$_FS/task-hygiene.md` — follow task hygiene protocol.

## Step 0: Validate and dispatch mode

Extract first word of `$ARGUMENTS` as `MODE`.

If `MODE` matches:
- `resume` or `pending` → **Mode: resume**
- `archive` → **Mode: archive**
- `summary` → **Mode: summary**

**Unsupported flag check** — after extracting the mode token, scan `$ARGUMENTS` for any remaining `--<token>` patterns. If found: print `! Unknown flag(s): \`--<token>\`. Supported modes: resume, archive, summary.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke correctly) · (b) **Continue ignoring** (skip unknown flags, proceed with recognized mode).

Otherwise (empty, unrecognized, misspelled): use `AskUserQuestion`:

> "Which session mode did you want?"
> Options: (a) `resume` — list all open parked items, (b) `archive <name>` — close a parked item by name, (c) `summary` — compact digest of this session's work

## Step 1 / Mode: resume (list pending items)

### Substep 1a: Resolve the memory directory

Derive `MEMORY_DIR` using the canonical snippet defined in `<constants>` above. Run that snippet here; do not duplicate it. `echo "$MEMORY_DIR"` to surface the resolved path.

### Substep 1b: Age-out expired items (≥ 30 days) silently

```bash
# MEMORY_DIR — must re-derive here; shell state lost across Bash calls
MEMORY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_memory_dir.py" 2>/dev/null)
[ -n "$MEMORY_DIR" ] || { echo "! resolve_memory_dir.py returned empty — aborting; check Python availability and plugin installation"; exit 1; }
# log before delete for audit trail
find "$MEMORY_DIR" -name "session-open-*.md" -mtime +30 2>/dev/null | while IFS= read -r f; do
    echo "Removing aged file: $f"
    rm "$f"
done # timeout: 5000
echo "cleanup done"
```

### Substep 1c: Collect remaining items and compute age

**Primary source (current)**: Read `.claude/state/session-context.md` if it exists. Extract all bullets under `## Parked items` section — each is a current parked item. Use item's `Raised:` date for age computation.

**Legacy source (backwards-compat)**: List `session-open-*.md` files via Bash (Glob with absolute paths outside project root may return empty on restricted installs — Bash `ls` is the reliable fallback):
```bash
ls "$MEMORY_DIR"/session-open-*.md 2>/dev/null  # timeout: 5000
```
For each file path returned, read with Read tool to extract `name` and `description` frontmatter fields and item body. Show legacy items alongside current items in output. If `ls` returns no files, skip — no legacy items.

Compute age in days per file using `session_age_files.py` (cross-platform; output is `<age>\t<path>` per line): <!-- file: session_age_files.py — consumers: foundry:session Substep 1c -->

```bash
# MEMORY_DIR — must re-derive here; shell state lost across Bash calls
MEMORY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/resolve_memory_dir.py" 2>/dev/null)
[ -n "$MEMORY_DIR" ] || { echo "! resolve_memory_dir.py returned empty — aborting; check Python availability and plugin installation"; exit 1; }
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/session_age_files.py" "$MEMORY_DIR" # timeout: 5000
```

### Substep 1d: Render grouped list

Group by age bucket:

- **This session** — files modified today (age = 0)
- **Earlier (`<date>`)** — files modified on prior dates, grouped by modification date

Apply `⚠ stale` prefix to items with age ≥ 14 days.

Print in this format:

```markdown
## Session Pending — <today's date>

### This session
- [ ] <item name> — <description>

### Earlier (<YYYY-MM-DD>)
- [ ] ⚠ stale — <item name> — <description>

→ /session archive <slug> to close an item
→ /session summary for a full session digest
```

If no files exist, print: `No pending session items.`

End resume mode output with a `## Confidence` block per quality-gates.md — score based on: memory sources resolved without error, age computation succeeded, legacy file enumeration returned a result (even empty).

## Step 2 / Mode: archive (close a parked item)

### Substep 2a: Locate memory directory and list candidates

Derive MEMORY_DIR using canonical snippet from `<constants>`. Candidates come from two sources:
1. **Current**: bullets under `## Parked items` in `.claude/state/session-context.md` (if exists)
2. **Legacy**: Glob tool with pattern `session-open-*.md` in MEMORY_DIR

Combine both into a single candidate list for fuzzy matching in Substep 2b.

### Substep 2b: Fuzzy-match the target item

Extract `<partial-text>` from `$ARGUMENTS` (everything after `archive `).

Search candidates from Substep 2a. For `session-open-*.md` files: Grep with partial text, match against file basenames. For session-context.md bullets: match `<partial-text>` against the slug or summary text. Select best match — if ambiguous (2+ equally close matches), list them and ask user to disambiguate before proceeding.

Track match source:
```bash
MATCHED_SOURCE="file"          # "file" for session-open-*.md, "context" for session-context.md
MATCHED_FILE="<full path>"     # only when MATCHED_SOURCE="file"
MATCHED_SLUG="<slug>"
ITEM_NAME="<name>"
printf '%s\n' "$MATCHED_SOURCE" "$MATCHED_FILE" "$MATCHED_SLUG" "$ITEM_NAME" \
    > "${TMPDIR:-/tmp}/session-match-${CLAUDE_SESSION_ID:-$$}.txt"
```

### Substep 2c: Remove the matched item

**If `MATCHED_SOURCE="file"`** (legacy `session-open-*.md`):
```bash
IFS=$'\n' read -r MATCHED_SOURCE MATCHED_FILE MATCHED_SLUG ITEM_NAME \
    < "${TMPDIR:-/tmp}/session-match-${CLAUDE_SESSION_ID:-$$}.txt"
rm "$MATCHED_FILE"  # timeout: 5000
echo "deleted"
```

**If `MATCHED_SOURCE="context"`** (bullet in `session-context.md`):
Use Edit tool to remove the matched bullet line from `.claude/state/session-context.md`. Remove only the bullet matching `MATCHED_SLUG` — leave other bullets unchanged.

### Substep 2d: Append audit entry to resolution log

Ensure log directory exists:

```bash
mkdir -p .claude/logs # timeout: 5000
```

Append one-line JSON entry atomically with bash redirection, using `ITEM_NAME` resolved in Substep 2b. Entry format: `{"ts":"<ISO8601-UTC>","item":"<name>","action":"archived"}`

```bash
IFS=$'\n' read -r MATCHED_SOURCE MATCHED_FILE MATCHED_SLUG ITEM_NAME \
    < "${TMPDIR:-/tmp}/session-match-${CLAUDE_SESSION_ID:-$$}.txt"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# jq escapes ITEM_NAME safely; prevents injection
jq -n --arg ts "$TS" --arg item "$ITEM_NAME" '{"ts":$ts,"item":$item,"action":"archived"}' >> .claude/logs/session-archive.jsonl  # timeout: 5000
```

### Substep 2e: Confirm to user

Print: `Archived: $ITEM_NAME` (substituting the value resolved in Substep 2b) — one line, terminal only.

End with `## Confidence` block per quality-gates.md — score based on match quality (did fuzzy-match find right item; was archive entry written cleanly).

## Step 3 / Mode: summary (session digest)

### Substep 3a: Collect completed tasks

Call TaskList (or use TaskCreate/TaskUpdate context) to get tasks with status `completed` from this session. Extract subject lines.

### Substep 3b: Collect parked items

Read from two sources and merge:

1. **Current** (primary) — Read `.claude/state/session-context.md` if present (written by the `PreCompact` hook). Extract all bullets under the `## Parked items` heading; each bullet's slug and one-line description become a parked-item entry. If the file does not exist, skip silently.
2. **Legacy** (backwards-compat) — Derive MEMORY_DIR using canonical snippet from `<constants>`. Use Glob tool with pattern `session-open-*.md` in MEMORY_DIR to list candidates. Read each matched file with Read tool for `name` and `description`.

Combine both sources into a single parked-items list. De-duplicate by slug — when an item appears in both, prefer the `session-context.md` entry (newer, hook-maintained). Carry both into Substep 3e composition under the same `### Parked / Pending` section.

### Substep 3c: Collect recent git commits

```bash
OS=$(uname -s)
SINCE=$([ "$OS" = "Darwin" ] && date -u -v-8H '+%Y-%m-%dT%H:%M:%SZ' || date -u -d '8 hours ago' '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u '+%Y-%m-%dT%H:%M:%SZ')
git log --oneline --since="$SINCE" | head -20 || true # timeout: 3000; empty OK (no commits in window)
```

### Substep 3d: Collect archived items from this session

Use Read tool with `limit=20` on `.claude/logs/session-archive.jsonl` (skip if file does not exist).

Filter entries with `ts` matching today's date.

### Substep 3e: Compose and route the digest

Draft digest:

```markdown
## Session Summary — <date>

### Completed
- <task 1>
- <task 2>

### Parked / Pending (<N> items)
- [ ] <item> — <description>

### Archived this session
- <item> — <ts>

### Recent commits
- <hash> <message>
```

Output-routing rule: ≤ 10 lines → terminal only. If longer:

```bash
mkdir -p .temp/
OUTPUT=".temp/output-session-summary-$(date +%Y-%m-%d).md"
# anti-overwrite: increment counter
if [ -f "$OUTPUT" ]; then
    n=2
    while [ -f "${OUTPUT%.md}-$n.md" ]; do n=$((n + 1)); done
    OUTPUT="${OUTPUT%.md}-$n.md"
fi
```

Write to `$OUTPUT`, print compact terminal summary with `→ file`.

End with `## Confidence` block per quality-gates.md — score based on summary completeness (all completed tasks captured, parked items current, git log resolved).

Follow-up gate (`AskUserQuestion`):
(a) `/session archive <item>` — archive a completed item
(b) Add item to parking lot (specify which)
(c) Skip

</workflow>

<notes>

**`context: fork`** — reads/writes files only; fork avoids polluting parent context with file listings and session state.

**Automatic parking behavior (core behavioral rule — no command needed)**

During any session, Claude proactively appends open-loop items to **`.claude/state/session-context.md`** (the project-scoped state file maintained by the PreCompact hook) as they arise.

> **Why not auto-memory?** Project CLAUDE.md `Memory Policy` forbids auto-writes under `~/.claude/projects/.../memory/`. Session state belongs in the project-scoped state file so it stays with the repo, survives compaction, and never pollutes auto-memory. The `resume` / `archive` / `summary` modes above continue to read the **legacy** `session-open-*.md` files (created by older versions) for backwards compatibility, but **new items are never written there**.

| Item type | Trigger | Entry format |
| --- | --- | --- |
| Unanswered clarifying question | User sends new top-level request before answering Claude's prior clarifying question | `"User raised: <idea>. Pending: <question asked>."` |
| Deferred exploration | "let's come back to that", "park this for later", idea mentioned but not pursued | `"Deferred: <idea>. Context: <one sentence why deferred>."` |
| Diverging idea mid-task | New feature/design idea mentioned while solving something else | `"Side idea: <idea>. Raised while: <what we were doing>."` |

**Topic-shift detection rule**: trigger strictly behavioural — user submits new top-level request without answering Claude's prior question (not follow-up or clarification). No semantic similarity scoring.

**Entry format**: append a bullet under a `## Parked items` section (create the section if absent):

```markdown
## Parked items

- **<short slug>** — <one-line summary>. Raised: <YYYY-MM-DD>. Why: <one sentence>. How to apply: <what to ask or do when revisiting>.
```

Written to: `.claude/state/session-context.md` (project-local; tracked or gitignored per project policy).

**Pollution guard**: before parking new item, count bullets under `## Parked items`. If count ≥ 10, surface full list and ask user to archive some (via `/session archive <slug>`) before appending a new one.

**TTL policy**: items ≥ 14 days listed with `⚠ stale`. Items ≥ 30 days deleted silently during `resume`. TTL thresholds fixed global values — not configurable.

**Session-start behavior**: open-loop items NOT surfaced automatically at session start. Appear only when `/session resume` explicitly invoked. Don't add session-start hygiene step for this in CLAUDE.md.

**Resolution log**: `.claude/logs/session-archive.jsonl` is project-local, append-only. Stays in git-tracked project directory as audit trail; separate from home-scoped memory files intentionally.

**Scope**: parked ideas scoped to current project only — don't appear across projects. Project isolation enforced by file location (`.claude/state/session-context.md` lives inside the project's working tree).

</notes>
