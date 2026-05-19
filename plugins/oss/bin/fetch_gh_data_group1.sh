#!/usr/bin/env bash
# fetch_gh_data_group1.sh — Group 1 parallel gh API data fetch for oss:gh-scraper.
#
# Fetches all GitHub REST + GraphQL data sources that have no inter-dependency
# (issues, PRs, releases, commits, contributor stats, security alerts, forks,
# stargazers, workflows, etc.). Writes one file per dataset under the output
# directory; the caller (gh-scraper agent Step 4) consolidates into JSONL.
#
# Failures on individual calls are non-fatal — printed to stderr with a warning
# prefix; missing files signal "data unavailable" to downstream scorers.
#
# Usage:
#   fetch_gh_data_group1.sh --repo <owner/repo> --output-dir <path>
#                           [--cutoff-3y <YYYY-MM-DD>] [--cutoff-90d <iso>] [--cutoff-180d <iso>]
#
# Exit: 0 on success (warnings on individual failures); 1 on bad args.
#
# Output files written to --output-dir:
#   open_issues.json          closed_issues.json       open_prs.json
#   closed_prs.json           commits.json             releases.json
#   contributor_stats.json    root_contents.json       repo_metadata.json
#   dependabot_alerts.json    secret_scanning_alerts.json
#   fork_dates.json           all_issues.json          all_prs.json
#   discussions.json          responsiveness_gql.json  review_coverage_gql.json
#   ci_workflows.json         ci_runs.json             merged_prs_90d.json
#   commits_50.json
set -euo pipefail

OWNER_REPO=""
OUTPUT_DIR=""
CUTOFF_3Y=""
CUTOFF_90D=""
CUTOFF_180D=""

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) OWNER_REPO="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --cutoff-3y) CUTOFF_3Y="$2"; shift 2 ;;
        --cutoff-90d) CUTOFF_90D="$2"; shift 2 ;;
        --cutoff-180d) CUTOFF_180D="$2"; shift 2 ;;
        *) echo "fetch_gh_data_group1.sh: unknown arg '$1'" >&2; exit 1 ;;
    esac
done

[ -n "$OWNER_REPO" ] || { echo "fetch_gh_data_group1.sh: --repo required" >&2; exit 1; }
[ -n "$OUTPUT_DIR" ] || { echo "fetch_gh_data_group1.sh: --output-dir required" >&2; exit 1; }
mkdir -p "$OUTPUT_DIR"

# Compute cutoffs if not supplied (cross-platform: macOS BSD vs GNU date)
if [ -z "$CUTOFF_3Y" ]; then
    if date -v-1d +%Y-%m-%d >/dev/null 2>&1; then
        CUTOFF_3Y=$(date -u -v-1095d +%Y-%m-%d)
        CUTOFF_90D=$(date -u -v-90d +%Y-%m-%dT%H:%M:%SZ)
        CUTOFF_180D=$(date -u -v-180d +%Y-%m-%dT%H:%M:%SZ)
    else
        CUTOFF_3Y=$(date -u -d '1095 days ago' +%Y-%m-%d)
        CUTOFF_90D=$(date -u -d '90 days ago' +%Y-%m-%dT%H:%M:%SZ)
        CUTOFF_180D=$(date -u -d '180 days ago' +%Y-%m-%dT%H:%M:%SZ)
    fi
fi

# Helper: run gh call in background; capture stdout to file; warn on failure.
_run() {
    local name="$1"; shift
    local out="$OUTPUT_DIR/$name.json"
    if "$@" >"$out" 2>/dev/null; then
        :
    else
        echo "⚠ fetch_gh_data_group1: $name failed (non-fatal)" >&2
        : >"$out"  # empty file signals "tried, failed"
    fi
}

# --- run all in parallel ---

# Axis 1: open issues (triage, stale, labels)
_run open_issues gh issue list -R "$OWNER_REPO" --state open \
    --json number,title,createdAt,updatedAt,labels --limit 501 &

# Axis 1: closed issues — time-bounded to last 3 years
_run closed_issues gh issue list -R "$OWNER_REPO" --state closed \
    --search "closed:>=$CUTOFF_3Y" \
    --json number,title,createdAt,closedAt --limit 1001 &

# Axis 2: open PRs (review, CI, age)
_run open_prs gh pr list -R "$OWNER_REPO" --state open \
    --json number,title,createdAt,updatedAt,reviews,statusCheckRollup --limit 201 &

# Axis 2: closed PRs recent (merge rate)
_run closed_prs gh pr list -R "$OWNER_REPO" --state closed \
    --json number,title,createdAt,closedAt,mergedAt --limit 201 &

