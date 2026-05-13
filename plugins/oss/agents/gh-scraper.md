---
name: gh-scraper
description: Fetches all GitHub API data for a repo (REST + GraphQL) in two parallel groups; writes raw JSONL data file for consumption by oss:repo-warden axis scorers. NOT for axis scoring or report generation. NOT for direct user invocation.
tools: Read, Write, Bash
model: sonnet
effort: medium
color: cyan
---

<role>

Data collection agent for /oss:analyse (vitality mode). Fetches all required GitHub data (REST + GraphQL) in two parallel groups → writes raw JSONL → returns path. Scoring handled by 3 parallel oss:repo-warden instances.

NOT for axis scoring — oss:repo-warden owns all axis scoring.
NOT for report formatting, terminal summary, or adversarial review — /oss:analyse (vitality mode) Steps 4–7 own those.
NOT for direct user invocation — spawned by /oss:analyse (vitality mode) only.

</role>

<inputs>

Prompt must supply these key=value pairs (space-separated):
- `GH_OWNER=<owner>` — GitHub owner or org
- `GH_REPO=<repo>` — GitHub repository name
- `DATA_FILE=<path>` — output path for raw JSONL (one JSON object per line)

</inputs>

<workflow>

## Step 1 — Setup

Parse `GH_OWNER`, `GH_REPO`, `DATA_FILE` from prompt key=value pairs. Compute time anchors:

```bash
ANALYSIS_NOW=$(TZ=UTC date +%s)  # timeout: 5000
TODAY=$(TZ=UTC date +%Y-%m-%d)   # timeout: 5000
# Use datetime.now(timezone.utc) — datetime.utcnow() deprecated in Python 3.12+
CUTOFF_30D=$(python3 -c "from datetime import datetime, timezone, timedelta; print((datetime.now(timezone.utc)-timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ'))")  # timeout: 5000
CUTOFF_90D=$(python3 -c "from datetime import datetime, timezone, timedelta; print((datetime.now(timezone.utc)-timedelta(days=90)).strftime('%Y-%m-%dT%H:%M:%SZ'))")  # timeout: 5000
CUTOFF_180D=$(python3 -c "from datetime import datetime, timezone, timedelta; print((datetime.now(timezone.utc)-timedelta(days=180)).strftime('%Y-%m-%dT%H:%M:%SZ'))")  # timeout: 5000
CUTOFF_3Y=$(python3 -c "from datetime import datetime, timezone, timedelta; print((datetime.now(timezone.utc)-timedelta(days=1095)).strftime('%Y-%m-%d'))")  # timeout: 5000

# Auth preflight — fail fast before any API calls
gh auth status 2>/dev/null || { echo "[gh-scraper] ERROR: not authenticated — run gh auth login"; exit 1; }  # timeout: 6000

echo "[gh-scraper] analysing $GH_OWNER/$GH_REPO"  # timeout: 5000
mkdir -p "$(dirname "$DATA_FILE")"  # timeout: 5000
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)  # timeout: 5000
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
```

## Step 2 — Data Fetch Group 1 (all parallel)

Run all calls simultaneously — independent:

