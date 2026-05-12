# Vitality Scoring Rubrics

Reference rubrics for oss:repo-warden (axis scoring and confidence assessment). Read by each of the 3 parallel scorer instances in oss:analyse vitality Step 2.
Variables `$GH_OWNER`, `$GH_REPO`, and fetched data are sourced from DATA_FILE (written by oss:gh-scraper).

## Axes

### Axis 1 — Responsiveness

(CHAOSS #1 metric — most predictive of project attractiveness to contributors)

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

### Axis 2 — Maintenance Activity

(velocity + cadence; most important single axis)
- Days since last commit; commits in last 30d and 90d
- Days since last release (if releases exist); release cadence = avg days between last 5 releases
- **Score** (B1 fix — no "stable/maintenance mode" false-positive loophole):
  - 🟢: last commit <14d AND commits/30d ≥5
  - 🟡: last commit 14–60d OR commits/30d 1–4 OR (last commit >60d AND commits/90d ≥3 AND last release <180d — genuine maintenance backports)
  - 🔴: last commit >60d AND commits/30d = 0 — regardless of release recency. Zero commits = 🔴. A release ≤180d ago only upgrades to 🟡 when commits/90d ≥3 proves ongoing work.
  - ALSO 🔴: commits/30d = 0 for >90d (no commits for an entire quarter)

---

### Axis 3 — Contributor Health

(individual concentration + community sustainability)

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

### Axis 4 — Issue & PR Health

(queue hygiene + code review quality; merged from old Axes 1+2)

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

### Axis 5 — CI/CD & Code Quality

(absent entirely from prior design; repohealth scores CI/CD 35/100)

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

### Axis 6 — Documentation

(content quality, not just presence; 9 checkpoints)

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

### Axis 7 — Governance

(7 checkpoints; weight increased above Documentation per H1 fix)

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

### Axis 8 — Security Posture

(weight reduced; partial scoring on 403 instead of excluding)

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

### Axis 9 — Trajectory

(momentum direction: is the project accelerating or decelerating?)

Four sub-signals, each scored 0–10; overall axis score = mean of available sub-signals.
Requires: merged PRs last 90d (Group 1 new fetch), last 50 commits (Group 1 new fetch),
open issues (reused from Axis 4), contributor stats weeks[] (reused from Axis 3).

**Sub-signal 9A — Reviewer pool drift** (uses Axis 3 contributor stats weeks[])

Computation:
- If stats 202 after all retries AND fallback used: pool_drift = undefined (sub-signal 9A unavailable)
- window_recent = weeks[-26:] (last ~6 months); window_prior = weeks[-52:-26] (months 7–12)
- Filter bots: exclude logins matching `*[bot]` or `*-bot` suffix
- pool_recent = set of logins with sum(window_recent.c) >= 1
- pool_prior  = set of logins with sum(window_prior.c) >= 1
- If len(pool_prior) == 0: sub-signal 9A = ⚪ (no baseline — repo too young or stats sparse)
- shrinkage_ratio = (len(pool_prior) - len(pool_recent)) / len(pool_prior)
  - positive = shrinking; negative = growing
- departed = pool_prior - pool_recent; arrived = pool_recent - pool_prior

Score 9A:
- 🟢 (10): shrinkage_ratio ≤ 0 (pool stable or growing)
- 🟡 (5):  0 < shrinkage_ratio ≤ 0.30 (up to 30% shrinkage)
- 🔴 (0):  shrinkage_ratio > 0.30 OR len(pool_recent) == 0 (zero active mergers last 6m)

**Sub-signal 9B — Time-to-merge trend** (uses merged PRs last 90d fetch)

Computation:
- Filter bot PRs (author login matching `*[bot]` or `*-bot` suffix)
- For each merged PR: merge_days = (mergedAt - createdAt) in fractional days
- window_30d = PRs where mergedAt >= CUTOFF_30D (last 30 days)
- window_90d = all PRs in the 90d fetch (full 90-day window)
- median_30d = median(merge_days for PRs in window_30d)
- median_90d = median(merge_days for all PRs in window_90d)
- If len(window_30d) == 0: signal = "no_merges_30d" → 🔴
- If len(window_90d) < 5: trend unstable (confidence degrader -0.2 applies); compute anyway
- trend_ratio = median_30d / median_90d  (> 1 = worsening; < 1 = improving)

Score 9B:
- 🟢 (10): len(window_30d) >= 1 AND trend_ratio <= 1.0 (improving or stable)
- 🟡 (5):  1.0 < trend_ratio <= 2.0 (up to 2× worse)
- 🔴 (0):  trend_ratio > 2.0 OR len(window_30d) == 0 (no merges last 30d)

**Sub-signal 9C — Queue staleness depth** (uses open issues list from Axis 4)

Computation:
- Use open issues list already fetched (--limit 501 with truncation detection)
- For each open issue: age_days = (ANALYSIS_NOW - createdAt) / 86400
- Sort ages ascending; P90 = value at 90th percentile position
  - p90_index = int(len(ages) * 0.90); p90_age_days = sorted_ages[p90_index]
- If len(open_issues) == 0: sub-signal 9C = ⚪ (no open issues — repo uses discussions or closed everything)
- If open issue list truncated (501 returned): note "P90 computed over 500-issue sample — actual P90 may be higher"; confidence -0.1

Score 9C:
- 🟢 (10): p90_age_days < 30
- 🟡 (5):  30 <= p90_age_days <= 180
- 🔴 (0):  p90_age_days > 180

**Sub-signal 9D — Commit substance ratio** (uses last 50 commits fetch)

Computation:
- Pattern (case-insensitive, anchored at message start):
  `^(bump|chore\(deps\)|build\(deps\)|dependabot|renovate|update deps|upgrade deps)`
- dep_bump_count = count of commits where message matches pattern
- total_count = len(commits fetched)
- dep_ratio = dep_bump_count / total_count
- If total_count < 10: sub-signal 9D confidence degraded -0.1; compute anyway
- If total_count == 0: sub-signal 9D = ⚪ (no commits — unlikely but guarded)

Score 9D:
- 🟢 (10): dep_ratio < 0.20 (< 20% dep-bumps — meaningful work dominates)
- 🟡 (5):  0.20 <= dep_ratio <= 0.50 (20–50% dep-bumps)
- 🔴 (0):  dep_ratio > 0.50 (> 50% dep-bumps — output is maintenance-only)

**Axis 9 overall score:**
- available_subs = sub-signals not marked ⚪
- If len(available_subs) == 0: Axis 9 = ⚪ (all sub-signals unavailable)
- AXIS9_SCORE = mean(score for sub in available_subs)  — 0–10 float
- Status: 🟢 if AXIS9_SCORE >= 7.5 | 🟡 if AXIS9_SCORE >= 3.75 | 🔴 if AXIS9_SCORE < 3.75

**Axis 9 confidence:**
- Base: 1.0
- -0.2 if len(window_90d) < 5 (time-to-merge trend unstable — too few merged PRs in window)
- -0.2 if stats returned 202 after all retries (reviewer pool unknown — sub-signal 9A unavailable)
- -0.1 if total commit count < 10 (substance ratio from sparse sample)
- -0.1 if open issue list truncated (P90 computed over partial set)
- Floor: 0.3

## Weights

| Axis | Weight |
| --- | --- |
| 1 Responsiveness | 0.17 |
| 2 Maintenance activity | 0.18 |
| 3 Contributor health | 0.14 |
| 4 Issue & PR health | 0.11 |
| 5 CI/CD & code quality | 0.09 |
| 6 Documentation | 0.07 |
| 7 Governance | 0.09 |
| 8 Security posture | 0.07 |
| 9 Trajectory | 0.08 |

## Per-Axis Confidence Thresholds

| Axis | Weight | Base | Key degraders | Floor |
| --- | --- | --- | --- | --- |
| 1 Responsiveness | 0.17 | 1.0 | -0.2 if <5 issues sampled; -0.2 if <5 PRs sampled; -0.3 if GraphQL 403 | 0.3 |
| 2 Maintenance activity | 0.18 | 1.0 | -0.3 commits API 403/empty; -0.15 100-commit truncation in window; -0.1 no releases | 0.2 |
| 3 Contributor health | 0.14 | 1.0 | fallback mode → 0.5; -0.3 if stats 403; -0.1 <3 contributors; -0.1 all 90d weeks zero | 0.0/0.4/0.5 |
| 4 Issue & PR health | 0.11 | 1.0 | -0.2 open issue list truncated (501 returned); -0.2 open PR list truncated; -0.15 <3 merged PRs (review coverage unstable); -0.1 GraphQL review query failed | 0.3 |
| 5 CI/CD & code quality | 0.09 | 1.0 | -0.3 actions/workflows 403; -0.2 workflow content unreadable (checkpoints 2–4 unknown); -0.1 <10 recent runs (pass rate unstable); -0.1 run list truncated (21 returned) | 0.4 |
| 6 Documentation | 0.07 | 1.0 | -0.1 README 404; -0.2 README API error; -0.05 per checkpoint with API failure; -0.1 CONTRIBUTING content fetch failed (checkpoints 7–9 indeterminate) | 0.5 |
| 7 Governance | 0.09 | 1.0 | -0.1 .github/ 403; -0.1 branch protection 403; -0.05 root contents 403; -0.1 Axis 3 ⚪ and CODEOWNERS has @usernames (checkpoint 7 uncomputable) | 0.6 |
| 8 Security posture | 0.07 | 1.0 | -0.6 Dependabot 403 → confidence 0.4 (partial scoring mode); -0.2 secret scanning 403; -0.15 alert list at 100-item limit | 0.2 |
| 9 Trajectory | 0.08 | 1.0 | -0.2 if <5 merged PRs in 90d window (TTM trend unstable); -0.2 if stats 202 (reviewer pool unknown); -0.1 if <10 commits sampled; -0.1 if open issues truncated | 0.3 |
