# Mode: Repo Vitality Overview

<workflow>

## Step 1 — Data Fetch Group 1 (all parallel)

Run all calls simultaneously — independent:

```bash
# GH_OWNER and GH_REPO set by SKILL.md Step 1 — guaranteed non-empty when vitality mode runs
# All gh commands use: gh ... -R "$GH_OWNER/$GH_REPO" or gh api "repos/$GH_OWNER/$GH_REPO/..."
echo "[vitality] analysing $GH_OWNER/$GH_REPO"  # timeout: 5000

# Pin analysis time anchor at run start — used for all 30d/90d/180d window computations
ANALYSIS_NOW=$(TZ=UTC date +%s)  # Unix timestamp; propagate to all date arithmetic  # timeout: 5000
TODAY=$(TZ=UTC date +%Y-%m-%d)   # UTC date for report filename  # timeout: 5000
# For 30d/90d/180d cutoffs, use python3 -c with datetime to avoid cross-platform date -d/-v issues:
CUTOFF_30D=$(python3 -c "import datetime; print((datetime.datetime.utcnow()-datetime.timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
CUTOFF_90D=$(python3 -c "import datetime; print((datetime.datetime.utcnow()-datetime.timedelta(days=90)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
CUTOFF_180D=$(python3 -c "import datetime; print((datetime.datetime.utcnow()-datetime.timedelta(days=180)).strftime('%Y-%m-%dT%H:%M:%SZ'))")

# --- run all in parallel ---

# Axis 1: open issues (triage, stale, labels)
# Truncation detection: set --limit to target+1; if length == target+1, limit was hit
# e.g. for issues: --limit 501; if 501 returned → truncated at 500, mark partial
gh issue list -R "$GH_OWNER/$GH_REPO" --state open --json number,title,createdAt,updatedAt,labels --limit 501  # timeout: 30000

# Axis 1: closed issues recent (close rate)
gh issue list -R "$GH_OWNER/$GH_REPO" --state closed --json number,title,createdAt,closedAt --limit 201  # timeout: 30000

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
  }' -f owner="$GH_OWNER" -f repo="$GH_REPO" 2>/dev/null  # timeout: 15000

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
```

## Step 2 — Data Fetch Group 2 (depends on Group 1)

After Group 1 complete — root file list and default_branch now known:

