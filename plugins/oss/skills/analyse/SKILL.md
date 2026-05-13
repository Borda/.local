---
name: analyse
description: Analyze GitHub issues, Pull Requests (PRs), Discussions, and repo vitality for an Open Source Software (OSS) project. For any specific item, casts a wide net — finds and lists all related open and closed issues/PRs/discussions, explicitly flags duplicates. Summarizes long threads, extracts reproduction steps, and generates repo vitality stats. Uses gh Command Line Interface (CLI) for GitHub Application Programming Interface (API) access. Complements oss:shepherd. NOT for PR readiness assessment or code review (use oss:review).
argument-hint: '<N|vitality [<owner>/<repo>|github-url]|ecosystem|path/to/report.md> [--reply]'
allowed-tools: Read, Bash, Write, Agent
context: fork
model: opus
effort: high
when_to_use: 'Use when the user asks to analyze a GitHub issue, PR, or discussion thread, needs repo vitality stats, or wants to triage/summarize OSS contributor threads.'
---

<objective>

Analyze GitHub threads + repo vitality. Help maintainers triage, respond, decide fast. Output actionable + structured — not just summaries.

NOT for implementing PR action items (use oss:resolve). NOT for multi-agent code review (use oss:review). NOT for CI pipeline diagnosis (use oss:cicd-steward).

</objective>

<inputs>

- **$ARGUMENTS**: one of:
  - `N` (number, plain `123` or `#123`) — any GitHub thread: issue, PR, or discussion; auto-detects type
  - `vitality [<owner>/<repo> | <github-url>]` — repo vitality overview with 9-axis health scorecard and duplicate detection. Optional repo argument accepts `owner/repo` shorthand or full `https://github.com/owner/repo` URL. When omitted, auto-detected from git upstream. Non-GitHub remotes (GitLab, Bitbucket, etc.) stop with warning.
  - `ecosystem` — downstream consumer impact analysis for library maintainers
  - `--reply` — only valid with `N`; spawns shepherd to draft contributor-facing reply after thread analysis. Silently ignored for `vitality` and `ecosystem`.
  - `path/to/report.md` — path to existing report file; only valid combined with `--reply`; skips all analysis, spawns shepherd directly using provided file

</inputs>

<constants>

<!-- Background agent health monitoring (CLAUDE.md §8) — applies to Step 7 shepherd spawn -->
MONITOR_INTERVAL=300   # 5 minutes between polls
HARD_CUTOFF=900        # 15 minutes of no file activity → declare timed out
EXTENSION=300          # one +5 min extension if output file explains delay

</constants>

<workflow>

<!-- Agent Resolution: canonical table at plugins/oss/skills/_shared/agent-resolution.md -->

## Agent Resolution

# Read $_OSS_SHARED/oss-shared-resolver.md and execute its contents
# Cold-start fallback (if shared resolver unreadable):
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"

```bash
FOUNDRY_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$FOUNDRY_SHARED" ] && FOUNDRY_SHARED="$(git rev-parse --show-toplevel 2>/dev/null || echo .)/.claude/skills/_shared"
```

## Step 1: Flag parsing

```bash
REPLY_MODE=false
CLEAN_ARGS=$ARGUMENTS
if [[ "$ARGUMENTS" == *"--reply"* ]]; then
    REPLY_MODE=true
    CLEAN_ARGS=$(echo "$ARGUMENTS" | sed 's/ --reply\b//')
    CLEAN_ARGS="${CLEAN_ARGS#"${CLEAN_ARGS%%[![:space:]]*}"}"
fi # timeout: 5000
```

```bash
# Strip leading '#' so both '123' and '#123' work
CLEAN_ARGS="${CLEAN_ARGS#\#}"
```

`REPLY_MODE` only meaningful when `$CLEAN_ARGS` is number — silently ignored for `vitality` and `ecosystem`.

```bash
DIRECT_PATH_MODE=false
if [[ "$CLEAN_ARGS" == *.md ]]; then
    DIRECT_PATH_MODE=true
    REPORT_FILE="$CLEAN_ARGS"
fi # timeout: 5000
TODAY=$(date +%Y-%m-%d)
```

