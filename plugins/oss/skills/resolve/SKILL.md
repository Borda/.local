---
name: resolve
description: "OSS maintainer fast-close workflow for GitHub PRs. Three phases: (1) PR intelligence — reads full thread, linked issues, PR body to synthesize contribution motivation and classify every comment into action items; (2) conflict resolution — checks out PR branch (fork-aware via gh pr checkout), merges BASE into it, resolves conflicts semantically using contributor's intent as priority lens; (3) implements each action item as separate attributed commit via Codex, pushes back to contributor's fork. Supports three source modes: pr (live GitHub comments only), report (latest /review report findings as action items, no GitHub re-fetch), and pr + report (both sources aggregated and deduplicated in one pass). Also accepts bare comment text for single-comment dispatch. NOT for reply drafting to /oss:analyse findings (use /oss:analyse --reply). NOT for code diff review of PR changes (use /oss:review). NOT for release preparation (use /oss:release). NOT for fixing local bugs unrelated to a PR (use /develop:fix; requires develop plugin)."
argument-hint: "<PR number or URL> [report] | report | <review comment text>"
when_to_use: "TRIGGER when: PR is ready to close and has open comments, conflicts, or review findings to address; user says 'close this PR', 'resolve comments on PR #N', or 'implement review findings'. SKIP: reply-drafting to /oss:analyse findings (use /oss:analyse --reply); local bug without a PR (use /develop:fix)."
disable-model-invocation: true
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
_OSS_RESOLVE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/resolve 2>/dev/null | head -1)  # timeout: 5000
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
```

Extracted to `bin/resolve_preflight.py` — checks codex availability, `gh` binary + auth, syncs with remote. Caches positive results under `.claude/state/preflight/` (4 h TTL). Writes `CODEX_AVAILABLE` and `GH_OK` to `${TMPDIR:-/tmp}/resolve-preflight-*` files; status messages go to stderr; exits non-zero only on hard failure (`gh` missing/unauthenticated, `git pull` conflict).

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_preflight.py"  # timeout: 30000
_PREFLIGHT_RC=$?
[ "$_PREFLIGHT_RC" -ne 0 ] && exit 1
CODEX_AVAILABLE=$(cat "${TMPDIR:-/tmp}/resolve-preflight-CODEX_AVAILABLE" 2>/dev/null || echo "false")
GH_OK=$(cat "${TMPDIR:-/tmp}/resolve-preflight-GH_OK" 2>/dev/null || echo "true")
```

gh missing or not authenticated → script exits 1 (error printed above; eval skipped when exit code non-zero).

```bash
# Codemap auto-detect: on by default if installed; --no-codemap to opt out; --codemap = strict (stop if not installed)  # timeout: 5000
_PROJ=$(git rev-parse --show-toplevel 2>/dev/null | xargs basename | tr -cd 'a-zA-Z0-9._-')
[ -z "$_PROJ" ] && _PROJ="default"
_IDX="${CODEMAP_INDEX_DIR:-.cache/codemap}"
if [ "$CODEMAP_FORCE_OFF" = "true" ]; then
    CODEMAP_ENABLED=false
elif command -v scan-query >/dev/null 2>&1 && [ -f "${_IDX}/${_PROJ}.json" ]; then
    CODEMAP_ENABLED=true
elif [ "$CODEMAP_STRICT" = "true" ]; then
    if ! command -v scan-query >/dev/null 2>&1; then
        printf "! --codemap passed but codemap plugin not installed.\n  Install: claude plugin install codemap@borda-ai-rig\n"; exit 1
    else
        printf "! --codemap passed but no index found for project '%s'.\n  Build index: /codemap:scan-codebase\n" "$_PROJ"; exit 1
    fi
else
    CODEMAP_ENABLED=false
fi
echo "$CODEMAP_ENABLED" > "${TMPDIR:-/tmp}/resolve-codemap-enabled"
```

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
# Extract codemap flags before passing to parser (parse-resolve-args.py does not handle them)  # timeout: 3000
CODEMAP_FORCE_OFF=false; CODEMAP_STRICT=false
[[ " $ARGUMENTS " == *" --no-codemap "* ]] && CODEMAP_FORCE_OFF=true
[[ " $ARGUMENTS " == *" --codemap "* ]] && [[ " $ARGUMENTS " != *" --no-codemap "* ]] && CODEMAP_STRICT=true
ARGUMENTS=$(echo "$ARGUMENTS" | sed 's/--no-codemap//g; s/ --codemap / /g' | xargs)
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

