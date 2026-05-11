---
name: resolve
description: "OSS maintainer fast-close workflow for GitHub PRs. Three phases: (1) PR intelligence — reads the full thread, linked issues, and PR body to synthesize contribution motivation and classify every comment into action items; (2) conflict resolution — checks out the PR branch (fork-aware via gh pr checkout), merges BASE into it, and resolves conflicts semantically using the contributor's intent as the priority lens; (3) implements each action item as a separate attributed commit via Codex, then pushes back to the contributor's fork. Supports three source modes: pr (live GitHub comments only), report (latest /review report findings as action items, no GitHub re-fetch), and pr + report (both sources aggregated and deduplicated in one pass). Also accepts bare comment text for single-comment dispatch. NOT for drafting contributor replies (use oss:analyse --reply). NOT for release preparation (use oss:release)."
argument-hint: '<PR number or URL> [report] | report | <review comment text>'
disable-model-invocation: true
effort: high
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

```bash
# Locate oss plugin shared dir — installed first, local workspace fallback
# sort -V orders semver correctly (0.9.0 < 0.10.0); tail -1 picks newest
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
```

Read `$_OSS_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:linting-expert → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. For each task:

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

# Sync with remote tracking branch before any git work.
# When local is 1 commit ahead and remote is also 1 commit ahead, git pull merges cleanly.
# This prevents the downstream `git merge --continue --no-edit` from being called out of state.
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

If gh missing or not authenticated: stop (error printed above).

Codex missing: set `CODEX_AVAILABLE=false`, continue — Steps 3–7 work without Codex. Step 8 degradation (applied in priority order):
1. Simple, single-file action items → implement in-process via `foundry:sw-engineer` (no Codex wrapper)
2. Complex or multi-file items → skip with notice; print: `⚠ codex not found — skipping complex item #<id>. Install: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`
3. No items fall through both (all items are either simple or complex) — proceed to Step 9 after processing

### Review-handoff auto-detect (when $ARGUMENTS is empty)

If `$ARGUMENTS` is empty:

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
[ -f "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.sh" ] || { echo "Error: parse-resolve-args.sh not found — verify oss plugin installation"; exit 1; }  # timeout: 5000
eval "$(bash "${CLAUDE_PLUGIN_ROOT}/bin/parse-resolve-args.sh" "$ARGUMENTS")"
# sets: PR_NUMBER, PR_URL, MODE, ARGUMENTS (leading '#' stripped only for comment-dispatch)
```

- `MODE="pr+report"` → strip `report` suffix conceptually (already captured separately); find latest review report via `ls -t .temp/output-review-*.md 2>/dev/null | head -1`; no report found → warn but continue in pr mode
- `MODE="report"` → find latest review report via `ls -t .temp/output-review-*.md 2>/dev/null | head -1`; no report found → stop with: "No review report found in .temp/ — run /review \<PR#> first, or provide a PR number"; extract PR# from header if present
- `MODE="pr"` → continue Step 2
- `MODE="comment-dispatch"` → jump to Step 12

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

Fetch resolved thread status — REST API `/pulls/{PR}/comments` returns individual comment objects but does **not** expose `isResolved`; that field lives only on `PullRequestReviewThread` in GraphQL:

```bash
# Derive owner + name from current remote (same repo as BASE_REPO_OWNER but avoids re-parsing URL)
REPO_OWNER=$(gh repo view --json owner --jq .owner.login 2>/dev/null || echo "$BASE_REPO_OWNER")  # timeout: 6000
REPO_NAME=$(gh repo view --json name --jq .name 2>/dev/null)  # timeout: 6000
RESOLVED_THREAD_IDS=$(gh api graphql \
  -f query='query($owner:String!,$repo:String!,$pr:Int!){repository(owner:$owner,name:$repo){pullRequest(number:$pr){reviewThreads(first:100){nodes{isResolved,comments(first:1){nodes{databaseId}}}}}}}' \
  -f owner="$REPO_OWNER" \
  -f repo="$REPO_NAME" \
  -F pr="$PR_NUMBER" \
  --jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved) | .comments.nodes[0].databaseId]' \
  2>/dev/null || echo "[]")  # timeout: 15000