`DIRECT_PATH_MODE=true` only valid when `REPLY_MODE=true` — if combined without `--reply`, Step 2 prints plain-text error and stops; execution never reaches Step 5 mode dispatch.

```bash
# --- Vitality mode: resolve target repo ---
GH_OWNER=""
GH_REPO=""
if [[ "$CLEAN_ARGS" == vitality* ]]; then
    VITALITY_EXTRA="${CLEAN_ARGS#vitality}"
    VITALITY_EXTRA="${VITALITY_EXTRA# }"  # trim leading space

    if [ -n "$VITALITY_EXTRA" ]; then
        # Argument provided — URL or owner/repo
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
        # No argument — detect from gh context or git remote
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
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If found: print following as plain text (AskUserQuestion not available in forked context) and stop:
```
! Unknown flag(s): `--<token>`. Supported: `--reply`.
Options: (a) re-invoke with correct flags  (b) continue ignoring unknown flags
```
Do not invoke `AskUserQuestion` — forked context; deferred tool schema not loaded.

## Step 2: Reply-mode fast-path (only when `REPLY_MODE=true`)

Skip when `REPLY_MODE=false` and `DIRECT_PATH_MODE=false`.

**Direct report path** (`DIRECT_PATH_MODE=true` — checked first):

- `REPLY_MODE=false` → print: "A report path was passed without `--reply`. Did you mean `/analyse <path.md> --reply`? Re-run with `--reply` to continue, or use `/analyse <N> | vitality | ecosystem`." and stop.
- `REPLY_MODE=true` and file missing (`[ ! -f "$REPORT_FILE" ]`) → print `Error: report not found: $REPORT_FILE` and stop.
- `REPLY_MODE=true` and file exists → print `[direct] using $REPORT_FILE` → skip to Step 7. Don't run auto-detection fast-path below.

Remaining fast-path logic (TODAY, REPORT_FILE auto-construction, drift check) only runs when `DIRECT_PATH_MODE=false`.

When `REPLY_MODE=true`, check if fresh report already exists before any API calls:

```bash
# REPORT_FILE assigned here only for numeric (thread) mode.
# vitality/ecosystem modes: REPORT_FILE set inside modes/vitality.md and modes/ecosystem.md respectively.
# DIRECT_PATH_MODE: REPORT_FILE already set from $CLEAN_ARGS above.
SUBDIR="thread"  # default for numeric args; overridden for health/ecosystem in their mode files
REPORT_FILE=".reports/analyse/$SUBDIR/output-analyse-$SUBDIR-$CLEAN_ARGS-$TODAY.md"
DRIFT=false
FAST_PATH=false
FAST_PATH_TENTATIVE=false

if [ -f "$REPORT_FILE" ]; then
    REPORT_MTIME=$(stat -f %m "$REPORT_FILE" 2>/dev/null || stat -c %Y "$REPORT_FILE")  # timeout: 5000
    FAST_PATH_TENTATIVE=true  # drift check deferred to Step 4 — type must be known first
fi
```

- `FAST_PATH_TENTATIVE=true` → continue to Steps 3–4 for type detection and type-aware drift check. If no new activity confirmed: `FAST_PATH=true` → print `[resume] reusing existing report for #$CLEAN_ARGS` → jump to Step 7.
- `FAST_PATH_TENTATIVE=false` (report missing) → continue to Step 3.

## Step 3: Cache layer (numeric arguments only)

Check local cache before API calls — prevents redundant fetches, avoids GitHub rate limits when re-analysing same item same day.

```bash
CACHE_DIR=".cache/gh"
# Include repo slug in cache key to prevent cross-repo cache poisoning (same issue# different repo)
_CACHE_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null | tr '/' '-' || echo 'unknown-repo')
CACHE_FILE="$CACHE_DIR/$_CACHE_REPO-$CLEAN_ARGS-$TODAY.json"
mkdir -p "$CACHE_DIR" # timeout: 5000
```

**Cache hit** — if `$CACHE_FILE` exists:

- Read `type`, `item`, `comments` fields from JSON; `TYPE` known
- Skip all primary `gh` item fetches in `modes/thread.md`
- Print `[cache] #$CLEAN_ARGS ($TODAY)` as one-line status note
- Still run wide-net searches (dynamic — never cached)
- `FAST_PATH_TENTATIVE=true`: run lightweight drift check now that `TYPE` known, then skip Step 4 type-detection API calls:

```bash
# Cache hit + FAST_PATH_TENTATIVE: one lightweight API call to get updatedAt, then apply drift check
# Drift check pattern (shared with Step 4): UPDATED_TS > REPORT_MTIME → DRIFT=true → full re-analysis
if [ "$TYPE" = "discussion" ]; then
    UPDATED_AT=$(gh api graphql \
        -f query='query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){discussion(number:$number){updatedAt}}}' \
        -f owner='{owner}' -f repo='{repo}' -F number=$CLEAN_ARGS \
        --jq '.data.repository.discussion.updatedAt' 2>/dev/null)  # timeout: 6000
else
    UPDATED_AT=$(gh api "repos/{owner}/{repo}/issues/$CLEAN_ARGS" --jq '.updated_at' 2>/dev/null)  # timeout: 6000
fi
UPDATED_TS=$(date -d "$UPDATED_AT" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$UPDATED_AT" +%s 2>/dev/null)  # timeout: 5000
# Guard: if date parse failed (empty UPDATED_TS), treat as drifted — conservative correct default
[ -z "$UPDATED_TS" ] && DRIFT=true
[ "$UPDATED_TS" -gt "$REPORT_MTIME" ] && DRIFT=true
[ "$DRIFT" = "false" ] && FAST_PATH=true && echo "[resume] reusing existing report for #$CLEAN_ARGS"
```

`FAST_PATH=true` → skip to Step 7. `DRIFT=true` → continue (full re-analysis from cached data).

**Cache miss** — after fetching in `modes/thread.md`, write:

```bash
[ -n "$ITEM" ] && jq -n \
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
# 4a: try the issues API (covers both issues and PRs)
ITEM=$(gh api "repos/{owner}/{repo}/issues/$CLEAN_ARGS" 2>/dev/null) # timeout: 6000

if [ -n "$ITEM" ]; then
    TYPE=$(echo "$ITEM" | jq -r 'if .pull_request then "pr" else "issue" end')  # timeout: 5000
    # Apply drift check (pattern per Step 3 comment): updated_at already in $ITEM; no extra API call
    if [ "$FAST_PATH_TENTATIVE" = "true" ]; then
        UPDATED_AT=$(echo "$ITEM" | jq -r '.updated_at' 2>/dev/null)
        UPDATED_TS=$(date -d "$UPDATED_AT" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$UPDATED_AT" +%s 2>/dev/null)  # timeout: 5000
        [ -z "$UPDATED_TS" ] && DRIFT=true  # parse failed — treat as drifted
        [ "$UPDATED_TS" -gt "$REPORT_MTIME" ] && DRIFT=true
        [ "$DRIFT" = "false" ] && FAST_PATH=true && echo "[resume] reusing existing report for #$CLEAN_ARGS"
    fi
else
    # 4b: try discussions via GraphQL — fetch updatedAt in same query; no extra call for drift check
    DISC_JSON=$(gh api graphql -f query='
    query($owner:String!,$repo:String!,$number:Int!){
      repository(owner:$owner,name:$repo){
        discussion(number:$number){ title updatedAt }
      }
    }' -f owner='{owner}' -f repo='{repo}' -F number=$CLEAN_ARGS 2>/dev/null)  # timeout: 6000
    DISC_TITLE=$(echo "$DISC_JSON" | jq -r '.data.repository.discussion.title // empty' 2>/dev/null)
    if [ -n "$DISC_TITLE" ]; then
        TYPE="discussion"
        # Apply drift check (pattern per Step 3 comment): updatedAt from same GraphQL response
        if [ "$FAST_PATH_TENTATIVE" = "true" ]; then
            UPDATED_AT=$(echo "$DISC_JSON" | jq -r '.data.repository.discussion.updatedAt' 2>/dev/null)
            UPDATED_TS=$(date -d "$UPDATED_AT" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$UPDATED_AT" +%s 2>/dev/null)  # timeout: 5000
            [ -z "$UPDATED_TS" ] && DRIFT=true  # parse failed — treat as drifted
            [ "$UPDATED_TS" -gt "$REPORT_MTIME" ] && DRIFT=true
            [ "$DRIFT" = "false" ] && FAST_PATH=true && echo "[resume] reusing existing report for #$CLEAN_ARGS"
        fi
    else
        TYPE="unknown"
    fi
fi
# unknown → print: "Item #$CLEAN_ARGS not found on GitHub. Re-run with a different number, or use `/analyse vitality` for repo overview." and stop

# FAST_PATH=true (set above): jump to Step 7. FAST_PATH=false: continue to Step 5.
```