# Axis 3: recent commits (last 100)
_run commits gh api "repos/$OWNER_REPO/commits?per_page=100" \
    --jq '[.[].commit.author.date]' &

# Axis 3 + 8A: releases (cadence + downloads)
_run releases gh api "repos/$OWNER_REPO/releases?per_page=10" \
    --jq '[.[] | {tag: .tag_name, published: .published_at, downloads: ([.assets[].download_count] | add // 0)}]' &

# Axis 4: contributor stats (may return 202 — caller retries)
_run contributor_stats gh api "repos/$OWNER_REPO/stats/contributors" \
    --jq '[.[] | {author: .author.login, total: .total, weeks: .weeks}]' &

# Axis 5 + 6: repo root file list
_run root_contents gh api "repos/$OWNER_REPO/contents" --jq '[.[] | .name]' &

# Axis 6 + 8 baseline: repo metadata
_run repo_metadata gh api "repos/$OWNER_REPO" \
    --jq '{default_branch, has_issues, has_projects, allow_forking, stargazers_count, forks_count, subscribers_count, open_issues_count}' &

# Axis 7: Dependabot alerts (403 = push access required)
_run dependabot_alerts gh api "repos/$OWNER_REPO/dependabot/alerts?state=open&per_page=100" &

# Axis 7: secret scanning (same access requirement)
_run secret_scanning_alerts gh api "repos/$OWNER_REPO/secret-scanning/alerts?state=open" &

# Axis 8D: fork velocity
_run fork_dates gh api "repos/$OWNER_REPO/forks?sort=newest&per_page=100" \
    --jq '[.[] | .created_at]' &

# Duplicate clustering: all issues + PRs + discussions
_run all_issues gh issue list -R "$OWNER_REPO" --state all \
    --json number,title,state,labels,createdAt --limit 200 &
_run all_prs gh pr list -R "$OWNER_REPO" --state all \
    --json number,title,state,createdAt --limit 100 &
_run discussions gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      discussions(first:100,orderBy:{field:UPDATED_AT,direction:DESC}){
        nodes { number title closed createdAt }
      }
    }
  }' -f owner="${OWNER_REPO%/*}" -f repo="${OWNER_REPO#*/}" &

# Axis 1: Responsiveness — recent issues + PRs for time-to-first-response
_run responsiveness_gql gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      issues(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:OPEN){
        nodes{ number createdAt author{login} comments(first:1){nodes{createdAt author{login}}} }
      }
      pullRequests(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:[OPEN,MERGED]){
        nodes{ number createdAt author{login} reviews(states:[APPROVED,CHANGES_REQUESTED,COMMENTED],first:1){nodes{createdAt author{login}}} comments(first:1){nodes{createdAt author{login}}} }
      }
    }
  }' -f owner="${OWNER_REPO%/*}" -f repo="${OWNER_REPO#*/}" &

# Axis 4: Code-review coverage — last 30 merged PRs with approval data
_run review_coverage_gql gh api graphql -f query='
  query($owner:String!,$repo:String!){
    repository(owner:$owner,name:$repo){
      pullRequests(last:30,states:MERGED,orderBy:{field:UPDATED_AT,direction:DESC}){
        nodes{ number author{login} reviews(states:APPROVED){nodes{author{login}}} }
      }
    }
  }' -f owner="${OWNER_REPO%/*}" -f repo="${OWNER_REPO#*/}" &

# Axis 5: CI/CD — workflow count and recent run health
_run ci_workflows gh api "repos/$OWNER_REPO/actions/workflows" \
    --jq '{count: (.workflows | length), names: [.workflows[].name]}' &
_run ci_runs gh api "repos/$OWNER_REPO/actions/runs?per_page=21" \
    --jq '[.workflow_runs[] | {conclusion: .conclusion, name: .name}]' &

# Axis 9A: merged PRs last 90d
_run merged_prs_90d gh pr list -R "$OWNER_REPO" --state closed \
    --search "merged:>=$CUTOFF_90D" \
    --json number,createdAt,mergedAt,author \
    --limit 201 &

# Axis 9B: last 50 commit messages
_run commits_50 gh api "repos/$OWNER_REPO/commits?per_page=50" \
    --jq '[.[] | {sha:.sha[:7], message:(.commit.message | split("\n")[0]), author:(.author.login // .commit.author.name // "unknown"), date:.commit.author.date}]' &

# Wait for all parallel fetches to complete
wait
echo "[fetch_gh_data_group1] wrote $(find "$OUTPUT_DIR" -maxdepth 1 -name '*.json' -type f | wc -l | tr -d ' ') dataset files → $OUTPUT_DIR" >&2