<!-- loads: review-section-taxonomy.md -->
Read `$_OSS_SHARED/review-section-taxonomy.md` — use **Grep pattern** row for header matching (contains-match; headers may carry `⚠ LOW CONFIDENCE — ` prefix), **Severity → Resolve Type** table for `type` assignment, **LOW Grouping Rule** for composite rows, and **Owner agent** column for `author` field. Skip sections where Grep key is `— skip`.

- `author`: Owner agent column from taxonomy
- `file`/`line`: extract from `file:line` notation; blank if absent or grouped composite
- `full_comment_text`: full finding bullet (or concatenated bullets for composites)
- All items get `[report]` prefix on `type` (e.g., `[report][req]`, `[report][suggest]`)

PR# found in report header → set `$ARGUMENTS = <N>`, go to Step 4; skip Step 3b entirely. After checkout, set `SELECTED_ITEMS` = all report-derived ACTION_ITEMS IDs (report mode executes all findings; no user selection step); skip to Step 8.

No PR# in header → skip Steps 3b and 4; work on current branch as-is. Before skipping, set fallback values for variables Step 8 reads: `HEAD_REF=$(git branch --show-current 2>/dev/null || echo "")` and `IS_FORK=false` (no cross-repo context). Set `SELECTED_ITEMS` = all report-derived ACTION_ITEMS IDs; skip to Step 8.

**Report mode — Step 8 behavior**: `SELECTED_ITEMS` initialized above; Step 3d (user selection) is skipped; Step 8 proceeds with all report-derived items. If report produces zero action items: `SELECTED_ITEMS=[]` → Step 8 skipped, jump to Step 9.