## Step 5: Mode dispatch

```bash
_OSS_MODE_DIR=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/analyse/modes 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_MODE_DIR" ] && _OSS_MODE_DIR="plugins/oss/skills/analyse/modes"
```

Read `$_OSS_MODE_DIR/<mode>.md` and execute all steps defined there.

| Argument | Mode file |
| --- | --- |
| number (any type) | `$_OSS_MODE_DIR/thread.md` |
| `vitality` | `$_OSS_MODE_DIR/vitality.md` |
| `ecosystem` | `$_OSS_MODE_DIR/ecosystem.md` |

## Step 6: Reply gate — STOP CHECK

**Run before Confidence block regardless of `--reply` mode.**

`REPLY_MODE=true`: response incomplete until Step 7 done and reply file written. Proceed to Step 7 — `## Confidence` block goes at end of Step 7 instead.

`REPLY_MODE=false` — do NOT proceed to Step 7. Execute both sub-steps below, then end response.

### 6a — Follow-up gate

<!-- AskUserQuestion NOT available in forked context — deferred tool schemas not loaded in fork; surface as plain text -->
Print options as plain text. Options depend on mode:

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

## Step 7: Draft contributor reply (only when --reply, thread mode only)

```bash
# Shepherd availability guard — oss plugin may not be installed
# Check installed cache path specifically (bare _OSS_SHARED fallback is always non-empty — cannot use it as availability signal)
SHEPHERD_AVAILABLE=0
ls ~/.claude/plugins/cache/borda-ai-rig/oss/*/agents/shepherd.md 2>/dev/null | grep -q . && SHEPHERD_AVAILABLE=1
[ -f ".claude/agents/shepherd.md" ] && SHEPHERD_AVAILABLE=1
if [ "$SHEPHERD_AVAILABLE" = "0" ]; then
    echo "⚠ oss:shepherd not available — --reply requires the oss plugin. Install: claude plugin install oss@borda-ai-rig"
    exit 1
fi # timeout: 5000
```

Report at `$REPORT_FILE` guaranteed to exist — either reused via fast-path (Step 2, `FAST_PATH=true`) or freshly written by Step 5.

```bash
[ -f "$_OSS_SHARED/shepherd-reply-protocol.md" ] || { echo "⚠ shepherd-reply-protocol.md not found at $_OSS_SHARED — verify oss plugin installation"; exit 1; }  # timeout: 5000
```

Read `$_OSS_SHARED/shepherd-reply-protocol.md` — apply invocation pattern and terminal summary format.

Spawn with:
- Report path: `$REPORT_FILE`
- Item number: `$CLEAN_ARGS`
- Thread context: also fetch `gh issue view $CLEAN_ARGS --comments` (or equivalent GraphQL for discussions) if not already in report
- Output path: `.reports/analyse/thread/output-reply-thread-$CLEAN_ARGS-$(date +%Y-%m-%d).md`
- Note: shepherd runs in forked context — all required context must be self-contained in prompt

Spawn prompt must include: `"Write your full output to <OUTPUT_PATH> using the Write tool. Return ONLY: {\"status\":\"done\",\"file\":\"<OUTPUT_PATH>\",\"confidence\":0.N}"`

Verify output file exists and is non-empty after spawn: `[ -s "<OUTPUT_PATH>" ] || { echo "⚠ shepherd output empty or missing"; }`

