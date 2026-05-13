---
name: resolve
description: "OSS maintainer fast-close workflow for GitHub PRs. Three phases: (1) PR intelligence — reads full thread, linked issues, PR body to synthesize contribution motivation and classify every comment into action items; (2) conflict resolution — checks out PR branch (fork-aware via gh pr checkout), merges BASE into it, resolves conflicts semantically using contributor's intent as priority lens; (3) implements each action item as separate attributed commit via Codex, pushes back to contributor's fork. Supports three source modes: pr (live GitHub comments only), report (latest /review report findings as action items, no GitHub re-fetch), and pr + report (both sources aggregated and deduplicated in one pass). Also accepts bare comment text for single-comment dispatch. NOT for drafting contributor replies (use /oss:analyse --reply). NOT for release preparation (use /oss:release)."
argument-hint: '<PR number or URL> [report] | report | <review comment text>'
disable-model-invocation: true
effort: high
when_to_use: Use to implement GitHub PR review comments and push fixes back to contributor's fork; NOT for drafting replies (use /oss:analyse --reply) or fixing local bugs (use /develop:fix; requires develop plugin).
allowed-tools: Read, Edit, Write, Bash, Agent, TaskCreate, TaskUpdate, TaskList, AskUserQuestion
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
  - Omitted → **review-handoff mode**: auto-detect PR from most recent `.temp/output-review-*.md`
  - PR number (e.g. `42` or `#42`) or GitHub PR URL → **pr mode**
  - `report` (bare word) → **report mode**: latest review findings as action items; no GitHub re-fetch
  - `42 report` or `<URL> report` → **pr + report mode**: aggregate live GitHub comments + review report, deduplicated in one pass
  - Bare review comment text → **comment dispatch mode** (jumps to Step 12)
- **`--no-challenge`**: optional — skip Step 3d entirely; all pending items treated as `VALID` (no challenge run)

</inputs>

<constants>
CHALLENGE_TIMEOUT_S=300   <!-- tightened from CLAUDE.md §8 default 900s -->
CHALLENGE_POLL_S=90       <!-- tightened from CLAUDE.md §8 default 300s -->
</constants>

<workflow>

<!-- Symbol legend: ⚠ = warning/skipped (non-blocking, proceed with caution) · ⛔ = blocked/stop (halt workflow, do not proceed) -->

<!-- Agent Resolution: canonical table at plugins/oss/skills/_shared/agent-resolution.md -->

## Agent Resolution

# Read $_OSS_SHARED/oss-shared-resolver.md and execute its contents
# Cold-start fallback (if shared resolver unreadable):
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"

```bash
_OSS_RESOLVE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/resolve 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_OSS_RESOLVE" ] && _OSS_RESOLVE="plugins/oss/skills/resolve"
```

Read `$_OSS_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. foundry not installed → use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:linting-expert → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. Per task:

- `completed` if done
- `deleted` if orphaned/irrelevant
- `in_progress` only if genuinely continuing

## Step 1: Pre-flight

```bash
# From plugins/foundry/skills/_shared/preflight-helpers.md — TTL 4 hours, keyed per binary
preflight_ok() {
    local f=".claude/state/preflight/$1.ok"
    [ -f "$f" ] && [ $(($(date +%s) - $(cat "$f"))) -lt 14400 ]
}
preflight_pass() {
    mkdir -p .claude/state/preflight
    date +%s >".claude/state/preflight/$1.ok"
}

# codex — optional; intelligence + conflict resolution work without it
CODEX_AVAILABLE=false
if preflight_ok codex; then
    CODEX_AVAILABLE=true && echo "codex (openai-codex): ok (cached)"
elif claude plugin list 2>/dev/null | grep -q 'codex@openai-codex'; then # timeout: 15000
    preflight_pass codex && CODEX_AVAILABLE=true && echo "codex (openai-codex): ok"
else
    echo "codex (openai-codex): missing — complex multi-file action items will be skipped; simple items implemented via foundry:sw-engineer (see Step 8 degradation)"
fi

# gh binary + auth — required; cached for 4h (auth won't change within a session)
if preflight_ok gh; then
    echo "gh: ok (cached)"
elif which gh &>/dev/null && gh auth status &>/dev/null; then
    preflight_pass gh && echo "gh: ok ($(gh auth status 2>&1 | grep 'Logged in' | head -1 | xargs))"