**`BASE_REF` derivation (no-PR path)** — when Step 3b is skipped (report mode without PR#, or comment-dispatch mode), Step 9's lint-qa gate still needs `BASE_REF` for `git merge-base HEAD "origin/$BASE_REF"`. Without this, `BASE_REF` expands empty → `origin/` is an invalid ref → linting sees no changes → workflow pushes silently with vacuous QA gate. Set it from the local default-branch symbolic-ref before Step 8, and guard the downstream `git merge-base` against shallow-clone empty output (CI checkouts frequently use `--depth=1` and `merge-base` returns nothing — linting again sees no changes):

```bash
BASE_REF=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||' || echo "main")  # timeout: 3000
# Pre-compute MERGE_BASE for Step 9 with shallow-clone fallback to the repo's root commit;
# without this, `git merge-base HEAD origin/$BASE_REF` returns empty in shallow clones and
# `git diff <empty>..HEAD` shows the entire branch history (or nothing at all).
MERGE_BASE=$(git merge-base HEAD "origin/$BASE_REF" 2>/dev/null)  # timeout: 3000
if [ -z "$MERGE_BASE" ]; then
    MERGE_BASE=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)  # timeout: 3000 — root commit fallback
fi
```

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
- `PR_TITLE` — `.title`
- `PR_BODY` — `.body` (short; kept in-context as motivation prompt seed)
- `PR_LABELS` — `.labels[].name | join(",")` (comma-separated label names; empty string if none)

Set up implementation work directory and fetch repo name (used throughout the workflow):

```bash
# Guarantee $IMPL_DIR is an absolute path before subagent dispatch — subagents may run
# with a CWD different from the orchestrator's; a relative $IMPL_DIR would resolve to
# the wrong directory inside the subagent and silently lose files.
[ -z "$IMPL_DIR" ] && IMPL_DIR=$(mktemp -d)  # timeout: 3000
[[ "$IMPL_DIR" = /* ]] || IMPL_DIR=$(mktemp -d)  # replace any relative path with a fresh absolute tempdir
mkdir -p "$IMPL_DIR"  # timeout: 3000
REPO_NAME=$(gh repo view --json name --jq .name 2>/dev/null)  # timeout: 6000
```

### Thread intelligence (subagent)

Infer `INTEL_AGENT` from `PR_LABELS` + `PR_TITLE` (lowercase, first match wins) using the same routing table as `action-item-dispatch.md`:

| Signal keywords in labels/title | `INTEL_AGENT` |
| --- | --- |
| `test`, `spec`, `pytest`, `coverage` | `foundry:qa-specialist` |
| `doc`, `readme`, `changelog`, `sphinx` | `foundry:doc-scribe` |
| `lint`, `style`, `format`, `ruff`, `mypy` | `foundry:linting-expert` |
| (no match / mixed) | `foundry:sw-engineer` |

**`--agent` override applies to `INTEL_AGENT`**: when the caller passes `--agent <name>`, the resolved (auto-prefixed) agent overrides the routing table for `INTEL_AGENT` as well as the Step 8 implementation agent — caller's explicit agent choice always wins. Exception: when the resolved agent is `codex:codex-rescue` (Codex is the implementation default; not a classification agent), fall back to the routing table for `INTEL_AGENT`.

Apply `agent-resolution.md` fallback to `INTEL_AGENT` (foundry absent → substitute with `general-purpose` + role prefix).

Raw PR discussion — all `--comments`, formal reviews, and inline code comments — can be thousands of tokens on an active PR. Offload fetching + classification to a subagent; orchestrator context stays small. Subagent writes structured output to `$IMPL_DIR/`; orchestrator reads only the compact envelope and loads the classified table from file.

```text
Agent(subagent_type="${INTEL_AGENT}", prompt="
Fetch and classify PR #<PR_NUMBER> review feedback for the /oss:resolve workflow.

Inputs (substitute literal values — agent does not inherit shell variables):
- PR: #<PR_NUMBER>  (repo: <BASE_REPO_OWNER>/<REPO_NAME>)
- PR title: <PR_TITLE>
- PR body: <PR_BODY>
- Linked issues: <CLOSING_ISSUES>  # comma-separated issue numbers; may be empty
- Contributor: @<PR_AUTHOR>
- Output dir: <IMPL_DIR>           # expand to absolute path before spawning

Fetch (each gh call timeout 15000 ms; run as Bash):
1. gh pr view <PR_NUMBER> --comments
2. gh api repos/<BASE_REPO_OWNER>/<REPO_NAME>/pulls/<PR_NUMBER>/reviews
3. gh api repos/<BASE_REPO_OWNER>/<REPO_NAME>/pulls/<PR_NUMBER>/comments
4. Resolved-thread databaseId list via GraphQL with full pagination:
   Use query with pageInfo{hasNextPage,endCursor} on reviewThreads(first:100,after:\$after).
   Loop until hasNextPage=false; accumulate databaseId values for isResolved=true threads.
   On GraphQL failure → treat as empty list.
5. For each issue number in CLOSING_ISSUES: gh issue view <N> --json title,body

Assign location field per source (determines GitHub resolvability):
  Source 1 (gh pr view --comments) → location: discussion (PR main-thread; no GitHub "Resolve conversation" button)
  Source 2 (gh api .../reviews) top-level body (no path/position) → location: discussion (review summary; no resolve button)
  Source 3 (gh api .../comments) → location: inline (code-review thread; "Resolve conversation" button available)
  [report] items (no GitHub source) → location: report
Key invariant: location tracks "does this comment have a resolvable PullRequestReviewThread?" not which endpoint returned it.

Synthesize contribution motivation (2–3 sentences using PR body + linked issues):
what problem contributor solving, why this approach, expected user-visible outcome.
This becomes the priority lens for conflict resolution.
**PR body = stated intent; thread = authoritative record**: PR descriptions often drift from actual implementation when reviewers request changes mid-review. When PR body conflicts with what thread discussion/reviewer requests agreed upon, thread wins. Use thread consensus to understand what was actually implemented, not original PR description.

Classify EVERY comment using these codes:
  [gh][req]      change required before merge (reviewer with write access / maintainer)
  [gh][suggest]  improvement, non-blocking
  [gh][question] open question — needs answer before deciding what code to write
  [done]         location:inline thread isResolved=true OR subsequent commit/reply addressed it; location:discussion — no isResolved signal; mark [done] only if a subsequent reply clearly addresses it (discussion items will otherwise remain pending — GitHub has no resolve button for them)
  [info]         praise / acknowledgement / emoji-only — skip
  [self-review]  /oss:review finding — not a GitHub commenter

Per location:inline comment: if its REST 'id' (= GraphQL databaseId) appears in resolved-thread
list → mark [done] without reading content. All others: apply codes above.
Per location:discussion comment: skip resolved-thread list entirely — PR discussion comments have no resolvable PullRequestReviewThread; apply classification codes directly.

**Deprecation false-positive filter**: Before finalising any action item whose `full_comment_text` requests adding a deprecation warning (keywords: "deprecate", "deprecation", "DeprecationWarning", "deprecated") for a removed argument, parameter, or function:
1. Determine the removed symbol name from comment context or diff.
2. Get latest release tag: `LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || gh release list --limit 1 --json tagName --jq '.[0].tagName' 2>/dev/null)`  # timeout: 6000
3. Check if symbol existed in that release: `git show "$LATEST_TAG" -- <file_path> 2>/dev/null | grep -qF "<symbol>"`  # timeout: 6000
4. **Not found in latest tag** → symbol was never released; downgrade item to `[done]`; set Notes to "unreleased API — deprecation not required; clean removal OK".
5. **Found in latest tag** → symbol was released; keep original classification ([gh][req] or [gh][suggest]) — deprecation is legitimately needed.
6. **No tag found** → cannot determine; keep original classification but add Notes "no release tag — deprecation status unknown".

ACTION_ITEM fields: id (sequential int starting at 1), type, change, severity, author,
summary (≤60 chars, truncated at word boundary with …), file, line, url (html_url from
API, blank for report items), full_comment_text, location.
  - change ∈ {code,test,docs,config,ci,style,refactor}; default=code when ambiguous
  - severity ∈ 1..5 (5=highest); [req] floor=3
  - location ∈ {inline, discussion, report}; inline = code-review comment (GitHub "Resolve conversation" button available); discussion = PR main-thread comment (no resolve button — cannot be marked resolved in GitHub UI); report = /review finding (no GitHub source)

Write THREE files using the Write tool (expand <IMPL_DIR> to the literal path above):

1. <IMPL_DIR>/pr-intelligence.md
   Sources block: Mode=pr · PR=#<PR_NUMBER> · GitHub=Read — PR body · <N> comments ·
   <N> reviews · <N> inline code comments · Report=not used
   Motivation paragraph (2–3 sentences).
   Table header: ### Action Items — PR #<PR_NUMBER>
   Columns: # | Type | Change | Severity | Author | Status | Summary | Loc | Notes
   Truncation: Summary ≤60 chars, Notes ≤45 chars (use — when empty). Loc = inline / discussion / report. All Status=pending.
   MUST render as markdown table. Example row:
   | 1 | [gh][req] | code | 4 | @reviewer | pending | rename param x to count | inline | — |

2. <IMPL_DIR>/action-items.jsonl
   One compact JSON object per line, one ACTION_ITEM each.
   Fields: id, type, change, severity, author, summary, file, line, url, full_comment_text, location.

3. <IMPL_DIR>/pr-vars.sh
   ONLY these assignments, one per line, each value single-quoted, no shell metacharacters:
     RESOLVED_THREAD_IDS_COUNT='<int>'
     ACTION_ITEMS_TOTAL='<int>'
     ACTION_ITEMS_REQ='<int>'
     ACTION_ITEMS_SUGGEST='<int>'
     ACTION_ITEMS_DONE='<int>'
     ACTION_ITEMS_INLINE='<int>'
     ACTION_ITEMS_DISCUSSION='<int>'
     PR_MOTIVATION='<motivation text; replace any literal single-quotes in text with spaces>'

DO NOT print table, motivation, or raw comment data in final message — write to files only.
Return ONLY this compact JSON as your FINAL message (nothing after it):
{\"status\":\"done\",\"items\":N,\"req\":N,\"suggest\":N,\"done\":N,\"files\":[\"<IMPL_DIR>/pr-intelligence.md\",\"<IMPL_DIR>/action-items.jsonl\",\"<IMPL_DIR>/pr-vars.sh\"]}
")
```

