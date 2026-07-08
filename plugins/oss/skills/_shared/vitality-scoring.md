# Vitality Scoring Rubrics

Reference rubrics for oss:repo-warden (axis scoring + confidence). Split by axis group so each of 3 parallel scorer instances in oss:analyse vitality Step 2 reads only its assigned group — not the full rubric.
Variables `$GH_OWNER`, `$GH_REPO`, fetched data sourced from DATA_FILE (written by oss:gh-scraper).

## Axis Group Index

Per-axis rubric text lives in group files, split by oss:repo-warden `AXIS_GROUP` assignment:

| Group file | Axes | Consumer |
| --- | --- | --- |
| `vitality-scoring-group-a.md` | 1 Responsiveness, 2 Maintenance Activity, 5 CI/CD & Code Quality, 6 Documentation | oss:repo-warden AXIS_GROUP=A |
| `vitality-scoring-group-b.md` | 4 Issue & PR Health, 7 Governance, 8 Security Posture | oss:repo-warden AXIS_GROUP=B |
| `vitality-scoring-group-c.md` | 3 Contributor Health, 9 Trajectory | oss:repo-warden AXIS_GROUP=C |
| `vitality-scoring-group-unassigned.md` | 10 Supply-Chain Integrity, 11 Ecosystem Criticality & Reach, 12 Dependency Health (Libyears), 13 Interface Stability & Community Engagement | none yet — see Implementation Status below |

This index file keeps only cross-cutting content shared across all groups: the weight table (read by `assemble_vitality_scores.py`), advisory signals, and data-fetching implementation status.

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
