<!-- file: vitality-adversarial-rework.md — consumers: analyse/modes/vitality.md (Step 6 pointer, QUICK_MODE-gated) -->

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

Returns to `vitality.md` Step 7 (terminal summary output).