# RESOLVED_THREAD_IDS: JSON array of databaseId integers for root comments of resolved threads
```

Non-empty `CLOSING_ISSUES` → fetch each linked issue:

```bash
gh issue view <ISSUE_NUMBER> --json title,body
```

### Synthesize contribution motivation

Read PR title, body, linked issues, commits. Produce 2–3 sentence paragraph:

- What problem/gap contributor is solving (linked issues or PR description)
- Why they chose this approach (PR body, design notes in commits)
- Expected user-visible outcome

Motivation = **priority lens for conflict resolution** in Step 7 — whose logic wins when both sides touched same area.

### Classify action items

Read every comment, review, inline code comment. For each inline code comment: if its `id` (REST response field `id`, same value as `databaseId` in GraphQL) appears in `RESOLVED_THREAD_IDS` → classify as `[done]` immediately without reading thread content. For all others, apply the table below:

| Code | Meaning |
| --- | --- |
| `[gh][req]` | Change **required** before merge — requested by a reviewer with write access or the maintainer |
| `[gh][suggest]` | Improvement suggested — nice-to-have, non-blocking |
| `[gh][question]` | Open question that needs an answer before deciding what code to write |
| `[done]` | Review thread marked resolved on GitHub (`isResolved=true`) OR subsequent commit/reply already addressed this — skip |
| `[info]` | Praise, acknowledgement, emoji-only — skip |
| `[self-review]` | Finding from the `/oss:review` report — not a GitHub commenter; author = agent name |

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

Long content is never a reason to switch to key-value or separator-delimited format — truncate and stay in the table.

Answer `[question]` items resolvable from code — clear answer → reclassify `[req]`/`[suggest]`; maintainer judgement needed → surface and pause. Contributor answer ≠ auto-close — answer revealing known limitation/deferred work → keep `[question]`, surface for maintainer to accept/reject.

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

```bash
# --no-challenge flag: skip this step entirely
[[ "$ARGUMENTS" == *"--no-challenge"* ]] && {
    echo "⚠ --no-challenge: skipping Step 3d — all pending items treated as VALID"
    CHALLENGE_VERDICTS="[]"
    # proceed directly to Step 3e; all items keep their type unchanged
}
```

When `--no-challenge` is NOT set:

Route each pending item by domain (default `foundry:challenger`); spawn one agent per group **in the background**:

| Item domain | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases | `foundry:sw-engineer` |
| Test coverage, assertions, regressions | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

Write a per-group output file before spawning each agent:

```bash
CHALLENGE_DIR="/tmp/resolve-challenge-$$"
mkdir -p "$CHALLENGE_DIR"  # timeout: 5000
LAUNCH_AT=$(date +%s)
NUM_GROUPS=0  # incremented once per spawned agent group below
```

Before spawning, write all pending action items to file using the Write tool (file-handoff protocol — CLAUDE.md §2):

Write `$CHALLENGE_DIR/items.json` with all pending ACTION_ITEMS in format:
`{"items": [{"id": <id>, "summary": "<summary>", "file_line": "<file:line or —>", "author": "<author>", "full_comment_text": "<full text>"}]}`

Spawn each challenge group with `run_in_background=true`, instructing it to write compact JSON to `$CHALLENGE_DIR/<group>.json`; increment `NUM_GROUPS` after each spawn:

```text
Agent(subagent_type="foundry:challenger", run_in_background=true, prompt="
Challenge each review comment for PR #<N>.
Read items from $CHALLENGE_DIR/items.json (JSON array under key 'items', each with id, summary, file_line, author, full_comment_text).
For each item: read referenced file at file_line if given; determine if comment is valid against actual code, or should be pushed back.
Be concise — max 2 tool calls per item.

Write ONLY compact JSON to $CHALLENGE_DIR/challenger.json using the Write tool:
{\"verdicts\": [{\"id\": <id>, \"verdict\": \"VALID\"|\"PUSH_BACK\", \"rationale\": \"<one sentence>\"}]}
Then return the same JSON as your final message.
")
```

(Repeat pattern for `foundry:sw-engineer` → `$CHALLENGE_DIR/sw-engineer.json`, `foundry:qa-specialist` → `$CHALLENGE_DIR/qa-specialist.json`; do `((NUM_GROUPS++))` after each `Agent(...)` call.)

**5-minute health monitor** — check every 90 s; hard cutoff at 300 s (5 min):

```bash
# Tightened from CLAUDE.md §8: hard cutoff 15min→5min, poll 5min→90s (appropriate for short challenge tasks)
# Poll until all groups done or 5-min deadline reached
while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAUNCH_AT))
    DONE=$(find "$CHALLENGE_DIR" -name "*.json" ! -name "items.json" -newer "/tmp/resolve-challenge-$$" 2>/dev/null | wc -l | tr -d ' ')

    [ "$DONE" -ge "$NUM_GROUPS" ] && break   # all groups returned
    [ "$ELAPSED" -ge 300 ] && {
        echo "⏱ Challenge timeout at ${ELAPSED}s — marking remaining items VALID"
        break
    }
    sleep 90
