---
name: resolve
description: "OSS maintainer fast-close workflow for GitHub PRs. Three phases: (1) PR intelligence — reads full thread, linked issues, PR body to synthesize contribution motivation and classify every comment into action items; (2) conflict resolution — checks out PR branch (fork-aware via gh pr checkout), merges BASE into it, resolves conflicts semantically using contributor's intent as priority lens; (3) implements each action item as separate attributed commit via Codex, pushes back to contributor's fork. Supports three source modes: pr (live GitHub comments only), report (latest /review report findings as action items, no GitHub re-fetch), and pr + report (both sources aggregated and deduplicated in one pass). Also accepts bare comment text for single-comment dispatch. NOT for reply drafting to /oss:analyse findings (use /oss:analyse --reply (requires `oss` plugin)). NOT for code diff review of PR changes (use /oss:review). NOT for release preparation (use /oss:release). NOT for fixing local bugs unrelated to a PR (use /develop:fix; requires develop plugin). TRIGGER when: PR is ready to close and has open comments, conflicts, or review findings to address; user says 'close this PR', 'resolve comments on PR #N', or 'implement review findings'."
argument-hint: "<PR number or URL> [report] | report | <review comment text>"
disable-model-invocation: true
model: sonnet
allowed-tools: Read, Edit, Write, Bash, Agent, TaskCreate, TaskUpdate, TaskList, AskUserQuestion
effort: high
---

<objective>

OSS maintainer fast-close workflow. PR number → three phases fire automatically:

1. **PR intelligence** — synthesize motivation from PR body, linked issues, thread; classify comments into action items
2. **Conflict resolution** — checkout PR branch (fork-aware), merge `BASE_REF`, resolve conflicts with contributor intent as priority lens
3. **Action item implementation** — implement each item as separate commit attributed to review comment, push to contributor's fork

Result: conflict-free PR branch pushed to fork, ready to merge — no GitHub UI.

**Core invariant — transparent and reversible**: every action = visible named git object. Use `git merge` (new commit, two parents), never `git rebase` (rewrites SHA, kills revert/cherry-pick). Each action item = own commit — granular revert always possible.

Bare comment text → skip to Codex dispatch (Step 12).

</objective>

<inputs>

- **$ARGUMENTS**: one of:
  - Omitted → **review-handoff mode**: auto-detect PR from most recent `.reports/review/*/review-report.md`
  - PR number (e.g. `42` or `#42`) or GitHub PR URL → **pr mode**
  - `report` (bare word) → **report mode**: latest review findings as action items; no GitHub re-fetch
  - `42 report` or `<URL> report` → **pr + report mode**: aggregate live GitHub comments + review report, deduplicated in one pass
  - Bare review comment text → **comment dispatch mode** (jumps to Step 12)
- **`--no-challenge`**: optional — skip challenge gate per item; all selected items treated as `VALID`
- **`--no-codemap`**: optional — disable codemap structural context (on by default when codemap installed + index present)
- **`--codemap`**: optional — strict mode: stop and report if codemap not installed or index missing
- **`--agent <name>`**: optional — use `<name>` agent for implementation instead of Codex; must be an implementation agent; bare name auto-prefixed with `foundry:` if no plugin prefix detected (e.g. `--agent sw-engineer` → `foundry:sw-engineer`; `--agent linting-expert` → `foundry:linting-expert`; `--agent doc-scribe` → `foundry:doc-scribe`); explicit prefix also accepted (`--agent foundry:sw-engineer`); see routing table in `action-item-dispatch.md`. **`--agent` also applies to `INTEL_AGENT` (Step 3b thread intelligence)** — explicit `--agent` overrides label/title routing for the thread-intelligence subagent as well, so a docs-focused PR routed via `--agent foundry:doc-scribe` uses doc-scribe for both classification and implementation.

NOT-for additions (scope guards):

- **NOT for non-Python source PRs** (TypeScript, Go, Rust, Java) unless action items are limited to documentation or CI/CD changes — Step 9's lint-qa gate runs Python-specific tools (`ruff`/`mypy`); non-Python PRs will receive partial or no static-analysis review. For non-Python repos, run `/oss:resolve` in `report` mode with manually-curated findings.
- **NOT for branches with uncommitted local edits** — the `report`-mode no-PR# path operates on the current branch as-is; uncommitted changes will be committed alongside the action items. Stash (`git stash`) or commit local edits before invoking; the workflow does not auto-stash.

</inputs>

<constants>
CHALLENGE_TIMEOUT_S=300  # tightened from CLAUDE.md §6 default 900s
CHALLENGE_POLL_S=90      # tightened from CLAUDE.md §6 default 300s
> Bash timeout convention — `# timeout: N` annotations in bash blocks are honored by the Claude Code
> Bash tool (sets tool-level timeout). Shell enforcement (`timeout S cmd` prefix) is NOT required for
> skills executed exclusively via Claude Code. Shell prefix added only for commands that could hang
> in direct-shell execution (git push, gh pr checkout).
</constants>

<workflow>

<!-- Symbol legend: ⚠ = warning/skipped (non-blocking, proceed with caution) · ⛔ = blocked/stop (halt workflow, do not proceed) -->