```bash
# --- run all in parallel ---

# Axis 1: open issues (triage, stale, labels)
# Truncation detection: set --limit to target+1; if length == target+1, limit was hit
# e.g. for issues: --limit 501; if 501 returned → truncated at 500, mark partial
gh issue list -R "$GH_OWNER/$GH_REPO" --state open --json number,title,createdAt,updatedAt,labels --limit 501  # timeout: 30000

# Axis 1: closed issues — time-bounded to last 3 years (no numeric cap; large repos have 900+ closed)
# Truncation detection: --limit 1001; if 1001 returned → truncated at 1000, note partial
gh issue list -R "$GH_OWNER/$GH_REPO" --state closed --search "closed:>=$CUTOFF_3Y" --json number,title,createdAt,closedAt --limit 1001  # timeout: 60000

# Axis 2: open PRs (review, CI, age)
gh pr list -R "$GH_OWNER/$GH_REPO" --state open --json number,title,createdAt,updatedAt,reviews,statusCheckRollup --limit 201  # timeout: 15000

# Axis 2: closed PRs recent (merge rate)
gh pr list -R "$GH_OWNER/$GH_REPO" --state closed --json number,title,createdAt,closedAt,mergedAt --limit 201  # timeout: 30000

# Axis 3: recent commits (last 100, paginate back 90d)
gh api "repos/$GH_OWNER/$GH_REPO/commits?per_page=100" --jq '.[].commit.author.date'  # timeout: 15000

# Axis 3 + 8A: releases (cadence + downloads) — REUSE for both axes
gh api "repos/$GH_OWNER/$GH_REPO/releases?per_page=10" \
    --jq '[.[] | {tag: .tag_name, published: .published_at, downloads: ([.assets[].download_count] | add // 0)}]'  # timeout: 15000

# Axis 4: contributor stats (may return 202 — retry logic below)
gh api "repos/$GH_OWNER/$GH_REPO/stats/contributors" \
    --jq '[.[] | {author: .author.login, total: .total, weeks: .weeks}]'  # timeout: 30000
# If 202: retry up to 6 times with 10s sleep (60s total — GitHub recompute typically <30s)
# If still 202 after 6 retries: mark Axis 4 ⚪; note in terminal score line with ⚠

# Axis 5 + 6: repo root file list — REUSE for both axes
gh api "repos/$GH_OWNER/$GH_REPO/contents" --jq '[.[] | .name]'  # timeout: 10000

# Axis 6 + 8 baseline: repo metadata
gh api "repos/$GH_OWNER/$GH_REPO" \
    --jq '{default_branch, has_issues, has_projects, allow_forking, stargazers_count, forks_count, subscribers_count, open_issues_count}'  # timeout: 10000

# Axis 7: Dependabot alerts (403 = push access required — graceful fallback)
gh api "repos/$GH_OWNER/$GH_REPO/dependabot/alerts?state=open&per_page=100" 2>/dev/null  # timeout: 15000

# Axis 7: secret scanning (same access requirement — graceful fallback)
gh api "repos/$GH_OWNER/$GH_REPO/secret-scanning/alerts?state=open" 2>/dev/null  # timeout: 15000

# Axis 8D: fork velocity
gh api "repos/$GH_OWNER/$GH_REPO/forks?sort=newest&per_page=100" \
    --jq '[.[] | .created_at]'  # timeout: 15000

# Duplicate clustering: all issues+PRs (open+closed)
gh issue list -R "$GH_OWNER/$GH_REPO" --state all --json number,title,state,labels,createdAt --limit 200  # timeout: 30000
gh pr list -R "$GH_OWNER/$GH_REPO" --state all --json number,title,state,createdAt --limit 100  # timeout: 30000
gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      discussions(first:100,orderBy:{field:UPDATED_AT,direction:DESC}){
        nodes { number title closed createdAt }
      }
    }
  }' -f owner="$GH_OWNER" -f repo="$GH_REPO"  # timeout: 15000
# Note: do not suppress errors on discussions call — 2>/dev/null hides auth failures AND disabled-discussions errors; write null dataset on error instead

# Axis 1: Responsiveness — sample 20 recent issues + 20 recent PRs for time-to-first-response
gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      issues(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:OPEN){
        nodes{ number createdAt author{login} comments(first:1){nodes{createdAt author{login}}} }
      }
      pullRequests(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:[OPEN,MERGED]){
        nodes{ number createdAt author{login} reviews(states:[APPROVED,CHANGES_REQUESTED,COMMENTED],first:1){nodes{createdAt author{login}}} comments(first:1){nodes{createdAt author{login}}} }
      }
    }
  }' -f owner="$GH_OWNER" -f repo="$GH_REPO"  # timeout: 30000

# Axis 4: Code-review coverage — last 30 merged PRs with approval data
gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      pullRequests(last:30,states:MERGED,orderBy:{field:UPDATED_AT,direction:DESC}){
        nodes{ number author{login} reviews(states:APPROVED){nodes{author{login}}} }
      }
    }
  }' -f owner="$GH_OWNER" -f repo="$GH_REPO"  # timeout: 30000

# Axis 5: CI/CD — workflow count and recent run health
gh api "repos/$GH_OWNER/$GH_REPO/actions/workflows" --jq '{count: (.workflows | length), names: [.workflows[].name]}' 2>/dev/null  # timeout: 10000
gh api "repos/$GH_OWNER/$GH_REPO/actions/runs?per_page=21" --jq '[.workflow_runs[] | {conclusion: .conclusion, name: .name}]' 2>/dev/null  # timeout: 15000

# Axis 9A: merged PRs last 90d with timing data (time-to-merge trend + reviewer pool drift)
# --limit 201: truncation detection — if 201 returned, pool data incomplete (confidence -0.2)
gh pr list -R "$GH_OWNER/$GH_REPO" --state closed \
    --search "merged:>=$CUTOFF_90D" \
    --json number,createdAt,mergedAt,author \
    --limit 201  # timeout: 30000

# Axis 9B: last 50 commit messages (commit substance ratio)
# author fallback: .commit.author.login // .author.login handles detached-push authors
gh api "repos/$GH_OWNER/$GH_REPO/commits?per_page=50" \
    --jq '[.[] | {sha:.sha[:7], message:(.commit.message | split("\n")[0]), author:(.commit.author.login // .author.login // "unknown"), date:.commit.author.date}]'  # timeout: 15000

# NOTE — no new fetch for open issues (reuse Axis 4 open issues list for queue staleness P90)
# NOTE — no new fetch for contributor stats (reuse Axis 3 weeks[] data for reviewer pool drift)
```