elif which gh &>/dev/null; then
    echo "Pre-flight failed: gh found but not authenticated — run: gh auth login" && exit 1
else
    echo "Pre-flight failed: gh not found — install: brew install gh" && exit 1
fi

# Show current remotes — confirms we are in the right repo and surfaces any existing fork remotes
git remote -v # timeout: 3000

# Sync with remote — prevents git merge --continue from being called out of state
UPSTREAM=$(git rev-parse --abbrev-ref @{u} 2>/dev/null)
if [ -n "$UPSTREAM" ]; then
    git fetch origin 2>/dev/null || true # timeout: 6000
    REMOTE_AHEAD=$(git log HEAD..@{u} --oneline 2>/dev/null | wc -l | tr -d ' ')
    if [ "$REMOTE_AHEAD" -gt 0 ]; then
        echo "Remote is $REMOTE_AHEAD commit(s) ahead — running git pull..."
        git pull || {
            echo "Pre-flight failed: git pull had conflicts — resolve manually before running /resolve"
            exit 1
        } # timeout: 6000
        echo "✓ git pull: merged"
    else
        echo "✓ git: up to date"
    fi
fi
```

gh missing or not authenticated → stop (error printed above).

Codex missing: set `CODEX_AVAILABLE=false` — Steps 3–7 work without it. Step 8 degradation:
1. Simple, single-file items → `foundry:sw-engineer`
2. Complex/multi-file → skip with: `⚠ codex not found — skipping item #<id>. Install: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`

### Review-handoff auto-detect (when $ARGUMENTS is empty)

When `$ARGUMENTS` empty:

```bash
# Find most recent review output (written by /review to .temp/)
REVIEW_FILE=$(ls -t .temp/output-review-*.md 2>/dev/null | head -1)
if [ -z "$REVIEW_FILE" ]; then
    echo "No review output found in .temp/ — run /review <PR#> first, or provide a PR number"
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
[ -f "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.sh" ] || { echo "Error: parse-resolve-args.sh not found — verify oss plugin installation"; exit 1; }  # timeout: 5000
eval "$(bash "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.sh" "$ARGUMENTS")"
# sets: PR_NUMBER, PR_URL, MODE, ARGUMENTS (leading '#' stripped only for comment-dispatch)
```

**Unsupported flag check** — after `eval`, scan remaining `$ARGUMENTS` for any `--<token>` not equal to `--no-challenge`. Found → invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown tokens). Supported: `--no-challenge`.

- `MODE="pr+report"` → strip `report` suffix conceptually (already captured separately); find latest review report via `ls -t .temp/output-review-*.md 2>/dev/null | head -1`; no report found → warn but continue in pr mode
- `MODE="report"` → find latest review report via `ls -t .temp/output-review-*.md 2>/dev/null | head -1`; no report found → stop with: "No review report found in .temp/ — run /review \<PR#> first, or provide a PR number"; extract PR# from header if present; no PR# in header → add branch safety check before Step 8 — `CURRENT=$(git branch --show-current); DEFAULT=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'); [ "$CURRENT" = "$DEFAULT" ] && { echo "⛔ On default branch '$CURRENT' — report mode without PR# must not operate on default branch; check out a feature branch first"; exit 1; }`
- `MODE="pr"` → continue Step 2
- `MODE="comment-dispatch"` → branch safety check before Step 12: `CURRENT=$(git branch --show-current); DEFAULT=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'); [ "$CURRENT" = "$DEFAULT" ] && { echo "⛔ On default branch '$CURRENT' — comment dispatch must not commit to default branch"; exit 1; }` → jump to Step 12

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

*Skip to Step 3b (PR intelligence) when in pr mode or pr + report mode.*

<!-- Sources block template (used in 3a/3b/3c): fields GitHub and Report vary by mode -->

When mode == **report**:

Print Sources block before parsing findings:

```markdown
## Resolve — sources

Mode   : report
PR     : #<N>  (extracted from report header, or "n/a — working on current branch")
GitHub : not fetched
Report : Read <path to report file>

Building action items…
```

Read report. Parse findings from each `###` header (`### [blocking] Critical`, `### Architecture & Quality`, `### Test Coverage Gaps`, `### Performance Concerns`, `### Documentation Gaps`, `### Static Analysis`, `### API Design`, `### Codex Co-Review`). Skip `### OSS Checks`, `### Recommended Next Steps`, `### Review Confidence`, `### Issue Root Cause Alignment`.