done  # timeout: 360000
```

Aggregate verdicts — read each `$CHALLENGE_DIR/*.json` that exists:

- File present → use verdicts
- File absent (agent timed out) → mark every item in that group as `VALID` with rationale `"challenge timed out — treated as VALID"`

```bash
rm -rf "$CHALLENGE_DIR"  # cleanup  # timeout: 5000
```

Per verdict:
- **VALID** → keep item unchanged
- **PUSH_BACK** → set type to `[challenged:pushback]`; store rationale; exclude from SELECTED_ITEMS

Print challenge summary:

```markdown
### Challenge Results — PR #<number>

| # | Type | Author | Verdict | Rationale |
|---|------|--------|---------|-----------|
| 1 | [gh][req] | @reviewer | VALID | — |
| 2 | [gh][suggest] | @maintainer | PUSH_BACK | already addressed in commit abc123 |
```

`[challenged:pushback]` items appear in final report (Step 11) with `⊘ push-back` status and rationale — for maintainer to communicate back to reviewer.

## Step 3e: Create per-item tasks

Mark Step 2 task `completed`:

```text
TaskUpdate(task_id=<step2_task_id>, status="completed")
```

For each item in `ACTION_ITEMS` create task:

```text
TaskCreate(
  subject="<type> <summary> — PR #<number>",
  description="Author: @<author> | File: <file:line or '—'> | <full_comment_text>",
  activeForm="Implementing: <summary>"
)
```

- `<type>` — full type string as-is (include brackets): `[gh][req]`, `[gh][suggest]`, `[gh][question]`, `[report][req]`, `[report][suggest]`, etc.
- `<summary>` — item's `summary` field (truncate to 80 chars if needed)
- Skip `[done]`/`[info]` items — no task needed.

Store returned task ID in each `ACTION_ITEMS` entry as `task_id`.

## Step 3f: User item selection

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text.

Pending items = ACTION_ITEMS where type ≠ `[done]` and type ≠ `[info]`. Zero pending → set `SELECTED_ITEMS` = all pending IDs, skip to Step 4.

Sort: `[req]` first, then `[suggest]`. Constraint: max 4 options/question, max 4 questions/call (3 item-group + 1 bulk-action).

Split items into groups of ≤4, one `multiSelect: true` question per group. Labels: `<type> #<id>: <summary>` (≤55 chars); description: `<file:line> · @<author>`.

Last question (single-select, always): "Or choose a bulk action:" — "Apply selected" / "Apply all [req]" / "Apply all" / "Skip all".

>12 pending items: two calls — call 1: `[req]` groups + bulk-action; call 2: `[suggest]` groups + bulk-action; merge selections.

Resolve `SELECTED_ITEMS`:
- "Skip all" or no selections → `[]` → skip Steps 4–8, jump to Step 9
- "Apply all [req]" → all `[req]` IDs
- "Apply all" → all pending IDs
- "Apply selected" → checked IDs from item questions

## Step 4: Checkout PR branch

*Only runs when `SELECTED_ITEMS` is non-empty (set in Step 3f). If empty → skip directly to Step 9.*

```bash
SAVED_BRANCH=$(git rev-parse --abbrev-ref HEAD)  # timeout: 3000
gh pr checkout <PR#>   # fetches HEAD_REF; for forks, adds the contributor's remote + sets up tracking  # timeout: 15000
```

`gh pr checkout` auto-handles forks — adds contributor's remote, configures tracking. Verify:

```bash
# Show one line per remote (fetch URL); each remote prints both (fetch) and (push) lines, so filter to (fetch) for de-dup
git remote -v | grep '(fetch)' | head -10 # timeout: 3000
git status                                # confirm we are on HEAD_REF  # timeout: 3000
```

Determine `FORK_REMOTE` explicitly — `gh pr checkout` adds the remote but the skill must know its name to push later (Step 10):

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

## Step 5: Conflict detection

```bash
# Detect in-progress merge via MERGE_HEAD sentinel — git status --porcelain does not expose this reliably
MERGE_HEAD_FILE="$(git rev-parse --git-dir)/MERGE_HEAD" # timeout: 3000
test -f "$MERGE_HEAD_FILE" && echo "MERGING" || echo "clean"
```

**Case A — MERGING** (`MERGE_HEAD` present — prior `git merge` left markers): work with existing markers. Skip to Step 7a.

**Case B — not MERGING**:

Merge `BASE_REF` into PR branch (BASE → HEAD_REF, not reverse):

```bash
git fetch origin "$BASE_REF"                     # ensure origin/$BASE_REF is current  # timeout: 6000
git merge "origin/$BASE_REF" --no-commit --no-ff # timeout: 6000
```

Check conflicted files:

```bash
git diff --name-only --diff-filter=U # timeout: 3000
```

### 5a: Create per-conflict tasks

For each conflicted file, create task **before touching any file**:

```text
TaskCreate(
  subject="Resolve conflict: <filepath> — PR #<number>",
  description="Merge conflict in <filepath> from merging origin/<BASE_REF> into <HEAD_REF>. Must be completed before action-item implementation begins.",
  activeForm="Resolving conflict: <filepath>"
)
```

Store returned task ID alongside each file path as `conflict_task_id`. Print conflict task table:

```markdown
### Merge Conflicts — PR #<number>

| File | Task | Status |
|------|------|--------|
| src/foo.py | #<task_id> | pending |
| config.yaml | #<task_id> | pending |
```

> **Invariant**: all conflict tasks `completed` before Step 8. Upfront creation keeps each conflict scoped and independently reversible.

No conflicts → complete merge, skip to Step 8:

```bash
git merge --continue --no-edit
```

Report clean merge, skip Steps 6–7, continue Step 8.

More than 20 conflicted files → abort and stop:

```bash
git merge --abort
```

Report count + file list; `AskUserQuestion` with options:
- (a) "Retry with base only — merge origin/$BASE_REF in batches (manual)" — re-attempt merge in chunks outside this workflow
- (b) "Open PR in browser for manual resolution" — `gh pr view <PR#> --web`
- (c) "Stop — merge aborted" — workflow complete; branch left on $SAVED_BRANCH

## Step 6: Distill conflict context

### 6a: Source-branch intent

Use Step 3b motivation as primary lens. Additionally:

```bash
MERGE_BASE=$(git merge-base "origin/$BASE_REF" "$HEAD_REF") # timeout: 3000
git log $MERGE_BASE..$HEAD_REF --oneline --no-merges        # timeout: 3000
git diff $MERGE_BASE $HEAD_REF --stat                       # timeout: 3000
```

One-sentence summary: which files/modules PR owns and what it changes.

### 6b: Target-branch drift (the "surprises")

```bash
git log $MERGE_BASE..origin/$BASE_REF --oneline --no-merges    # timeout: 3000
SOURCE_LAST_TIME=$(git log "$HEAD_REF" -1 --format="%ci")      # timeout: 3000
git log origin/$BASE_REF --after="$SOURCE_LAST_TIME" --oneline # commits the contributor never saw  # timeout: 3000
```

One-sentence summary: independent base changes after contributor's last commit — preserve unconditionally.

## Step 7: Resolve per conflicted file

### 7a: Spawn sw-engineer

Spawn `foundry:sw-engineer` (fill brackets from indicated steps):

```markdown
Agent(subagent_type="foundry:sw-engineer", prompt="
You are resolving merge conflicts in a checked-out PR branch.

## Conflicted files
<list every file from Step 5 `git diff --name-only --diff-filter=U` output, one per line>

## Contribution motivation (whose intent wins)
<2–3 sentence motivation summary from Step 3b>

## Merge context
### What HEAD_REF added (merge-base log)
<git log $MERGE_BASE..$HEAD_REF --oneline --no-merges output from Step 6a>

### Files changed by this PR (diff stat)
<git diff $MERGE_BASE $HEAD_REF --stat output from Step 6a>

## Instructions
For each conflicted file:
1. Use the Read tool to inspect the full file and locate all conflict markers
2. Determine the correct resolution using the contribution motivation above as the priority lens:
   - Contributor's new functionality takes priority for files the PR owns (introduced or substantially rewrote)
   - Base's independent refactors and config updates are always preserved
   - When both sides changed the same logic, blend: keep the PR's semantic change while incorporating the base's structural update
3. Use the Edit tool to apply targeted replacements that remove all conflict markers and produce the correct resolved content — do NOT rewrite the whole file; use Edit for minimal targeted replacements
4. After resolving each file, stage it with: git add -- <file>  (timeout: 3000)

Return ONLY a compact JSON envelope — no prose, no explanation:
{\"status\":\"done\",\"resolved\":N,\"staged\":N,\"confidence\":0.N}
")
```

> **Health monitoring**: synchronous; Claude awaits natively. No response ~15 min → surface partial results ⏱, proceed with staged files.

### 7b: Verify and complete merge

Parse JSON from sw-engineer. Check `resolved == staged` — mismatch = file resolved but not staged → surface before proceeding.

Complete merge:

```bash
git merge --continue --no-edit # timeout: 3000
```

Print conflict report:

```markdown
### Conflict Resolution

| File | Strategy | Notes |
|------|----------|-------|
| src/foo.py | Blended | kept PR's new param, adopted base's renamed import |
| config.yaml | Target | unrelated config change from base, PR had no opinion |

**Result**: N files resolved. Merge commit created.
```

Mark all conflict tasks completed:

```text
for each (filepath, conflict_task_id) pair from Step 5a: TaskUpdate(task_id=\<conflict_task_id>, status="completed")
```

## Step 8: Implement action items

Authorize commits for this workflow:

```bash
SENTINEL="/tmp/claude-commit-auth-$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')-$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')"
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"' EXIT INT TERM  # ensure cleanup even if workflow crashes
```

If `CODEX_AVAILABLE=false`: apply degradation rules from Step 1 (simple items → foundry:sw-engineer; complex items → skip with notice). Never blanket-skip all items.

> **Conflict gate**: verify all Step 5a conflict tasks `completed` before any action item. Still `pending`/`in_progress` → stop, surface list, wait. Items on unresolved conflicts compound diff.

Process items in `SELECTED_ITEMS` (from Step 3f) in priority order (`[req]` first, then `[suggest]`). **Each item gets its own commit.**

For each action item:

```bash
# Guard: ensure clean state before each item — substitute <id> with item.id before executing
test -z "$(git status --porcelain)" || { echo "⚠ dirty tree before item #<id> — stashing"; git stash push -m "resolve-pre-item-<id>"; }  # timeout: 3000

# Snapshot before
git diff HEAD --stat  # timeout: 3000
```

Mark item's task in_progress:

```text
TaskUpdate(task_id=<item.task_id>, status="in_progress")
```

```bash
# Dispatch to Codex
Agent(subagent_type="codex:codex-rescue", prompt="Apply this review feedback to the codebase. Implement exactly what is requested and nothing more. If the change is already present or there is nothing actionable, make no changes and explain why. Feedback from @<author>: <full_comment_text>")

# Check whether code changed
git diff HEAD --stat  # timeout: 3000
```

Code changed → commit:

```bash
# Stage tracked modifications + new files from Codex (never git add -A)
git add $(git diff HEAD --name-only)                                                     # timeout: 3000
git ls-files --others --exclude-standard | grep . | xargs git add -- 2>/dev/null || true # timeout: 3000
# Replace all <placeholder> tokens with actual values before committing
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

No code changed (already done or non-actionable) → record Codex's reason; do NOT create empty commit.

Record per-item: `committed <SHA>` or `skipped — <Codex reason>`.

Mark item's task completed:

```text
TaskUpdate(task_id=<item.task_id>, status="completed")
```

Clean up stash if dirty-tree guard created one for this item:

```bash
git stash list --quiet | grep -q "resolve-pre-item" && git stash pop  # timeout: 3000
```

## Step 9: Lint and QA gate

```bash
RUN_DIR=".reports/resolve/$(date -u +%Y-%m-%dT%H-%M-%SZ)"  # IMPORTANT: expand $RUN_DIR to its literal value in each prompt string below — agents receive text, not shell context; un-expanded $RUN_DIR means literal string in instructions
mkdir -p "$RUN_DIR" # timeout: 5000
# Compute BASE_REF merge base for accurate diff range in agent prompts
BASE_REF_MERGE=$(git merge-base HEAD "origin/$BASE_REF" 2>/dev/null || echo "origin/$BASE_REF")
```

Spawn both in parallel:

```text
Agent(subagent_type="foundry:linting-expert", maxTurns=15, prompt="Review all files changed in the current branch since $BASE_REF_MERGE (expand to literal SHA before spawning). List every lint/type violation. Apply inline fixes for any that are auto-fixable. Write your full findings to $RUN_DIR/linting-expert-step9.md using the Write tool, then return ONLY a compact JSON envelope: {fixed: N, remaining: N, files: [...]}.")

Agent(subagent_type="foundry:qa-specialist", maxTurns=15, prompt="Review all files changed in the current branch since $BASE_REF_MERGE (expand to literal SHA before spawning) for correctness, edge cases, and regressions. Flag any blocking issues (bugs, broken contracts, missing test coverage for the changed logic). Write your full findings to $RUN_DIR/qa-specialist-step9.md using the Write tool, then return ONLY a compact JSON envelope: {blocking: N, warnings: N, issues: [...]}.")
```

> **Health monitoring**: synchronous. No response ~15 min → surface partial results from `$RUN_DIR` ⏱.

- `foundry:linting-expert` made file changes → commit:

```bash
git add $(git diff HEAD --name-only)                          # timeout: 3000
git commit -m "$(cat <<'EOF'
lint: auto-fix violations after resolve cycle

---
Co-authored-by: Claude Code <noreply@anthropic.com>
EOF
)"  # timeout: 3000
```

- Blocking issues from `foundry:qa-specialist` → fix (via Codex or inline edit), re-run qa-specialist once to confirm; issues remaining after one fix pass → **stop workflow — do not proceed to Step 10 (push)**; surface all remaining blocking issues in report; print: `⛔ QA gate blocked push — review findings above, fix errors, then re-run /resolve or push manually after fixing.`
- Warnings (non-blocking) → record in report; do not block push

Revoke commit authorization:

```bash
rm -f "$SENTINEL"  # timeout: 3000
```

## Step 10: Push

*Skip when report mode with no PR# (`$FORK_REMOTE`, `$HEAD_REF`, `$BASE_REF` unset — no fork branch; workflow ends at Step 11).*

```bash
# Ensure fork remote is present (gh pr checkout may not have added it for all setups)
if ! git remote get-url "$FORK_REMOTE" &>/dev/null; then # timeout: 3000
    REPO_NAME=$(git remote get-url origin | sed 's|.*/||' | sed 's|\.git$||')
    git remote add "$FORK_REMOTE" "https://github.com/$FORK_REMOTE/$REPO_NAME.git" # timeout: 3000
    echo "→ Added remote $FORK_REMOTE → https://github.com/$FORK_REMOTE/$REPO_NAME.git"