```bash
# Axis 5: README content (decode base64)
gh api "repos/$GH_OWNER/$GH_REPO/readme" --jq '.content' | base64 -d  # timeout: 10000

# Axis 5 checkpoints 8–10: CONTRIBUTING.md content (only if checkpoint 5 ✓ — CONTRIBUTING.md in root file list)
gh api "repos/$GH_OWNER/$GH_REPO/contents/CONTRIBUTING.md" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null  # timeout: 10000

# Axis 6: .github/ directory contents
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github" --jq '[.[] | .name]' 2>/dev/null  # timeout: 10000

# Axis 6 checkpoint 5+7: CODEOWNERS content (check .github/CODEOWNERS first, then root)
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github/CODEOWNERS" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || \
gh api "repos/$GH_OWNER/$GH_REPO/contents/CODEOWNERS" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null  # timeout: 10000

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
#   PAGE=1
#   while true; do
#     BATCH=$(gh api "repos/$GH_OWNER/$GH_REPO/stargazers?per_page=100&page=$PAGE" \
#       -H "Accept: application/vnd.github.star+json" --jq '.[].starred_at')  # timeout: 15000
#     [ -z "$BATCH" ] && break  # no more pages
#     echo "$BATCH" >> /tmp/star-dates.txt
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

## Step 3 — Axis Scoring

Compute each axis score from fetched data. Any axis where all API calls fail → ⚪ "data unavailable" with reason.

**Axis 1 — Responsiveness** (CHAOSS #1 metric — most predictive of project attractiveness to contributors)

Data: GraphQL response from Group 1 (20 sampled issues + 20 sampled PRs).

Computation:
- For each issue: find first comment where `comment.author.login != issue.author.login`; `response_time = comment.createdAt − issue.createdAt` (fractional days). Issues with 0 non-author comments = "unresponded".
- For each PR: find earliest of (first non-author review) or (first non-author comment); `response_time = event.createdAt − pr.createdAt`.
- `median_issue_response_days` = median of response_times for issues that have responses
- `median_pr_response_days` = median of response_times for PRs with non-author events
- `pct_responded_7d` = (count issues with response_time ≤7d) / (count all sampled issues)
- `pct_unresponded` = count issues with 0 non-author comments / count all sampled

Score:
- 🟢: median_issue_response <3d AND median_pr_response <2d AND pct_responded_7d ≥80%
- 🟡: median_issue_response ≤14d OR pct_responded_7d ≥50% (some responsiveness)
- 🔴: median_issue_response >14d OR pct_responded_7d <50% OR pct_unresponded >60%
- ⚪: GraphQL 403 AND <5 issues to sample (cannot compute)

---

**Axis 2 — Maintenance Activity** (velocity + cadence; most important single axis)
- Days since last commit; commits in last 30d and 90d
- Days since last release (if releases exist); release cadence = avg days between last 5 releases
- **Score** (B1 fix — no "stable/maintenance mode" false-positive loophole):
  - 🟢: last commit <14d AND commits/30d ≥5
  - 🟡: last commit 14–60d OR commits/30d 1–4 OR (last commit >60d AND commits/90d ≥3 AND last release <180d — genuine maintenance backports)
  - 🔴: last commit >60d AND commits/30d = 0 — regardless of release recency. Zero commits = 🔴. A release ≤180d ago only upgrades to 🟡 when commits/90d ≥3 proves ongoing work.
  - ALSO 🔴: commits/30d = 0 for >90d (no commits for an entire quarter)

---

**Axis 3 — Contributor Health** (individual concentration + community sustainability)

- Filter `*[bot]` and `*-bot` suffixed accounts from contributor list
- Bus factor = min contributors whose removal drops 90d commit total >50% (sort desc by 90d commits; accumulate until >50%)
- Top contributor % of total commits last 90d
- **Contributor retention rate**: using stats weeks[-13:] (last 90d):
  - Q1 = weeks[-13:-7] (90d–45d ago); Q2 = weeks[-7:] (45d–0d ago)
  - active_Q1 = contributors with sum(Q1.c) ≥1
  - active_both = contributors active in Q1 AND Q2
  - retention_rate = len(active_both) / len(active_Q1) — undefined if len(active_Q1) = 0

Score:
- 🟢: bus factor ≥3 AND top contributor <50% last 90d AND retention ≥50% (when available)
- 🟡: bus factor = 2 OR top contributor 50–75% OR retention 30–50% OR retention undefined
- 🔴: (bus factor = 1 AND Axis 2 🔴) OR top contributor >75% OR retention <30%

**202 fallback** (H4 fix — do not always mark ⚪):
- If stats API returns 202 after 6× retry: attempt commit-author fallback:
  - From last 100 commits (already fetched): count unique non-bot author logins
  - unique_authors ≤1 → approximate bus factor 1 (🔴 floor); ≤2 → 2 (🟡 floor); ≥3 → 3 (🟢 ceiling)
  - Mark confidence = 0.5; add "⚠ bus factor estimated from commit authors (stats API computing)"
- Mark ⚪ only if: 202 persists AND commit fallback also fails

Stats 202 after all retries WITH successful fallback: ⚪ is NOT used; fallback score at confidence 0.5.

---

**Axis 4 — Issue & PR Health** (queue hygiene + code review quality; merged from old Axes 1+2)

Issue signals (from open/closed issue lists):
- stale % = open issues with no update >90d / total open
- close rate = closed last 30d / opened last 30d (0 if denominator 0)
- median open issue age (days)

PR signals (from open/closed PR lists; filter bot PRs):
- merge rate = merged last 30d / opened last 30d (bot-filtered)
- abandoned % = open PRs with no update >30d / total open
- closed-without-merge ratio = closed PRs with mergedAt=null / total closed last 30d

Code-review coverage (from GraphQL, last 30 merged PRs; filter bot PRs):
- `review_coverage` = count(PRs with ≥1 non-author approving review) / count(all non-bot merged PRs sampled)
- "undefined" if <5 non-bot merged PRs in sample

Score (worst-of composite — any 🔴 dimension → axis 🔴):
- 🟢: stale <10% AND close_rate ≥0.8 AND merge_rate ≥0.7 AND review_coverage ≥80%
- 🟡: stale 10–30% OR close_rate 0.4–0.8 OR merge_rate 0.3–0.7 OR review_coverage 50–80% OR review_coverage undefined
- 🔴: stale >30% OR close_rate <0.4 OR merge_rate <0.3 OR review_coverage <50%

---

**Axis 5 — CI/CD & Code Quality** (absent entirely from prior design; repohealth scores CI/CD 35/100)

5 checkpoints:
1. CI workflows present — `actions/workflows` count ≥1 OR `.github/workflows/` non-empty in directory listing
2. Workflows run tests — workflow file content grep (case-insensitive): `pytest|jest|cargo test|go test|npm test|mvn test|rspec|phpunit`
3. Workflows run linter/formatter — grep: `ruff|flake8|eslint|prettier|rubocop|golangci|black|mypy`
4. SAST or security scan present — grep: `codeql|semgrep|sonar|snyk|trivy|bandit` OR CodeQL action used
5. Recent CI health — ≥80% of last 20 run conclusions are "success" (from `actions/runs` response; N+1 detection: per_page=21, truncated if 21 returned)

If `actions/workflows` returns 403: checkpoint 1 = ✗; confidence -0.3.
If `.github/workflows/` absent from root-contents and API 403: checkpoint 1 = ✗ (no extra API call).
If workflow content fetch fails (403 or decode error): checkpoints 2–4 = ✗; confidence -0.2.
If <10 run results: pass rate unstable; confidence -0.1.

Score: floor(met / 5 × 10) → 0–10; 🟢 ≥4/5 | 🟡 2–3/5 | 🔴 ≤1/5

---

**Axis 6 — Documentation** (content quality, not just presence; 9 checkpoints)

Note: CONTRIBUTING.md presence is tracked in Axis 7 Governance — this axis scores content depth only.

9 checkpoints:
1. README present and >500 bytes
2. README has install section (grep: `install|pip install|npm install|cargo add|brew install`)
3. README has usage/quickstart section (grep: `usage|quickstart|getting started|example`)
4. CHANGELOG present (CHANGELOG.md, CHANGES.md, HISTORY.md, NEWS.md)
5. docs/ or doc/ directory present
6. examples/ or example/ directory present
7. CONTRIBUTING.md has dev-setup section (auto-fail if no CONTRIBUTING.md; grep: `setup|local.*install|dev.*env|getting started`)
8. CONTRIBUTING.md has PR/review process (grep: `pull.request|review.*process|merge.*process|workflow`)
9. CONTRIBUTING.md has code style or lint guidance (grep: `code.*style|lint|format|coding.*standard|ruff|mypy|eslint|prettier`)

Score: floor(met / 9 × 10); 🟢 ≥7/9 | 🟡 4–6/9 | 🔴 ≤3/9

---

**Axis 7 — Governance** (7 checkpoints; weight increased above Documentation per H1 fix)

1. LICENSE present (root)
2. SECURITY.md present (root or .github/)
3. CODE_OF_CONDUCT.md present (root or .github/)
4. CONTRIBUTING.md present (root or .github/)
5. CODEOWNERS present (.github/ or root)
6. Branch protection enabled on default branch
7. Active maintainer ratio ≥0.5 — conditional: CODEOWNERS has @username entries (not @org/team) AND Axis 3 contributor stats available; cross-reference CODEOWNERS usernames against stats weeks[-13:]; active_ratio = active_90d / listed; ✓ if ≥0.5

max_applicable = 7 if checkpoint 7 applicable, else 6
Score: floor(met / max_applicable × 10); 🟢 ≥5/applicable | 🟡 3–4 | 🔴 ≤2

---

**Axis 8 — Security Posture** (weight reduced; partial scoring on 403 instead of excluding)

Primary signals (push access required — Dependabot alerts API):
- Open alerts by severity: critical_count, high_count, medium_count, low_count
- Secret scanning alerts

Secondary signals (always available, no push access needed):
- Dependabot/Renovate configured: `.github/dependabot.yml` present OR `renovate.json`/`.renovaterc` in root-contents
- dep-update commits in last 90d (grep commit messages: case-insensitive `^(bump|chore\(deps\)|build\(deps\)|deps:|dependabot|update deps|upgrade deps)`)
- SECURITY.md content depth: present=1pt; contains `@` email=+1pt; contains digit+("day"|"hour"|"week") SLA=+1pt; depth_score 0–3

Score when Dependabot available (no 403):
- 🟢: 0 critical/high alerts AND dep-config present
- 🟡: 0 critical but ≥1 high OR no dep-config
- 🔴: ≥1 critical OR ≥5 high

**B2 fix — Score when Dependabot 403 (partial scoring; NOT excluded ⚪)**:
- partial_score = 0
- +4 if dep-config present (highest weight — proves proactive security hygiene)
- +3 if dep-update commits present (proves active dependency maintenance)
- +2 if depth_score ≥1 (SECURITY.md with contact or SLA)
- +1 if all three present (bonus: belt-and-suspenders)
- Score = min(10, partial_score)
- Confidence = 0.4 (Dependabot alerts unavailable — primary signal missing)
- Note in report: "Dependabot alerts unavailable (push access required) — score from config signals only"
- Never 🟢 when Dependabot 403; max effective 🟡 from partial scoring when all secondary signals present

---

**Per-axis numeric score** (unified 0–10 scale):
- Threshold axes (1, 2, 3, 8 when push access): 🟢 → 10, 🟡 → 5, 🔴 → 0, ⚪ → excluded
- Axis 8 when 403: numeric partial_score (0–10) used directly
- Checkpoint axes: score = floor(met / total_checkpoints × 10)
  - Axis 5: floor(met / 5 × 10)
  - Axis 6: floor(met / 9 × 10)
  - Axis 7: floor(met / max_applicable × 10)

**Weights** (sum = 1.00):
| Axis | Weight |
| --- | --- |
| 1 Responsiveness | 0.18 |
| 2 Maintenance activity | 0.20 |
| 3 Contributor health | 0.15 |
| 4 Issue & PR health | 0.12 |
| 5 CI/CD & code quality | 0.10 |
| 6 Documentation | 0.08 |
| 7 Governance | 0.10 |
| 8 Security posture | 0.07 |

**Health Score %** computation:
1. Collect available axes (non-⚪); let W = sum of their weights
2. Coverage gate: if W < 0.5 (fewer than ~4 axes available) → mark score provisional: "Health Score: XX% ⚠ (provisional — <50% of axes have data)"
3. If W = 0 (all axes ⚪) → emit "Health Score: N/A — insufficient data" and stop
4. Health Score % = round(sum(score_i × weight_i) / W × 10) (round half-up; Python: `int(x + 0.5)`)
- Ranges: 80–100% excellent · 60–79% healthy · 40–59% needs attention · <40% critical / likely abandoned
- Maximum achievable score: 100% (all axes scored 10)

**Overall**: count 🟢/🟡/🔴/⚪; compute Health Score %; top risk = highest-severity finding across all 🔴 axes.

## Per-Axis Confidence

Compute each axis's confidence (0.0–1.0) — reflects data quality, not score direction. A 🔴 axis with complete data has confidence=1.0.

| Axis | Weight | Base | Key degraders | Floor |
| --- | --- | --- | --- | --- |
| 1 Responsiveness | 0.18 | 1.0 | -0.2 if <5 issues sampled; -0.2 if <5 PRs sampled; -0.3 if GraphQL 403 | 0.3 |
| 2 Maintenance activity | 0.20 | 1.0 | -0.3 commits API 403/empty; -0.15 100-commit truncation in window; -0.1 no releases | 0.2 |
| 3 Contributor health | 0.15 | 1.0 | fallback mode → 0.5; -0.3 if stats 403; -0.1 <3 contributors; -0.1 all 90d weeks zero | 0.0/0.4/0.5 |
| 4 Issue & PR health | 0.12 | 1.0 | -0.2 open issue list truncated (501 returned); -0.2 open PR list truncated; -0.15 <3 merged PRs (review coverage unstable); -0.1 GraphQL review query failed | 0.3 |
| 5 CI/CD & code quality | 0.10 | 1.0 | -0.3 actions/workflows 403; -0.2 workflow content unreadable (checkpoints 2–4 unknown); -0.1 <10 recent runs (pass rate unstable); -0.1 run list truncated (21 returned) | 0.4 |
| 6 Documentation | 0.08 | 1.0 | -0.1 README 404; -0.2 README API error; -0.05 per checkpoint with API failure; -0.1 CONTRIBUTING content fetch failed (checkpoints 7–9 indeterminate) | 0.5 |
| 7 Governance | 0.10 | 1.0 | -0.1 .github/ 403; -0.1 branch protection 403; -0.05 root contents 403; -0.1 Axis 3 ⚪ and CODEOWNERS has @usernames (checkpoint 7 uncomputable) | 0.6 |
| 8 Security posture | 0.07 | 1.0 | -0.6 Dependabot 403 → confidence 0.4 (partial scoring mode); -0.2 secret scanning 403; -0.15 alert list at 100-item limit | 0.2 |

Axis 3 confidence logic:
```
if status == 202 AND fallback (commit authors) succeeds: axis3_confidence = 0.5
if status == 202 AND fallback fails: axis3_confidence = 0.0  # mark ⚪
if status == 403: axis3_confidence = 0.4
else: axis3_confidence = max(0.4, 1.0 - low_contributor_penalty - dormant_penalty)
```

Axis 8 confidence logic:
```python
if dependabot_status == 403:
    axis8_confidence = 0.4  # partial scoring mode