Map each finding to action item schema:

| Severity in report | `type` |
| --- | --- |
| CRITICAL or `[blocking]` | `[req]` |
| HIGH | `[req]` |
| MEDIUM | `[suggest]` |
| LOW | `[suggest]` (omit if total items > 10) |

- `author`: section owner agent (e.g., `foundry:sw-engineer` for Architecture, `foundry:qa-specialist` for Test Coverage)
- `file`/`line`: extract from `file:line` notation; blank if absent
- `full_comment_text`: full finding bullet
- All items get `[report]` prefix on `type` (e.g., `[report][req]`, `[report][suggest]`)

PR# found in report header → set `$ARGUMENTS = <N>`, go to Step 4; skip Step 3b entirely. After checkout, skip to Step 8 with report-derived action items.

No PR# in header → skip Steps 3b and 4; work on current branch as-is. Skip to Step 8 with report-derived action items.

## Step 3b: PR intelligence

Fetch full PR metadata in one call:

```bash
gh pr view <PR_NUMBER> \
    --json number,title,body,author,labels,isDraft,state,headRefName,baseRefName,headRepositoryOwner,headRepository,isCrossRepository,url,closingIssuesReferences
```

Extract and record:

- `HEAD_REF` — source branch name (`.headRefName`)
- `BASE_REF` — target branch name (`.baseRefName`, e.g. `main`, `develop`)
- `PR_AUTHOR` — contributor's GitHub login (`.author.login`)
- `HEAD_REPO_OWNER` — owner of fork/head repo (`.headRepositoryOwner.login`)
- `BASE_REPO_OWNER` — owner of base repo; from `.url` via `split("/")[3]` or `gh repo view --json owner -q .owner.login`
- `IS_FORK` — `.isCrossRepository` (`true` = fork PR, `false` = same-repo branch)
- `CLOSING_ISSUES` — linked issue numbers (`.closingIssuesReferences[].number`)

Fetch full discussion:

```bash
gh pr view <PR_NUMBER> --comments                        # PR-level comments + timeline
gh api repos/{owner}/{repo}/pulls/<PR_NUMBER>/reviews  # formal reviews (Approve / Request Changes)
gh api repos/{owner}/{repo}/pulls/<PR_NUMBER>/comments # inline code comments with file + line
```

Fetch resolved thread status via GraphQL (`isResolved` not in REST `/pulls/{PR}/comments`):

```bash
REPO_OWNER=$(gh repo view --json owner --jq .owner.login 2>/dev/null || echo "$BASE_REPO_OWNER")  # timeout: 6000
REPO_NAME=$(gh repo view --json name --jq .name 2>/dev/null)  # timeout: 6000
RESOLVED_THREAD_IDS=$(gh api graphql \
  -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{isResolved,comments(first:1){nodes{databaseId}}}}}}}' \
  -f owner="$REPO_OWNER" \
  -f repo="$REPO_NAME" \
  -F pr="$PR_NUMBER" \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved) | .comments.nodes[0].databaseId]' \
  2>/dev/null || echo "[]")  # timeout: 15000
[ "$RESOLVED_THREAD_IDS" = "[]" ] && echo "⚠ Could not fetch resolved thread status — some action items may already be resolved on GitHub; review the table carefully before implementing"
```

Non-empty `CLOSING_ISSUES` → fetch each linked issue:

```bash
gh issue view <ISSUE_NUMBER> --json title,body
```

### Synthesize contribution motivation

Read PR title, body, linked issues, commits. Produce 2–3 sentence paragraph:

- What problem/gap contributor solving (linked issues or PR description)
- Why they chose this approach (PR body, design notes in commits)
- Expected user-visible outcome

Motivation = **priority lens for conflict resolution** in Step 7 — whose logic wins when both sides touched same area.

### Classify action items

Read every comment, review, inline code comment. Per inline code comment: if its `id` (REST response field `id`, same value as `databaseId` in GraphQL) appears in `RESOLVED_THREAD_IDS` → classify as `[done]` immediately without reading thread content. All others, apply table below:

| Code | Meaning |
| --- | --- |
| `[gh][req]` | Change **required** before merge — requested by reviewer with write access or maintainer |
| `[gh][suggest]` | Improvement suggested — nice-to-have, non-blocking |
| `[gh][question]` | Open question needing answer before deciding what code to write |
| `[done]` | Review thread marked resolved on GitHub (`isResolved=true`) OR subsequent commit/reply already addressed — skip |
| `[info]` | Praise, acknowledgement, emoji-only — skip |
| `[self-review]` | Finding from `/oss:review` report — not a GitHub commenter; author = agent name |

Build `ACTION_ITEMS`: `[{id, type, author, summary, file, line, url, full_comment_text}]` — `url`: `html_url` from GitHub API response; blank for report items

### Sources confirmation

Print Sources block (same format as Step 3a template; Mode=pr · PR=#<N> · GitHub=Read — PR body · <N> comments · <N> reviews · <N> inline code comments · Report=not used) right before action item table.

Print action item table — **MUST render as markdown table; never use key-value list, prose, or separator-delimited format regardless of cell length**. Mandatory per-cell truncation (truncate with `…`, never wrap or split):

- **Summary**: ≤60 chars — truncate at word boundary, append `…`
- **Comment**: markdown link `[↗](<html_url>)` from GitHub API `html_url` field; `—` when absent (report items or no inline URL)
- **Notes**: ≤45 chars — truncate; full text preserved in `full_comment_text`; use `—` when empty

Status codes: `pending` · `✓ resolved` · `⊘ skipped` · `⊘ no action`. Verbose reason → Notes column:

```markdown
### Action Items — PR #<number>

| # | Type | Author | Status | Summary | Comment | Notes |
|---|------|--------|--------|---------|---------|-------|
| 1 | [gh][req] | @reviewer | pending | rename param `x` to `count` | [↗](https://github.com/owner/repo/pull/42#discussion_r123) | — |
| 2 | [gh][suggest] | @maintainer | pending | add docstring | [↗](https://github.com/owner/repo/pull/42#issuecomment-456) | — |
| 3 | [gh][question] | @reviewer | pending | why not use X instead? | — | — |
```

Long content never justifies switching to key-value or separator-delimited format — truncate, stay in table.

Answer `[question]` items resolvable from code — clear answer → present answer and proposed reclassification via `AskUserQuestion` before implementing: "[question] #N: '<summary>' — answer: '<answer>'. Reclassify as [req]?" Options: (a) Yes, implement · (b) Keep as question for maintainer. Never self-promote `[question]` to `[req]` without user confirmation. Maintainer judgement needed → surface and pause. Contributor answer ≠ auto-close — answer revealing known limitation/deferred work → keep `[question]`, surface for maintainer to accept/reject.

## Step 3c: Merge report findings (pr + report mode only)

*Skip when in pr mode.*

When mode == **pr + report**:

Find + read latest review report (`ls -t .temp/output-review-*.md 2>/dev/null | head -1`). Parse findings same as Step 3a.

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

## Step 3d: Challenge action items

Read and execute `$_OSS_RESOLVE/modes/challenge-dispatch.md`.

## Step 3e: User item selection

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text.

Pending items = ACTION_ITEMS where type ≠ `[done]` and type ≠ `[info]`. Zero pending → set `SELECTED_ITEMS` = all pending IDs, skip to Step 3f.

Sort: `[req]` first, then `[suggest]`. Constraint: max 4 options/question, max 4 questions/call (3 item-group + 1 bulk-action).

**≤12 pending items**: split into groups of ≤4, one `multiSelect: true` question per group. Labels: `<type> #<id>: <summary>` (≤55 chars); description: `<file:line> · @<author>`. Last question (single-select): "Or choose a bulk action:" — "Apply selected" / "Apply all [req]" / "Apply all" / "Skip all".

**13–19 pending items**: two calls — call 1: `[req]` groups + bulk-action; call 2: `[suggest]` groups + bulk-action; merge selections.

**≥20 pending items — context-budget mode**: skip per-item multiSelect; print compressed table (type · id · summary ≤40 chars · file) then single bulk-action call only:

```text
AskUserQuestion: "N pending items (X [req], Y [suggest]). Choose bulk action:"
Options: (a) Apply all [req] (X items) · (b) Apply all (N items) · (c) Skip all
```

If per-item control needed: advise re-run after reducing source (e.g. use `report` mode instead of `pr + report`, or `--no-challenge` to cut upstream findings).

Resolve `SELECTED_ITEMS`:
- "Skip all" or no selections → `[]` → skip Steps 4–8, jump to Step 9
- "Apply all [req]" → all `[req]` IDs
- "Apply all" → all pending IDs
- "Apply selected" → checked IDs from item questions

## Step 3f: Create tasks for selected items

Mark Step 2 task `completed`:

```text
TaskUpdate(task_id=<step2_task_id>, status="completed")
```

Create tasks **only for `SELECTED_ITEMS`** — not all pending items; avoids context bloat when 20+ action items exist but only a subset is actioned:

```text
TaskCreate(
  subject="<type> <summary> — PR #<number>",   # <type> = full string with brackets
  description="Author: @<author> | File: <file:line or '—'> | <full_comment_text>",
  activeForm="Implementing: <summary>"          # <summary> truncated to 80 chars
)
```

Store returned task ID in each `SELECTED_ITEMS` entry as `task_id`.

## Step 4: Checkout PR branch

*Runs only when `SELECTED_ITEMS` non-empty (set in Step 3f). Empty → skip to Step 9.*

```bash
SAVED_BRANCH=$(git rev-parse --abbrev-ref HEAD)  # timeout: 3000
gh pr checkout <PR#>   # fetches HEAD_REF; for forks, adds the contributor's remote + sets up tracking  # timeout: 15000
```

`gh pr checkout` auto-handles forks — adds contributor's remote, configures tracking. Verify:

```bash
git remote -v | grep '(fetch)' | head -10 # timeout: 3000
git status                                # confirm we are on HEAD_REF  # timeout: 3000
```

Determine `FORK_REMOTE` for push in Step 10:

```bash
IS_CROSS_REPO=$(gh pr view "<PR#>" --json isCrossRepository --jq .isCrossRepository 2>/dev/null || echo false) # timeout: 6000
if [ "$IS_CROSS_REPO" = "true" ]; then
    FORK_REMOTE=$(gh pr view "<PR#>" --json headRepositoryOwner --jq .headRepositoryOwner.login) # timeout: 6000
else
    FORK_REMOTE="origin"
fi
# Soft-verify remote exists; gh pr checkout layouts vary across versions
git remote get-url "$FORK_REMOTE" >/dev/null 2>&1 \
    || echo "⚠ Remote $FORK_REMOTE not registered — Step 10 will add it before push" # timeout: 3000
```

`FORK_REMOTE`: contributor login (e.g. `alice`) for forks, `origin` for same-repo. Push always `git push` — tracking configured by `gh pr checkout`.

## Steps 5–7: Conflict detection, context, and resolution
<!-- Steps 5–7 defined in conflict-resolution.md — see that file for sub-step numbering -->

Read and execute `$_OSS_RESOLVE/modes/conflict-resolution.md`.

## Step 8: Implement action items

Before committing, show user final pre-commit summary and request confirmation:

```text
AskUserQuestion: "Codex has applied changes. Ready to commit N items to <branch>? Summary: <list item summaries>."
Options: (a) Commit all changes as shown · (b) Show git diff first (review each file before committing) · (c) Abort and inspect manually
```

On (a) confirmed — authorize commits for this workflow:

```bash
SENTINEL="/tmp/claude-commit-auth-$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')-$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')"
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"' EXIT INT TERM  # ensure cleanup even if workflow crashes
```

`CODEX_AVAILABLE=false`: apply degradation rules from Step 1 (simple items → foundry:sw-engineer; complex items → skip with notice). Never blanket-skip all items.

> **Conflict gate**: verify all Step 5a conflict tasks `completed` before any action item. Still `pending`/`in_progress` → stop, surface list, wait. Items on unresolved conflicts compound diff.

Process items in `SELECTED_ITEMS` (from Step 3f) in priority order (`[req]` first, then `[suggest]`). **Each item gets own commit.**

**Codex effort classification** — classify each item before dispatch; set `ITEM_EFFORT`; aggregate to `CHANGE_SCOPE` for Step 9:
- typo/spelling/whitespace/formatting/comment/rename-single/docstring → `medium`; multi-file/refactor/architecture/new-feature/redesign → `xhigh`; all else → `high` (default)
- Minimum effort is always `medium` — never `low`
- `ITEM_EFFORT` set per item; include in Codex prompt as `"Effort level: $ITEM_EFFORT.\n..."` prefix
- `CHANGE_SCOPE` = aggregate across all `SELECTED_ITEMS`:
  - ALL items classified `medium` → `CHANGE_SCOPE=lint-only`
  - ANY item classified `xhigh` → `CHANGE_SCOPE=full`
  - otherwise → `CHANGE_SCOPE=targeted` (default)
- Compute `CHANGE_SCOPE` once before the loop; pass to Step 9 via shell variable

**≥10 selected items — batched Codex dispatch**: group items by file affinity (items touching the same file → one batch; max 3 per batch; unrelated items → solo batch). Per batch: single Codex dispatch listing all items; one `git add` + one commit referencing all batch item IDs. Print compact progress `[N/total] batch #<ids> — <files>` instead of per-item verbose diff output. Skip per-item stash/unstash — perform one clean-state check per batch instead.

Per action item (or per batch when batching):

```bash
# Ensure clean state before each item — substitute <id> with item.id
test -z "$(git status --porcelain)" || { echo "⚠ dirty tree before item #<id> — stashing"; git stash push -m "resolve-pre-item-<id>"; }  # timeout: 3000
git diff HEAD --stat  # timeout: 3000
```

Mark item's task in_progress:

```text
TaskUpdate(task_id=<item.task_id>, status="in_progress")
```

```bash
Agent(subagent_type="codex:codex-rescue", prompt="Effort level: $ITEM_EFFORT. Apply this review feedback to the codebase. Implement exactly what is requested and nothing more. If the change is already present or there is nothing actionable, make no changes and explain why. Feedback from @<author>: <full_comment_text>")
git diff HEAD --stat  # timeout: 3000
```

Code changed → pop stash BEFORE committing (pop after commit risks conflict markers in committed content), then commit:

```bash
if git stash list --quiet | grep -q "resolve-pre-item-<id>"; then
    git stash pop || { echo "⚠ stash pop conflict — resolve conflicts in $(git stash list | head -1) before committing item #<id>"; exit 1; }  # timeout: 3000
fi
```

```bash
git add $(git diff HEAD --name-only)                                                     # timeout: 3000
# Stage new untracked files — known source extensions only (prevent staging secrets/artifacts)
UNTRACKED=$(git ls-files --others --exclude-standard | grep -E '\.(py|md|yaml|yml|toml|cfg|ini|json|txt|sh|js|ts|go|rs|rb|java|c|cpp|h|hpp)$' 2>/dev/null)
[ -n "$UNTRACKED" ] && echo "$UNTRACKED" | xargs git add -- 2>/dev/null || true         # timeout: 3000
git commit -m "$(
	cat <<'EOF'
<imperative short summary of the change>

[resolve #<item_id>] Review comment by @<author> (PR #<PR_NUMBER>):
"<first 72 chars of full_comment_text>..."

---
Co-authored-by: Claude Code <noreply@anthropic.com>
Co-authored-by: OpenAI Codex <codex@openai.com>
EOF
)"  # timeout: 3000
```

No code changed → record Codex's reason; do NOT create empty commit. Record per-item: `committed <SHA>` or `skipped — <Codex reason>`.

Mark item's task completed:

```text
TaskUpdate(task_id=<item.task_id>, status="completed")
```

## Step 9: Lint and QA gate

Read and execute `$_OSS_RESOLVE/modes/lint-qa-gate.md`.

## Step 10: Push

*Skip when report mode with no PR# (`$FORK_REMOTE`, `$HEAD_REF`, `$BASE_REF` unset — no fork branch; workflow ends at Step 11).*

```bash
if ! git remote get-url "$FORK_REMOTE" &>/dev/null; then # timeout: 3000
    REPO_NAME=$(git remote get-url origin | sed 's|.*/||' | sed 's|\.git$||')
    ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")
    # Mirror SSH vs HTTPS to avoid push failures for SSH-only contributors
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
echo "→ $PUSH_COUNT commits ready to push to $FORK_REMOTE/$HEAD_REF — approve the git push request in the toolbar ↑ to complete"
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

```bash
[ -n "$SAVED_BRANCH" ] && git checkout "$SAVED_BRANCH" 2>/dev/null && echo "→ Restored to $SAVED_BRANCH"  # timeout: 5000
```

Invoke `AskUserQuestion` — options: (a) Open PR in browser (`gh pr view <PR_NUMBER> --web`) · (b) Merge now (`gh pr merge <PR_NUMBER> --merge`) · (c) Skip.

## Step 12: Comment dispatch + Codex review loop

Read and execute `$_OSS_RESOLVE/modes/comment-dispatch.md`.

</workflow>

<calibration>

Non-calibratable — `disable-model-invocation: true` means skill dispatches to sub-agents rather than running model pass directly; calibrate cannot score model output for skill that produces none.

Reference scenarios (for documentation; not for calibrate runs):
1. Mode selection: bare PR number (e.g. `42`) → pr mode; `42 report` → pr + report mode; bare `report` → report mode; bare comment text → comment dispatch (Step 12)
2. Action item classification: LGTM/emoji comment → `[info]` (skip); `nit:` suggestion → `[gh][suggest]`; resolved thread → `[done]`; "must fix X before merge" from reviewer with write access → `[gh][req]`
3. Challenge accuracy: comment about actually-present bug (confirmed by reading code) → VALID; comment about issue already addressed in subsequent commit → REJECT

</calibration>

<notes>

- **Pre-flight git pull** — Step 1 fetches remote tracking ref, pulls if ahead; 1-local/1-remote divergence merges clean; `git pull` conflicts → exit with message to resolve manually — prevents `git merge --continue` with no in-progress merge
- **Branch safety** — `gh pr checkout <PR#>` always lands on PR's HEAD, never `main`/`master`. Never push to default branch — if PR branch = default branch, abort and surface.
- **OSS fork support** — `gh pr checkout <PR#>` works same for branches + forks; forks get contributor remote + tracking; plain `git push` targets fork branch automatically.
- **Merge direction** — `origin/BASE_REF` INTO `HEAD_REF` (not reverse); PR branch = source of truth; maintainer still clicks Merge.
- **Contribution motivation before code** — provides "whose intent wins" lens; PR body + linked issues reveal constraints invisible in git diff.
- **`[question]` items** — answer inline in resolve report only (never post to PR); reclassify before implementing; never silently implement unanswered question.
- **Push verification** — confirm via `gh pr view --json commits` before reporting success; exit 0 from `git push` necessary but not sufficient (branch protection can silently reject).
- **Merge-push sequencing** — `git merge` and `git push` not atomic; concurrent push to same branch between these steps causes non-fast-forward rejection. Fetch + pull and retry push step only — do not re-run full merge.
- **`gh pr merge` flags**: `--merge` = preserves all commits; `--squash` = collapses (loses action-item commits); never `--rebase` (rewrites SHAs); default `--merge`.
- **Escape hatch**: `git merge --abort` = undo all conflict state; `git push --force-with-lease` (never plain `--force`) only when user explicitly requests — if push rejected after local amend.
- **Codex agent health**: subject to CLAUDE.md §8 — 15-min cutoff, ⏱ on timeout; partial results via `tail -100` on output file.
- **Codex effort calibration**: effort set per item — never `low`; minimum `medium`; typo/doc/formatting/rename-simple → `medium`; multi-file/architecture/new-feature → `xhigh`; default → `high`; effort prefix in Codex prompt, not a separate tool param; `CHANGE_SCOPE` aggregated from all items for Step 9 test targeting
- **Thread resolution via GraphQL** — `isResolved` lives on `PullRequestReviewThread` (GraphQL only); REST `/pulls/{PR}/comments` does not expose it. `RESOLVED_THREAD_IDS` = root comment `databaseId` values; GraphQL failure → `[]` fallback.
- **Commit attribution** — `[gh]` items: `[resolve #<id>] @<reviewer> (gh):`; `[report]` items: `[resolve #<id>] /review finding by <agent-name> (report: <report-path>):` — distinguishes automated findings in git history.
- **Sources block**: print after all sources read, before action item table.
- **Step 7 delegation** — resolve owns orchestration + context; sw-engineer owns code-level resolution; resolve retains conflict report + `git merge --continue`.
- Follow-up chains:
  - After push → never approve/comment on PR; maintainer reviews + clicks Merge.
  - Unanswered `[question]` items → record in resolve report only; do NOT post to PR.
  - After merge → linked issues close if PR body has `Closes #<issue#>`/`Fixes #<issue#>`; `CLOSING_ISSUES` found in Step 3b but body lacks keywords → surface gap in Resolve Report under `### Closing Keywords` note — do not edit PR body. Note: "PR body does not contain `Closes #<issue#>` — linked issue will not auto-close on merge. Add closing keyword manually via GitHub PR edit UI."

</notes>