fi

# Configure tracking if not already set
git branch --set-upstream-to="$FORK_REMOTE/$HEAD_REF" 2>/dev/null || true # timeout: 3000

# Count commits ready to push and announce — user must approve the toolbar permission prompt
PUSH_COUNT=$(git rev-list "$FORK_REMOTE/$HEAD_REF..HEAD" --count 2>/dev/null || git rev-list "origin/$BASE_REF..HEAD" --count) # timeout: 3000
echo "→ $PUSH_COUNT commits ready to push to $FORK_REMOTE/$HEAD_REF — approve the git push request in the toolbar ↑ to complete"

git push # timeout: 30000
# gh pr checkout configured tracking to the fork branch — git push targets it automatically
```

Push rejected (fork protection or stale tracking):

```bash
git push "$FORK_REMOTE" HEAD:"$HEAD_REF" # timeout: 30000
```

Verify push reached GitHub:

```bash
gh pr view <PR_NUMBER> --json headRefOid,commits --jq '.commits[-3:] | .[].messageHeadline' # timeout: 6000
```

Confirm latest commit headlines match what was just committed.

## Step 11: Final report

Mark remaining open tasks `completed`. Per-item tasks should be done by Step 8; this closes items skipped (guard paused, question items, codex-not-available).

Then print:

```markdown
## Resolve Report — PR #<number>