else:
    axis8_confidence = max(0.2, 1.0 - other_penalties)
```

## Overall Confidence

```python
# Weights for available (non-⚪) axes only
W_total = sum(weights[ax] for ax in available_axes)
if W_total == 0:
    overall_confidence = 0.0
else:
    overall_confidence = sum(available_axes[ax] * weights[ax] for ax in available_axes) / W_total

# Headline score format:
if overall_confidence < 0.7:
    "Health Score: {XX}% ⚠ LOW CONFIDENCE ({conf:.2f}) — directional only; see Gaps & Limitations"
else:
    "Health Score: {XX}%"
```

Checkpoint axes carry sub-tier resolution — numeric score is more precise than 🟢/🟡/🔴 status; consumers should use numeric score for comparison across repos.

**Data Sources log**: track actual record counts as each API call completes — open_issues_count, closed_issues_count, open_prs_count, closed_prs_count, commits_count (with date range), releases_count, contributors_count (or "202-fallback"), responsiveness_sample_issues, responsiveness_sample_prs, ci_workflows_count, ci_runs_count, readme_size_bytes, dependabot_status ("N alerts" or "403"), star_history_days. These populate the Data Sources table in Step 4.

## Step 4 — Report Generation

```bash
REPORT_TIMESTAMP=$(TZ=UTC date +%Y-%m-%dT%H-%M-%SZ)  # timeout: 5000
REPORT_FILE=".reports/analyse/vitality/output-analyse-vitality-${GH_OWNER}-${GH_REPO}-${REPORT_TIMESTAMP}.md"

