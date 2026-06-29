<!-- loads: vitality-report.md -->

<workflow>

**Task hygiene**: call TaskList first; close orphaned tasks from prior runs. **Task tracking**: TaskCreate tasks for each major phase before starting: "Step 1 Data Fetch", "Step 2 Axis Scoring (3 parallel)", "Step 3 Assemble Scores", "Step 4 Report", "Step 5 Codex Review", "Step 6 Adversarial Rework Loop", "Step 7 Terminal Output"; mark each in_progress/completed as you go.

## Step 1 — Data Fetch

**Task tracking**: mark "Step 1 Data Fetch" in_progress before spawning.

```bash
mkdir -p .reports/analyse/vitality  # timeout: 5000
TODAY=$(TZ=UTC date +%Y-%m-%d)  # timeout: 5000
RUN_TS=$(TZ=UTC date +%Y-%m-%dT%H-%M-%SZ)  # timeout: 5000
DATA_FILE=".reports/analyse/vitality/raw-data-${GH_OWNER}-${GH_REPO}-${TODAY}.jsonl"
PARTIAL_A=".reports/analyse/vitality/partial-A-${GH_OWNER}-${GH_REPO}-${RUN_TS}.json"
PARTIAL_B=".reports/analyse/vitality/partial-B-${GH_OWNER}-${GH_REPO}-${RUN_TS}.json"
PARTIAL_C=".reports/analyse/vitality/partial-C-${GH_OWNER}-${GH_REPO}-${RUN_TS}.json"
SCORES_FILE=".reports/analyse/vitality/scores-${GH_OWNER}-${GH_REPO}-${RUN_TS}.json"
```

**Spawn**:

> `Agent(subagent_type="oss:gh-scraper", prompt="GH_OWNER=$GH_OWNER GH_REPO=$GH_REPO DATA_FILE=$DATA_FILE")`

Wait for completion. Verify `$DATA_FILE` exists and non-empty. TaskUpdate "Step 1 Data Fetch" completed.

## Step 2 — Parallel Axis Scoring

**Task tracking**: mark "Step 2 Axis Scoring (3 parallel)" in_progress.

Spawn all 3 `oss:repo-warden` agents simultaneously in single response:

> `Agent(subagent_type="oss:repo-warden", prompt="GH_OWNER=$GH_OWNER GH_REPO=$GH_REPO DATA_FILE=$DATA_FILE PARTIAL_FILE=$PARTIAL_A AXIS_GROUP=A")`
> `Agent(subagent_type="oss:repo-warden", prompt="GH_OWNER=$GH_OWNER GH_REPO=$GH_REPO DATA_FILE=$DATA_FILE PARTIAL_FILE=$PARTIAL_B AXIS_GROUP=B")`
> `Agent(subagent_type="oss:repo-warden", prompt="GH_OWNER=$GH_OWNER GH_REPO=$GH_REPO DATA_FILE=$DATA_FILE PARTIAL_FILE=$PARTIAL_C AXIS_GROUP=C")`

**Health monitoring** (CLAUDE.md §6): before spawning, create checkpoint:

```bash
SCORE_CHECKPOINT_FILE="/tmp/vitality-score-check-${GH_OWNER}-${GH_REPO}-${RUN_TS}"
touch "$SCORE_CHECKPOINT_FILE"  # timeout: 5000
```

Every 5 min while waiting: `find .reports/analyse/vitality -newer "$SCORE_CHECKPOINT_FILE" -name "partial-*.json" | wc -l` — new files = alive; zero = stalled. Hard cutoff: 15 min no file activity → timed out. One extension (+5 min) if partial file tail explains delay — second unexplained stall = cutoff. On timeout: read tail of any partial output; surface with ⏱ marker.

Wait for all 3 agents. Verify all 3 partial files exist: `$PARTIAL_A`, `$PARTIAL_B`, `$PARTIAL_C`.

TaskUpdate "Step 2 Axis Scoring (3 parallel)" completed.