<!-- Agent resolution: see _OSS_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
# loads: oss-shared-resolver.md
# loads: review-section-taxonomy.md
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
_OSS_RESOLVE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_shared_path.py" oss skills/resolve 2>/dev/null)  # timeout: 5000
[ -z "$_OSS_RESOLVE" ] && _OSS_RESOLVE="plugins/oss/skills/resolve"
```
Read `$_OSS_SHARED/oss-shared-resolver.md` and execute its contents.

Read `$_OSS_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. foundry not installed → use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:doc-scribe`, `foundry:challenger`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:linting-expert → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. Per task:

- `completed` if done
- `deleted` if orphaned/irrelevant
- `in_progress` only if genuinely continuing

## Step 1: Pre-flight

Capture caller's branch first — needed for Step 11 restore even when Step 4 (`gh pr checkout`) is skipped or fails mid-checkout. Initialise here so the restore path in Step 11 is always well-defined:

```bash
SAVED_BRANCH=$(git branch --show-current 2>/dev/null || echo "")  # timeout: 3000
echo "$SAVED_BRANCH" > "${TMPDIR:-/tmp}/resolve-saved-branch"
```

Extracted to `bin/resolve_preflight.py` — checks codex availability, `gh` binary + auth, syncs with remote. Caches positive results under `.claude/state/preflight/` (4 h TTL). Writes `CODEX_AVAILABLE` and `GH_OK` to `${TMPDIR:-/tmp}/resolve-preflight-*` files; status messages go to stderr; exits non-zero only on hard failure (`gh` missing/unauthenticated, `git pull` conflict).

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_preflight.py"  # timeout: 30000
_PREFLIGHT_RC=$?
[ "$_PREFLIGHT_RC" -ne 0 ] && { echo "! BLOCKED — resolve_preflight.py failed (gh missing/unauthenticated or git pull conflict); cannot proceed"; exit 1; }
CODEX_AVAILABLE=$(cat "${TMPDIR:-/tmp}/resolve-preflight-CODEX_AVAILABLE" 2>/dev/null || echo "false")
GH_OK=$(cat "${TMPDIR:-/tmp}/resolve-preflight-GH_OK" 2>/dev/null || echo "true")
```

gh missing or not authenticated → script exits 1 (error printed above; eval skipped when exit code non-zero).

```bash
# Codemap auto-detect: on by default if installed; --no-codemap to opt out; --codemap = strict (stop if not installed)
# loads: detect_codemap.py — consumers: resolve/SKILL.md, review/SKILL.md
_DETECT_CODEMAP="${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/detect_codemap.py"
[ "$CODEMAP_FORCE_OFF" = "true" ] && _DETECT_FLAGS="--force-off" || _DETECT_FLAGS=""
[ "$CODEMAP_STRICT" = "true" ] && _DETECT_FLAGS="$_DETECT_FLAGS --strict"
python "$_DETECT_CODEMAP" --prefix resolve $_DETECT_FLAGS 2>&1  # timeout: 5000
[ $? -ne 0 ] && { echo "! BLOCKED — codemap strict mode requested but codemap not installed or index missing"; exit 1; }
CODEMAP_ENABLED=$(cat "${TMPDIR:-/tmp}/resolve-codemap-enabled" 2>/dev/null || echo "false")
CODEMAP_CURRENCY=$(cat "${TMPDIR:-/tmp}/resolve-codemap-currency" 2>/dev/null || echo "off")
```

**Codemap gates** — when `CODEMAP_FORCE_OFF=false`, read `$_OSS_SHARED/codemap-gates.md` and run: **Gate A** if `CODEMAP_ENABLED=false` (missing index → offer to build); **Gate B** if `CODEMAP_ENABLED=true` and `CODEMAP_CURRENCY=stale`. On a build choice, after `codemap:scan-codebase` set `CODEMAP_ENABLED=true`. Skip both gates when `CODEMAP_FORCE_OFF=true` (`--no-codemap`).

Codex missing: set `CODEX_AVAILABLE=false` — Steps 3–7 work without it. Step 8 degradation:
1. Simple, single-file items → `foundry:sw-engineer`
2. Complex/multi-file → skip with: `⚠ codex not found — skipping item #<id>. Install: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`

### Review-handoff auto-detect (when $ARGUMENTS is empty)

When `$ARGUMENTS` empty:

```bash
# written by /review to .reports/review/
REVIEW_FILE=$(ls -t .reports/review/*/review-report.md 2>/dev/null | head -1)
if [ -z "$REVIEW_FILE" ]; then
    echo "No review output found in .reports/review/ — run /review <PR#> first, or provide a PR number"
    exit 1
fi
echo "→ Using: $REVIEW_FILE"
```

Read `$REVIEW_FILE`. Extract PR number from header:

- Pattern: `## Code Review: PR #<N>` or `## Code Review: <N>`
- Grep: `grep -oE '(PR #|#)?[0-9]+' "$REVIEW_FILE" | head -1 | grep -oE '[0-9]+'`

PR found → set `$ARGUMENTS = <N>`, proceed PR mode. Print: `→ Resolved PR #<N> from review output.`

No PR number extractable → print: "Review output does not reference a PR — provide a PR number explicitly: `/oss:resolve <PR#>`" and exit 1.

Parse $ARGUMENTS:

```bash
[ -n "$CLAUDE_PLUGIN_ROOT" ] || { echo "Error: CLAUDE_PLUGIN_ROOT is unset — verify oss plugin installation and that skill is invoked via Claude Code plugin system"; exit 1; }  # timeout: 5000
[ -f "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.py" ] || { echo "Error: parse-resolve-args.py not found — verify oss plugin installation"; exit 1; }  # timeout: 5000
# parse-resolve-args.py does not handle codemap flags — strip before passing  # timeout: 3000
CODEMAP_FORCE_OFF=false; CODEMAP_STRICT=false
[[ " $ARGUMENTS " == *" --no-codemap "* ]] && CODEMAP_FORCE_OFF=true
[[ " $ARGUMENTS " == *" --codemap "* ]] && [[ " $ARGUMENTS " != *" --no-codemap "* ]] && CODEMAP_STRICT=true
ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--no-codemap//g; s/ --codemap / /g' | xargs)
# Defence-in-depth: validate every output line is plain VAR=value (no metacharacters) before sourcing.
# parse-resolve-args.py uses shlex.quote but this guards against future regressions or a tampered binary.
tmpenv=$(mktemp)  # timeout: 3000
trap 'rm -f "$tmpenv"' EXIT INT TERM
python "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.py" "$ARGUMENTS" >"$tmpenv"  # timeout: 5000
if grep -qvE "^[A-Z_][A-Z0-9_]*=([A-Za-z0-9_./:#@+-]*|'[^']*')$" "$tmpenv"; then
    echo "Error: parse-resolve-args.py emitted unexpected output — refusing to source"
    cat "$tmpenv"
    exit 1
fi
. "$tmpenv"
# sets: PR_NUMBER, PR_URL, MODE, ARGUMENTS (leading '#' stripped only for comment-dispatch)
```

