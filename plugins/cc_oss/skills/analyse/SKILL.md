---
name: analyse
description: |
  Analyze GitHub issues, Pull Requests (PRs), Discussions, and repo vitality for an Open Source Software (OSS) project. For any specific item, casts a wide net — finds and lists all related open and closed issues/PRs/discussions, explicitly flags duplicates. Summarizes long threads, extracts reproduction steps, and generates repo vitality stats. Uses gh Command Line Interface (CLI) for GitHub Application Programming Interface (API) access. Complements oss:shepherd (requires `oss` plugin). NOT for PR readiness assessment or code review (use oss:review).
  TRIGGER when: user provides GitHub issue number (#N), PR number, or github.com URL with issue/PR/discussion path AND asks to analyze, summarize, understand, or triage it; user asks for repo vitality stats or "is this repo healthy".
  SKIP: user already pasted full thread text inline; oss:resolve already active on same PR; user wants code review (use oss:review); user phrasing is "review PR" meaning code quality assessment, not thread triage (route to oss:review).
argument-hint: "<N|vitality [<owner>/<repo>|github-url]|ecosystem|path/to/report.md> [--reply] [--quick] [--keep \"<items>\"]"
allowed-tools: Read, Bash, Write, Edit, Agent, AskUserQuestion, TaskList, TaskCreate, TaskUpdate
context: fork
model: sonnet
effort: high
---

<objective>

Analyze GitHub threads + repo vitality. Help maintainers triage, respond, decide fast. Output actionable + structured — not just summaries.

NOT for implementing PR action items (use oss:resolve). NOT for **code-quality assessment on a PR** — phrasing like "review PR #N" or "does this PR look good?" routes here via TRIGGER (PR number + "analyze/summarize" verbs) but yields thread analysis, not code review. When request is code quality, route to `oss:review` (requires `oss` plugin) instead. NOT for multi-agent code review (use oss:review). NOT for CI pipeline diagnosis (use oss:cicd-steward (requires `oss` plugin)).

</objective>

<inputs>

- **$ARGUMENTS**: one of:
  - `N` (number, plain `123` or `#123`) — any GitHub thread: issue, PR, or discussion; auto-detects type
  - `vitality [<owner>/<repo> | <github-url>]` — repo vitality overview with 9-axis health scorecard, duplicate detection. Optional repo argument accepts `owner/repo` shorthand or full `https://github.com/owner/repo` URL. Omitted → auto-detected from git upstream. Non-GitHub remotes (GitLab, Bitbucket, etc.) stop with warning.
  - `ecosystem` — downstream consumer impact analysis for library maintainers
  - `--reply` — only valid with `N`; spawns shepherd to draft contributor-facing reply after thread analysis. Silently ignored for `vitality` and `ecosystem`.
  - `--quick` — only meaningful with `vitality`; fast daily-scorecard path skipping Codex independent review (Step 5) and mandatory adversarial rework loop (Step 6), reduces spawns to core 4 (gh-scraper + 3 axis scorers). Full mode (all quality passes) stays default. Silently ignored for `N`, `ecosystem`, report-path modes.
  - `path/to/report.md` — path to existing report file; only valid combined with `--reply`; skips all analysis, spawns shepherd directly using provided file

</inputs>

<constants>

> Background agent health monitoring (CLAUDE.md §6) — applies to Step 7 shepherd spawn
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay

</constants>

<compaction>

> loads: compaction-contract.md
Key boundary: end of Step 5 — gather/fetch complete, before Step 6 synthesis gate.
Preserve: cache-dir (.cache/gh), target # (CLEAN_ARGS), synthesized report path, reply-mode flag.

</compaction>

<workflow>

<!-- Agent resolution: see _OSS_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# loads: compaction-contract.md
# Cold-start fallback:
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
# Empty _OSS_SHARED → resolve_shared_path.py failed (missing python/script or oss plugin);
# downstream `[ -f "$_OSS_SHARED/..." ]` paths silently expand, Step 7 fails after full analysis.
# --reply: hard fail; non-reply: degrade gracefully.
if [ -z "$_OSS_SHARED" ]; then
    if [ "$REPLY_MODE" = "true" ]; then
        echo "! BLOCKED — could not resolve _OSS_SHARED (oss plugin missing, python unavailable, or resolve_shared_path.py absent); --reply mode requires it"
        exit 1
    else
        echo "⚠ _OSS_SHARED empty — oss plugin shared dir unresolved; continuing with degraded functionality (--reply will fail in this run)"
    fi
fi
# Persist $_OSS_SHARED — fresh shell loses vars (Check 41)
# loads: terminal-summaries.md (ships in this plugin's _shared); consumed by modes/thread.md, modes/vitality.md, modes/ecosystem.md
echo "${_OSS_SHARED:-}" > "${TMPDIR:-/tmp}/analyse-oss-shared-${CSID}"
```
> loads: oss-shared-resolver.md

## Step 1: Flag parsing

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Extract --keep value before CLEAN_ARGS cleaning (compaction-contract.md §keep: semantics)
KEEP_ITEMS=""
if [[ "$ARGUMENTS" =~ --keep[[:space:]]\"([^\"]+)\" ]]; then
    KEEP_ITEMS="${BASH_REMATCH[1]}"
fi
echo "${KEEP_ITEMS:-}" > "${TMPDIR:-/tmp}/analyse-keep-items-${CSID}"  # timeout: 5000
# Clear stale contract from any prior incomplete run (compaction-contract.md §Lifecycle)
rm -f .temp/state/skill-contract.md  # timeout: 5000
REPLY_MODE=false
QUICK_MODE=false
CLEAN_ARGS=$ARGUMENTS
# Anchored token match, not substring — substring falsely fires on `--reply-later`, repo names with `--reply-bot`.
if [[ " $ARGUMENTS " == *" --reply "* ]]; then
    REPLY_MODE=true
    CLEAN_ARGS=$(echo "$CLEAN_ARGS" | sed -E 's/(^| )--reply($| )/\1\2/')
fi
# --quick: vitality-only fast path — skips codex review + adversarial rework loop, fewer spawns. Silently ignored for N/ecosystem modes.
if [[ " $ARGUMENTS " == *" --quick "* ]]; then
    QUICK_MODE=true
    CLEAN_ARGS=$(echo "$CLEAN_ARGS" | sed -E 's/(^| )--quick($| )/\1\2/')
fi
# Strip --keep and its quoted value — consumed above
CLEAN_ARGS=$(echo "$CLEAN_ARGS" | sed 's/ --keep "[^"]*"//g')
CLEAN_ARGS="${CLEAN_ARGS#"${CLEAN_ARGS%%[![:space:]]*}"}"
# Persist REPLY_MODE + QUICK_MODE + CLEAN_ARGS — fresh shell loses vars (Check 41)
echo "$REPLY_MODE" > "${TMPDIR:-/tmp}/analyse-reply-mode-${CSID}"
echo "$QUICK_MODE" > "${TMPDIR:-/tmp}/analyse-quick-mode-${CSID}"
echo "$CLEAN_ARGS" > "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" # timeout: 5000
```

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload CLEAN_ARGS — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
CLEAN_ARGS="${CLEAN_ARGS#\#}"
echo "$CLEAN_ARGS" > "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}"
```

`REPLY_MODE` only meaningful when `$CLEAN_ARGS` is number — silently ignored for `vitality` and `ecosystem`.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload CLEAN_ARGS — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
DIRECT_PATH_MODE=false
REPORT_FILE=""
# *.md check must not intercept vitality/ecosystem; also reject plan/todo files
if [[ "$CLEAN_ARGS" == *.md ]] && [[ "$CLEAN_ARGS" != vitality* ]] && [[ "$CLEAN_ARGS" != ecosystem* ]]; then
    if [[ "$CLEAN_ARGS" == .plans/* ]] || [[ "$CLEAN_ARGS" == *todo_*.md ]]; then
        echo "! Invalid report path: '$CLEAN_ARGS' — plan/todo files are not valid report paths."
        echo "Usage: /oss:analyse <path/to/report.md> --reply  (use a .reports/ path)"
        exit 1
    fi
    DIRECT_PATH_MODE=true
    REPORT_FILE="$CLEAN_ARGS"
fi
# Persist DIRECT_PATH_MODE + REPORT_FILE — fresh shell loses vars (Check 41)
echo "$DIRECT_PATH_MODE" > "${TMPDIR:-/tmp}/analyse-direct-path-mode-${CSID}"
echo "$REPORT_FILE" > "${TMPDIR:-/tmp}/analyse-report-file-${CSID}" # timeout: 5000
# Persist TODAY — repeated `date +%Y-%m-%d` may roll over midnight, producing mismatched cache/report paths
_TODAY_FILE="${TMPDIR:-/tmp}/analyse-today-${CSID}"
if [ -f "$_TODAY_FILE" ]; then
    IFS= read -r TODAY < "$_TODAY_FILE" 2>/dev/null || TODAY=""
else
    TODAY=$(date +%Y-%m-%d)
    echo "$TODAY" > "$_TODAY_FILE"
fi
```

`DIRECT_PATH_MODE=true` only valid when `REPLY_MODE=true` — if combined without `--reply`, Step 2 prints plain-text error and stops; execution never reaches Step 5 mode dispatch.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload CLEAN_ARGS — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
GH_OWNER=""
GH_REPO=""
if [[ "$CLEAN_ARGS" == vitality* ]]; then
    VITALITY_EXTRA="${CLEAN_ARGS#vitality}"
    VITALITY_EXTRA="${VITALITY_EXTRA# }"

    if [ -n "$VITALITY_EXTRA" ]; then
        if [[ "$VITALITY_EXTRA" =~ ^https?:// ]]; then
            if [[ "$VITALITY_EXTRA" != *"github.com"* ]]; then
                echo "⚠ Not a GitHub URL — this skill supports GitHub only."
                echo "Other providers (GitLab, Bitbucket, Azure DevOps) are not supported."
                echo "Usage: /oss:analyse vitality https://github.com/owner/repo"
                exit 0
            fi
            VITALITY_REPO=$(echo "$VITALITY_EXTRA" | sed 's|https\?://github\.com/||' | cut -d'/' -f1-2)  # timeout: 5000
        elif [[ "$VITALITY_EXTRA" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
            VITALITY_REPO="$VITALITY_EXTRA"
        else
            echo "⚠ Unrecognised vitality argument: '$VITALITY_EXTRA'"
            echo "Usage: /oss:analyse vitality [owner/repo | https://github.com/owner/repo]"
            exit 0
        fi
    else
        VITALITY_REPO=$(gh repo view --json nameWithOwner --jq '.nameWithOwner' 2>/dev/null)  # timeout: 10000
        if [ -z "$VITALITY_REPO" ]; then
            REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")  # timeout: 5000
            if [[ "$REMOTE_URL" == *"github.com"* ]]; then
                VITALITY_REPO=$(echo "$REMOTE_URL" | sed 's|.*github\.com[:/]||' | sed 's|\.git$||')  # timeout: 5000
            elif [ -n "$REMOTE_URL" ]; then
                echo "⚠ Remote '$REMOTE_URL' is not a GitHub repository."
                echo "This skill supports GitHub only. Other providers are not supported."
                echo "Tip: /oss:analyse vitality https://github.com/owner/repo"
                exit 0
            else
                echo "⚠ No GitHub repository detected. Pass a URL:"
                echo "  /oss:analyse vitality https://github.com/owner/repo"
                exit 0
            fi
        fi
    fi
    GH_OWNER=$(echo "$VITALITY_REPO" | cut -d'/' -f1)  # timeout: 5000
    GH_REPO=$(echo "$VITALITY_REPO" | cut -d'/' -f2)  # timeout: 5000
    CLEAN_ARGS="vitality"  # normalise for mode dispatch
fi
# Persist $CLEAN_ARGS, $GH_OWNER, $GH_REPO — fresh shell loses vars (Check 41); vitality.md reloads these
echo "${CLEAN_ARGS:-}" > "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}"
echo "${GH_OWNER:-}" > "${TMPDIR:-/tmp}/analyse-gh-owner-${CSID}"
echo "${GH_REPO:-}" > "${TMPDIR:-/tmp}/analyse-gh-repo-${CSID}"
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If found: invoke `AskUserQuestion` with:
- question: "Unknown flag(s): `--<token>`. Supported: `--reply`, `--quick`, `--keep`. How to proceed?"
- (a) Abort — re-invoke with correct flags
- (b) Continue ignoring unknown flags

## Step 2: Reply-mode fast-path (only when `REPLY_MODE=true`)

Skip when `REPLY_MODE=false` and `DIRECT_PATH_MODE=false`.

**Direct report path** (`DIRECT_PATH_MODE=true` — checked first). The error branches below execute as explicit bash `exit 1` blocks — `stop` is not prose advice; the workflow must terminate hard before any downstream step can fire a misleading `Item .md not found on GitHub` error:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload vars — fresh shell (Check 41)
IFS= read -r REPLY_MODE < "${TMPDIR:-/tmp}/analyse-reply-mode-${CSID}" 2>/dev/null || REPLY_MODE="false"
IFS= read -r DIRECT_PATH_MODE < "${TMPDIR:-/tmp}/analyse-direct-path-mode-${CSID}" 2>/dev/null || DIRECT_PATH_MODE="false"
IFS= read -r REPORT_FILE < "${TMPDIR:-/tmp}/analyse-report-file-${CSID}" 2>/dev/null || REPORT_FILE=""
# Both aborts drop the sentinel: a leftover path to a report that will never be written would make
# enforce-analyse-header.js deny the follow-up question the user needs after the error (Step 6a note).
if [ "$DIRECT_PATH_MODE" = "true" ] && [ "$REPLY_MODE" = "false" ]; then
    echo "! Error: report path '$REPORT_FILE' passed without --reply."
    echo "  Re-run as: /oss:analyse $REPORT_FILE --reply"
    echo "  Or use:    /oss:analyse <N> | vitality | ecosystem"
    rm -f "${TMPDIR:-/tmp}/analyse-report-file-${CSID}"
    exit 1
fi
if [ "$DIRECT_PATH_MODE" = "true" ] && [ "$REPLY_MODE" = "true" ] && [ ! -f "$REPORT_FILE" ]; then
    echo "! Error: report not found at $REPORT_FILE"
    rm -f "${TMPDIR:-/tmp}/analyse-report-file-${CSID}"
    exit 1
fi
if [ "$DIRECT_PATH_MODE" = "true" ] && [ "$REPLY_MODE" = "true" ] && [ -f "$REPORT_FILE" ]; then
    echo "[direct] using $REPORT_FILE"
    # Skip to Step 7 — orchestrator branches on DIRECT_PATH_MODE=true && REPLY_MODE=true
fi
```

After the block above: `DIRECT_PATH_MODE=true && REPLY_MODE=true && file exists` → skip to Step 7 (don't run auto-detection fast-path below).

Remaining fast-path logic (TODAY, REPORT_FILE auto-construction, drift check) only runs when `DIRECT_PATH_MODE=false`.

When `REPLY_MODE=true`, check if fresh report already exists before any API calls:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload vars — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
IFS= read -r TODAY < "${TMPDIR:-/tmp}/analyse-today-${CSID}" 2>/dev/null || TODAY=$(date +%Y-%m-%d)
# Numeric mode only — vitality/ecosystem set REPORT_FILE in their mode files; DIRECT_PATH_MODE already set above.
SUBDIR="thread"  # default for numeric args; overridden in vitality/ecosystem mode files
_REPO_SLUG=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null | tr '/' '-' | tr -cd '[:alnum:]-')
[ -z "$_REPO_SLUG" ] && _REPO_SLUG="local"
REPORT_FILE=".reports/analyse/$SUBDIR/output-analyse-$SUBDIR-${_REPO_SLUG}-$CLEAN_ARGS-$TODAY.md"
DRIFT=false
FAST_PATH=false
FAST_PATH_TENTATIVE=false

if [ -f "$REPORT_FILE" ]; then
    REPORT_MTIME=$(stat -f %m "$REPORT_FILE" 2>/dev/null || stat -c %Y "$REPORT_FILE")  # timeout: 5000
    FAST_PATH_TENTATIVE=true  # drift check deferred to Step 4 — type must be known first
fi
# Persist — fresh shell loses vars (Check 41)
echo "$DRIFT" > "${TMPDIR:-/tmp}/analyse-drift-${CSID}"
echo "$FAST_PATH" > "${TMPDIR:-/tmp}/analyse-fast-path-${CSID}"
echo "$FAST_PATH_TENTATIVE" > "${TMPDIR:-/tmp}/analyse-fast-path-tentative-${CSID}"
echo "${REPORT_MTIME:-0}" > "${TMPDIR:-/tmp}/analyse-report-mtime-${CSID}"
```

- `FAST_PATH_TENTATIVE=true` → continue to Steps 3–4 for type detection and type-aware drift check. If no new activity confirmed: `FAST_PATH=true` → print `[resume] reusing existing report for #$CLEAN_ARGS` → jump to Step 7.
- `FAST_PATH_TENTATIVE=false` (report missing) → continue to Step 3.

## Step 3: Cache layer (numeric arguments only)

Check local cache before API calls — prevents redundant fetches, avoids GitHub rate limits when re-analysing same item same day.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload vars — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
IFS= read -r TODAY < "${TMPDIR:-/tmp}/analyse-today-${CSID}" 2>/dev/null || TODAY=$(date +%Y-%m-%d)
CACHE_DIR=".cache/gh"
# Repo slug in key prevents cross-repo cache poisoning (same issue# different repo)
_CACHE_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null | tr '/' '-')
if [ -z "$_CACHE_REPO" ]; then
    # No stable repo ID — disable caching; fallback key risks cross-repo collision
    CACHE_FILE=""
else
    CACHE_FILE="$CACHE_DIR/$_CACHE_REPO-$CLEAN_ARGS-$TODAY.json"
fi
# Persist $CACHE_FILE — fresh shell (Check 41)
echo "${CACHE_FILE:-}" > "${TMPDIR:-/tmp}/analyse-cache-file-${CSID}"
mkdir -p "$CACHE_DIR" # timeout: 5000
# Thread mode requires git+GitHub context for {owner}/{repo} substitution
if [ -z "$_CACHE_REPO" ] && [[ "$CLEAN_ARGS" =~ ^[0-9]+$ ]]; then
    echo "⚠ No GitHub repository context — cannot resolve repository for thread mode."
    echo "Run from inside a git repository with a GitHub remote:"
    echo "  cd /path/to/repo && /oss:analyse $CLEAN_ARGS"
    exit 0
fi
```

**Cache hit** — if `$CACHE_FILE` exists:

- Read `type`, `item`, `comments` fields from JSON; `TYPE` known
- Skip all primary `gh` item fetches in `modes/thread.md`
- Print `[cache] #$CLEAN_ARGS ($TODAY)` as one-line status note
- Still run wide-net searches (dynamic — never cached)
- `FAST_PATH_TENTATIVE=true`: run lightweight drift check now that `TYPE` known, then skip Step 4 type-detection API calls:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload drift state — fresh shell (Check 41)
IFS= read -r DRIFT < "${TMPDIR:-/tmp}/analyse-drift-${CSID}" 2>/dev/null || DRIFT="false"
IFS= read -r FAST_PATH < "${TMPDIR:-/tmp}/analyse-fast-path-${CSID}" 2>/dev/null || FAST_PATH="false"
IFS= read -r FAST_PATH_TENTATIVE < "${TMPDIR:-/tmp}/analyse-fast-path-tentative-${CSID}" 2>/dev/null || FAST_PATH_TENTATIVE="false"
IFS= read -r REPORT_MTIME < "${TMPDIR:-/tmp}/analyse-report-mtime-${CSID}" 2>/dev/null || REPORT_MTIME="0"
# Corrupt cache guard — validate TYPE before use
[ "$TYPE" = "pr" ] || [ "$TYPE" = "issue" ] || [ "$TYPE" = "discussion" ] || { echo "! Error: corrupt cache — invalid type \"$TYPE\" for #$CLEAN_ARGS; delete .cache/gh/ to reset"; exit 1; }
# Cache hit + FAST_PATH_TENTATIVE: lightweight updatedAt call; UPDATED_TS > REPORT_MTIME → DRIFT=true
if [ "$TYPE" = "discussion" ]; then
    UPDATED_AT=$(gh api graphql \
        -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){discussion(number:$number){updatedAt}}}' \
        -f owner='{owner}' -f repo='{repo}' -F number=$CLEAN_ARGS \
        --jq '.data.repository.discussion.updatedAt' 2>/dev/null)  # timeout: 6000
else
    UPDATED_AT=$(gh api "repos/{owner}/{repo}/issues/$CLEAN_ARGS" --jq '.updated_at' 2>/dev/null)  # timeout: 6000
fi
UPDATED_TS=$(date -d "$UPDATED_AT" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$UPDATED_AT" +%s 2>/dev/null)  # timeout: 5000
# Date parse failure → treat as drifted (conservative)
[ -z "$UPDATED_TS" ] && DRIFT=true
[ "$UPDATED_TS" -gt "$REPORT_MTIME" ] && DRIFT=true
[ "$DRIFT" = "false" ] && FAST_PATH=true && echo "[resume] reusing existing report for #$CLEAN_ARGS"
```

`FAST_PATH=true` → skip to Step 7. `DRIFT=true` → continue (full re-analysis from cached data).

**Cache miss** — after fetching in `modes/thread.md`, write:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload vars — fresh shell (Check 41)
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
IFS= read -r CACHE_FILE < "${TMPDIR:-/tmp}/analyse-cache-file-${CSID}" 2>/dev/null || CACHE_FILE=""
[ -n "$ITEM" ] && [ -n "$CACHE_FILE" ] && jq -n \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg type "$TYPE" \
    --argjson number "$CLEAN_ARGS" \
    --argjson item "$ITEM" \
    --arg comments "$COMMENTS" \
    '{"ts":$ts,"type":$type,"number":$number,"item":$item,"comments":$comments}' \
    >"$CACHE_FILE" || echo "⚠ cache write skipped — empty or malformed API response" # timeout: 5000
```

**Stale cache** — file for same number but earlier date ignored. Old files left — small, provide audit history.

> **mtime reliability caveat**: `stat` mtime unreliable after `rsync`/copy, in CI with frozen clocks, or on HFS+ (1-second granularity). If drift check produces unexpected fast-path hits, verify report mtime with `stat "$REPORT_FILE"`. Workaround: delete cached report to force full re-analysis.

Cache applies to: issue/PR/discussion primary fetch and comments. Cache does NOT apply to: `gh issue list`, `gh pr list`, `gh pr checks`, `gh pr diff`, discussion list queries, vitality/ecosystem modes.

## Step 4: Auto-Detection (numeric arguments only)

Issues, PRs, discussions share unified running index — given number is exactly one type. Cache hit: read `TYPE` and `ITEM` from `$CACHE_FILE` — skip `gh` calls below.

Cache miss:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload drift state — fresh shell (Check 41)
IFS= read -r DRIFT < "${TMPDIR:-/tmp}/analyse-drift-${CSID}" 2>/dev/null || DRIFT="false"
IFS= read -r FAST_PATH_TENTATIVE < "${TMPDIR:-/tmp}/analyse-fast-path-tentative-${CSID}" 2>/dev/null || FAST_PATH_TENTATIVE="false"
IFS= read -r REPORT_MTIME < "${TMPDIR:-/tmp}/analyse-report-mtime-${CSID}" 2>/dev/null || REPORT_MTIME="0"
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
# One call covers all types; writes TYPE/UPDATED_AT/DRIFT to ${TMPDIR:-/tmp}/oss-detect-<var>-${CSID}
if [ "$FAST_PATH_TENTATIVE" = "true" ]; then
    python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/detect_thread_type.py" --number "$CLEAN_ARGS" --report-mtime "$REPORT_MTIME" 2>/dev/null  # timeout: 15000
else
    python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/detect_thread_type.py" --number "$CLEAN_ARGS" 2>/dev/null  # timeout: 15000
fi
IFS= read -r TYPE < "${TMPDIR:-/tmp}/oss-detect-type-${CSID}" 2>/dev/null || TYPE="unknown"
IFS= read -r DRIFT < "${TMPDIR:-/tmp}/oss-detect-drift-${CSID}" 2>/dev/null || DRIFT="false"
if [ "$FAST_PATH_TENTATIVE" = "true" ] && [ "$TYPE" != "unknown" ] && [ "$DRIFT" = "false" ]; then
    FAST_PATH=true
    echo "[resume] reusing existing report for #$CLEAN_ARGS"
fi
# TYPE=unknown: stop — don't fall through to Step 5
if [ "$TYPE" = "unknown" ]; then
    echo "Item #$CLEAN_ARGS not found on GitHub. Re-run with a different number, or use \`/oss:analyse vitality\` for repo overview."
    exit 1
fi
```

## Step 5: Mode dispatch

Read and execute the mode file from `${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/skills/analyse/modes/`.

| Argument | Mode file |
| --- | --- |
| number (any type) | `modes/thread.md` |
| `vitality` | `modes/vitality.md` |
| `ecosystem` | `modes/ecosystem.md` |

> loads: vitality-report.md (used by modes/vitality.md as REPORT_TPL)

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Compaction contract — boundary: after gather/fetch (Step 5), before synthesis gate (compaction-contract.md §Lifecycle)
IFS= read -r _CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || _CLEAN_ARGS=""
IFS= read -r _REPORT_FILE < "${TMPDIR:-/tmp}/analyse-report-file-${CSID}" 2>/dev/null || _REPORT_FILE="pending"
IFS= read -r _REPLY_MODE < "${TMPDIR:-/tmp}/analyse-reply-mode-${CSID}" 2>/dev/null || _REPLY_MODE="false"
IFS= read -r _KEEP < "${TMPDIR:-/tmp}/analyse-keep-items-${CSID}" 2>/dev/null || _KEEP=""
_PRESERVE="target=#${_CLEAN_ARGS}, cache-dir=.cache/gh, report=${_REPORT_FILE}, reply-mode=${_REPLY_MODE}"
[ -n "$_KEEP" ] && _PRESERVE="$_PRESERVE; user-keep: $_KEEP"
mkdir -p .temp/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: oss:analyse · phase: synthesis (after gather/fetch)"
    echo "- run-dir: .cache/gh"
    echo "- preserve: ${_PRESERVE}"
    echo "- next: reply gate (Step 6) or shepherd reply (Step 7)"
} > .temp/state/skill-contract.md  # timeout: 5000
```

## Step 6: Reply gate — STOP CHECK

**Run before Confidence block regardless of `--reply` mode.**

`REPLY_MODE=true`: response incomplete until Step 7 done and reply file written. Proceed to Step 7 — `## Confidence` block goes at end of Step 7 instead.

`REPLY_MODE=false` — do NOT proceed to Step 7. Execute both sub-steps below, then end response.

### 6a — Follow-up gate

**Hook-enforced**: `hooks/enforce-analyse-header.js` (PreToolUse on `AskUserQuestion`) denies this call while the report path each mode file writes to `${TMPDIR:-/tmp}/analyse-report-file-${CSID}` names a missing or empty file. A denial reading `oss:analyse report gate` means the mode never wrote its report — write it, print its `---` header, then re-issue the question.

Invoke `AskUserQuestion`. Options depend on mode:

**Thread mode** (`$CLEAN_ARGS` is a number):
- question: "What next?"
- (a) label: `/develop:fix` — description: diagnose and fix the reported issue (requires `develop` plugin)
- (b) label: `/develop:feature` — description: implement as new feature (requires `develop` plugin)
- (c) label: `draft reply` — description: run `/oss:analyse $CLEAN_ARGS --reply` to shepherd a contributor-facing reply
- (d) label: `skip` — description: no action

**Vitality / ecosystem mode** (`$CLEAN_ARGS` is `vitality` or `ecosystem`):
- question: "What next?"
- (a) label: `/oss:analyse <N> --reply` — description: draft reply for specific thread
- (b) label: `/oss:review <N>` — description: full code review for specific PR (requires `oss` plugin)
- (c) label: `skip` — description: no action

### 6b — Confidence block (REPLY_MODE=false only)

End response with `## Confidence` block per CLAUDE.md output standards.

```bash
rm -f .temp/state/skill-contract.md  # clear contract — skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

## Step 7: Draft contributor reply (only when --reply, thread mode only)

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload vars — fresh shell (Check 41)
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/analyse-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""
IFS= read -r CLEAN_ARGS < "${TMPDIR:-/tmp}/analyse-clean-args-${CSID}" 2>/dev/null || CLEAN_ARGS=""
IFS= read -r TODAY < "${TMPDIR:-/tmp}/analyse-today-${CSID}" 2>/dev/null || TODAY=$(date +%Y-%m-%d)
```

Report at `$REPORT_FILE` guaranteed to exist — either reused via fast-path (Step 2, `FAST_PATH=true`) or freshly written by Step 5.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload _OSS_SHARED — fresh shell (Check 41)
IFS= read -r _OSS_SHARED < "${TMPDIR:-/tmp}/analyse-oss-shared-${CSID}" 2>/dev/null || _OSS_SHARED=""
cat "$_OSS_SHARED/shepherd-reply-protocol.md"  # timeout: 5000
```

`shepherd-reply-protocol.md` (loaded above) — apply invocation pattern and terminal summary format.

```text
Agent(
  subagent_type="oss:shepherd",
  description="Draft contributor reply for thread #<CLEAN_ARGS>",
  prompt="Read <_OSS_SHARED>/shepherd-reply-protocol.md and follow its invocation pattern. Report: <REPORT_FILE>. Thread #<CLEAN_ARGS>. Fetch thread context via `gh issue view <CLEAN_ARGS> --comments` (or GraphQL for discussions) if not already in report. Write full reply draft to .reports/analyse/thread/output-reply-thread-<CLEAN_ARGS>-<TODAY>.md using the Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<OUTPUT_PATH>\",\"confidence\":0.N}"
)
```

**Replace `<_OSS_SHARED>`, `<REPORT_FILE>`, `<CLEAN_ARGS>`, `<TODAY>` with actual runtime values before spawning — agents receive text, not shell variables.**

Verify output file exists and is non-empty after spawn: `[ -s "<OUTPUT_PATH>" ] || { echo "⚠ shepherd output empty or missing"; }`

If `DRIFT=true`: append `[analysis refreshed — new activity since last report]` to terminal summary.

**Health monitoring** (CLAUDE.md §6): Agent spawns synchronous — Claude awaits natively. On timeout (`$HARD_CUTOFF` seconds): read `tail -100` of expected reply path; if none, use `{"verdict":"timed_out"}`; surface with ⏱. Never silently omit.

End response with `## Confidence` block per CLAUDE.md — always **absolute last thing**.

```bash
rm -f .temp/state/skill-contract.md  # clear contract — skill complete (compaction-contract.md §Lifecycle)  # timeout: 5000
```

</workflow>

<calibration>

Calibratable modes: thread (duplicate detection recall), vitality (repo vitality metrics accuracy), ecosystem (impact analysis accuracy).

Scenarios:
1. Thread — duplicate detection: synthetic issue with identical symptoms to existing closed issue → root cause match ≥0.9; duplicate link surfaced
2. Thread — actionable response quality: feature request with no linked PRs → concrete scope + next step; no vague suggestions
3. Vitality — metric accuracy: repo with known issue/PR/response-time counts → numeric values within ±10% of ground truth; archetype scenario matrix with expected score ranges per repo type: `vitality-calibration.md`

</calibration>

<notes>

- **Thread analysis output schema** (canonical section order): `## Item Type`, `## Summary`, `## Related Items`, `## Reproduction Steps` (issues only), `## Risks / Blockers`, `## Next Steps`, `## Confidence`. Use these exact headings — consistent section names enable downstream parsing, diff-based change detection across runs. `## Confidence` mandatory, always last — omitting it triggers calibration failure (confidence defaults to 0.5, producing large negative bias).
- **Precision guidance**: flag issues, don't solve them; flag blockers, don't design solutions. Reference `/develop:fix` and `/develop:feature` (requires `develop` plugin) for implementation work. Verbose implementation sketches in triage output dilute signal-to-noise ratio. Each flagged item (duplicate, blocker, next step) must carry explicit severity/priority label (high/medium/low) inline — enables downstream triage, satisfies format scoring.
- **Vitality mode repo resolution**: `GH_OWNER` and `GH_REPO` set in Step 1 from: (1) explicit URL/owner-repo arg, (2) `gh repo view`, (3) `git remote origin`. vitality.md uses `-R "$GH_OWNER/$GH_REPO"` on all gh commands and literal `$GH_OWNER/$GH_REPO` in all `gh api` paths — never `{owner}/{repo}` template substitution in vitality mode.
- Mode files live in `${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/skills/analyse/modes/` — one file per mode, fully self-contained
- `modes/thread.md` handles all three thread types (issue, PR, discussion) via internal branching
- Always use `gh` CLI — never hardcode repo URLs
- Run `gh auth status` first if commands fail; user may need to authenticate
- For closed items, note resolution so history useful
- Don't post responses without explicit user instruction — draft only
- **Out-of-scope early-exit**: when input clearly outside skill's domain (e.g. CI pipeline diagnosis, code review), print scope note + redirect (e.g. "use oss:cicd-steward (requires `oss` plugin)") and stop — don't provide full analysis of out-of-scope content. Flag then stop; flag then analyze = precision cost with no recall benefit.
- **Forked context**: skill runs with `context: fork` — no access to current conversation history. All required context must be in skill argument or prompt. `Agent` IS available in forked context (non-deferred, declared in `allowed-tools`) — do NOT skip Steps 5–6 adversarial review assuming Agent unavailable; available, those steps mandatory.
- **`--reply` drafts only** — shepherd produces draft file; does NOT auto-post to GitHub. User posts manually. Write access to repo not required for `--reply`; required only if user subsequently posts draft via `gh issue comment` or `gh pr comment`.
- **Follow-up context gap**: skill runs with `context: fork` — follow-up chains (`/develop:fix` (requires `develop` plugin), `/oss:review`) receive no analysis context from this run. Pass report path explicitly or re-summarize key findings in follow-up invocation.
- Follow-up chains:
  - Issue with confirmed bug → `/develop:fix` to diagnose, reproduce with test, apply targeted fix (requires `develop` plugin)
  - Issue is feature request → `/develop:feature` for TDD-first implementation (requires `develop` plugin)
  - PR with quality concerns → `/oss:review` for comprehensive multi-agent code review (requires `oss` plugin)
  - Draft responses → use `--reply` to auto-draft via shepherd; or invoke shepherd manually

</notes>