## Step 3 — Data Fetch Group 2 (depends on Group 1)

After Group 1 complete — root file list and default_branch now known. Run all calls simultaneously — independent (Group 1 must finish first):

```bash
# Axis 5: README content (decode base64; --ignore-garbage tolerates padded/partial base64 from API)
gh api "repos/$GH_OWNER/$GH_REPO/readme" --jq '.content' | base64 -d --ignore-garbage 2>/dev/null || base64 -D 2>/dev/null  # timeout: 10000

# Axis 5 checkpoints 8–10: CONTRIBUTING.md content (only if checkpoint 5 ✓ — CONTRIBUTING.md in root file list)
gh api "repos/$GH_OWNER/$GH_REPO/contents/CONTRIBUTING.md" --jq '.content' 2>/dev/null | base64 -d --ignore-garbage 2>/dev/null || base64 -D 2>/dev/null  # timeout: 10000

# Axis 6: .github/ directory contents
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github" --jq '[.[] | .name]' 2>/dev/null  # timeout: 10000

# Axis 6 checkpoint 5+7: CODEOWNERS content (check .github/CODEOWNERS first, then root)
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github/CODEOWNERS" --jq '.content' 2>/dev/null | base64 -d --ignore-garbage 2>/dev/null || \
gh api "repos/$GH_OWNER/$GH_REPO/contents/CODEOWNERS" --jq '.content' 2>/dev/null | base64 -d --ignore-garbage 2>/dev/null  # timeout: 10000

# Axis 6: branch protection on default branch
gh api "repos/$GH_OWNER/$GH_REPO/branches/{default_branch}/protection" 2>/dev/null  # timeout: 10000

# Axis 8C: package registry — detect package from root contents, then WebFetch
# If pyproject.toml found in root:
#   PYPROJECT=$(gh api "repos/$GH_OWNER/$GH_REPO/contents/pyproject.toml" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null)
#   Extract [project].name or [tool.poetry].name; WebFetch https://pypistats.org/api/packages/<name>/recent
# If package.json found in root:
#   PKG_JSON=$(gh api "repos/$GH_OWNER/$GH_REPO/contents/package.json" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null)
#   Extract .name; WebFetch https://api.npmjs.org/downloads/range/last-month/<name>
# 404 from registry: skip sub-signal C silently

# Axis 8B: star velocity — page-by-page loop; stop when starred_at < 180d ago
# gh --paginate fetches ALL pages unconditionally; use explicit loop with date check instead:
#   STAR_TMP="/tmp/star-dates-$GH_OWNER-$GH_REPO-$ANALYSIS_NOW.txt"
#   PAGE=1
#   while true; do
#     BATCH=$(gh api "repos/$GH_OWNER/$GH_REPO/stargazers?per_page=100&page=$PAGE" \
#       -H "Accept: application/vnd.github.star+json" --jq '.[].starred_at')  # timeout: 15000
#     [ -z "$BATCH" ] && break  # no more pages
#     echo "$BATCH" >> "$STAR_TMP"
#     OLDEST=$(echo "$BATCH" | tail -1)
#     [[ "$OLDEST" < "$CUTOFF_180D" ]] && break  # crossed 180d boundary
#     PAGE=$((PAGE+1))
#   done
# Derive: stars gained last 30d, 90d, 180d; trend = 30d rate vs 90d rate
# If fewer than 2 pages collected before timeout: mark 8B ⚪ unavailable

# Axis 5: Workflow content analysis — detect test/lint/SAST signals
# List .github/workflows/ directory (parallel with other Group 2 calls)
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github/workflows" --jq '[.[] | .name]' 2>/dev/null  # timeout: 10000
# Fetch content of first 2 workflow files (up to 2 calls); grep for signals:
# has_tests: grep -qi 'pytest\|jest\|cargo test\|go test\|npm test\|mvn test\|rspec\|phpunit'
# has_lint: grep -qi 'ruff\|flake8\|eslint\|prettier\|rubocop\|golangci\|black\|mypy'
# has_sast: grep -qi 'codeql\|semgrep\|sonar\|snyk\|trivy\|bandit'

# Axis 8: Dependabot/Renovate config check
# renovate.json and .renovaterc are in root-contents (already fetched in Group 1) — check from list
# .github/dependabot.yml requires this separate call:
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github/dependabot.yml" 2>/dev/null  # timeout: 10000
```

