---
name: gh-scraper
description: "Fetches all GitHub API data for a repo (REST + GraphQL) in two parallel groups; writes raw JSONL data file for consumption by oss:repo-warden axis scorers. TRIGGER when: spawned by /oss:analyse (vitality mode) to fetch raw GitHub data. NOT for axis scoring or report generation. NOT for direct user invocation."
tools: Write, Bash
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
# Compute cutoff dates using date (cross-platform: macOS BSD and GNU/Linux)
if date -v-1d +%Y-%m-%d 2>/dev/null | grep -q '^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$'; then
    # macOS BSD date (-v relative offset) — verify output shape, not just exit code
    CUTOFF_30D=$(date -u -v-30d +%Y-%m-%dT%H:%M:%SZ)    # timeout: 5000
    CUTOFF_90D=$(date -u -v-90d +%Y-%m-%dT%H:%M:%SZ)    # timeout: 5000
    CUTOFF_180D=$(date -u -v-180d +%Y-%m-%dT%H:%M:%SZ)  # timeout: 5000
    CUTOFF_3Y=$(date -u -v-1095d +%Y-%m-%d)              # timeout: 5000
else
    # GNU date (-d relative offset)
    CUTOFF_30D=$(date -u -d '30 days ago' +%Y-%m-%dT%H:%M:%SZ)    # timeout: 5000
    CUTOFF_90D=$(date -u -d '90 days ago' +%Y-%m-%dT%H:%M:%SZ)    # timeout: 5000
    CUTOFF_180D=$(date -u -d '180 days ago' +%Y-%m-%dT%H:%M:%SZ)  # timeout: 5000
    CUTOFF_3Y=$(date -u -d '1095 days ago' +%Y-%m-%d)             # timeout: 5000
fi

# Auth preflight — fail fast before any API calls
gh auth status 2>/dev/null || { echo "[gh-scraper] ERROR: not authenticated — run gh auth login"; exit 1; }  # timeout: 6000

# Rate-limit preflight — warn if too few calls remain for a full scrape (~80 API calls needed)
RATE_REMAINING=$(gh api rate_limit --jq '.resources.core.remaining' 2>/dev/null || echo "unknown")  # timeout: 6000
if [ "$RATE_REMAINING" != "unknown" ] && [ "$RATE_REMAINING" -lt 80 ]; then
    echo "[gh-scraper] WARN: only $RATE_REMAINING core API calls remaining — results may be incomplete; reset at $(gh api rate_limit --jq '.resources.core.reset' 2>/dev/null | xargs -I{} date -r {} 2>/dev/null || echo 'unknown time')"  # timeout: 6000
fi

echo "[gh-scraper] analysing $GH_OWNER/$GH_REPO"  # timeout: 5000
mkdir -p "$(dirname "$DATA_FILE")"  # timeout: 5000
# loads: oss-shared-resolver.md
# shared pattern — see plugins/oss/skills/_shared/oss-shared-resolver.md (intentional boilerplate; also used in repo-warden.md, shepherd.md)
_OSS_SHARED=$("${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve-shared-path.sh" oss skills/_shared 2>/dev/null)  # timeout: 5000
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
```

## Step 2 — Data Fetch Group 1 (all parallel)

Run all calls simultaneously — independent. Extracted to `bin/fetch_gh_data_group1.sh` (parallel `gh api` + `gh issue list` + `gh pr list` calls; one JSON file per dataset under `$GROUP1_DIR`). Pre-compute output dir tied to `$DATA_FILE` so Step 4 can read each file back:

```bash
GROUP1_DIR="$(dirname "$DATA_FILE")/group1"  # timeout: 5000
"${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/fetch_gh_data_group1.sh" \
    --repo "$GH_OWNER/$GH_REPO" \
    --output-dir "$GROUP1_DIR" \
    --cutoff-3y "$CUTOFF_3Y" \
    --cutoff-90d "$CUTOFF_90D" \
    --cutoff-180d "$CUTOFF_180D"  # timeout: 90000