## Step 3 — Assemble Scores

**Task tracking**: mark "Step 3 Assemble Scores" in_progress.

Read all 3 partial files using Read tool. Merge into unified `$SCORES_FILE`:

```bash
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)  # timeout: 5000
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
SCORING_FILE="$_OSS_SHARED/vitality-scoring.md"
```

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/assemble_vitality_scores.py" \
    "$PARTIAL_A" "$PARTIAL_B" "$PARTIAL_C" "$SCORING_FILE" "$SCORES_FILE"  # timeout: 15000
```

Extract variables from `$SCORES_FILE` for use in Steps 4–7:

```bash
eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/extract_vitality_vars.py" "$SCORES_FILE")"  # timeout: 5000
echo "[vitality] scorer complete: health=${HEALTH_SCORE_PCT}% conf=${OVERALL_CONFIDENCE} passes=${TOTAL_PASSES}"
```

TaskUpdate "Step 3 Assemble Scores" completed.

## Step 4 — Report Generation

```bash
REPORT_TIMESTAMP=$(TZ=UTC date +%Y-%m-%dT%H-%M-%SZ)  # timeout: 5000
REPORT_FILE=".reports/analyse/vitality/output-analyse-vitality-${GH_OWNER}-${GH_REPO}-${REPORT_TIMESTAMP}.md"

