<!-- file: vitality-scoring-group-c.md — consumers: oss/agents/repo-warden.md -->

# Vitality Scoring Rubrics — Group C

> Axes 3, 9 — scored by oss:repo-warden AXIS_GROUP=C (Axis 3 scored first, feeds Axis 9A)
> Split from `vitality-scoring.md` (see that file for Weights & Confidence Thresholds table, Advisory Signals, Implementation Status).

## Axes

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

Stats 202 after all retries WITH successful fallback: ⚪ NOT used; fallback score at confidence 0.5.

---

### Axis 9 — Trajectory

(momentum direction: accelerating or decelerating?)

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
- Per merged PR: merge_days = (mergedAt - createdAt) in fractional days
- window_30d = PRs where mergedAt >= CUTOFF_30D (last 30 days)
- window_90d = all PRs in 90d fetch (full 90-day window)
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
- Per open issue: age_days = (ANALYSIS_NOW - createdAt) / 86400
- Sort ages ascending; P90 = value at 90th percentile position
  - p90_index = int(len(ages) * 0.90); p90_age_days = sorted_ages[p90_index]
- If len(open_issues) == 0: sub-signal 9C = ⚪ (no open issues — repo uses discussions or closed everything)
- If open issue list truncated (501 returned): note "P90 computed over 500-issue sample — actual P90 may be higher"; confidence -0.1

Score 9C:
- 🟢 (10): p90_age_days < 30
- 🟡 (5):  30 <= p90_age_days <= 180
- 🔴 (0):  p90_age_days > 180

**Sub-signal 9D — Commit automation ratio** (uses last 50 commits fetch)

Rationale: dep-bump merges by human maintainers = legitimate maintenance work; only fully bot-authored commits indicate zero human engagement

Computation:
- automated_count = commits where BOTH conditions hold: (a) message matches dep-bump pattern (case-insensitive, anchored at start): `^(bump|chore\(deps\)|build\(deps\)|dependabot|renovate|update deps|upgrade deps)` AND (b) author login matches `*[bot]` or `*-bot` suffix
- total_count = len(commits fetched)
- auto_ratio = automated_count / total_count
- If total_count < 10: sub-signal 9D confidence degraded -0.1; compute anyway
- If total_count == 0: sub-signal 9D = ⚪ (no commits — unlikely but guarded)

Score 9D:
- 🟢 (10): auto_ratio < 0.50 (majority of recent commits are human-authored)
- 🟡 (5):  0.50 <= auto_ratio <= 0.90 (automated majority but human commits present)
- 🔴 (0):  auto_ratio > 0.90 (nearly all commits bot-authored — possible zombie-maintenance or fork-only repo)

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

---
