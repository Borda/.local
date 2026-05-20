---
name: resolve
description: "OSS maintainer fast-close workflow for GitHub PRs. Three phases: (1) PR intelligence — reads full thread, linked issues, PR body to synthesize contribution motivation and classify every comment into action items; (2) conflict resolution — checks out PR branch (fork-aware via gh pr checkout), merges BASE into it, resolves conflicts semantically using contributor's intent as priority lens; (3) implements each action item as separate attributed commit via Codex, pushes back to contributor's fork. Supports three source modes: pr (live GitHub comments only), report (latest /review report findings as action items, no GitHub re-fetch), and pr + report (both sources aggregated and deduplicated in one pass). Also accepts bare comment text for single-comment dispatch. NOT for drafting contributor replies (use /oss:analyse --reply). NOT for release preparation (use /oss:release). NOT for fixing local bugs unrelated to a PR (use /develop:fix; requires develop plugin)."
argument-hint: "<PR number or URL> [report] | report | <review comment text>"
disable-model-invocation: true
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
  - Omitted → **review-handoff mode**: auto-detect PR from most recent `.reports/review/*/review-report.md`
  - PR number (e.g. `42` or `#42`) or GitHub PR URL → **pr mode**
  - `report` (bare word) → **report mode**: latest review findings as action items; no GitHub re-fetch
  - `42 report` or `<URL> report` → **pr + report mode**: aggregate live GitHub comments + review report, deduplicated in one pass
  - Bare review comment text → **comment dispatch mode** (jumps to Step 12)
- **`--no-challenge`**: optional — skip challenge gate per item; all selected items treated as `VALID`
- **`--agent <name>`**: optional — use `<name>` agent for implementation instead of Codex (e.g. `--agent curator` → `foundry:curator` for targeted edits; `--agent sw-engineer` → `foundry:sw-engineer` for code-heavy fixes)

</inputs>

<constants>
CHALLENGE_TIMEOUT_S=300  # tightened from CLAUDE.md §8 default 900s
CHALLENGE_POLL_S=90      # tightened from CLAUDE.md §8 default 300s
</constants>

<workflow>

<!-- Symbol legend: ⚠ = warning/skipped (non-blocking, proceed with caution) · ⛔ = blocked/stop (halt workflow, do not proceed) -->

<!-- Agent resolution: see _OSS_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
# loads: oss-shared-resolver.md
_OSS_SHARED=$("${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve-shared-path.sh" oss skills/_shared 2>/dev/null)  # timeout: 5000
_OSS_RESOLVE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/resolve 2>/dev/null | head -1)  # timeout: 5000
[ -z "$_OSS_RESOLVE" ] && _OSS_RESOLVE="plugins/oss/skills/resolve"
```
Read `$_OSS_SHARED/oss-shared-resolver.md` and execute its contents.

Read `$_OSS_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. foundry not installed → use table to substitute each `foundry:X` with `general-purpose`. Agents this skill uses: `foundry:sw-engineer`, `foundry:qa-specialist`, `foundry:linting-expert`, `foundry:challenger`.

<!-- Inline fallback (if agent-resolution.md unreadable): foundry:sw-engineer → general-purpose, foundry:qa-specialist → general-purpose, foundry:linting-expert → general-purpose, foundry:challenger → general-purpose. -->

**Task hygiene**: Before creating tasks, call `TaskList`. Per task:

- `completed` if done
- `deleted` if orphaned/irrelevant
- `in_progress` only if genuinely continuing

## Step 1: Pre-flight

Extracted to `bin/resolve_preflight.sh` — checks codex availability, `gh` binary + auth, syncs with remote. Caches positive results under `.claude/state/preflight/` (4 h TTL). Emits `CODEX_AVAILABLE=<bool>` and `GH_OK=true` on stdout for `eval`; status messages go to stderr; exits non-zero only on hard failure (`gh` missing/unauthenticated, `git pull` conflict).

```bash
eval "$("${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_preflight.sh")"  # timeout: 30000
```

gh missing or not authenticated → script exits 1 (error printed above).

Codex missing: set `CODEX_AVAILABLE=false` — Steps 3–7 work without it. Step 8 degradation:
1. Simple, single-file items → `foundry:sw-engineer`
2. Complex/multi-file → skip with: `⚠ codex not found — skipping item #<id>. Install: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`

### Review-handoff auto-detect (when $ARGUMENTS is empty)

When `$ARGUMENTS` empty:

```bash
# Find most recent review output (written by /review to .reports/review/)
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
# Defence-in-depth: capture parser output to a temp file and validate that every
# line is a plain VAR=value assignment (no shell metacharacters that could trigger
# command substitution, pipelines, or backgrounding) before sourcing. parse-resolve-args.py
# uses shlex.quote so its output is already safe, but validating here protects against
# future regressions or a tampered binary.
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

**Unsupported flag check** — after `eval`, scan remaining `$ARGUMENTS` for any `--<token>` not in `{--no-challenge, --agent}`. Found → invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown tokens). Supported: `--no-challenge`, `--agent <name>`.

- `MODE="pr+report"` → strip `report` suffix conceptually (already captured separately); find latest review report via `ls -t .reports/review/*/review-report.md 2>/dev/null | head -1`; no report found → warn but continue in pr mode
- `MODE="report"` → find latest review report via `ls -t .reports/review/*/review-report.md 2>/dev/null | head -1`; no report found → stop with: "No review report found in .reports/review/ — run /review \<PR#> first, or provide a PR number"; extract PR# from header if present; no PR# in header → add branch safety check before Step 8 — `CURRENT=$(git branch --show-current); DEFAULT=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}'); [ "$CURRENT" = "$DEFAULT" ] && { echo "⛔ On default branch '$CURRENT' — report mode without PR# must not operate on default branch; check out a feature branch first"; exit 1; }`
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