<!-- branch: unsupported-flags — isolated; ≤1 call; fires only when unknown flags present -->
**Unsupported flag check** — after `eval`, scan remaining `$ARGUMENTS` for any `--<token>` not in `{--no-challenge, --agent, --codemap, --no-codemap}`. Found → invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown tokens). Supported: `--no-challenge`, `--agent <name>`, `--codemap`, `--no-codemap`.

- `MODE="pr+report"` → strip `report` suffix conceptually (already captured separately); find latest review report via `ls -t .reports/review/*/review-report.md 2>/dev/null | head -1`; no report found → warn but continue in pr mode
- `MODE="report"` → find latest review report via `ls -t .reports/review/*/review-report.md 2>/dev/null | head -1`; no report found → stop with: "No review report found in .reports/review/ — run /review \<PR#> first, or provide a PR number"; extract PR# from header if present; no PR# in header → add branch safety check before Step 8 — `CURRENT=$(git branch --show-current); DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||'); [ -z "$DEFAULT" ] && DEFAULT=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'); [ -z "$DEFAULT" ] && { printf "! BLOCKED — cannot determine default branch; refusing to proceed\n"; exit 1; }; [ "$CURRENT" = "$DEFAULT" ] && { echo "⛔ On default branch '$CURRENT' — report mode without PR# must not operate on default branch; check out a feature branch first"; exit 1; }`
- `MODE="pr"` → continue Step 2
- `MODE="comment-dispatch"` → branch safety check before Step 12: `CURRENT=$(git branch --show-current); DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||'); [ -z "$DEFAULT" ] && DEFAULT=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'); [ -z "$DEFAULT" ] && { printf "! BLOCKED — cannot determine default branch; refusing to proceed\n"; exit 1; }; [ "$CURRENT" = "$DEFAULT" ] && { echo "⛔ On default branch '$CURRENT' — comment dispatch must not commit to default branch"; exit 1; }` → jump to Step 12

## Step 2: Create initial task

```text
TaskCreate(
  subject="Resolve PR #<number> — gather action items",
  description="Fetch PR thread, linked issues, and/or review report; classify all comments into ACTION_ITEMS",
  activeForm="Gathering action items for PR #<number>"
)
```

Mark `in_progress` immediately:

```text
TaskUpdate(task_id=<task_id_from_above>, status="in_progress")
```

## Step 3a: Report intelligence (report mode only)
<!-- loads: report-intelligence.md -->

Read and execute `$_OSS_RESOLVE/modes/report-intelligence.md`.

## Step 3b: PR intelligence
<!-- loads: pr-intelligence.md -->

Read and execute `$_OSS_RESOLVE/modes/pr-intelligence.md`.

## Step 3c: Merge report findings (pr + report mode only)

*Skip when in pr mode.*

! NO user input in this step — deterministic merge only; Step 3d handles all user selection.

When mode == **pr + report**:

Find + read latest review report (`ls -t .reports/review/*/review-report.md 2>/dev/null | head -1`). Parse findings same as Step 3a.

**Deduplication**:

- Report finding matches GitHub item at same `file:line` → drop report item; annotate GitHub item with `(also flagged by /review)`
- Semantic match (same file, no exact line, similar description) → drop report item; same annotation
- No match → append report finding as `[report]` item

**Re-prefix GitHub items** in deduplication: `[gh][req]` stays `[gh][req]`; `[suggest]` → `[gh][suggest]`, `[question]` → `[gh][question]` if not already prefixed. GitHub items carry `[gh]` prefix in all modes — no change needed for items already classified with `[gh]` in Step 3b.

### Sources confirmation