# Provenance metadata — embedded in report header for self-complete, deterministic output
SKILL_VERSION=$(python3 -c "
import json, os, glob
# Try installed cache first, then workspace source
paths = sorted(glob.glob(os.path.expanduser('~/.claude/plugins/cache/borda-ai-rig/oss/*/.claude-plugin/plugin.json')))
if not paths:
    paths = glob.glob('plugins/oss/.claude-plugin/plugin.json')
if paths:
    print(json.load(open(paths[-1])).get('version','unknown'))
else:
    print('unknown')
" 2>/dev/null || echo "unknown")  # timeout: 5000

REPORT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")  # timeout: 5000

# Codex availability check — done here so agents list in frontmatter is accurate at write time
find ~/.claude/plugins -name "codex-rescue.md" 2>/dev/null | grep -q . && CODEX_AVAILABLE=1 || CODEX_AVAILABLE=0

# Build agents list for YAML frontmatter — deterministic, reflects actual contributors
REPORT_AGENTS_YAML="  - oss:analyse (orchestrator)
  - foundry:challenger (adversarial review)"
[ "$CODEX_AVAILABLE" = "1" ] && REPORT_AGENTS_YAML="$REPORT_AGENTS_YAML
  - codex:codex-rescue (independent repo review + adversarial review)"
```

Run `mkdir -p .reports/analyse/vitality` then write full report to `$REPORT_FILE` via Write tool — do not print full analysis to terminal.

Report structure:

```markdown
---
generated_at: {REPORT_TIMESTAMP}
repo: {GH_OWNER}/{GH_REPO}
skill: oss:analyse
mode: vitality
skill_version: {SKILL_VERSION}
commit: {REPORT_COMMIT}
agents:
{REPORT_AGENTS_YAML}
---

# Repo Vitality — {GH_OWNER}/{GH_REPO}

**Generated:** {REPORT_TIMESTAMP}
**Skill:** oss:analyse · mode: vitality · v{SKILL_VERSION}
**Commit:** {REPORT_COMMIT}
**Agents:** {comma-joined agent list from REPORT_AGENTS_YAML}

---

## Summary

{2–3 sentence verdict: overall health, top strength, top risk. Include health score badge and axis tally.}

**Health Score:** {XX}% · {🟢|🟡|🔴} · {N} healthy · {N} warning · {N} critical · {N} unavailable (⚪)

---

## Scorecard

| Axis | Weight | Score | Status | Conf | Key Signal |
|------|--------|-------|--------|------|------------|
| 1 Responsiveness | 18% | N.N | 🟢/🟡/🔴 | 0.00 | median issue Xd, PR Xd; X% ≤7d |
| 2 Maintenance activity | 20% | N.N | 🟢/🟡/🔴 | 0.00 | last commit Xd, X commits/30d |
| 3 Contributor health | 15% | N.N | 🟢/🟡/🔴 | 0.00 | bus factor N, retention X% |
| 4 Issue & PR health | 12% | N.N | 🟢/🟡/🔴 | 0.00 | stale X%, close rate X, review cov X% |
| 5 CI/CD & code quality | 10% | N.N | 🟢/🟡/🔴 | 0.00 | N/5 checks, CI pass rate X% |
| 6 Documentation | 8% | N.N | 🟢/🟡/🔴 | 0.00 | N/9 checkpoints |
| 7 Governance | 10% | N.N | 🟢/🟡/🔴 | 0.00 | N/7 files, active maintainers X/Y |
| 8 Security posture | 7% | N.N | 🟢/🟡/🔴 | 0.00 | dep-config: yes/no, alerts: N or "403" |
| **Health Score** | 100% | **XX%** | | | |

_(Conf: per-axis confidence 0.00–1.00; ⚠ = below 0.9. ⚪ axes excluded from score; weight renormalized.)_

---

## Finding Matrix

Quick severity cross-reference across all axes:

| Axis | Critical | High | Medium | Low | Total |
|------|----------|------|--------|-----|-------|
| 1 Responsiveness | N | N | N | N | N |
| 2 Maintenance activity | N | N | N | N | N |
| 3 Contributor health | N | N | N | N | N |
| 4 Issue & PR health | N | N | N | N | N |
| 5 CI/CD & code quality | N | N | N | N | N |
| 6 Documentation | N | N | N | N | N |
| 7 Governance | N | N | N | N | N |
| 8 Security posture | N | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** | **N** |

_Severity mapping: 🔴 axis score = Critical or High findings; 🟡 = Medium; Low = informational observations within any axis._

---

## Findings

Ordered by severity. Each finding includes evidence from fetched data, impact assessment, and concrete action.

### 🔴 Critical

_(Only emitted when axis scores 🔴 with high-impact evidence. If none: "No critical findings.")_

#### [Axis N] {Finding title}
**Axis:** {name} · **Score:** {N.N} · **Conf:** {0.00}
**Evidence:** {specific numbers and data points from API fetch — not assertions}
**Impact:** {why this matters for the project and its contributors}
**Action:** {concrete, specific next step with ownership hint}

### 🟡 High

_(🟡 axes with strong signal. If none: "No high-severity findings.")_

#### [Axis N] {Finding title}
**Axis:** {name} · **Score:** {N.N} · **Conf:** {0.00}
**Evidence:** {specific numbers}
**Impact:** {impact}
**Action:** {action}

### 🟠 Medium

_(Informational issues within 🟡 axes, or boundary-case 🔴 axes with mitigating factors.)_

### 🔵 Low

_(Observations worth tracking but not urgent.)_

---

## Duplicate Clustering

Group all issues, PRs, and discussions (open and closed) by their shared duplication root —
the specific element that makes them the same problem: identical error message, identical
feature ask, or identical root cause even if symptoms differ. Flag as RELATED (not duplicate)
when items share a component/area but have distinct problems.

#### Group 1
**Root**: [the shared key — e.g. exact error message, exact feature request, exact failure mode]
- Issue #N: [title] ([open/closed]) — created [date]  ← CANONICAL
- Issue #N: [title] ([open/closed]) ← DUPLICATE
- PR #N: [title] ([state]) ← related fix
  → Close duplicates with: "Closing as duplicate of #[canonical]"

_(Repeat for each group. If no duplicate groups found: "No obvious duplicates detected.")_

---

## Recommended Actions

Ordered by priority (highest impact first):

1. {action} — addresses {axis}, expected impact: {outcome}
2. ...

---

## Independent Codex Review

{Populated by Step 5 — codex:codex-rescue independent assessment and aggregation. When codex unavailable: "codex unavailable — single-pass analysis only."}

---

## Data Sources

All data fetched from GitHub API at {REPORT_TIMESTAMP}. Record counts confirm analysis is grounded in actual repository state.

| Source | API Endpoint | Records Fetched | Window | Notes |
|--------|-------------|-----------------|--------|-------|
| Open issues | `GET /repos/{repo}/issues?state=open` | N | all open | {truncated at 500 if >500} |
| Closed issues | `GET /repos/{repo}/issues?state=closed` | N | recent 200 | close rate window |
| Open PRs | `GET /repos/{repo}/pulls?state=open` | N | all open | |
| Closed PRs | `GET /repos/{repo}/pulls?state=closed` | N | recent 200 | merge rate window |
| Commits | `GET /repos/{repo}/commits` | N | last 100 | date range: {earliest}–{latest} |
| Releases | `GET /repos/{repo}/releases` | N | last 10 | cadence + downloads |
| Contributor stats | `GET /repos/{repo}/stats/contributors` | N contributors | all-time | {202-fallback if applicable} |
| Responsiveness sample | GraphQL issues + PRs | 20 + 20 | most recent | time-to-first-response |
| CI workflows | `GET /repos/{repo}/actions/workflows` | N workflows | — | |
| CI runs | `GET /repos/{repo}/actions/runs` | N | last 20 | pass rate |
| README | `GET /repos/{repo}/readme` | {size} bytes | — | |
| Dependabot alerts | `GET /repos/{repo}/dependabot/alerts` | N or 403 | open | 403 = no push access |
| Star history | `GET /repos/{repo}/stargazers` | N | last 180d | advisory only |

_{Any endpoint returning 403 or 202 is noted in Gaps & Limitations. All counts are actual response sizes, not estimates.}_

---

## Methodology

Axes and weights reflect signal quality, data reliability, and predictive value for project sustainability. Sources: CHAOSS practitioner guides, OpenSSF Scorecard risk levels, repohealth category weights.

| Axis | Weight | Rationale |
|------|--------|-----------|
| 1 Responsiveness | 18% | CHAOSS #1 metric — time-to-first-response is the most visible signal to contributors and directly predicts contributor retention |
| 2 Maintenance activity | 20% | Highest weight — commit velocity is objective evidence the project is alive; cannot be gamed by documentation alone |
| 3 Contributor health | 15% | Bus factor and retention rate predict abandonment risk 1–2 quarters before commit counts drop |
| 4 Issue & PR health | 12% | Throughput + code-review coverage; merged from two prior axes to avoid double-counting maintainer behaviour |
| 5 CI/CD & code quality | 10% | Projects with CI accumulate fewer silent regressions; absence correlates with abandonment (repohealth: CI/CD = 35/100) |
| 6 Documentation | 8% | Lagging usability signal — content depth weighted over presence; lower than governance because docs are easier to retrofit |
| 7 Governance | 10% | Legal usability (LICENSE), security contact (SECURITY.md), succession planning (CODEOWNERS) — harder to retrofit than docs |
| 8 Security posture | 7% | Lowest — primary signal (Dependabot alerts) requires push access; most runs score via secondary signals at confidence 0.4 |

Weights sum to 1.00. Axes where data is unavailable (⚪) are excluded; remaining weights renormalized.

---

## Gaps & Limitations

**Overall confidence:** {overall_confidence:.2f} {🟢 ≥0.9 | 🟡 0.7–0.9 | 🔴 <0.7}

{If overall_confidence < 0.7: "⚠ Health Score reliability is LOW — findings are directional only. Re-run with improved data access before acting on this score."}

### Per-Axis Confidence

| Axis | Confidence | Gap | Score Impact |
|------|------------|-----|--------------|
| {axes with conf < 1.0, sorted ascending} | | | |

_(Only axes with confidence < 1.0 appear. If all ≥ 0.9: "All axes scored with high-confidence data.")_

### Re-run Recommendations

{conditional bullets — only emit when actionable:}
- **Axis 8 full data**: re-run with push access — Dependabot alert counts then available
- **Axis 3**: re-run in 5–10 min — contributor stats computing (202); retry when complete
- **Axis 4 merge rate**: re-run after {date+30d} — low-volume repo; <3 PRs this month makes rate unstable

---

## Adversarial Review

**Challenger:** {findings written by foundry:challenger — always present}

**Codex:** {findings written by codex:codex-rescue — present when codex plugin installed; "codex unavailable — single adversarial pass only" when absent}

---

## Sign-off & Disclaimer

Report generated by **oss:analyse v{SKILL_VERSION}** on commit `{REPORT_COMMIT}` at `{REPORT_TIMESTAMP}`.
Data sourced exclusively from GitHub API — no manual input or cached external data.
Scores reflect repository state at time of generation. Re-run for current state.
Adversarial review performed by foundry:challenger{codex line: " and codex:codex-rescue" when CODEX_AVAILABLE=1}.
```

## Step 5 — Codex Independent Repo Review

When `CODEX_AVAILABLE=1`: spawn `codex:codex-rescue` to independently assess the repo on the same 8 axes using the raw fetched data — NOT by reading the main analysis report. This produces a parallel verdict for aggregation and divergence detection.

```bash
REVIEW_DIR=".reports/analyse/vitality/$(date +%Y-%m-%d)-review"
CODEX_REVIEW_OUT="$REVIEW_DIR/codex-repo-review.md"
mkdir -p "$REVIEW_DIR"  # timeout: 5000
```

**Spawn instruction for `codex:codex-rescue`** (only when CODEX_AVAILABLE=1):

```text
You are performing an independent vitality assessment of {GH_OWNER}/{GH_REPO}.
Do NOT read the main analysis report. Assess the same 8 axes from raw evidence only:
- Axis 1 Responsiveness (weight 18%)
- Axis 2 Maintenance activity (weight 20%)
- Axis 3 Contributor health (weight 15%)
- Axis 4 Issue & PR health (weight 12%)
- Axis 5 CI/CD & code quality (10%)
- Axis 6 Documentation (8%)
- Axis 7 Governance (10%)
- Axis 8 Security posture (7%)

Use only this raw data: [pass all fetched API data: issue counts, PR counts, commit dates,
contributor stats, CI workflow/run data, root file list, branch protection, Dependabot status].

For each axis: assign a numeric score 0–10 and status 🟢/🟡/🔴/⚪. Provide one-sentence
evidence statement per axis. Compute overall Health Score %.

Write findings to {CODEX_REVIEW_OUT} using Write tool in this exact format:
# Codex Independent Review — {GH_OWNER}/{GH_REPO}
| Axis | Score | Status | Evidence |
|------|-------|--------|----------|
| 1 Responsiveness | N.N | 🟢/🟡/🔴 | {one sentence} |
...
| **Health Score** | **XX%** | | |

## Divergences
[note any axis where you expect main analysis to differ — include reasoning]

Write sentinel {REVIEW_DIR}/codex-repo-review.done on completion.
Return compact JSON only: {"status":"done","file":"{CODEX_REVIEW_OUT}","health_score":XX,"confidence":0.N}
```

**When CODEX_AVAILABLE=0**: skip this step; note "codex unavailable — single-pass analysis only" in the Codex Independent Review report section.

### Aggregation

After codex review completes (sentinel verified), compute per-axis delta:

```bash
# delta = abs(main_score[axis] - codex_score[axis])
# divergence threshold: delta >= 2.0 points
# flag axes where delta >= 2.0 as "⚠ divergent"
# aggregate health score = mean(main_health_score, codex_health_score)
```

Update the report's `## Independent Codex Review` section (append using Edit tool) with:
- The codex scorecard table (from `$CODEX_REVIEW_OUT`)
- Aggregate health score
- Per-axis delta table with divergence flags
- Divergence explanations where delta ≥ 2.0

```markdown
## Independent Codex Review

Codex independently assessed the same 8 axes from raw fetched data — without reading the main analysis. Divergences ≥ 2.0 score points are flagged for human review.

**Codex Health Score:** {XX}% · **Aggregate (mean):** {XX}%

| Axis | Main | Codex | Delta | Agreement |
|------|------|-------|-------|-----------|
| 1 Responsiveness | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 2 Maintenance activity | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 3 Contributor health | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 4 Issue & PR health | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 5 CI/CD & code quality | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 6 Documentation | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 7 Governance | N.N | N.N | ±N.N | ✓ / ⚠ divergent |
| 8 Security posture | N.N | N.N | ±N.N | ✓ / ⚠ divergent |

### Divergences

_(Only axes with delta ≥ 2.0. If none: "Main analysis and Codex agree within 2.0 points on all axes.")_

#### Axis N — {name} (main: N.N · codex: N.N · delta: ±N.N)
**Main evidence:** {what main analysis used}
**Codex evidence:** {what codex found}
**Resolution:** {which reading is more likely correct and why — or "inconclusive, re-run recommended"}
```

## Step 6 — Adversarial Review

After Step 5 aggregation complete — report now includes main analysis + Codex independent review + divergence resolution. Adversarial reviewers assess the **complete combined report**. Two reviewers write to separate files to avoid concurrent-write race; parent merges results after both complete.

```bash
# CODEX_AVAILABLE already set in Step 4 — do not re-check; use value as-is
# REVIEW_DIR already set in Step 5 — do not redefine
CHALLENGER_OUT="$REVIEW_DIR/challenger.md"
CODEX_OUT="$REVIEW_DIR/codex.md"
```

**Run sequentially** (not parallel — avoids concurrent writes to report file):

1. Spawn `foundry:challenger` — reads report file; writes findings to `$CHALLENGER_OUT` (Write tool); on completion writes sentinel `$REVIEW_DIR/challenger.done`; instruction: stress-test scoring thresholds, flag weak evidence, challenge causality claims, verify limit-hit detection, check coverage gate logic; stress-test both main analysis and Codex independent review — flag where both analyses share the same blind spot, or where divergence resolution is unconvincing. Return compact JSON envelope only.
2. Verify sentinel before reading: `[ -f "$REVIEW_DIR/challenger.done" ] || { echo "⚠ challenger did not complete"; CHALLENGER_OUT=""; }`
3. If CODEX_AVAILABLE=1: spawn `codex:codex-rescue` — reads report file and `$CHALLENGER_OUT` (if complete); writes independent findings to `$CODEX_OUT`; on completion writes sentinel `$REVIEW_DIR/codex.done`; second adversarial pass avoiding duplication with challenger. Return compact JSON envelope only.
4. Verify codex sentinel: `[ -f "$REVIEW_DIR/codex.done" ] || CODEX_OUT=""`
5. Append available outputs to report under `### Adversarial Review` in deterministic order (challenger first, codex second); skip any whose file is empty or sentinel absent.
6. If CODEX_AVAILABLE=0: note "codex unavailable — single adversarial pass only" in Adversarial Review section.

## Step 7 — Terminal Summary Output

Read `$FOUNDRY_SHARED/terminal-summaries.md` for compact block format. File absent → warn "foundry:init required — printing plain terminal output instead."

Print compact block to terminal (values read from report YAML frontmatter + scorecard):

```markdown
# Repo Vitality — {GH_OWNER}/{GH_REPO}
**Generated:** {REPORT_TIMESTAMP}
**Skill:**     oss:analyse · mode: vitality · v{SKILL_VERSION}
**Commit:**    {REPORT_COMMIT}

---

**Health Score:** {XX}% (confidence: {0.NN} 🟢/🟡/🔴) | {N}/8 healthy | {N} warning | {N} critical
**Aggregate Score:** {XX}% (mean of main + Codex) — omit line when CODEX_AVAILABLE=0
**Top Risk:**    {single most urgent finding}
→ {REPORT_FILE}

| Axis                   | Score | Status   | Conf | Weight |
|------------------------|-------|----------|------|--------|
| 1 Responsiveness       | N.N   | 🟢/🟡/🔴 | 0.00 | 18% |
| 2 Maintenance activity | N.N   | 🟢/🟡/🔴 | 0.00 | 20% |
| 3 Contributor health   | N.N   | 🟢/🟡/🔴 | 0.00 | 15% |
| 4 Issue & PR health    | N.N   | 🟢/🟡/🔴 | 0.00 | 12% |
| 5 CI/CD & code quality | N.N   | 🟢/🟡/🔴 | 0.00 | 10% |
| 6 Documentation        | N.N   | 🟢/🟡/🔴 | 0.00 |  8% |
| 7 Governance           | N.N   | 🟢/🟡/🔴 | 0.00 | 10% |
| 8 Security posture     | N.N   | 🟢/🟡/🔴 | 0.00 |  7% |

---
```

For ⚪ axes: show `--` in Score/Status/Conf columns; append below the closing `---`:
```text
⚠ Axis {N} ({name}, wt {X}%) unavailable — score normalized over {M}/8 axes
```
If Axis 3 specifically ⚪: use `⚠ Axis 3 (contributor health, wt 15%) unavailable — rerun in 5–10 min for full score`.

Block must begin with `# Repo Vitality — {GH_OWNER}/{GH_REPO}` title and close with `---` on own line. Do not print full analysis to terminal.

</workflow>

<notes>

- **Parallel group discipline**: Group 1 all calls truly independent — run simultaneously; Group 2 only after Group 1 resolves (needs root file list and default_branch)
- **Data reuse**: root-contents fetch shared by Axes 6 and 7 — never fetch twice; releases fetch shared by Axis 2 and security signals
- **--limit caps and truncation detection**: all limits set to target+1 (e.g. `--limit 501` for open issues targeting 500); if response length == limit, truncation occurred — mark axis partial and note "data truncated at N — large repo; run with `--paginate` for full data"
- **Duplicate clustering**: flag DUPLICATE only when root = same problem (identical error/feature ask/root cause); flag RELATED when same component, distinct problems — do not conflate
- **Discussions API**: GraphQL `discussions(first:100)` sufficient for health snapshot; full pagination not needed
- **Stats 202 retry**: contributor stats endpoint returns 202 (computing) on first call for large repos — retry up to 6× with 10s sleep (60s total); if still 202 after all retries: attempt commit-author fallback (Axis 3); mark ⚪ only if fallback also fails — see Axis 3 scoring
- **403 on security APIs**: Dependabot and secret scanning require push access; 403 = expected for public repos without push access — Axis 8 uses partial scoring from secondary signals (dep-config, dep-update commits, SECURITY.md depth); confidence 0.4; never ⚪ solely from Dependabot 403
- **Axis 3 fallback**: when contributor stats return 202 after retries, fall back to commit-authorship bus factor approximation from already-fetched commits; mark confidence 0.5 — not ⚪
- **Axis 1 response time**: responses by the issue/PR author themselves do not count — only first non-author comment/review contributes to response time computation
- **Code-review coverage (Axis 4)**: bot-submitted PRs (Dependabot, Renovate) are excluded from both numerator and denominator — bot PRs cannot be "reviewed" in the human sense and would distort the coverage rate
- **Star velocity**: advisory only — excluded from numeric score; page loop stops at 180d boundary via `$CUTOFF_180D`; if coverage < 30 days of stars when loop ends, mark 8B ⚪; partial data (≥30d coverage but <180d) → note truncation and use available window for trend
- **Package registry 404**: skip sub-signal C silently — not all repos publish to PyPI/npm
- **Axis independence**: failure of one axis (API unavailable, access denied, computing) → ⚪ row in scorecard, continue with remaining axes; never block report on single axis failure
- **Codex independent review (Step 5)**: runs before adversarial review — codex assesses raw data independently, not the main report; produces parallel scorecard and divergence notes; aggregate health score = mean(main, codex); when CODEX_AVAILABLE=0, note "codex unavailable — single-pass analysis only" in report section.
- **Adversarial review is mandatory** — Step 6 always runs; `foundry:challenger` always spawned; `codex:codex-rescue` spawned when `CODEX_AVAILABLE=1`. No skip path exists.
- **codex availability check**: `find ~/.claude/plugins -name "codex-rescue.md" 2>/dev/null | grep -q .` — run before spawn; do not assume codex installed
- **Health Score footer row**: Score column shows weighted %; Weight column shows "100%"; Status/Key Signal/Risk left blank

</notes>

<calibration>

Validate scoring range and sensitivity across known archetypes. Run `/oss:analyse vitality` on each repo below; compare output Health Score % against expected range.

## Scenario Matrix

| Archetype | Scale | Expected Health Score | Key discriminator |
| --- | --- | --- | --- |
| Active, well-governed | Large (>50k stars) | 80–95% | Axes 1+2+7 all 🟢 |
| Active, well-governed | Mid (5k–50k stars) | 68–85% | Axes 1+2+4 all 🟢 |
| Active, solo maintainer | Small (<5k stars) | 42–65% | Axis 3 🔴 drags score |
| Archived / abandoned | Mid | 12–28% | Axes 1+2+4 all 🔴 |
| Never-governed, dead | Small | 2–12% | Axes 1+2+3+7 all 🔴 |

## Concrete Test Repos

**Active & healthy — expect high scores:**
- `pytest-dev/pytest-mock` — small, active, good governance → expect **76–84%**
- `pallets/click` — mid, active, excellent docs+governance → expect **80–88%**
- `django/django` — large, extremely active, top-tier governance → expect **85–95%**

**Abandoned / archived — expect low scores:**
- `jpadilla/django-rest-framework-jwt` — archived May 2020, mid (3.2k stars) → expect **12–22%**
- `mozilla/bleach` — deprecated 2023-01-23 (self-declared; NOT GitHub-archived — still read-write), mid (2.8k stars), good historical governance → expect **26–40%**
- `jakevdp/JSAnimation` — abandoned ~2017 (functionality merged into matplotlib 2.1), small (240 stars), minimal governance → expect **2–12%**

## Per-Repo Expected Axis Status

| Repo | A1 Resp | A2 Maint | A3 Contrib | A4 Issue/PR | A5 CI/CD | A6 Docs | A7 Gov | A8 Sec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pytest-mock | 🟢 | 🟢 | 🟡 | 🟢/🟡* | 🟢 | 🟢 | 🟢 | 🟡† |
| click | 🟢 | 🟢 | 🟡 | 🟢 | 🟢 | 🟢 | 🟢 | 🟡† |
| django | 🟢 | 🟢 | 🟢/⚪‡ | 🟢 | 🟢 | 🟢 | 🟢 | 🟡† |
| jwt | 🔴 | 🔴 | 🟡 | 🔴 | 🔴 | 🟡 | 🟡 | 🟡† |
| bleach | 🔴 | 🔴 | 🟡 | 🔴 | 🟡 | 🟢 | 🟢 | 🟡† |
| JSAnimation | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴 | 🔴† |

`*` review coverage volatile when <5 merged PRs in window
`†` Dependabot 403 in calibration runs (no push access) — partial scoring from secondary signals; confidence 0.4
`‡` large repo — stats 202 likely; fallback to commit-author bus factor (confidence 0.5)

## Pass Criteria

- Active repos: Health Score ≥65%
- Abandoned repos: Health Score ≤40%
- **Axis 2 must be 🔴 for all abandoned repos** — hard requirement; any 🟢/🟡 on jwt/bleach/JSAnimation = B1 scoring bug (commits/30d = 0 must always → 🔴 regardless of release)
- **Axis 1 must be 🔴 for all abandoned repos** — no maintainer responses expected; pct_unresponded should be >60%
- **Axis 8 never 🟢 in calibration runs** — Dependabot 403 always expected; 🟢 = bug
- Size neutrality: score must not systematically bias by repo size — run small vs large active repos; difference must be ≤15% for same governance quality
- Axis 3 fallback: when contributor stats 202 → report must show "⚠ bus factor estimated from commit authors" footnote; verify for django
- Determinism: re-run same repo twice same UTC day → Health Score % identical (0% drift); any diff = reproducibility bug
- Coverage gate: run a scenario where ≥4 axes return 403/202 → verify score shows `⚠ provisional` flag
- Review coverage: test a solo-maintainer repo with known self-merge pattern → review_coverage <50% → Axis 4 🔴
- pytest-mock Axis 4 caveat: review coverage volatile with <5 merged PRs — validate across ≥3 months before treating as definitive

## Failure Modes to Watch

- **B1 false positive**: repo with old release but zero commits in 90d → Axis 2 must score 🔴; any 🟡 = bug
- **Responsiveness with no issues**: new repo with 0 open issues — Axis 1 confidence degraded; score based on PR response only; note "Axis 1 low sample — <5 issues sampled" in Gaps section
- **Bot-only PRs**: repos where all recent merged PRs are Dependabot/Renovate → review coverage undefined (all filtered); note "review coverage: bot PRs excluded, insufficient human PR sample" in Key Signal
- **Discussions-only support**: maintainer routes support to Discussions → Axis 4 issue close rate may appear artificially low; note discussion volume in Key Signal when discussions count > open issues count
- **No CI at all** (legacy or non-code repos): Axis 5 🔴 expected for all abandoned repos and some small projects; not a bug
- bleach: deprecated but NOT GitHub-archived — API endpoints still active; Axis 2 must still be 🔴 (no new commits since deprecation); Axes 6 and 7 may be 🟢 (governance files intact from pre-deprecation era — this is correct, not a bug)
- JSAnimation: 240 stars — Axis 1 confidence likely low (<5 issues); score may be ⚪ or based on PR sample only; acceptable
- Large repos: contributor stats 202 → Axis 3 fallback to commit-author bus factor (confidence 0.5); terminal must show ⚠ footnote
- Repos with no releases: Axis 2 release cadence unavailable; must not penalise — cadence is optional sub-signal
- Monorepos: root-contents check may miss docs/ inside subdirs — known limitation; note if detected
- Axis 7 checkpoint 7 requires both CODEOWNERS and Axis 3 stats; repos with only @org/team entries in CODEOWNERS (no individual @username) skip checkpoint 7 — expected behaviour

</calibration>
