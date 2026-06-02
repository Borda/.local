# Vitality Scoring Rubrics

Reference rubrics for oss:repo-warden (axis scoring + confidence). Read by each of 3 parallel scorer instances in oss:analyse vitality Step 2.
Variables `$GH_OWNER`, `$GH_REPO`, fetched data sourced from DATA_FILE (written by oss:gh-scraper).

## Axes

### Axis 1 — Responsiveness

(CHAOSS #1 metric — most predictive of contributor attractiveness)

Data: GraphQL response from Group 1 (20 sampled issues + 20 sampled PRs).

Computation:
- Per issue: find first comment where `comment.author.login != issue.author.login`; `response_time = comment.createdAt − issue.createdAt` (fractional days). Issues with 0 non-author comments = "unresponded".
- Per PR: find earliest of (first non-author review) or (first non-author comment); `response_time = event.createdAt − pr.createdAt`.
- `median_issue_response_days` = median of response_times for issues with responses
- `median_pr_response_days` = median of response_times for PRs with non-author events
- `pct_responded_7d` = (count issues with response_time ≤7d) / (count all sampled issues)
- `pct_unresponded` = count issues with 0 non-author comments / count all sampled

Score:
- 🟢: median_issue_response <7d AND median_pr_response <5d AND pct_responded_7d ≥60%
- 🟡: median_issue_response ≤21d OR pct_responded_7d ≥40% (some responsiveness)
- 🔴: median_issue_response >21d OR pct_responded_7d <40% OR pct_unresponded >60%
- ⚪: GraphQL 403 AND <5 issues to sample (cannot compute)

---

### Axis 2 — Maintenance Activity

(velocity + cadence; most important single axis)
- Days since last commit; commits in last 30d and 90d
- Days since last release (if releases exist); release cadence = avg days between last 5 releases
- **Score** (B1 fix — no "stable/maintenance mode" false-positive loophole):
  - 🟢: last commit <14d AND commits/30d ≥5
  - 🟡: last commit 14–60d OR commits/30d 1–4 OR (last commit >60d AND commits/90d ≥3 AND last release <180d — genuine maintenance backports)
  - 🔴: last commit >60d AND commits/30d = 0 — regardless of release recency. Zero commits = 🔴. Release ≤180d only upgrades to 🟡 when commits/90d ≥3 proves ongoing work.
  - ALSO 🔴: commits/30d = 0 for >90d (no commits entire quarter)
  - ⛔ OVERRIDE 🔴 (abandonment signal): if repository description OR README first 500 bytes contains any of `abandoned`, `no longer maintained`, `deprecated`, `end-of-life`, `unmaintained`, `not maintained` (case-insensitive) → score 🔴 regardless of commit activity. Maintainer has explicitly signaled discontinuation.

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

Stats 202 after all retries WITH successful fallback: ⚪ NOT used; fallback score at confidence 0.5.

---

### Axis 4 — Issue & PR Health

(queue hygiene + code review quality; merged from old Axes 1+2)

Issue signals (from open/closed issue lists):
- stale % = open issues with no update >90d / total open
- close rate = closed last 30d / opened last 30d (0 if denominator 0); if stale-bot config present (`.github/stale.yml` or `stale` in workflow names) AND close_rate ≥2.0, flag "⚠ potential stalebot inflation" in report — stalebot auto-closes inflate close_rate without resolution
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

(absent from prior design; repohealth scores CI/CD 35/100)

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

Note: CONTRIBUTING.md presence tracked in Axis 7 Governance — this axis scores content depth only.

9 checkpoints:
1. README present and >500 bytes
2. README has install section (grep: `install|pip install|npm install|cargo add|brew install`)
3. README has usage/quickstart section (grep: `usage|quickstart|getting started|example`)
4. CHANGELOG present (CHANGELOG.md, CHANGES.md, HISTORY.md, NEWS.md) AND most recent entry <365d old (date in first 10 lines of file, formats: YYYY-MM-DD, DD Month YYYY, Month YYYY)
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

Rationale: dep-bump merges by human maintainers = legitimate maintenance work; only fully bot-authored commits indicate zero human engagement.

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

### Axis 10 — Supply-Chain Integrity

(entirely absent from prior design; post-XZ-backdoor critical gap; OpenSSF Risk: High for all sub-checks)

**Data requirements** (new gh-scraper fetches needed — see Phase 2 note at file end):
- Full workflow YAML content for all `.github/workflows/*.yml` files (Axis 5 fetches presence only; Axis 10 needs full YAML text)
- Release assets list: `GET /repos/{owner}/{repo}/releases?per_page=10` → `assets[].name` per release
- Workflow run names already fetched (Axis 5) — reuse for checkpoint 5 grep

5 checkpoints:

1. **Action pin discipline** — `uses:` lines in all workflow YAMLs SHA-pinned (not `@v1`, `@main`, `@master`, `@latest`). Pattern: `uses:\s+\S+@[a-f0-9]{40}` = SHA-pinned. Pass: ≥80% of all `uses:` lines across all workflows are SHA-pinned. (Score: met / max)
2. **Least-privilege token permissions** — no workflow file contains `permissions: write-all`; all workflow files have an explicit top-level `permissions:` block (not absent). Pass: all workflow files satisfy both conditions. Note: `permissions: {}` (empty) is NOT a pass — empty block grants no permissions but is intentional only if job-level perms exist; score it as 🟡 case.
3. **Dangerous patterns absent** — no workflow step contains: (a) `pull_request_target` trigger combined with `ref: ${{ github.event.pull_request.head.ref }}` or equivalent head-ref checkout; (b) `curl | bash`, `curl | sh`, `wget | sh`, `wget | bash` in `run:` steps. Pass: none of these patterns detected in any workflow file.
4. **Signed releases** — last 5 releases (or all releases if <5 exist) have at least one of: release asset matching `*.sig`, `*.asc`, `*.minisig`, `*.sigstore`, `*.bundle`; OR workflow step contains `sigstore/cosign-installer`, `actions/attest-build-provenance`, `slsa-framework/slsa-github-generator`. Pass: ≥60% of sampled releases satisfy at least one condition.
5. **SBOM published** — any release asset matches `*.sbom.json`, `sbom.spdx`, `*.cdx.json`, `*.spdx.json`; OR workflow step contains `anchore/sbom-action`, `microsoft/sbom-tool`, `CycloneDX`. Pass: SBOM generation step found in any workflow OR SBOM asset in last release.

Score: `floor(checkpoints_met / 5 × 10)`; 🟢 ≥4/5 | 🟡 2–3/5 | 🔴 ≤1/5

**403 / access failure handling**:
- Workflow content fetch 403 or decode error → checkpoints 1, 2, 3 = ✗; confidence -0.3
- Releases 403 or 0 releases → checkpoints 4, 5 = ✗; confidence -0.2
- GitHub Actions not used (no `.github/workflows/`) → checkpoints 1–3 = ✗ (no actions to pin); note in report; confidence unchanged

**Axis 10 confidence:**
- Base: 1.0
- -0.3 if workflow content unreadable (checkpoints 1–3 indeterminate)
- -0.2 if releases API 403 or <2 releases (checkpoints 4–5 unreliable sample)
- -0.1 if <3 releases sampled (signed-releases pass-rate unstable)
- Floor: 0.3

---

### Axis 11 — Ecosystem Criticality & Reach

(signals how embedded this project is in the dependency graph; changes interpretation of other axis scores — a 🟡-health package with 100k dependents deserves different urgency than a 🟡 hobby project)

**Data requirements** (new gh-scraper fetches needed — see Phase 2 note):
- GitHub dependency network: `GET https://github.com/{owner}/{repo}/network/dependents` HTML parse → dependent repository count (no official API; use Accept: `application/json` undocumented endpoint OR deps.dev REST: `GET https://api.deps.dev/v3alpha/systems/{system}/packages/{name}/dependents` if package known)
- Package registry presence: root-contents already fetched — detect `package.json`, `pyproject.toml`/`setup.py`, `Cargo.toml`, `go.mod`; then query registry for weekly downloads: PyPI `https://pypistats.org/api/packages/{name}/recent?period=week`, npm `https://api.npmjs.org/downloads/point/last-week/{name}`
- Stars and forks already in repo metadata (Group 1 fetch)

Computation:
- `dependent_repos` = parsed dependent repository count (⚪ if API unavailable after 2 retries)
- `registered_package` = True if package found on any of: PyPI, npm, crates.io, pkg.go.dev
- `weekly_downloads` = weekly download count from registry (⚪ if registry does not expose downloads API)
- Stars and forks from repo metadata

Score — **impact tier** (not a health failure; 🔴 = low-impact, not broken):
- 🟢: `dependent_repos ≥ 100` OR (`registered_package` AND `weekly_downloads ≥ 10 000`) OR (`stars ≥ 1 000` AND `registered_package`)
- 🟡: `dependent_repos 10–99` OR (`registered_package` AND `weekly_downloads 1 000–9 999`) OR `stars 100–999`
- 🔴: `dependent_repos < 10` AND NOT(`registered_package` AND `weekly_downloads ≥ 1 000`) — niche or personal project
- ⚪: neither dependents API nor registry available (cannot compute; axis excluded from weighted score)

**Report framing**: always surface as "Ecosystem impact: low / moderate / high" alongside emoji — never phrase 🔴 here as a health failure. Annotate: "🔴 = low downstream impact, not a quality signal."

**Axis 11 confidence:**
- Base: 1.0
- -0.4 if dependent_repos = ⚪ AND weekly_downloads = ⚪ (score derived only from stars/registry presence — very indirect)
- -0.2 if dependent count API returned inconsistent pagination (partial count)
- -0.1 if only one registry checked (monolingual; other ecosystems unchecked)
- Floor: 0.3

---

### Axis 12 — Dependency Health (Libyears)

(current design only checks "Dependabot config present" — no actual dep freshness signal; leading indicator where Axis 8 Dependabot alerts are lagging)

**Data requirements** (new gh-scraper fetches needed — see Phase 2 note):
- Package manifest files via GitHub contents API: `requirements.txt`, `pyproject.toml`, `setup.cfg`, `setup.py`, `package.json`, `package-lock.json`, `Cargo.toml`, `Cargo.lock`, `go.mod`, `go.sum`; parse pinned version per dep
- Per-dependency latest release date from registry:
  - PyPI: `GET https://pypi.org/pypi/{name}/json` → `releases.{v}.upload_time` for pinned version; `info.version` for latest
  - npm: `GET https://registry.npmjs.org/{name}/{pinned_version}` → `_time`; `GET https://registry.npmjs.org/{name}/latest` → `version`
  - crates.io: `GET https://crates.io/api/v1/crates/{name}/versions` → `created_at` per version
  - Go: `GET https://proxy.golang.org/{module}/@v/{version}.info` → `Time`
- Lock file presence: `poetry.lock`, `package-lock.json`, `yarn.lock`, `Cargo.lock`, `go.sum`, `uv.lock`, `pdm.lock`

Computation:
- For each direct dependency `d` with pinned version `v_pinned`:
  - `release_date_pinned` = upload date of `v_pinned` from registry
  - `release_date_latest` = upload date of current latest stable version
  - `libyears_d` = (`release_date_latest` − `release_date_pinned`) / 365.25
- `median_libyears` = median across all successfully resolved deps
- `max_libyears` = max (sentinel for severely outdated single dep)
- `outdated_ratio` = count(deps where `libyears_d > 0.5`) / total_resolved_deps (>0.5 = more than 6 months behind)
- `lock_file_present` = True if any lock file found in root-contents
- Skip: dev-only deps (`*-dev`, test extras) unless no production deps found

Score:
- 🟢: `median_libyears < 0.5` AND `outdated_ratio < 25%` AND `lock_file_present`
- 🟡: `median_libyears 0.5–2.0` OR `outdated_ratio 25–60%` OR `not lock_file_present`
- 🔴: `median_libyears > 2.0` OR `outdated_ratio > 60%` OR `max_libyears > 5` (critical dep severely outdated)
- ⚪: no package manifest found in root; OR ecosystem not PyPI/npm/crates.io/Go (no Libyears API available); OR <3 deps resolved (sample too small for median)

**Axis 12 confidence:**
- Base: 1.0
- -0.2 if <5 deps resolved (small sample; median unstable)
- -0.2 if ≥1 registry API returned 429/503 (partial data; some deps unresolved)
- -0.3 if transitive deps not included (direct-only; total Libyears may be underestimated)
- -0.1 if lock file absent (pinned versions from manifest may differ from installed)
- Floor: 0.3

---

### Axis 13 — Interface Stability & Community Engagement

(two grouped signal sets, each scored 0–5; axis score = sum 0–10; split enables separate reporting of stability vs community health while keeping combined weight light)

#### Group A — Interface Stability (scored 0–5)

**Data requirements** — reuses existing fetches:
- Last 50 commits (commit messages) — already in Group 1 data
- Releases list with body text — already in Group 1 data (last 10 releases)
- CHANGELOG file content — already fetched for Axis 6 checkpoint 4

Computation:
- `breaking_commits_365d` = count of commits in last 365d where message contains `BREAKING CHANGE:` or `!:` (conventional commits breaking indicator), or subject line contains `[breaking]` (case-insensitive)
- `major_bumps_365d` = count of releases in last 365d where version tag is `vN.0.0` with N > prior major (or `N.0.0` without v prefix)
- `semver_compliant` = True if every BREAKING CHANGE commit has a corresponding major version bump within 60 days (True also if `breaking_commits_365d = 0` — no breaking changes = compliant by definition)
- `deprecation_pattern` = True if: CHANGELOG or release notes contain both a "deprecated" entry AND a "removed"/"breaking" entry for at least one feature AND the "deprecated" entry appears in an earlier release than the "removed" entry (minimum 1 release gap)
- `migration_guide_ratio` = count(major releases with "migration" OR "upgrade guide" OR "upgrade from" in release body) / max(major_bumps_365d, 1)

Score A (0–5):
- 5: `semver_compliant` AND (`deprecation_pattern` OR `breaking_commits_365d = 0`) AND (`migration_guide_ratio ≥ 0.80` OR `major_bumps_365d = 0`)
- 4: `semver_compliant` AND `migration_guide_ratio ≥ 0.50`
- 3: `semver_compliant` but missing deprecation warnings or migration guides
- 2: `NOT semver_compliant` but `migration_guide_ratio ≥ 0.50` (communicated but process incomplete)
- 1: `breaking_commits_365d > 6` without `deprecation_pattern` or `migration_guide_ratio < 0.25`
- 0: BREAKING CHANGE commits with no corresponding major version bump AND no migration guidance in any affected release
- ⚪ (exclude from sum, reduce max to 5): no releases exist — cannot assess SemVer compliance

**Note**: high `breaking_commits_365d` is NOT automatically penalized — a project in active API evolution with SemVer compliance + migration guides may score 5 regardless. The axis rewards process, not stagnation.

#### Group B — Community Engagement (scored 0–5)

**Data requirements** — mostly reuses existing fetches:
- Contributor stats weeks[] (already in Group 1 data, reused from Axis 3)
- Merged PR author logins (already in Group 1 data, reused from Axis 4)
- New fetch: GitHub Discussions count (GraphQL `repository.discussions(first:1) { totalCount }` — lightweight single-field query)

Computation:
- `top5_authors` = set of top-5 all-time commit authors by commit count (from contributor stats)
- `external_pr_ratio` = count(merged PRs last 90d where author NOT in `top5_authors`) / total merged non-bot PRs last 90d
- `new_contributors_90d` = distinct contributor logins active in stats weeks[-13:] but NOT active in stats weeks[-26:-13] (new faces in last 90d vs prior 90d)
- `active_contributors_90d` = distinct contributors with ≥1 commit in stats weeks[-13:]
- `contributor_acquisition_rate` = new_contributors_90d / max(active_contributors_90d, 1)
- `discussion_count_90d` = GitHub Discussions opened in last 90d (from new GraphQL query; ⚪ if repo has Discussions disabled)

Score B (0–5):
- 5: `external_pr_ratio ≥ 0.40` AND `new_contributors_90d ≥ 3` AND `contributor_acquisition_rate ≥ 0.20`
- 4: `external_pr_ratio ≥ 0.25` AND `new_contributors_90d ≥ 1`
- 3: `external_pr_ratio ≥ 0.10` OR `new_contributors_90d ≥ 1`
- 2: external_pr_ratio < 0.10 but `discussion_count_90d ≥ 5` (community engages via discussions, not PRs)
- 1: zero external contribution but ≥1 issue from non-contributor in last 90d
- 0: all contributions single person, zero external engagement of any kind
- ⚪ (exclude from sum, reduce max to 5): repo <6 months old (too early to assess community formation) OR contributor stats API 202 with no fallback

**Axis 13 overall score** = Score_A + Score_B (0–10)
- 🟢: ≥7
- 🟡: 4–6
- 🔴: ≤3
- ⚪: BOTH groups ⚪ simultaneously (new repo with no releases and no activity data)

When one group is ⚪: score = remaining group score × 2 (normalize to 0–10); reduce confidence -0.3; note in report which group was unavailable.

**Axis 13 confidence:**
- Base: 1.0
- -0.3 if Group A ⚪ (no releases — interface stability not assessable)
- -0.3 if Group B ⚪ (repo too young — community engagement not assessable)
- -0.2 if contributor stats 202 with fallback used (acquisition rate approximate)
- -0.1 if Discussions API unavailable or disabled (discussion_count_90d unknown)
- -0.1 if <5 merged PRs in 90d (external_pr_ratio sample unstable)
- Floor: 0.3

---

## Weights & Confidence Thresholds

| Axis | Weight | Conf base | Key confidence degraders | Conf floor |
| --- | --- | --- | --- | --- |
| 1 Responsiveness | 0.10 | 1.0 | -0.2 if <5 issues sampled; -0.2 if <5 PRs sampled; -0.3 if GraphQL 403 | 0.3 |
| 2 Maintenance activity | 0.08 | 1.0 | -0.3 commits API 403/empty; -0.15 100-commit truncation in window; -0.1 no releases | 0.2 |
| 3 Contributor health | 0.10 | 1.0 | fallback mode → 0.5; -0.3 if stats 403; -0.1 <3 contributors; -0.1 all 90d weeks zero | 0.0/0.4/0.5 |
| 4 Issue & PR health | 0.07 | 1.0 | -0.2 open issue list truncated (501 returned); -0.2 open PR list truncated; -0.15 <3 merged PRs (review coverage unstable); -0.1 GraphQL review query failed | 0.3 |
| 5 CI/CD & code quality | 0.07 | 1.0 | -0.3 actions/workflows 403; -0.2 workflow content unreadable (checkpoints 2–4 unknown); -0.1 <10 recent runs (pass rate unstable); -0.1 run list truncated (21 returned) | 0.4 |
| 6 Documentation | 0.05 | 1.0 | -0.1 README 404; -0.2 README API error; -0.05 per checkpoint with API failure; -0.1 CONTRIBUTING content fetch failed (checkpoints 7–9 indeterminate) | 0.5 |
| 7 Governance | 0.06 | 1.0 | -0.1 .github/ 403; -0.1 branch protection 403; -0.05 root contents 403; -0.1 Axis 3 ⚪ and CODEOWNERS has @usernames (checkpoint 7 uncomputable) | 0.6 |
| 8 Security posture | 0.11 | 1.0 | -0.6 Dependabot 403 → confidence 0.4 (partial scoring mode); -0.2 secret scanning 403; -0.15 alert list at 100-item limit | 0.2 |
| 9 Trajectory | 0.07 | 1.0 | -0.2 if <5 merged PRs in 90d window (TTM trend unstable); -0.2 if stats 202 (reviewer pool unknown); -0.1 if <10 commits sampled; -0.1 if open issues truncated | 0.3 |
| 10 Supply-chain integrity | 0.10 | 1.0 | -0.3 workflow content unreadable (checkpoints 1–3 indeterminate); -0.2 releases 403 or <2 releases (checkpoints 4–5 unreliable); -0.1 <3 releases sampled | 0.3 |
| 11 Ecosystem criticality | 0.06 | 1.0 | -0.4 dependents API unavailable AND downloads unavailable (score from stars/registry only); -0.2 dependent count pagination partial; -0.1 only one registry checked | 0.3 |
| 12 Dependency health | 0.08 | 1.0 | -0.2 if <5 deps resolved; -0.2 if ≥1 registry API 429/503 (partial data); -0.3 transitive deps absent; -0.1 lock file absent | 0.3 |
| 13 Interface stability & community | 0.05 | 1.0 | -0.3 Group A ⚪ (no releases); -0.3 Group B ⚪ (repo <6 months old); -0.2 contributor stats 202 with fallback; -0.1 Discussions API unavailable; -0.1 <5 merged PRs in 90d | 0.3 |

## Advisory Signals (non-scoring)

These signals appear in report annotations but do not affect numeric axis scores:

- **Version stability flag**: if latest release tag matches `^0\.` or contains `alpha`/`beta`/`rc` (case-insensitive) → append `⚠ pre-release stability` flag to report header. Pre-release APIs may break without SemVer guarantee.
- **Stalebot inflation warning**: see Axis 4 close rate definition. Surfaced as report annotation, not score degrader.

## Implementation Status — Data Fetching Requirements

Axes 1–9 and 13 Group A use data already fetched by `oss:gh-scraper`. Axes 10–13 require new gh-scraper fetch groups. Until implemented, these axes score ⚪ and are excluded from weighted Health Score.

### gh-scraper changes required per axis

| Axis | New fetch(es) required | API / endpoint |
| --- | --- | --- |
| 10 Supply-chain integrity | Full workflow YAML content (not just list); release assets list | `GET /repos/{o}/{r}/contents/.github/workflows/{file}` per file; `GET /repos/{o}/{r}/releases?per_page=10` → `assets[].name` |
| 11 Ecosystem criticality | Dependent repo count; package registry weekly downloads | `GET https://github.com/{o}/{r}/network/dependents` HTML parse; PyPI `pypistats.org/api/packages/{n}/recent`; npm `api.npmjs.org/downloads/point/last-week/{n}` |
| 12 Dependency health | Package manifest files content; per-dep version dates from registry | `GET /repos/{o}/{r}/contents/{manifest_file}` for each manifest; PyPI `pypi.org/pypi/{n}/json`; npm `registry.npmjs.org/{n}/{v}`; crates.io `crates.io/api/v1/crates/{n}/versions` |
| 13 Group B community | GitHub Discussions count (single GraphQL field) | `graphql: repository { discussions(first:1) { totalCount } }` |

### Remaining Phase 2 signals (not yet assigned to an axis)

| Signal | Priority | Rationale |
| --- | --- | --- |
| OSV/CVE direct query (Axis 8 supplement) | Critical | Dependabot 403 common; OSV.dev `api.osv.dev/v1/query` fully public; supplements partial scoring in Axis 8 |
| Organizational diversity / Elephant Factor (Axis 3 supplement) | High | CNCF graduation requirement; single-org repos fail sustainable ownership; requires `GET /users/{login}` for top contributors → `company` field |
| Fuzzing enrollment (Axis 5 supplement) | Medium | OpenSSF Scorecard Fuzzing check; high value for parser/codec/network repos; OSS-Fuzz membership list publicly queryable |
| SLSA build level (Axis 10 supplement) | Medium | Build provenance level L1–L3; data already partially in Axis 10 checkpoint 4 (signed-releases) — needs SLSA-specific parsing |