Print Sources block (same format as Step 3a template; Mode=pr + report · PR=#<N> · GitHub=Read — PR body · <N> comments · <N> reviews · <N> inline code comments · Report=Read <path>) right before merge summary and action item table.

Result: single merged `ACTION_ITEMS`. GitHub items first (`[gh][req]`/`[gh][suggest]`), then `[report]` items. Print merge summary before table:

```text
Report merged: <N> findings from /review · <M> deduplicated against GitHub comments · <K> added as [report] items
```

Print merged ACTION_ITEMS as markdown table to terminal immediately after the merge summary (severity descending; same columns as pr-intelligence.md table):

> **Output-Routing exemption (canonical — applies to every ACTION_ITEMS table in this skill, Steps 3b/3c/3d)**: ACTION_ITEMS tables are selection-driving, read-in-context enumerations the user must see before the Step 3d picker. Always print inline to terminal regardless of row count. Global Output Routing (*5+ findings → `.temp/output-*.md`, summary only*) does **not** apply — never divert these tables to a file. This makes explicit what the global rule's own copy-intent override (*read-in-context, acted-on-immediately → terminal only even if long*) already implies.

```markdown
### Action Items — PR #<N> (merged)

| # | Type | Change | Severity | Author | Status | Summary | Loc | Notes |
|---|------|--------|----------|--------|--------|---------|-----|-------|
| 1 | [gh][req] | code | 4 | @reviewer | pending | rename param x to count | inline | — |
| 2 | [report][suggest] | docs | 2 | foundry:doc-scribe | pending | add docstring to Foo.bar | report | — |
```

**Author field rules** — Author = who owns fixing this item:
- `[gh]` items: GitHub reviewer's `@login`
- `[report]` items: Owner agent from taxonomy (e.g. `foundry:doc-scribe`, `foundry:qa-specialist`) — **never** the skill name `review` or `/review`

Summary ≤60 chars. Loc = inline / discussion / report. Notes = `—` when empty. Print only when merged ACTION_ITEMS has ≥1 row. The merged table is the authoritative set for Step 3d selection — it supersedes the pre-merge table shown in Step 3b.

## Step 3d: User item selection

<!-- branch: main-path — item-selection (call 1 of 4 on normal path; always fires in step 3d) -->
! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text.

Gather is complete here (3b/3c done). Mark the Step 2 gather task `completed` **before** the selection prompt — otherwise its `activeForm` ("Gathering action items for PR #<number>") keeps driving the spinner through the entire user-selection + commit-mode window, falsely implying gather is still running:

```text
TaskUpdate(task_id=<step2_task_id>, status="completed")
```

Pending items = ACTION_ITEMS where type ≠ `[done]` and type ≠ `[info]`. Zero pending → set `SELECTED_ITEMS` = all pending IDs, skip to Step 3e.

Sort all pending items by severity descending (most impactful first). Constraint: max 3 items/question, max 4 questions/call — Q1–Q3 = item checkboxes, Q4 = bulk action. Note: `AskUserQuestion` always appends "Type something" outside the option list — 3 items + Type something = 4 visible per page; keep ≤3 items per group.

**Q4 = bulk action — hard rule**: Q4 is always the last question, single-select, fixed options. Never put items in Q4. Items span ≤3 groups regardless of how many type categories exist.

```text
Q4 — multiSelect: FALSE (single-select only — user picks one bulk action, not a checklist)
"Q4 — Or choose a bulk action:"
  (a) +All [req] — implement all required items
  (b) +All [suggest] — implement all suggested items
  (c) ALL (req + suggest) — implement all pending items
  (d) Skip all — skip all items, exit
```

**Bulk-action resolution from Q4**:
- (a) → `SELECTED_ITEMS` = all `[req]` IDs; skip Call 2 in two-call flow; proceed to commit mode question
- (b) → `SELECTED_ITEMS` = all `[suggest]` IDs; skip Call 2 in two-call flow; proceed to commit mode question
- (c) → `SELECTED_ITEMS` = all pending [req+suggest] IDs; skip Call 2; proceed to commit mode question (do NOT hardcode `COMMIT_MODE` — scope and commit mode are orthogonal; user still chooses granularity)
- (d) → stop; print `→ All items skipped.`; jump to Step 11
- Q4 unanswered / "Type something" → use checked IDs from Q1–Q3; proceed to commit mode question; `COMMIT_MODE = each` (default)

**Item checkbox questions (Q1–Q3)**: each `multiSelect: true`, header "Items to implement:", labels: `<type> #<id>: <summary>` (≤55 chars), description: `<file:line> · @<author>` + for `location: discussion` items append `· thread (no GH resolve)`. Fill Q1→Q3 in severity order (≤3 items each). If >9 pending items: two calls — print `→ N pending items — selecting in 2 calls` before call 1; Call 2 gets remaining items + Q4 again; "ALL (req + suggest)" in Call 1 → skip Call 2.

**≥20 pending items — context-budget mode**: skip per-item checkboxes; print compressed table (type · id · summary ≤40 chars · file) **inline to terminal** (Output-Routing exemption from Step 3c applies — never divert to `.temp`) then Q4 only; follow with commit mode question unless (d) selected.

<!-- branch: main-path — commit-mode (call 2 of 4; skipped only when Q4=(d) skip) -->
**Commit mode follow-up** — ask immediately after Q4 resolves to (a), (b), (c), or unanswered (skip only when (d) skip-all). Commit mode is always the user's choice; item scope ((c) = all items) never implies a commit mode:

```text
AskUserQuestion: "Commit mode for selected items:"
  (a) Each item separately — one commit per action item (default)
  (b) By topic group — ask for topic labels; group related items into themed commits
  (c) All at once — single commit after all items
  (d) Stage only — no commits; stay staged on PR branch (⚠ cannot cleanly restore to $SAVED_BRANCH after Step 11)
```

**ESSENTIAL — all 4 options are mandatory; never emit fewer than 4.** Never merge this menu with Q4; these are commit MODES (how to commit), not item SCOPE (which items). Do not pull Q4 bulk-action options into this menu. Option (b) By topic group is a commit mode and must appear — do not drop it. LLMs tend to drop option (d) — do not omit it either.

Set `COMMIT_MODE`:
- (a) → `each`
- (b) → `grouped`
- (c) → `all`
- (d) → `stage`
- unanswered → `each` (default)

## Step 3e: Create tasks for selected items

> Step 2 gather task already marked `completed` at top of Step 3d.

For each item in `SELECTED_ITEMS`, call `TaskCreate` **once per item** — one task per action item; scoped to selected items only, not all pending (avoids bloat when 20+ items exist but only a subset is selected):

```text
TaskCreate(
  subject="<type> <summary> — PR #<number>",   # <type> = full string with brackets, e.g. "[gh][req] rename param — PR #42"
  description="Author: @<author> | Change: <change> | Severity: <severity> | File: <file:line or '—'> | <full_comment_text>",
  activeForm="Implementing: <summary>"          # <summary> truncated to 80 chars
)
```

Store returned task ID in each `SELECTED_ITEMS` entry as `task_id`. Then use the **Write tool** to persist the `{item_id: task_id}` map (you hold it in-context after the TaskCreate calls above) to `$IMPL_DIR/task-ids.json` as a JSON object, e.g. `{"3":"task_abc","7":"task_def"}`. The Step 8 subagent path (>20 items) reads this file to stamp `task_id` into `results.jsonl` for the orchestrator's post-return sweep; without it the sweep cannot map results back to tasks. (The ≤20 orchestrator-owned path updates tasks live from the in-memory `task_id` and does not read this file.) **Applies to `pr` and `pr+report` modes only** — these are the only modes that run Step 3b (which initialises `IMPL_DIR`) and Step 3e. `report` mode skips both steps and has no per-item tasks; do not write this file in report mode.

## Step 4: Checkout PR branch

*Skip only when `MODE = report` with no PR# (`$PR_NUMBER` unset — no remote branch to check out). In pr mode, runs unconditionally regardless of `SELECTED_ITEMS` — conflict resolution must happen even when 0 action items selected.*

**`gh` availability check** — hard prereq; `gh pr checkout` has no fallback path:

```bash
command -v gh >/dev/null 2>&1 || { echo "! BLOCKED — gh CLI required; install: https://cli.github.com"; exit 1; }  # timeout: 3000
```

**Branch-safety pre-check** — must run BEFORE `gh pr checkout` so a wrong-branch commit is impossible (per `git-commit.md` Gate 2). Verify the PR's `headRefName` is not the repo's default branch — `gh pr checkout` of a same-repo PR whose HEAD = default branch would land us on default and any later commit (Step 8) would violate Gate 2:

```bash
# local-first (no network); network fallback; hard-fail if neither resolves
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')  # timeout: 3000
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')  # timeout: 6000
[ -z "$DEFAULT_BRANCH" ] && { printf "! BLOCKED — cannot determine default branch; refusing to proceed\n"; exit 1; }
PR_HEAD_REF=$(gh pr view "<PR#>" --json headRefName --jq .headRefName 2>/dev/null)  # timeout: 6000
if [ "$PR_HEAD_REF" = "$DEFAULT_BRANCH" ]; then
    echo "⛔ PR HEAD ref ($PR_HEAD_REF) equals default branch — refusing to check out and commit on default branch"
    exit 1
fi
SAVED_BRANCH=$(git rev-parse --abbrev-ref HEAD)  # timeout: 3000
echo "$SAVED_BRANCH" > "${TMPDIR:-/tmp}/resolve-saved-branch"
# SHA-first checkout guard: skip if already at PR head. Avoids worktree conflict — gh pr checkout
# creates pr-N-slug alias when branch active in another worktree.
PR_HEAD_OID=$(gh pr view "<PR#>" --json headRefOid --jq .headRefOid 2>/dev/null)  # timeout: 6000
LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null)  # timeout: 3000
# diagnostic trace for reflog forensics (cf. investigate report 2026-06-13T11-00-00Z: pr195 alias when state opaque)
>&2 echo "→ Step 4 state: SAVED_BRANCH=$SAVED_BRANCH PR_HEAD_REF=$PR_HEAD_REF PR_HEAD_OID=${PR_HEAD_OID:-<empty>} LOCAL_SHA=${LOCAL_SHA:-<empty>}"
if [ -n "$PR_HEAD_OID" ] && [ "$LOCAL_SHA" = "$PR_HEAD_OID" ]; then
    echo "→ Already at PR head ($LOCAL_SHA) — skipping gh pr checkout"
    # SHA matches but caller may be on different branch name pointing at same OID
    # (e.g. prior gh pr checkout left pr<N> alias). Force-align to PR_HEAD_REF so
    # Step 8 commits + Step 10 push land on correct branch.
    CURRENT=$(git branch --show-current 2>/dev/null)
    if [ -n "$PR_HEAD_REF" ] && [ "$CURRENT" != "$PR_HEAD_REF" ]; then
        echo "→ Re-aligning local branch: $CURRENT → $PR_HEAD_REF (same SHA $LOCAL_SHA)"
        git switch "$PR_HEAD_REF" 2>/dev/null \
            || git switch -c "$PR_HEAD_REF" "$LOCAL_SHA" \
            || { echo "⛔ Cannot switch to $PR_HEAD_REF — aborting (branch active in another worktree?)"; exit 1; }
    fi
else
    # Hard-exit on checkout failure — silent failure leaves git on caller's branch while
    # $HEAD_REF is set, causing Step 8 commits to land on wrong branch.
    # --branch "$PR_HEAD_REF": without it, gh CLI v2.93+ falls back to pr<N> alias on name
    # collision → Step 10 push creates unrelated remote branch (CRITICAL bug pyDeprecate 2026-06-13T08:33Z).
    gh pr checkout <PR#> --branch "$PR_HEAD_REF" \
        || { echo "⛔ gh pr checkout failed — aborting (network, branch deleted, auth expired, or local conflicts)"; exit 1; }   # timeout: 15000
fi
```

`gh pr checkout` auto-handles forks — adds contributor's remote, configures tracking. Verify checkout landed on expected branch — if not, abort before Step 8 can commit:

```bash
git remote -v | grep '(fetch)' | head -10 # timeout: 3000
git status  # timeout: 3000
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)  # timeout: 3000
# Same-repo rule: local branch MUST equal PR_HEAD_REF — no aliases.
# gh CLI silently falls back to pr<N> on same-name collision; --branch above prevents it,
# but assert here as hard gate.
if [ "$IS_CROSS_REPO" = "false" ] && [ "$CURRENT_BRANCH" != "$PR_HEAD_REF" ]; then
    echo "⛔ SAME-REPO RULE VIOLATION: on '$CURRENT_BRANCH' but PR headRefName='$PR_HEAD_REF' — branch alias (pr<N>) created instead of using original branch. Aborting to prevent push to wrong branch."
    exit 1
fi
[ "$CURRENT_BRANCH" = "$HEAD_REF" ] || { echo "⛔ checkout did not land on $HEAD_REF (current: $CURRENT_BRANCH) — aborting before Step 8 can commit to wrong branch"; exit 1; }  # timeout: 3000
```

Determine `FORK_REMOTE` for push in Step 10:

```bash
IS_CROSS_REPO=$(gh pr view "<PR#>" --json isCrossRepository --jq .isCrossRepository 2>/dev/null || echo false) # timeout: 6000
if [ "$IS_CROSS_REPO" = "true" ]; then
    FORK_REMOTE=$(gh pr view "<PR#>" --json headRepositoryOwner --jq .headRepositoryOwner.login) # timeout: 6000
else
    FORK_REMOTE="origin"
fi
# soft-verify — gh pr checkout layouts vary across versions
git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 \
    || echo "⚠ Remote $FORK_REMOTE not registered — Step 10 will add it before push" # timeout: 3000
```

`FORK_REMOTE`: contributor login (e.g. `alice`) for forks, `origin` for same-repo. Push always `git push` — tracking configured by `gh pr checkout`.

## Steps 5–7: Conflict detection, context, and resolution
<!-- Steps 5–7 defined in conflict-resolution.md — see that file for sub-step numbering -->

Read and execute `$_OSS_RESOLVE/modes/conflict-resolution.md`.

## Step 8: Implement action items

*Skip when `SELECTED_ITEMS` is empty — jump to Step 9.*

**Soft cap: 8 Codex dispatches per session** — Codex-specific. Skip this cap entirely when `--agent <name>` is set and the resolved agent is not `codex:codex-rescue` (other implementation agents have no per-session dispatch ceiling here):

```bash
# computed here (resolved fully in action-item-dispatch.md) to branch on cap threshold
_RESOLVE_IMPL_AGENT="codex:codex-rescue"
[[ "$ARGUMENTS" == *"--agent "* ]] && _RESOLVE_IMPL_AGENT=$(echo "$ARGUMENTS" | grep -oP '(?<=--agent )\S+')
if [ "$_RESOLVE_IMPL_AGENT" = "codex:codex-rescue" ] && [ "$(echo "$SELECTED_ITEMS" | wc -w)" -gt 8 ]; then
    :
fi
```

<!-- branch: codex-cap — only when codex agent AND N>8 items; adds 1 call (max 5 if user proceeds; worst case = item-select + commit-mode + codex-cap + push-auth + post-pr) -->
If `_RESOLVE_IMPL_AGENT = codex:codex-rescue` AND `SELECTED_ITEMS` has > 8 items, invoke `AskUserQuestion`: "N items selected — Codex cap is 8 per session. Split into batches?" Options: (a) Apply first 8 now, re-run for remainder · (b) Apply all [req] only (if ≤8) · (c) Proceed anyway (sequential, may be slow). For non-Codex agents (`--agent foundry:sw-engineer`, `--agent foundry:linting-expert`, etc.): skip this gate; proceed with all selected items sequentially.

**Structural context (codemap — if `CODEMAP_ENABLED=true`)**: before reading action-item-dispatch.md, query blast radius of modules affected by selected items:

```bash
CODEMAP_ENABLED=$(cat "${TMPDIR:-/tmp}/resolve-codemap-enabled" 2>/dev/null || echo false)  # timeout: 3000
if [ "$CODEMAP_ENABLED" = "true" ]; then
    _IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
    _PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename | tr -cd 'a-zA-Z0-9._-')
    scan-query rdeps --top 10 2>/dev/null || true  # timeout: 5000
fi
```

If codemap output returned: prepend `## Structural Context (codemap)` block to each implementation agent prompt in action-item-dispatch.md — blast radius, top callers, coupling pairs.

<!-- Step 8 defined in action-item-dispatch.md + dispatch-runner.md -->
<!-- loads: dispatch-runner.md -->

Read `$_OSS_RESOLVE/modes/action-item-dispatch.md`; execute its prelude (IMPL_AGENT routing, IMPL_DIR init, blast-radius scan). Then choose **one** loop path below — do NOT run the per-item loop body from the load step unconditionally.

**Default — orchestrator owns the per-item loop (`SELECTED_ITEMS` ≤ 20).** Run the `action-item-dispatch.md` loop directly: per item, `TaskUpdate(in_progress)` → challenge → impl → commit → `TaskUpdate(completed)`. This is the path that gives the user **live per-item progress** — each task flips as work starts and finishes. Do NOT delegate to the dispatch subagent at this size; a subagent cannot drive the parent's task list, so delegating freezes all per-item tasks until return. The ≤20 cap matches the Step 8 hard cap in `action-item-dispatch.md` (>20 is gated by AskUserQuestion to split or proceed).

**Step 8 batch dispatch (only when `SELECTED_ITEMS` > 20 and the user chose "proceed with all")** — at this size the orchestrator context cannot hold the full loop; delegate to a dedicated subagent. Per-item live `TaskUpdate` is not possible on this path (subagent constraint); the orchestrator runs a post-return sweep instead (see below). Spawn shape:

```text
Agent(subagent_type="foundry:sw-engineer", prompt="Read $_OSS_RESOLVE/modes/dispatch-runner.md and execute with these variables:
SELECTED_ITEMS='$SELECTED_ITEMS'
COMMIT_MODE='$COMMIT_MODE'
IMPL_AGENT='$IMPL_AGENT'
IMPL_DIR='$IMPL_DIR'
PR_NUMBER='$PR_NUMBER'
PR_AUTHOR='$PR_AUTHOR'
BLAST_RADIUS_CONTEXT='$BLAST_RADIUS_CONTEXT'
NO_CHALLENGE='$NO_CHALLENGE'
CODEX_AVAILABLE='$CODEX_AVAILABLE'
CLAUDE_PLUGIN_ROOT='$CLAUDE_PLUGIN_ROOT'
RESOLVE_TASK_IDS_FILE='$IMPL_DIR/task-ids.json'
Return compact JSON envelope when done.")
```

Parse result envelope; use `results_file` and `challenge_log_file` paths for Step 11 report.

**Post-return TaskUpdate sweep (>20 subagent path only)** — the dispatch subagent cannot call `TaskUpdate`, so it leaves every per-item task `pending`. After parsing the envelope, read `results.jsonl` and flip each task to its terminal state so the list reflects what happened (the ≤20 orchestrator path already updated tasks live and skips this):

```bash
jq -rc 'select(.task_id != "null" and .task_id != null) | "\(.task_id) \(.status)"' "$IMPL_DIR/results.jsonl"  # timeout: 5000
```

For each `task_id status` line: `committed`/`staged` → `TaskUpdate(task_id=<id>, status="completed")`; `skipped`/`error` → `TaskUpdate(task_id=<id>, status="completed")` (terminal; note outcome in Step 11 report — the task list has no failed state). Any selected item whose `task_id` is `null` (map miss) → surface in the report rather than silently leaving it `pending`.

## Step 9: Lint and QA gate

Read and execute `$_OSS_RESOLVE/modes/lint-qa-gate.md`.

## Step 10: Push

*Skip when report mode with no PR# (`$FORK_REMOTE`, `$HEAD_REF`, `$BASE_REF` unset — no fork branch; workflow ends at Step 11).*

```bash
if ! git remote get-url "$FORK_REMOTE" &>/dev/null; then # timeout: 3000
    REPO_NAME=$(git remote get-url origin | sed 's|.*/||' | sed 's|\.git$||')
    ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")
    # mirror SSH vs HTTPS — SSH-only contributors have no HTTPS credentials; hardcoding HTTPS breaks push silently
    if [[ "$ORIGIN_URL" == git@* ]]; then
        FORK_URL="git@github.com:$FORK_REMOTE/$REPO_NAME.git"
    else
        FORK_URL="https://github.com/$FORK_REMOTE/$REPO_NAME.git"
    fi
    git remote add "$FORK_REMOTE" "$FORK_URL" # timeout: 3000
    echo "→ Added remote $FORK_REMOTE → $FORK_URL"
fi
git branch --set-upstream-to="$FORK_REMOTE/$HEAD_REF" 2>/dev/null || true # timeout: 3000
PUSH_COUNT=$(git rev-list "$FORK_REMOTE/$HEAD_REF..HEAD" --count 2>/dev/null || git rev-list "origin/$BASE_REF..HEAD" --count) # timeout: 3000
PUSH_STAT=$(git diff "$FORK_REMOTE/$HEAD_REF..HEAD" --stat 2>/dev/null | tail -1 || git diff "origin/$BASE_REF..HEAD" --stat | tail -1) # timeout: 3000
LAST_SUBJECT=$(git log -1 --format=%s 2>/dev/null) # timeout: 3000
echo "→ $PUSH_COUNT commits ready to push to $FORK_REMOTE/$HEAD_REF ($PUSH_STAT); last commit: \"$LAST_SUBJECT\""
```

<!-- branch: main-path — push-auth (call 3 of 4 normal / 4 of 5 with codex-cap) -->
**Push authorization gate** — per `git-commit.md` push-safety rule ("Never push without explicit user confirmation"), invoke `AskUserQuestion` before any `git push`. The question must surface:

- Target remote and branch: `$FORK_REMOTE/$HEAD_REF`
- Diff stat: `$PUSH_STAT` (e.g. `3 files changed, 47 insertions(+), 12 deletions(-)`)
- Commit count and last subject: `$PUSH_COUNT commits — last: "$LAST_SUBJECT"`

Options:

- (a) **Push** — proceed with `git push` below (default)
- (b) **Skip push** — stop after Step 9; user pushes manually later

Only proceed to the `git push` below on option (a). On option (b): print `→ Push skipped — run \`git push\` manually when ready.` and jump to Step 11.

```bash
git push # timeout: 30000
```

Push rejected → fallback:

```bash
git push "$FORK_REMOTE" HEAD:"$HEAD_REF" # timeout: 30000
```

Verify push reached GitHub — confirm latest commit headlines match what was committed:

```bash
gh pr view <PR_NUMBER> --json headRefOid,commits --jq '.commits[-3:] | .[].messageHeadline' # timeout: 6000
```

## Step 11: Final report

Mark remaining open tasks `completed`. Read report template from `$_OSS_RESOLVE/templates/resolve-report.md` for section structure.

**Action Items table** — one row per selected item, columns: `#` | `Type` | `Change` | `Status` | `Resolution` | `Commit`:

- `Status`: ✓ implemented · ⊘ skipped · ✗ challenge-rejected
- `Resolution`: `implemented` · `self-resolved` (challenger provided alternative) · `skipped` · `challenge-rejected`
- `Change`: action type — `code` / `test` / `docs` / `config` / `ci` / `style` / `refactor`
- `Commit`: short SHA (7 chars); `—` when `COMMIT_MODE=stage`
- For `location: discussion` rows append `· thread (no GH resolve)` to Status — no GitHub Resolve button exists for PR main-thread comments

Include `### Challenge Log` section in report — one row per item: id · evidence verdict · suggestion verdict · resolution (as-suggested / self-resolved / rejected). Omit section when `--no-challenge`.

```bash
SAVED_BRANCH=$(cat "${TMPDIR:-/tmp}/resolve-saved-branch" 2>/dev/null || echo "")
# skip restore when COMMIT_MODE=stage — staged changes would be lost
if [ "$COMMIT_MODE" = "stage" ]; then
    echo "⚠ COMMIT_MODE=stage: changes are staged on $(git branch --show-current) — restore to $SAVED_BRANCH skipped to preserve staged work. Run: git stash && git switch $SAVED_BRANCH && git stash pop (on PR branch) when ready."
elif [ -n "$SAVED_BRANCH" ]; then
    git switch "$SAVED_BRANCH" 2>/dev/null && echo "→ Restored to $SAVED_BRANCH"  # timeout: 5000
fi
```

<!-- branch: main-path — post-pr (call 4 of 4 normal / 5 of 5 with codex-cap) -->
Invoke `AskUserQuestion` — options: (a) Open PR in browser (`gh pr view <PR_NUMBER> --web`) · (b) Merge now (`gh pr merge <PR_NUMBER> --merge`) · (c) Skip.

## Step 12: Comment dispatch + Codex review loop

Read and execute `$_OSS_RESOLVE/modes/comment-dispatch.md`.

</workflow>

<calibration>

Non-calibratable — `disable-model-invocation: true` means skill dispatches to sub-agents rather than running model pass directly; calibrate cannot score model output for skill that produces none.

</calibration>

<notes>

- **Pre-flight git fetch** — Step 1 always runs `git fetch origin` (unconditional) so all remote tracking refs — including `origin/$BASE_REF` — are current before Step 5 merges. Then pulls current branch if upstream tracking ref exists and remote is ahead. `git pull` conflicts → exit with message to resolve manually — prevents `git merge --continue` with no in-progress merge
- **Branch safety** — `gh pr checkout <PR#>` always lands on PR's HEAD, never `main`/`master`. Never push to default branch — if PR branch = default branch, abort and surface.
- **Same-repo branch rule** — for non-fork PRs (`isCrossRepository=false`), local branch name MUST equal `headRefName` at all times. Never create a `pr<N>` alias or any other branch name substitute. Enforced by `--branch "$PR_HEAD_REF"` at checkout + hard assertion post-checkout. Rationale: `git push HEAD:$HEAD_REF` on a `pr<N>` alias creates a new remote branch instead of pushing to the PR head — silent data-loss class bug.
- **OSS fork support** — `gh pr checkout <PR#>` works same for branches + forks; forks get contributor remote + tracking; plain `git push` targets fork branch automatically.
- **Merge direction** — `origin/BASE_REF` INTO `HEAD_REF` (not reverse); PR branch = source of truth; maintainer still clicks Merge.
- **Contribution motivation before code** — "whose intent wins" lens; PR body + linked issues reveal constraints invisible in diff.
- **`[question]` items** — answer inline in resolve report only; reclassify before implementing; never silently implement unanswered question.
- **Push verification** — confirm via `gh pr view --json commits`; exit 0 from `git push` necessary but not sufficient (branch protection can silently reject).
- **Merge-push sequencing + escape hatch** — not atomic; concurrent push → non-fast-forward rejection; retry push only (don't re-run full merge). `git merge --abort` = undo conflict state; `git push --force-with-lease` on explicit user request only.
- **`gh pr merge` flags**: `--merge` = preserves all commits; `--squash` = collapses; never `--rebase` (rewrites SHAs); default `--merge`.
- **Impl agent health + effort**: IMPL_AGENT defaults to `codex:codex-rescue` (CLAUDE.md §6 — 15-min cutoff, ⏱ on timeout). Effort: never `low`; minimum `medium`; typo/doc → `medium`; multi-file/new-feature → `xhigh`; default `high`. `--agent foundry:*`: foreground only, no health monitoring.
- **Two-phase challenge**: evidence = problem exists?; suggestion = fix quality?; evidence reject → skip; suggestion reject → self-resolved via `alternative` field; all in `CHALLENGE_LOG` + Step 11 report.
- **COMMIT_MODE**: `each` (default); `all`; `stage` (⚠ branch restore skipped); `grouped` (falls back to `each` when labels skipped). Set via a separate `AskUserQuestion` (Step 3d, "call 2 of 4") issued after Q4 resolves to (a), (b), (c), or unanswered — skipped only when Q4=(d) skip-all — distinct from Q4 (which sets item scope, not commit strategy). Item scope never implies a commit mode. Do not merge these two questions.
- **AskUserQuestion usage**: 10 total calls across all paths. Normal path: 4 calls (Steps 3a, 3d, per-item challenge, Step 11); worst-case path: 5 calls when codex-cap fires (N>8 items + codex available adds 1 call). <!-- worst-case path: 5 calls (with codex-cap) -->
- **`--agent <name>`**: bare name auto-prefixed `foundry:`; must be implementation agent (not curator); omit Codex trailer when IMPL_AGENT ≠ `codex:codex-rescue`.
- **Thread resolution via GraphQL** — `isResolved` on `PullRequestReviewThread` (GraphQL only); REST not expose it. `RESOLVED_THREAD_IDS` = root comment `databaseId`; GraphQL failure → `[]`.
- **Discussion vs inline**: `gh pr view --comments` = discussion (`location: discussion`; no Resolve button); `gh api .../pulls/<N>/comments` = inline (`location: inline`; resolvable). `location: discussion` + `[report]` items: implement-only, no GitHub close action. Surface `Loc` column in Step 11 report.
- **Commit attribution** — `[gh]`: `[resolve #<id>] @<reviewer> (gh):`; `[report]`: `[resolve #<id>] /review finding by <agent> (report: <path>):`.
- **Reference scenarios**: Mode: bare PR# → pr; `42 report` → pr+report; `report` → report mode; bare comment → comment dispatch. Classification: LGTM/emoji → `[info]`; `nit:` → `[gh][suggest]`; resolved thread → `[done]`; "must fix" from write-access reviewer → `[gh][req]`. Challenge: present bug → VALID; already addressed → REJECT; better alternative → REJECT with alternative.
- Follow-up chains:
  - After push → maintainer reviews + clicks Merge; never approve/comment on PR.
  - Unanswered `[question]` → resolve report only; do NOT post to PR.
  - After merge → `Closes #N`/`Fixes #N` in body auto-closes linked issues; absent keywords → surface gap under `### Closing Keywords` note; do not edit PR body.

</notes>