### Contribution
<2–3 sentence motivation summary from Step 3b>

### Conflicts
<conflict table from Step 7, or "No conflicts detected">

### Action Items

<!-- Use same action item schema as Step 3b (columns: item, type, status, commit, notes); statuses now final (✓ resolved / ⊘ skipped / ⊘ no action) -->

### Lint + QA
<linting-expert summary: N fixes applied | or "no violations"> / <foundry:qa-specialist summary: N blocking fixed, N warnings | or "clean">

### Push
✓ Pushed to <remote>/<HEAD_REF> — N new commits

**Next**:
- `gh pr merge <PR#> --merge` to merge now (preserves all commits)

## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.8–0.9 | low <0.8 ⚠]
**Gaps**: [e.g. conflict strategy ambiguity, action items skipped at guard, Codex partial completion]
**Refinements**: N passes. — omit if 0 passes
```

Restore original branch after report:

```bash
if [ -n "$SAVED_BRANCH" ]; then
    git checkout "$SAVED_BRANCH" 2>/dev/null && echo "→ Restored to $SAVED_BRANCH"  # timeout: 5000
fi
```

## Step 12: Comment dispatch + Codex review loop

```bash
# pipe exit code from ls|head is head's (0) — correct here; only path discovery, not guarding execution; ls failure suppressed by 2>/dev/null; fallback guard below handles empty result
_OSS_RESOLVE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/resolve 2>/dev/null | head -1)
[ -z "$_OSS_RESOLVE" ] && _OSS_RESOLVE="plugins/oss/skills/resolve"
```

Read and execute `$_OSS_RESOLVE/modes/comment-dispatch.md`.

</workflow>

<calibration>

Scenarios:
1. Mode selection: bare PR number (e.g. `42`) → pr mode; `42 report` → pr + report mode; bare `report` → report mode; bare comment text → comment dispatch (Step 12)
2. Action item classification: LGTM/emoji comment → `[info]` (skip); `nit:` suggestion → `[gh][suggest]`; resolved thread → `[done]`; "must fix X before merge" from reviewer with write access → `[gh][req]`
3. Challenge accuracy: comment about actually-present bug (confirmed by reading code) → VALID; comment about issue already addressed in a subsequent commit → PUSH_BACK

</calibration>

<notes>

- **Pre-flight git pull** — Step 1 fetches remote tracking ref, pulls if ahead; 1-local/1-remote divergence merges clean; `git pull` conflicts → exit with message to resolve manually — prevents `git merge --continue` with no in-progress merge
- **Branch safety** — `gh pr checkout <PR#>` always lands on PR's HEAD, never `main`/`master`. Never push to default branch — if PR branch = default branch, abort and surface.
- **OSS fork support** — `gh pr checkout <PR#>` works same for branches + forks; forks get contributor remote + tracking; plain `git push` targets fork branch automatically.
- **Merge direction** — `origin/BASE_REF` INTO `HEAD_REF` (not reverse); PR branch = source of truth; maintainer still clicks Merge.
- **Contribution motivation before code** — provides "whose intent wins" lens; PR body + linked issues reveal constraints invisible in git diff.
- **`[question]` items** — answer inline in resolve report only (never post to PR); reclassify before implementing; never silently implement unanswered question.
- **Push verification** — confirm via `gh pr view --json commits` before reporting success; exit 0 from `git push` necessary but not sufficient (branch protection can silently reject).
- **Merge-push sequencing** — `git merge` and `git push` are not atomic; a concurrent push to the same branch between these steps causes a non-fast-forward rejection. If that happens, fetch + pull and retry the push step only — do not re-run the full merge.
- **`gh pr merge` flags**: `--merge` = preserves all commits; `--squash` = collapses (loses action-item commits); never `--rebase` (rewrites SHAs); default `--merge`.
- **Escape hatch**: `git merge --abort` = undo all conflict state; `git push --force-with-lease` (never plain `--force`) only when user explicitly requests — if push rejected after local amend.
- **Codex agent health**: subject to CLAUDE.md §8 — 15-min cutoff, ⏱ on timeout; partial results via `tail -100` on output file.
- **Thread resolution via GraphQL** — GitHub REST `/pulls/{PR}/comments` returns individual comment objects; `isResolved` lives on `PullRequestReviewThread` (GraphQL only). Step 3b fetches it separately. `RESOLVED_THREAD_IDS` = array of root comment `databaseId` values for all resolved threads; inline comments matching any ID → auto-`[done]`. GraphQL fetch failure (network, permissions) → `[]` fallback — skill continues without resolved-status data.
- **`[gh]` items** (all pr-sourced items in all modes): commit messages use: `[resolve #<id>] @<reviewer> (gh):`
- **`[report]` items**: attribute to agent, not GitHub commenter — distinguishes automated findings in git history. Format: `[resolve #<id>] /review finding by <agent-name> (report: <report-path>):`
- **Sources block**: print after all sources read, before action item table — pre-table summary confirming what was fetched.
- **Step 7 delegation** — resolve owns orchestration + context; sw-engineer owns code-level resolution (Read → Edit → stage); resolve retains conflict report + `git merge --continue`.
- Follow-up chains:
  - After push → never approve/comment on PR; maintainer reviews + clicks Merge.
  - Unanswered `[question]` items → record in resolve report only; do NOT post to PR.
  - After merge → linked issues close if PR body has `Closes #<issue#>`/`Fixes #<issue#>`; if `CLOSING_ISSUES` found in Step 3b but body lacks keywords, surface this gap in the Resolve Report under a `### Closing Keywords` note — do not attempt to edit the PR body. Note: "PR body does not contain `Closes #<issue#>` — linked issue will not auto-close on merge. Add the closing keyword manually via the GitHub PR edit UI."

</notes>