> **Health monitoring** — CLAUDE.md §6: checkpoint before spawn; poll every 5 min; hard cutoff 15 min (tighten: use `CHALLENGE_TIMEOUT_S=300` from `<constants>` as the polling interval). On timeout ⏱: fall back to inline execution (fetch GitHub data directly in orchestrator context, classify inline) with explicit warning — never silently produce empty ACTION_ITEMS.

Validate and source vars after agent returns:

```bash
# Validate: only VAR='value' lines — mirrors parse-resolve-args.py defence-in-depth
if grep -qvE "^[A-Z_][A-Z0-9_]*='[^']*'$" "$IMPL_DIR/pr-vars.sh"; then
    echo "! BLOCKED — pr-vars.sh has unexpected output; refusing to source"
    cat "$IMPL_DIR/pr-vars.sh"
    exit 1
fi
. "$IMPL_DIR/pr-vars.sh"
[ "${RESOLVED_THREAD_IDS_COUNT:-0}" = "0" ] && echo "⚠ Could not fetch resolved thread status — some items may already be resolved; review table carefully"  # timeout: 3000
```

Read `$IMPL_DIR/pr-intelligence.md` and print its contents (Sources block + motivation + action item table). Orchestrator context now holds the *classified* table (~500–1000 tokens) rather than raw PR thread (often 5000–20000+ tokens on active PRs). All later steps read per-item details from `$IMPL_DIR/action-items.jsonl` when `full_comment_text` or other fields are needed:

```bash
jq -c ". | select(.id == <id>)" "$IMPL_DIR/action-items.jsonl"  # timeout: 5000
```

### `[question]` item handling