```

The script handles truncation-detection limits (`--limit 501`/`1001`/`201`), 403 fallbacks for security APIs, and disabled-discussions error swallowing. Per-call failures emit `⚠` to stderr; the corresponding output file is left empty so Step 4 marks the dataset as unavailable instead of crashing. Retry of contributor stats 202s and pagination of forks/issues stays inline below — those need iterative LLM-driven state.

## Step 3 — Data Fetch Group 2 (depends on Group 1)

After Group 1 complete — root file list and default_branch now known. Run all calls below sequentially in one Bash call (Group 2 as a whole runs after Group 1 completes — the parallelism is Group 1 vs later calls, not within Group 2):

Read Group 1 outputs before the bash block:

```bash
# ROOT_FILES: JSON array of filenames in repo root, written by fetch_gh_data_group1.sh to $GROUP1_DIR/root_contents.json
ROOT_FILES=$(cat "${GROUP1_DIR}/root_contents.json" 2>/dev/null || echo "[]")  # timeout: 5000
DEFAULT_BRANCH=$(jq -r '.[]|select(.name=="default_branch")|.data' "${GROUP1_DIR}/repo_meta.json" 2>/dev/null || echo "main")  # timeout: 5000
```

```bash
# Axis 5: README content (decode base64; --ignore-garbage tolerates padded/partial base64 from API)
_README_RAW=$(gh api "repos/$GH_OWNER/$GH_REPO/readme" --jq '.content' 2>/dev/null)  # timeout: 10000
_README_DECODED=$(echo "$_README_RAW" | base64 -d --ignore-garbage 2>/dev/null || echo "$_README_RAW" | base64 -D 2>/dev/null)

# Axis 5 checkpoints 8–10: CONTRIBUTING.md content (only if checkpoint 5 ✓ — CONTRIBUTING.md in root file list)
if echo "$ROOT_FILES" | grep -q '"CONTRIBUTING.md"'; then  # M29: only fetch if present in root file list from Group 1
    _CONTRIB_RAW=$(gh api "repos/$GH_OWNER/$GH_REPO/contents/CONTRIBUTING.md" --jq '.content' 2>/dev/null)  # timeout: 10000
    _CONTRIB_DECODED=$(echo "$_CONTRIB_RAW" | base64 -d --ignore-garbage 2>/dev/null || echo "$_CONTRIB_RAW" | base64 -D 2>/dev/null)
fi

# Axis 6: .github/ directory contents
gh api "repos/$GH_OWNER/$GH_REPO/contents/.github" --jq '[.[] | .name]' 2>/dev/null  # timeout: 10000

# Axis 6 checkpoint 5+7: CODEOWNERS content (check .github/CODEOWNERS first, then root)
_CO_RAW=$(gh api "repos/$GH_OWNER/$GH_REPO/contents/.github/CODEOWNERS" --jq '.content' 2>/dev/null)  # timeout: 10000
if [ -n "$_CO_RAW" ]; then
    echo "$_CO_RAW" | base64 -d --ignore-garbage 2>/dev/null || echo "$_CO_RAW" | base64 -D 2>/dev/null
else
    _CO_RAW=$(gh api "repos/$GH_OWNER/$GH_REPO/contents/CODEOWNERS" --jq '.content' 2>/dev/null)
    echo "$_CO_RAW" | base64 -d --ignore-garbage 2>/dev/null || echo "$_CO_RAW" | base64 -D 2>/dev/null
fi

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
- Include text-content records for README and CONTRIBUTING using captured `_README_DECODED` / `_CONTRIB_DECODED` variables — set `"type":"readme_text"` / `"type":"contributing_text"` with `"data"` as plain string; skip if variable empty

## Step 5 — Return Envelope

```bash
DATASET_COUNT=$(grep -c '' "$DATA_FILE" 2>/dev/null || echo 0)  # timeout: 5000  # grep -c counts lines including files without trailing newline
PARTIAL_COUNT=$(jq -c 'select(.partial == true)' "$DATA_FILE" 2>/dev/null | wc -l || echo 0)  # timeout: 5000
if [ "$PARTIAL_COUNT" -eq 0 ]; then CONFIDENCE=0.95
elif [ "$PARTIAL_COUNT" -le 2 ]; then CONFIDENCE=0.88
else CONFIDENCE=0.78; fi
echo "[gh-scraper] fetch complete: $DATASET_COUNT datasets ($PARTIAL_COUNT partial) → $DATA_FILE"  # timeout: 5000
```

Return ONLY this JSON as final output line:

`{"status":"done","file":"<DATA_FILE>","datasets":<DATASET_COUNT>,"confidence":<CONFIDENCE>}`

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