Read report. Parse findings from each `###` header matching any of: `Critical` or `[blocking]`, `Architecture`, `Test Coverage`, `Performance`, `Documentation`, `Static Analysis`, `API Design`, `Codex Co-Review`. Use contains-match (`grep -E '^### .*(Critical|Architecture|Test Coverage|Performance Concerns|Documentation|Static Analysis|API Design|Codex Co-Review)'`) — headers may carry a `⚠ LOW CONFIDENCE — ` prefix (e.g. `### ⚠ LOW CONFIDENCE — Architecture & Quality`) that exact-match misses. Skip headers matching: `OSS Checks`, `Recommended Next Steps`, `Review Confidence`, `Issue Root Cause Alignment`.

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
- **Notes**: ≤45 chars — truncate; full text preserved in `full_comment_text`; use `—` when empty

Status codes: `pending` · `✓ resolved` · `⊘ skipped` · `⊘ no action`. Verbose reason → Notes column:

```markdown
### Action Items — PR #<number>

| # | Type | Author | Status | Summary | Notes |
|---|------|--------|--------|---------|-------|
| 1 | [gh][req] | @reviewer | pending | rename param `x` to `count` | — |
| 2 | [gh][suggest] | @maintainer | pending | add docstring | — |
| 3 | [gh][question] | @reviewer | pending | why not use X instead? | — |
```

Long content never justifies switching to key-value or separator-delimited format — truncate, stay in table.

Answer `[question]` items resolvable from code — clear answer → present answer and proposed reclassification via `AskUserQuestion` before implementing: "[question] #N: '<summary>' — answer: '<answer>'. Reclassify as [req]?" Options: (a) Yes, implement · (b) Keep as question for maintainer. Never self-promote `[question]` to `[req]` without user confirmation. Maintainer judgement needed → surface and pause. Contributor answer ≠ auto-close — answer revealing known limitation/deferred work → keep `[question]`, surface for maintainer to accept/reject.

## Step 3c: Merge report findings (pr + report mode only)

*Skip when in pr mode.*

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

## Step 3d: User item selection

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text.

Pending items = ACTION_ITEMS where type ≠ `[done]` and type ≠ `[info]`. Zero pending → set `SELECTED_ITEMS` = all pending IDs, skip to Step 3e.

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

**Commit mode** — after resolving `SELECTED_ITEMS` (non-empty), invoke `AskUserQuestion` as a separate call:

```text
AskUserQuestion: "How should changes be committed?"
Options:
  (a) Commit each item separately — one commit per item, staged+committed inline (default)
  (b) Commit all at once — stage as you go, single commit after all items
  (c) Stage only — no commits; changes stay staged on PR branch
      ⚠ Stage-only: cannot cleanly restore original branch after Step 11 — stash or pop manually
```

Set `COMMIT_MODE`:
- (a) → `each`
- (b) → `all`
- (c) → `stage`

## Step 3e: Create tasks for selected items

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

*Runs only when `SELECTED_ITEMS` non-empty (set in Step 3e). Empty → skip to Step 9.*

**Branch-safety pre-check** — must run BEFORE `gh pr checkout` so a wrong-branch commit is impossible (per `git-commit.md` Gate 2). Verify the PR's `headRefName` is not the repo's default branch — `gh pr checkout` of a same-repo PR whose HEAD = default branch would land us on default and any later commit (Step 8) would violate Gate 2:

```bash
DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')  # timeout: 6000
PR_HEAD_REF=$(gh pr view "<PR#>" --json headRefName --jq .headRefName 2>/dev/null)  # timeout: 6000
if [ -n "$DEFAULT_BRANCH" ] && [ "$PR_HEAD_REF" = "$DEFAULT_BRANCH" ]; then
    echo "⛔ PR HEAD ref ($PR_HEAD_REF) equals default branch — refusing to check out and commit on default branch"
    exit 1
fi
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

**Soft cap: 8 Codex dispatches per session.** If `SELECTED_ITEMS` has > 8 items, invoke `AskUserQuestion`: "N items selected — Codex cap is 8 per session. Split into batches?" Options: (a) Apply first 8 now, re-run for remainder · (b) Apply all [req] items only (if ≤8) · (c) Proceed anyway (sequential, may be slow).

<!-- Step 8 defined in action-item-dispatch.md — see that file for phase/sub-step detail -->

Read and execute `$_OSS_RESOLVE/modes/action-item-dispatch.md`.

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
PUSH_STAT=$(git diff "$FORK_REMOTE/$HEAD_REF..HEAD" --stat 2>/dev/null | tail -1 || git diff "origin/$BASE_REF..HEAD" --stat | tail -1) # timeout: 3000
LAST_SUBJECT=$(git log -1 --format=%s 2>/dev/null) # timeout: 3000
echo "→ $PUSH_COUNT commits ready to push to $FORK_REMOTE/$HEAD_REF ($PUSH_STAT); last commit: \"$LAST_SUBJECT\""
```

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