Answer `[question]` items resolvable from code — collect all resolvable ones, then present in a single batched `AskUserQuestion` call (up to 4 questions per call): each question = "[question] #N: '<summary>' — answer: '<answer>'. Reclassify as [req]?" Options per item: (a) Yes, implement · (b) Keep as question for maintainer. For >4 [question] items, use 2 batched calls. Never self-promote `[question]` to `[req]` without user confirmation. Maintainer judgement needed → surface and pause. Contributor answer ≠ auto-close — answer revealing known limitation/deferred work → keep `[question]`, surface for maintainer to accept/reject.

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

## Step 3d: User item selection

! IMPORTANT — invoke `AskUserQuestion` tool directly. Never write options as plain text.

Pending items = ACTION_ITEMS where type ≠ `[done]` and type ≠ `[info]`. Zero pending → set `SELECTED_ITEMS` = all pending IDs, skip to Step 3e.

Sort all pending items by severity descending (most impactful first). Constraint: max 3 items/question, max 4 questions/call — Q1–Q3 = item checkboxes, Q4 = bulk action. Note: `AskUserQuestion` always appends "Type something" outside the option list — 3 items + Type something = 4 visible per page; keep ≤3 items per group.

**Q4 = bulk action only — hard rule**: Q4 is always the last question, single-select, fixed options — never varies by item count or path:

```text
"Or choose a bulk action:"
  (a) +all [req]           — checked items UNION all [req] items
  (b) +all [suggest]       — checked items UNION all [suggest] items
  (c) Apply ALL [req + suggest] — all pending items (ignore checkboxes)
  (d) Skip all             — nothing; terminate after push
```

Never put items in Q4. Items span ≤3 groups regardless of how many type categories exist.

**Item checkbox questions (Q1–Q3)**: each `multiSelect: true`, header "Items to implement:", labels: `<type> #<id>: <summary>` (≤55 chars), description: `<file:line> · @<author>` + for `location: discussion` items append `· thread (no GH resolve)`. Fill Q1→Q3 in severity order (≤3 items each). If >9 pending items: two calls — print `→ N pending items — selecting in 2 calls` before call 1; Call 2 gets remaining items + Q4 again; "Apply ALL [req + suggest]" in Call 1 → skip Call 2.

**≥20 pending items — context-budget mode**: skip per-item checkboxes; print compressed table (type · id · summary ≤40 chars · file) then Q4 only.

Resolve `SELECTED_ITEMS`:
- Q4 = "Skip all" → `[]` → skip Step 8, jump to Step 9 (checkout + conflict resolution still run)
- Q4 = "+all [req]" → checked IDs ∪ all `[req]` IDs
- Q4 = "+all [suggest]" → checked IDs ∪ all `[suggest]` IDs
- Q4 = "Apply ALL [req + suggest]" → all pending IDs; skip Call 2 when in two-call flow
- Q4 = "Type something" / no bulk selected → checked IDs from Q1–Q3 only; for two-call flow, merge both calls

**Commit mode** — after resolving `SELECTED_ITEMS` (non-empty), invoke `AskUserQuestion` as a separate call.

**ESSENTIAL — all 4 options are mandatory; never emit fewer than 4.** LLMs tend to drop option (d) — do not omit it.

```text
AskUserQuestion: "How should changes be committed?"
Options:
  (a) Commit each item separately — one commit per item, staged+committed inline (default)
  (b) Commit by logical/topic group — ask for topic labels, then group related items into themed commits
  (c) Commit all at once — stage as you go, single commit after all items
  (d) Stage only — no commits; stays staged on PR branch (⚠ cannot cleanly restore original branch after Step 11 — stash/pop manually)
```

Set `COMMIT_MODE`:
- (a) → `each`
- (b) → `grouped`
- (c) → `all`
- (d) → `stage`

## Step 3e: Create tasks for selected items

Mark Step 2 task `completed`:

```text
TaskUpdate(task_id=<step2_task_id>, status="completed")
```

For each item in `SELECTED_ITEMS`, call `TaskCreate` **once per item** — one task per action item; scoped to selected items only, not all pending (avoids bloat when 20+ items exist but only a subset is selected):

```text
TaskCreate(
  subject="<type> <summary> — PR #<number>",   # <type> = full string with brackets, e.g. "[gh][req] rename param — PR #42"
  description="Author: @<author> | Change: <change> | Severity: <severity> | File: <file:line or '—'> | <full_comment_text>",
  activeForm="Implementing: <summary>"          # <summary> truncated to 80 chars
)
```

Store returned task ID in each `SELECTED_ITEMS` entry as `task_id`.

## Step 4: Checkout PR branch