If `DRIFT=true`: append `[analysis refreshed — new activity since last report]` to terminal summary.

**Health monitoring** (CLAUDE.md §8): Agent spawns synchronous — Claude awaits natively. On timeout (`$HARD_CUTOFF` seconds): read `tail -100` of expected reply path; if none, use `{"verdict":"timed_out"}`; surface with ⏱. Never silently omit.

End response with `## Confidence` block per CLAUDE.md — always **absolute last thing**.

</workflow>

<calibration>

Calibratable modes: thread (duplicate detection recall), vitality (repo vitality metrics accuracy), ecosystem (impact analysis accuracy).

Scenarios:
1. Thread — duplicate detection: synthetic issue with identical symptoms to existing closed issue → root cause match ≥0.9; duplicate link surfaced
2. Thread — actionable response quality: feature request with no linked PRs → concrete scope + next step; no vague suggestions
3. Vitality — metric accuracy: repo with known issue/PR/response-time counts → numeric values within ±10% of ground truth

</calibration>

<notes>

- **Thread analysis output schema** (canonical section order): `## Item Type`, `## Summary`, `## Related Items`, `## Reproduction Steps` (issues only), `## Risks / Blockers`, `## Next Steps`. Use these exact headings — consistent section names enable downstream parsing and diff-based change detection across runs.
- **Precision guidance**: flag issues, do not solve them; flag blockers, do not design solutions. Reference `/develop:fix` and `/develop:feature` (requires `develop` plugin) for implementation work. Verbose implementation sketches in triage output dilute signal-to-noise ratio.
- **Vitality mode repo resolution**: `GH_OWNER` and `GH_REPO` set in Step 1 from: (1) explicit URL/owner-repo arg, (2) `gh repo view`, (3) `git remote origin`. vitality.md uses `-R "$GH_OWNER/$GH_REPO"` on all gh commands and literal `$GH_OWNER/$GH_REPO` in all `gh api` paths — never `{owner}/{repo}` template substitution in vitality mode.
- Mode files live in `plugins/oss/skills/analyse/modes/` — one file per mode, fully self-contained
- `modes/thread.md` handles all three thread types (issue, PR, discussion) via internal branching
- Always use `gh` CLI — never hardcode repo URLs
- Run `gh auth status` first if commands fail; user may need to authenticate
- For closed items, note resolution so history useful
- Don't post responses without explicit user instruction — draft only
- **Out-of-scope early-exit**: when input is clearly outside this skill's domain (e.g. CI pipeline diagnosis, code review), print scope note + redirect (e.g. "use oss:cicd-steward") and stop — do not provide full analysis of out-of-scope content. Flag then stop; flag then analyze = precision cost with no recall benefit.
- **Forked context**: skill runs with `context: fork` — no access to current conversation history. All required context must be in skill argument or prompt. `AskUserQuestion` NOT available (deferred tool schema not loaded in fork) — interactive gates surface as plain text instead. `Agent` IS available in forked context (non-deferred, declared in `allowed-tools`) — do NOT skip Steps 5–6 adversarial review assuming Agent unavailable; it is available and those steps are mandatory.
- **`--reply` drafts only** — shepherd produces draft file; does NOT auto-post to GitHub. User posts manually. Write access to repo not required to use `--reply`; required only if user subsequently posts draft via `gh issue comment` or `gh pr comment`.
- **Follow-up context gap**: skill runs with `context: fork` — follow-up chains (`/develop:fix` (requires `develop` plugin), `/oss:review`) receive no analysis context from this run. Pass report path explicitly or re-summarize key findings in follow-up invocation.
- Follow-up chains:
  - Issue with confirmed bug → `/develop:fix` to diagnose, reproduce with test, apply targeted fix (requires `develop` plugin)
  - Issue is feature request → `/develop:feature` for TDD-first implementation (requires `develop` plugin)
  - PR with quality concerns → `/oss:review` for comprehensive multi-agent code review (requires `oss` plugin)
  - Draft responses → use `--reply` to auto-draft via shepherd; or invoke shepherd manually

</notes>