Include `### Challenge Log` section in report — one row per item: id · evidence verdict · suggestion verdict · resolution (as-suggested / self-resolved / rejected). Omit section when `--no-challenge`.

```bash
# Branch restore — skip when COMMIT_MODE=stage (staged changes would be lost)
if [ "$COMMIT_MODE" = "stage" ]; then
    echo "⚠ COMMIT_MODE=stage: changes are staged on $(git branch --show-current) — restore to $SAVED_BRANCH skipped to preserve staged work. Run: git stash && git checkout $SAVED_BRANCH && git stash pop (on PR branch) when ready."
elif [ -n "$SAVED_BRANCH" ]; then
    git checkout "$SAVED_BRANCH" 2>/dev/null && echo "→ Restored to $SAVED_BRANCH"  # timeout: 5000
fi
```

Invoke `AskUserQuestion` — options: (a) Open PR in browser (`gh pr view <PR_NUMBER> --web`) · (b) Merge now (`gh pr merge <PR_NUMBER> --merge`) · (c) Skip.

## Step 12: Comment dispatch + Codex review loop

Read and execute `$_OSS_RESOLVE/modes/comment-dispatch.md`.

</workflow>

<calibration>

Non-calibratable — `disable-model-invocation: true` means skill dispatches to sub-agents rather than running model pass directly; calibrate cannot score model output for skill that produces none.

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
- **Impl agent health**: IMPL_AGENT defaults to `codex:codex-rescue`; subject to CLAUDE.md §8 — 15-min cutoff, ⏱ on timeout; partial results via `tail -100` on output file. `--agent curator` or other agents: foreground only, no health monitoring needed.
- **Effort calibration**: effort set per item — never `low`; minimum `medium`; typo/doc/formatting/rename-simple → `medium`; multi-file/architecture/new-feature → `xhigh`; default → `high`; effort prefix in agent prompt; `CHANGE_SCOPE` aggregated for Step 9 test targeting
- **Two-phase challenge**: evidence phase checks code reality (problem exists?); suggestion phase checks fix quality (right approach?); evidence reject → item skipped; suggestion reject → self-resolved fix using challenger's `alternative` field; all outcomes recorded to `CHALLENGE_LOG` and surfaced in Step 11 report
- **COMMIT_MODE**: set in Step 3d; `each` = commit after each item (default); `all` = single commit after loop; `stage` = no commits (⚠ branch restore in Step 11 leaves staged changes — warn user before attempting restore)
- **`--agent <name>`**: agent name must match an installed agent (plugin-prefixed, e.g. `foundry:curator`); skip availability check — failure at dispatch time surfaces error naturally; omit Codex co-author trailer when IMPL_AGENT ≠ `codex:codex-rescue`
- **Thread resolution via GraphQL** — `isResolved` lives on `PullRequestReviewThread` (GraphQL only); REST `/pulls/{PR}/comments` does not expose it. `RESOLVED_THREAD_IDS` = root comment `databaseId` values; GraphQL failure → `[]` fallback.
- **Commit attribution** — `[gh]` items: `[resolve #<id>] @<reviewer> (gh):`; `[report]` items: `[resolve #<id>] /review finding by <agent-name> (report: <report-path>):` — distinguishes automated findings in git history.
- **Sources block**: print after all sources read, before action item table.
- **Reference scenarios** (documentation only — not for `/calibrate`): (1) Mode selection: bare PR number → pr mode; `42 report` → pr + report mode; bare `report` → report mode; bare comment text → comment dispatch (Step 12). (2) Action item classification: LGTM/emoji → `[info]`; `nit:` suggestion → `[gh][suggest]`; resolved thread → `[done]`; "must fix before merge" from reviewer with write access → `[gh][req]`. (3) Challenge accuracy: evidence challenge on actually-present bug → VALID; already addressed in commit → REJECT; suggestion with better alternative available → REJECT with alternative.
- **Step 7 delegation** — resolve owns orchestration + context; sw-engineer owns code-level resolution; resolve retains conflict report + `git merge --continue`.
- Follow-up chains:
  - After push → never approve/comment on PR; maintainer reviews + clicks Merge.
  - Unanswered `[question]` items → record in resolve report only; do NOT post to PR.
  - After merge → linked issues close if PR body has `Closes #<issue#>`/`Fixes #<issue#>`; `CLOSING_ISSUES` found in Step 3b but body lacks keywords → surface gap in Resolve Report under `### Closing Keywords` note — do not edit PR body. Note: "PR body does not contain `Closes #<issue#>` — linked issue will not auto-close on merge. Add closing keyword manually via GitHub PR edit UI."

</notes>