*Skip only when `MODE = report` with no PR# (`$PR_NUMBER` unset — no remote branch to check out). In pr mode, runs unconditionally regardless of `SELECTED_ITEMS` — conflict resolution must happen even when 0 action items selected.*

**`gh` availability check** — hard prereq; `gh pr checkout` has no fallback path:

```bash
command -v gh >/dev/null 2>&1 || { echo "! BLOCKED — gh CLI required; install: https://cli.github.com"; exit 1; }  # timeout: 3000
```

**Branch-safety pre-check** — must run BEFORE `gh pr checkout` so a wrong-branch commit is impossible (per `git-commit.md` Gate 2). Verify the PR's `headRefName` is not the repo's default branch — `gh pr checkout` of a same-repo PR whose HEAD = default branch would land us on default and any later commit (Step 8) would violate Gate 2:

```bash
# Local-first detection (no network); fall back to network query; hard-fail when neither resolves
DEFAULT_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's|refs/remotes/origin/||')  # timeout: 3000
[ -z "$DEFAULT_BRANCH" ] && DEFAULT_BRANCH=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | awk '{print $NF}')  # timeout: 6000
[ -z "$DEFAULT_BRANCH" ] && { printf "! BLOCKED — cannot determine default branch; refusing to proceed\n"; exit 1; }
PR_HEAD_REF=$(gh pr view "<PR#>" --json headRefName --jq .headRefName 2>/dev/null)  # timeout: 6000
if [ "$PR_HEAD_REF" = "$DEFAULT_BRANCH" ]; then
    echo "⛔ PR HEAD ref ($PR_HEAD_REF) equals default branch — refusing to check out and commit on default branch"
    exit 1
fi
SAVED_BRANCH=$(git rev-parse --abbrev-ref HEAD)  # timeout: 3000
# SHA-first checkout guard: if local HEAD already matches PR remote head, skip checkout entirely.
# Avoids worktree conflict where gh pr checkout creates pr-N-slug alias instead of HEAD_REF
# (git rejects checking out a branch active in another worktree).
PR_HEAD_OID=$(gh pr view "<PR#>" --json headRefOid --jq .headRefOid 2>/dev/null)  # timeout: 6000
LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null)  # timeout: 3000
# Diagnostic trace so reflog forensics can correlate skill state with branch outcome
# (cf. investigate report 2026-06-13T11-00-00Z: pr195 alias created when state opaque)
>&2 echo "→ Step 4 state: SAVED_BRANCH=$SAVED_BRANCH PR_HEAD_REF=$PR_HEAD_REF PR_HEAD_OID=${PR_HEAD_OID:-<empty>} LOCAL_SHA=${LOCAL_SHA:-<empty>}"
if [ -n "$PR_HEAD_OID" ] && [ "$LOCAL_SHA" = "$PR_HEAD_OID" ]; then
    echo "→ Already at PR head ($LOCAL_SHA) — skipping gh pr checkout"
    # SHA matches but caller may sit on a *different branch name* pointing at same OID
    # (e.g. a prior `gh pr checkout` left them on `pr<N>` alias from a previous run).
    # Force-align to PR_HEAD_REF so Step 8 commits + Step 10 push land on the PR branch.
    CURRENT=$(git branch --show-current 2>/dev/null)
    if [ -n "$PR_HEAD_REF" ] && [ "$CURRENT" != "$PR_HEAD_REF" ]; then
        echo "→ Re-aligning local branch: $CURRENT → $PR_HEAD_REF (same SHA $LOCAL_SHA)"
        git switch "$PR_HEAD_REF" 2>/dev/null \
            || git switch -c "$PR_HEAD_REF" "$LOCAL_SHA" \
            || { echo "⛔ Cannot switch to $PR_HEAD_REF — aborting (branch active in another worktree?)"; exit 1; }
    fi
else
    # Hard-exit on checkout failure — silent failure leaves git on the caller's branch while
    # $HEAD_REF is set from Step 3b, causing Step 8 commits to land on the wrong branch.
    # `--branch "$PR_HEAD_REF"` forces gh to use the PR's headRefName as the local branch
    # name — without it, gh CLI v2.93+ falls back to a `pr<N>` alias when name collision
    # is detected, causing Step 10 `git push HEAD:$HEAD_REF` to create an unrelated remote
    # branch (root cause of CRITICAL bug in pyDeprecate run 2026-06-13T08:33Z).
    gh pr checkout <PR#> --branch "$PR_HEAD_REF" \
        || { echo "⛔ gh pr checkout failed — aborting (network, branch deleted, auth expired, or local conflicts)"; exit 1; }   # fetches HEAD_REF; for forks, adds the contributor's remote + sets up tracking  # timeout: 15000
fi
```