## Step 4 — Raw Data Dump (JSONL)

Write all fetched API responses to JSONL before scoring — file = scorer reference + reproducibility artifact. Run after all Group 1 and Group 2 fetches complete.

Use Write tool to create `$DATA_FILE`. Format: one JSON object per line (overwrite same-day file — one raw snapshot per repo per day; users needing intermediate data use timestamped paths).

One line per dataset. Record type specs and schema: `$_OSS_SHARED/vitality-data-schema.md`.

Rules:
- Skip datasets returning 403, persistent 202, or empty
- Set `"partial": true` when truncation detected
- Set `"records"` to item count in `data`
- After writing: `echo "[gh-scraper] raw data: N datasets → $DATA_FILE"`

## Step 5 — Return Envelope

```bash
DATASET_COUNT=$(grep -c '' "$DATA_FILE" 2>/dev/null || echo 0)  # timeout: 5000  # grep -c counts lines including files without trailing newline
echo "[gh-scraper] fetch complete: $DATASET_COUNT datasets → $DATA_FILE"  # timeout: 5000
```

Return ONLY this JSON as final output line:

`{"status":"done","file":"<DATA_FILE>","datasets":<DATASET_COUNT>,"confidence":0.95}`

</workflow>

<notes>

- **Parallel group discipline**: Group 1 calls all run simultaneously — independent; Group 2 only after Group 1 resolves (needs root file list and default_branch)
- **Data reuse**: root-contents fetch shared by Axes 6 and 7; releases fetch shared by Axis 2 and security signals; contributor stats weeks[] shared by Axis 3 and sub-signal 9A; open issues list shared by Axis 4 and sub-signal 9C — write all datasets to JSONL; scorers read what they need
- **--limit caps and truncation detection**: all limits set to target+1 (e.g. `--limit 501`); if response length equals limit → at least that many items exist (truncation at target count); set `"partial": true` in JSONL record; scorers apply confidence degraders. Note: unambiguous — 501 returned means ≥501 items exist, not off-by-one ambiguity
- **Stats 202 retry**: contributor stats returns 202 on first call for large repos — retry up to 6× with 10s sleep (60s total); if still 202 after all retries, write record with `"partial": true, "data": null, "202_pending": true`; scorer Group C handles fallback
- **403 on security APIs**: Dependabot and secret scanning require push access; 403 = expected; write `"data": "403"` string in JSONL record; Group B scorer applies partial-scoring formula
- **CUTOFF_* variables**: computed in Step 1; CUTOFF_90D/CUTOFF_30D used in Axis 9 merged PR fetch; ANALYSIS_NOW used for all age calculations throughout
- **Scoring removed**: scoring steps removed — scoring handled by 3 parallel oss:repo-warden instances; this agent is fetch-only

</notes>