# Provenance metadata — embedded for self-complete, deterministic output
_VER_FILE=$(ls ~/.claude/plugins/cache/borda-ai-rig/oss/*/.claude-plugin/plugin.json 2>/dev/null | sort | tail -1)  # timeout: 5000
[ -z "$_VER_FILE" ] && _VER_FILE="plugins/oss/.claude-plugin/plugin.json"
SKILL_VERSION=$(jq -r '.version // "unknown"' "$_VER_FILE" 2>/dev/null || echo "unknown")  # timeout: 5000

REPORT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")  # timeout: 5000

# Codex check here — agents list in frontmatter must be accurate at write time
find ~/.claude/plugins -name "codex-rescue.md" 2>/dev/null | grep -q . && CODEX_AVAILABLE=1 || CODEX_AVAILABLE=0

# Build agents list for frontmatter — reflects actual contributors
REPORT_AGENTS_YAML="  - oss:analyse (orchestrator)
  - foundry:challenger (adversarial review)"
[ "$CODEX_AVAILABLE" = "1" ] && REPORT_AGENTS_YAML="$REPORT_AGENTS_YAML
  - codex:codex-rescue (independent repo review + adversarial review)"
```

Resolve template path (installed cache first, source tree fallback):

```bash
_OSS_ANALYSE=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/analyse 2>/dev/null | sort -V | tail -1)  # timeout: 5000
[ -z "$_OSS_ANALYSE" ] && _OSS_ANALYSE="plugins/oss/skills/analyse"
REPORT_TPL="$_OSS_ANALYSE/templates/vitality-report.md"
```

Run `mkdir -p .reports/analyse/vitality` then **Read `$REPORT_TPL`** to get full report structure. Write `$REPORT_FILE` using that structure as scaffold — substitute all `{VARIABLE}` placeholders with bash variables set above (`REPORT_TIMESTAMP`, `GH_OWNER`, `GH_REPO`, `SKILL_VERSION`, `REPORT_COMMIT`, `TOTAL_PASSES`, `CONFIDENCE_HISTORY`, `REPORT_AGENTS_YAML`, etc.). Do not print full analysis to terminal.

## Step 5 — Codex Independent Repo Review

When `CODEX_AVAILABLE=1`: spawn `codex:codex-rescue` to independently assess repo on same 9 axes from raw fetched data — NOT from main analysis report. Produces parallel verdict for aggregation and divergence detection.

```bash
REVIEW_DIR=".reports/analyse/vitality/$(date +%Y-%m-%d)-review"
CODEX_REVIEW_OUT="$REVIEW_DIR/codex-repo-review.md"
mkdir -p "$REVIEW_DIR"  # timeout: 5000
```

**Spawn instruction for `codex:codex-rescue`** (only when CODEX_AVAILABLE=1):

```text
You are performing an independent vitality assessment of {GH_OWNER}/{GH_REPO}.
Do NOT read the main analysis report. Assess the same 9 axes from raw evidence only (axes 1–9; weights from $SCORING_FILE weight table: 17%, 18%, 14%, 11%, 9%, 7%, 9%, 7%, 8%):

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
| 9 Trajectory | N.N | 🟢/🟡/🔴 | {one sentence} |
| **Total Score** | **XX%** | 🟢/🟡/🔴 | — |

## Divergences
[note any axis where you expect main analysis to differ — include reasoning]

Write sentinel {REVIEW_DIR}/codex-repo-review.done on completion.
Return compact JSON only: {"status":"done","file":"{CODEX_REVIEW_OUT}","health_score":XX,"confidence":0.N}
```

**When CODEX_AVAILABLE=0**: skip step; note "codex unavailable — single-pass analysis only" in Codex Independent Review report section.

### Aggregation

After codex review completes (sentinel verified), compute per-axis delta:

```bash
# delta = abs(main_score[axis] - codex_score[axis])
# divergence threshold: delta >= 2.0 points
# flag axes where delta >= 2.0 as "⚠ divergent"
# aggregate health score = mean(main_health_score, codex_health_score)
```

Update report's `## Independent Codex Review` section (append via Edit tool) with:
- Codex scorecard table (from `$CODEX_REVIEW_OUT`)
- Aggregate health score
- Per-axis delta table with divergence flags
- Divergence explanations where delta ≥ 2.0

```markdown
## Independent Codex Review

Codex independently assessed the same 9 axes from raw fetched data — without reading the main analysis. Divergences ≥ 2.0 score points are flagged for human review.

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
| 9 Trajectory | N.N | N.N | ±N.N | ✓ / ⚠ divergent |

### Divergences

_(Only axes with delta ≥ 2.0. If none: "Main analysis and Codex agree within 2.0 points on all axes.")_

#### Axis N — {name} (main: N.N · codex: N.N · delta: ±N.N)
**Main evidence:** {what main analysis used}
**Codex evidence:** {what codex found}
**Resolution:** {which reading is more likely correct and why — or "inconclusive, re-run recommended"}
```

## Step 6 — Adversarial Rework Loop

After Step 5 aggregation complete — report includes main analysis + Codex independent review + divergence resolution. Adversarial reviewers assess **complete combined report** iteratively; rework applied between iterations.

```bash
# CODEX_AVAILABLE set in Step 4 — reuse as-is
# REVIEW_DIR set in Step 5 — do not redefine
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)  # timeout: 5000
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
REWORK_ITER=0
REWORK_MAX=2
REWORK_SECTIONS=""
```

**Iteration loop** (repeat up to `$REWORK_MAX` times):

### 6a — Adversarial Review (fresh spawn each iteration)

Spawn reviewers simultaneously in single response — each writes to own iter-indexed file. No shared input between reviewers.

**When CODEX_AVAILABLE=1**: spawn `foundry:challenger` AND `codex:codex-rescue` simultaneously:

1. `foundry:challenger` — reads `$REPORT_FILE`; stress-tests scoring thresholds, flags weak evidence, challenges causality claims, verifies limit-hit detection, checks coverage gate logic; flags shared blind spots between main analysis and Codex independent review, or unconvincing divergence resolution; assesses all 9 axes including Axis 9 Trajectory. Writes findings to `$REVIEW_DIR/challenger-iter${REWORK_ITER}.md` (Write tool). Writes sentinel `$REVIEW_DIR/challenger-iter${REWORK_ITER}.done`. After narrative findings, writes machine-readable block on own line:
   ```
   REWORK_JSON: {"verdict":"pass"}
   ```
   OR
   ```
   REWORK_JSON: {"verdict":"needs_rework","items":[{"axis":N,"section":"<heading>","issue":"<specific claim that needs correction>","severity":"critical|high|medium"}]}
   ```
   Only flag `verdict=needs_rework` when finding is factually wrong or unsupported by evidence — not style/emphasis differences. Returns compact JSON envelope only.

2. `codex:codex-rescue` — reads `$REPORT_FILE` independently (do NOT read challenger output — independent assessment eliminates anchoring bias); adversarial pass from fresh perspective; focus on evidence quality, threshold calibration, data-gap risks, scoring edge cases not in main analysis; assesses all 9 axes. Writes findings to `$REVIEW_DIR/codex-iter${REWORK_ITER}.md` (Write tool). Writes sentinel `$REVIEW_DIR/codex-iter${REWORK_ITER}.done`. Returns compact JSON envelope only.

**When CODEX_AVAILABLE=0**: spawn `foundry:challenger` only (step 1 above; skip step 2).

After spawning, verify sentinels:

```bash
[ -f "$REVIEW_DIR/challenger-iter${REWORK_ITER}.done" ] || { echo "⚠ challenger iter${REWORK_ITER} did not complete"; CHALLENGER_ITER_OUT=""; }
[ "$CODEX_AVAILABLE" = "1" ] && { [ -f "$REVIEW_DIR/codex-iter${REWORK_ITER}.done" ] || CODEX_ITER_OUT=""; }
```

Parse REWORK_JSON from challenger output:

```bash
REWORK_JSON=$(grep "^REWORK_JSON:" "$REVIEW_DIR/challenger-iter${REWORK_ITER}.md" 2>/dev/null | sed 's/^REWORK_JSON: //')
REWORK_VERDICT=$(echo "$REWORK_JSON" | jq -r '.verdict // "pass"' 2>/dev/null || echo "pass")  # timeout: 5000
```

### 6b — Rework (only when REWORK_VERDICT=needs_rework)

If `$REWORK_VERDICT` = `needs_rework` AND `$REWORK_ITER` < `$REWORK_MAX`:

For each item in rework list (parsed from `$REWORK_JSON`):

1. Extract specific section from `$REPORT_FILE` — grep from section heading to next `##` heading
2. Extract relevant axis data from `$DATA_FILE` — `type` record(s) for that axis from JSONL
3. Identify axis rubric section from `$_OSS_SHARED/vitality-scoring.md`

Spawn FRESH rework agent per flagged section with MINIMAL context (no report history, no prior iteration findings):

```
Agent(subagent_type="foundry:sw-engineer", prompt="""
You are a technical writer revising one section of a vitality analysis report.
REPO: {GH_OWNER}/{GH_REPO}
AXIS: {axis N — axis name}
SECTION TO REVISE (current content):
---
{section_content}
---
REVIEWER ISSUE: {item.issue}
RAW DATA for this axis (from GitHub API):
{axis_specific_data_from_DATA_FILE}
SCORING RUBRIC for this axis:
{axis_N_section_from_vitality_scoring_md}

Instructions: Rewrite the section to address the reviewer's issue. Use only the raw data provided above — do not introduce claims unsupported by this data. Preserve the existing markdown format (headings, bold labels, evidence/impact/action structure). Do not change the axis score or label unless the raw data clearly contradicts the current value.

Write the revised section to {REVIEW_DIR}/axis_{axis_N}_iter{REWORK_ITER}.md using Write tool.
Return ONLY: {"status":"done","file":"<path>","axis":N}
""")
```

After all rework agents complete: patch `$REPORT_FILE` in-place — replace each original section with revised version via Edit tool (exact string match on section heading). Track revised sections in `$REWORK_SECTIONS`.

Increment `REWORK_ITER`:

```bash
REWORK_ITER=$((REWORK_ITER + 1))
```

If `$REWORK_ITER >= $REWORK_MAX` OR `$REWORK_VERDICT = "pass"`: exit loop.

Otherwise: return to 6a with new `Agent()` spawns (prior iteration's reviewer findings must NOT be in new reviewer's prompt — each adversarial spawn is fresh blank-context agent).

### 6c — Merge Adversarial Findings into Report

After loop exits (pass or max iterations): update `$REPORT_FILE` — replace placeholder `## Adversarial Review` block from Step 4 with final content via Edit tool:

```markdown
## Adversarial Review

**Rework iterations:** {REWORK_ITER} of {REWORK_MAX} maximum
{If REWORK_ITER > 0: "**Sections revised:** {REWORK_SECTIONS comma-separated}"}

**Challenger:** {findings from $REVIEW_DIR/challenger-iter{final_iter}.md}

**Codex:** {findings from $REVIEW_DIR/codex-iter{final_iter}.md — or "codex unavailable — single adversarial pass only" when CODEX_AVAILABLE=0}
```

**TaskUpdate**: mark "Step 6 Adversarial Rework Loop" completed. If overall confidence from adversarial findings drops below 0.7 AND re-run of specific axes warranted, create new task "Step 3 re-score: {axis list}" and mark in_progress before re-fetching — keep task list current when confidence-driven reruns happen.

## Step 7 — Terminal Summary Output

Read `$FOUNDRY_SHARED/terminal-summaries.md` for compact block format. File absent → warn "foundry:setup required — printing plain terminal output instead."

Print compact block to terminal. Three sections: header, exec summary, simplified scorecard. Axis rows must appear in numeric order 1–9; never reorder by score, weight, or status:

```markdown
# Repo Vitality — {GH_OWNER}/{GH_REPO}
**Skill:** oss:analyse v{SKILL_VERSION} · **Commit:** {REPORT_COMMIT} · **Generated:** {REPORT_TIMESTAMP}
**Passes:** {TOTAL_PASSES}/5 · confidence: {OVERALL_CONFIDENCE} (history: {CONFIDENCE_HISTORY colons→commas})
```
_(Omit Passes line when TOTAL_PASSES=1 — no retry loop needed.)_

```markdown
---

## Executive Summary

{2–3 sentences: overall health verdict, single top strength, single top risk. Example: "Project is in healthy condition (72%) with strong CI/CD and responsive maintainers. Contributor bus factor of 1 is the primary risk — a single maintainer departure could stall development. Dependency update automation is absent, leaving security hygiene dependent on manual effort."}

**Health Score:** {XX}% {🟢/🟡/🔴} · {N} healthy · {N} warning · {N} critical · {N} unavailable (⚪)
_(When OVERALL_CONFIDENCE < 0.7 prefix this line with: `⚠ LOW CONFIDENCE ({OVERALL_CONFIDENCE:.2f}) — directional only`)_
**Aggregate:**   {XX}% (mean main + Codex) — omit line when CODEX_AVAILABLE=0
**Rework:**      {REWORK_ITER} iteration(s) — omit line when REWORK_ITER=0
**Top Risk:**    {single most urgent finding, one line}
→ {REPORT_FILE}

---

| # | Axis                 | Score | Status   | Key Signal |
|---|----------------------|-------|----------|------------|
| 1 | Responsiveness       | N.N   | 🟢/🟡/🔴 | median issue Xd, PR Xd; X% ≤7d |
| 2 | Maintenance activity | N.N   | 🟢/🟡/🔴 | last commit Xd, X commits/30d |
| 3 | Contributor health   | N.N   | 🟢/🟡/🔴 | bus factor N, retention X% |
| 4 | Issue & PR health    | N.N   | 🟢/🟡/🔴 | stale X%, close X, review cov X% |
| 5 | CI/CD & code quality | N.N   | 🟢/🟡/🔴 | N/5 checks, CI pass X% |
| 6 | Documentation        | N.N   | 🟢/🟡/🔴 | N/9 checkpoints |
| 7 | Governance           | N.N   | 🟢/🟡/🔴 | N/7 files, active maint X/Y |
| 8 | Security posture     | N.N   | 🟢/🟡/🔴 | dep-config: yes/no, alerts: N or 403 |
| 9 | Trajectory           | N.N   | 🟢/🟡/🔴 | pool ±N%, TTM Xd→Yd, P90 Zd, dep-bump X% |
|   | **Total Score**      | **XX%** | 🟢/🟡/🔴 | — |

---
```

For ⚪ axes: show `--` in Score/Status columns; append below closing `---`:
```text
⚠ Axis {N} ({name}, wt {X}%) unavailable — score normalized over {M}/9 axes
```
If Axis 3 specifically ⚪: `⚠ Axis 3 (contributor health, wt 14%) unavailable — rerun in 5–10 min for full score`.

**Post-table validation (mandatory)**: after printing the scorecard, verify: (a) exactly 9 data rows appear with axis numbers 1–9, (b) no axis number repeated. Any duplicate or omission = immediately reprint the corrected full table before any other output. Never omit an axis row — even when data missing, show `--` in Score/Status.

Block must begin with `# Repo Vitality — {GH_OWNER}/{GH_REPO}` title and close with `---` on own line. Do not print full analysis to terminal. Full Conf/Weight columns and per-axis detail in report file only.

</workflow>

<notes>

- **Parallel scoring**: Group A (Axes 1,2,5,6), Group B (Axes 4,7,8), Group C (Axes 3→9) run simultaneously. Each reads DATA_FILE independently — no shared state between scorer agents. Assembler merges after all 3 complete.
- **Rework loop**: max 2 iterations. Rework agents get MINIMAL context — only section content + raw data + rubric + reviewer issue. No full report history passed. Prevents anchoring on prior flawed reasoning.
- **Fresh adversarial agents each iteration**: spawn new Agent() each rework cycle — prior iteration's reviewer findings must NOT be in new reviewer's context. Independent assessment is the point.
- **Adversarial review is mandatory** — Step 6 always runs; `foundry:challenger` always spawned; `codex:codex-rescue` spawned when `CODEX_AVAILABLE=1`. No skip path exists.
- **Parallel group discipline**: Group 2 data fetches in gh-scraper only after Group 1 resolves (needs root file list and default_branch); scoring Groups A/B/C have no such dependency — all read from DATA_FILE independently
- **Data reuse**: root-contents fetch shared by Axes 6 and 7; releases fetch shared by Axis 2 and security signals; contributor stats weeks[] shared by Axis 3 and sub-signal 9A — all written to DATA_FILE, each scorer reads what it needs
- **--limit caps and truncation detection**: all limits set to target+1 (e.g. `--limit 501` for open issues targeting 500); if response length == limit, truncation occurred — JSONL record has `"partial": true`; scorer degrades confidence accordingly
- **Duplicate clustering**: flag DUPLICATE only when root = same problem (identical error/feature ask/root cause); flag RELATED when same component, distinct problems — do not conflate
- **Discussions API**: GraphQL `discussions(first:100)` sufficient for health snapshot; full pagination not needed
- **Stats 202 retry**: contributor stats endpoint returns 202 on first call for large repos — gh-scraper retries up to 6× with 10s sleep; if still 202, writes partial record; scorer Group C handles fallback from `commits_50`
- **403 on security APIs**: Dependabot and secret scanning require push access; 403 = expected; scorer Group B applies partial scoring for Axis 8; confidence 0.4; never ⚪ solely from Dependabot 403
- **Axis 1 response time**: responses by issue/PR author do not count — only first non-author comment/review contributes to response time computation
- **Code-review coverage (Axis 4)**: bot-submitted PRs (Dependabot, Renovate) excluded from both numerator and denominator — bot PRs cannot be "reviewed" in human sense and distort coverage rate
- **Star velocity**: advisory only — excluded from numeric score; page loop stops at 180d boundary via `$CUTOFF_180D`; if coverage < 30 days of stars when loop ends, mark 8B ⚪; partial data (≥30d coverage but <180d) → note truncation and use available window for trend
- **Package registry 404**: skip sub-signal C silently — not all repos publish to PyPI/npm
- **Axis independence**: failure of one axis (API unavailable, access denied, computing) → ⚪ row in scorecard, continue with remaining axes; never block report on single axis failure
- **Codex independent review (Step 5)**: runs before adversarial review — codex assesses raw data independently, not main report; produces parallel scorecard and divergence notes; aggregate health score = mean(main, codex); when CODEX_AVAILABLE=0, note "codex unavailable — single-pass analysis only" in report section
- **codex availability check**: `find ~/.claude/plugins -name "codex-rescue.md" 2>/dev/null | grep -q .` — run before spawn; do not assume codex installed
- **Health Score footer row**: Score column shows weighted %; Weight column shows "100%"; Status/Key Signal/Risk left blank
- **Rework loop exit conditions**: exits when `$REWORK_VERDICT = "pass"` OR `$REWORK_ITER >= $REWORK_MAX`; always exits after 2 iterations max regardless of verdict
- **SCORES_FILE**: assembled in Step 3 by orchestrator from 3 partial files — not written by gh-scraper; gh-scraper prompt in Step 1 does NOT include SCORES_FILE
- **CI pass-rate denominator**: always `success / total` (full denominator); never trim to success/conclusive; report `action_required` runs as separate "workflow auth failures" note — never exclude from denominator; inconsistent denominators break cross-repo Health Score comparison
- **Dependabot manifest_path classification**: before classifying alert as runtime user exposure, check `manifest_path` — `*_test.txt`, `**/test*.txt`, `**/dev*.txt`, `**/ci*.txt` = test/CI deps, not user-facing; GitHub `scope=runtime` field is unreliable for extras classification; actual runtime exposure = alert in file referenced by published extras_require; always split security finding: "N user-facing (extras/*.txt)" vs "M dev/CI-facing (*_test.txt)"
- **CODEOWNERS activity verification**: compute CODEOWNERS active-maintainer count programmatically from commit-author data (`commits.json`/stats); never enumerate by name recognition; inactive = 0 commits in window; still counts as CODEOWNERS member but labelled "nominal"; correct list must include all commit authors who appear in CODEOWNERS, exclude those with 0 commits
- **Issue truncation framing**: when `open_issues.json` size == (`open_issues_count` − open PRs count), sample IS full population — state "all N open issues sampled"; reserve "N-cap window" framing for genuinely truncated samples only (response size == fetch limit); check: `sample_size = len(open_issues.json)`, `population = repo_meta.open_issues_count - open_prs_count`, if `sample_size >= population` → no truncation
- **Workflow count reconciliation**: when API `total_count` differs from count of YAML files in `.github/workflows/`, reconcile — API includes archived/disabled; filesystem is active only; report as "N active (M registered)" never a single ambiguous number; SAST/security claims must use filesystem count (active workflows only)
- **Bus factor confidence discounting**: when Axis 3 conf < 0.70 (e.g. stats 202 fallback), surface explicitly — add "X% of Health Score sits on low-confidence Axis 3" note; when conf ≤ 0.50, treat as partial contribution (effective weight × conf); never carry full axis weight at conf 0.50
- **TTFR primary metric**: headline responsiveness metric is % of issues/PRs with zero response (silence rate); TTFR is secondary — characterises responded sub-sample only; always append "(responded only, N=X)" to TTFR figure; in scorecard row show silence rate first, TTFR second; for non-responded issues TTFR = ∞, not omitted
- **Commit denominator discipline**: always use non-bot count as denominator for per-author concentration (bus factor, contributor share); phrase as "X% of non-bot commits"; never "X% of last N commits" when bots inflate N; applies to: Axis 3 bus factor, committer counts, all contributor-share metrics
- **Skill version in Health Score**: record `SKILL_VERSION` in report header; when comparing Health Scores across two reports, warn if skill versions differ — axis weights may have changed; format: "Health Score 57.7% (v0.7.1)" not bare "57.7%"; never compare bare scores across runs with different skill versions

</notes>