`gh pr checkout` auto-handles forks — adds contributor's remote, configures tracking. Verify checkout landed on expected branch — if not, abort before Step 8 can commit:

```bash
git remote -v | grep '(fetch)' | head -10 # timeout: 3000
git status                                # confirm we are on HEAD_REF  # timeout: 3000
CURRENT_BRANCH=$(git branch --show-current 2>/dev/null)  # timeout: 3000
# Same-repo rule: for non-fork PRs, local branch name MUST equal PR_HEAD_REF — no aliases ever.
# gh CLI sometimes silently falls back to `pr<N>` when a same-name local branch exists;
# `--branch "$PR_HEAD_REF"` in the checkout above prevents this, but assert here as hard gate.
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
# Soft-verify remote exists; gh pr checkout layouts vary across versions
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
# IMPL_AGENT resolved in action-item-dispatch.md (Step 8); compute here too for cap branching
_RESOLVE_IMPL_AGENT="codex:codex-rescue"
[[ "$ARGUMENTS" == *"--agent "* ]] && _RESOLVE_IMPL_AGENT=$(echo "$ARGUMENTS" | grep -oP '(?<=--agent )\S+')
if [ "$_RESOLVE_IMPL_AGENT" = "codex:codex-rescue" ] && [ "$(echo "$SELECTED_ITEMS" | wc -w)" -gt 8 ]; then
    # invoke AskUserQuestion as described below
    :
fi
```

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

**Action Items table** — one row per selected item, columns: `#` | `Type` | `Change` | `Status` | `Resolution` | `Commit`:

- `Status`: ✓ implemented · ⊘ skipped · ✗ challenge-rejected
- `Resolution`: `implemented` · `self-resolved` (challenger provided alternative) · `skipped` · `challenge-rejected`
- `Change`: action type — `code` / `test` / `docs` / `config` / `ci` / `style` / `refactor`
- `Commit`: short SHA (7 chars); `—` when `COMMIT_MODE=stage`
- For `location: discussion` rows append `· thread (no GH resolve)` to Status — no GitHub Resolve button exists for PR main-thread comments

Include `### Challenge Log` section in report — one row per item: id · evidence verdict · suggestion verdict · resolution (as-suggested / self-resolved / rejected). Omit section when `--no-challenge`.

```bash
# Branch restore — skip when COMMIT_MODE=stage (staged changes would be lost)
if [ "$COMMIT_MODE" = "stage" ]; then
    echo "⚠ COMMIT_MODE=stage: changes are staged on $(git branch --show-current) — restore to $SAVED_BRANCH skipped to preserve staged work. Run: git stash && git switch $SAVED_BRANCH && git stash pop (on PR branch) when ready."
elif [ -n "$SAVED_BRANCH" ]; then
    git switch "$SAVED_BRANCH" 2>/dev/null && echo "→ Restored to $SAVED_BRANCH"  # timeout: 5000
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

- **Pre-flight git fetch** — Step 1 always runs `git fetch origin` (unconditional) so all remote tracking refs — including `origin/$BASE_REF` — are current before Step 5 merges. Then pulls current branch if upstream tracking ref exists and remote is ahead. `git pull` conflicts → exit with message to resolve manually — prevents `git merge --continue` with no in-progress merge
- **Branch safety** — `gh pr checkout <PR#>` always lands on PR's HEAD, never `main`/`master`. Never push to default branch — if PR branch = default branch, abort and surface.
- **Same-repo branch rule** — for non-fork PRs (`isCrossRepository=false`), local branch name MUST equal `headRefName` at all times. Never create a `pr<N>` alias or any other branch name substitute. Enforced by `--branch "$PR_HEAD_REF"` at checkout + hard assertion post-checkout. Rationale: `git push HEAD:$HEAD_REF` on a `pr<N>` alias creates a new remote branch instead of pushing to the PR head — silent data-loss class bug.
- **OSS fork support** — `gh pr checkout <PR#>` works same for branches + forks; forks get contributor remote + tracking; plain `git push` targets fork branch automatically.
- **Merge direction** — `origin/BASE_REF` INTO `HEAD_REF` (not reverse); PR branch = source of truth; maintainer still clicks Merge.
- **Contribution motivation before code** — provides "whose intent wins" lens; PR body + linked issues reveal constraints invisible in git diff.
- **`[question]` items** — answer inline in resolve report only (never post to PR); reclassify before implementing; never silently implement unanswered question.
- **Push verification** — confirm via `gh pr view --json commits` before reporting success; exit 0 from `git push` necessary but not sufficient (branch protection can silently reject).
- **Merge-push sequencing** — `git merge` and `git push` not atomic; concurrent push to same branch between these steps causes non-fast-forward rejection. Fetch + pull and retry push step only — do not re-run full merge.
- **`gh pr merge` flags**: `--merge` = preserves all commits; `--squash` = collapses (loses action-item commits); never `--rebase` (rewrites SHAs); default `--merge`.
- **Escape hatch**: `git merge --abort` = undo all conflict state; `git push --force-with-lease` (never plain `--force`) only when user explicitly requests — if push rejected after local amend.
- **Impl agent health**: IMPL_AGENT defaults to `codex:codex-rescue`; subject to CLAUDE.md §6 — 15-min cutoff, ⏱ on timeout; partial results via `tail -100` on output file. `--agent foundry:sw-engineer` or other implementation agents: foreground only, no health monitoring needed.
- **Effort calibration**: effort set per item — never `low`; minimum `medium`; typo/doc/formatting/rename-simple → `medium`; multi-file/architecture/new-feature → `xhigh`; default → `high`; effort prefix in agent prompt; `CHANGE_SCOPE` aggregated for Step 9 test targeting
- **Two-phase challenge**: evidence phase checks code reality (problem exists?); suggestion phase checks fix quality (right approach?); evidence reject → item skipped; suggestion reject → self-resolved fix using challenger's `alternative` field; all outcomes recorded to `CHALLENGE_LOG` and surfaced in Step 11 report
- **COMMIT_MODE**: set in Step 3d; `each` = commit after each item (default); `all` = single commit after loop; `stage` = no commits (⚠ branch restore in Step 11 leaves staged changes — warn user before attempting restore); `grouped` = stage all items first, then ask for topic labels, commit one commit per topic group — falls back to `each` when user skips label assignment
- **`--agent <name>`**: agent name accepted with or without plugin prefix; bare name auto-prefixed with `foundry:` (e.g. `sw-engineer` → `foundry:sw-engineer`); must resolve to an installed implementation agent (NOT config-review agents such as `foundry:curator`); skip availability check — failure at dispatch time surfaces error naturally; omit Codex co-author trailer when IMPL_AGENT ≠ `codex:codex-rescue`
- **Thread resolution via GraphQL** — `isResolved` lives on `PullRequestReviewThread` (GraphQL only); REST `/pulls/{PR}/comments` does not expose it. `RESOLVED_THREAD_IDS` = root comment `databaseId` values; GraphQL failure → `[]` fallback.
- **Discussion vs inline comments** — `gh pr view --comments` = PR main-thread discussion (`location: discussion`; no GitHub "Resolve conversation" button); `gh api .../pulls/<N>/comments` = inline code-review threads (`location: inline`; resolvable). `isResolved` GraphQL field only applies to `location: inline` items. `location: discussion` items cannot be auto-closed — they remain `pending` in action items even after implementation; GitHub has no resolve mechanism for them. Surface this in Step 11 report (`Loc` column + status suffix) so maintainers do not look for a non-existent Resolve button. `[report]` items (`location: report`) follow same convention: implement-only, no GitHub close action.
- **Commit attribution** — `[gh]` items: `[resolve #<id>] @<reviewer> (gh):`; `[report]` items: `[resolve #<id>] /review finding by <agent-name> (report: <report-path>):` — distinguishes automated findings in git history.
- **Sources block**: print after all sources read, before action item table.
- **Reference scenarios** (documentation only — not for `/calibrate`): (1) Mode selection: bare PR number → pr mode; `42 report` → pr + report mode; bare `report` → report mode; bare comment text → comment dispatch (Step 12). (2) Action item classification: LGTM/emoji → `[info]`; `nit:` suggestion → `[gh][suggest]`; resolved thread → `[done]`; "must fix before merge" from reviewer with write access → `[gh][req]`. (3) Challenge accuracy: evidence challenge on actually-present bug → VALID; already addressed in commit → REJECT; suggestion with better alternative available → REJECT with alternative.
- **Step 7 delegation** — resolve owns orchestration + context; sw-engineer owns code-level resolution; resolve retains conflict report + `git merge --continue`.
- Follow-up chains:
  - After push → never approve/comment on PR; maintainer reviews + clicks Merge.
  - Unanswered `[question]` items → record in resolve report only; do NOT post to PR.
  - After merge → linked issues close if PR body has `Closes #<issue#>`/`Fixes #<issue#>`; `CLOSING_ISSUES` found in Step 3b but body lacks keywords → surface gap in Resolve Report under `### Closing Keywords` note — do not edit PR body. Note: "PR body does not contain `Closes #<issue#>` — linked issue will not auto-close on merge. Add closing keyword manually via GitHub PR edit UI."

</notes>
