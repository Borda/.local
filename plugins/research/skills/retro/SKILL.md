---
name: retro
description: "Post-run retrospective: reads .experiments/ JSONL, computes Wilcoxon significance, detects dead iterations, flags suspicious jumps, generates next-hypothesis queue for --hypothesis flag."
argument-hint: "[<run-id>] [--compare <run-id-2>] [--threshold <delta>] [--alpha <significance>]"
effort: medium
allowed-tools: Read, Write, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Post-run retrospective analysis. After `/research:run` completes, reads `.experiments/state/<run-id>/experiments.jsonl`, computes statistical significance, detects dead iterations, flags suspicious metric jumps, generates learning summary with next-hypothesis queue.

NOT for: running experiments (use `/research:run`); designing experiments (use `/research:plan`); validating methodology (use `/research:judge`); verifying paper implementation (use `/research:verify`). Read-only — never modifies code, commits, or experiment state.

</objective>

<workflow>

## Agent Resolution

```bash
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains: foundry check + fallback table. `research:scientist` in same plugin — no fallback needed if research plugin installed.

## Retro Mode (Steps T1–T7)

Triggered by `retro`, `retro <run-id>`, or `retro <run-id> --compare <run-id-2>`.

**Defaults**: `--threshold 0.001`, `--alpha 0.05`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--compare\`, \`--threshold\`, \`--alpha\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Task tracking**: create tasks for T1–T7 at start — before any tool calls.

### Step T1: Locate and load run data

**Input resolution** (priority order):

1. Explicit `<run-id>` argument → read `.experiments/state/<run-id>/`
2. No argument → scan `.experiments/state/`, pick latest dir where `state.json` has `status: completed` or `status: goal-achieved`
3. None found → stop with error:
   ```text
   No completed run found. Run /research:run first, or provide: /research:retro <run-id>
   ```

**Load files** from `.experiments/state/<run-id>/`:

- `state.json`: extract `goal`, `best_metric`, `config` (including `metric.direction`), `iteration` count, `best_commit`. Compute `baseline_metric` from iteration 0 in `experiments.jsonl`.
- `experiments.jsonl`: full iteration history — validate each line parses as JSON. If last line truncated, warn and skip.
- `diary.md`: if present, read for qualitative context in T5.

If `--compare <run-id-2>` present: load second run identically from `.experiments/state/<run-id-2>/`. If not found, stop: `"Compare target not found: .experiments/state/<run-id-2>/. Check run ID and retry."`

**Assign `RUN_ID_ARG`** from `$ARGUMENTS` — first positional non-flag token, empty if absent (ADV-H17):

```bash
# Strip known flags before extracting positional; only positional is treated as run-id
_REMAINDER=$(echo "$ARGUMENTS" | sed -E 's/--compare[= ]+[^ ]+//g; s/--threshold[= ]+[^ ]+//g; s/--alpha[= ]+[^ ]+//g')
RUN_ID_ARG=$(echo "$_REMAINDER" | awk '{for (i=1; i<=NF; i++) if ($i !~ /^--/) { print $i; exit }}')
RUN_ID_ARG="${RUN_ID_ARG:-}"
# Persist for T3 (separate Bash shell — variables lost between calls)
echo "$RUN_ID_ARG" > "${TMPDIR:-/tmp}/retro-run-id"
```

**Pre-compute run directory** — also fix `$RUN_ID` (resolved from input resolution above) and persist `$RUN_DIR` for T3 (ADV-H18 + ADV-L16):

```bash
# RUN_ID = run-id argument if provided, else dir name of latest completed run  <!-- loads: find_run_id.py -->
RUN_ID="${RUN_ID_ARG:-$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/find_run_id.py" .experiments/state 2>/dev/null)}"
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
echo "$RUN_ID" > "${TMPDIR:-/tmp}/retro-run-id-resolved"  # persist resolved id for T3 / fallback paths
```

```bash
RUN_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/make_run_dir.py" "retro" ".experiments" 2>/dev/null)  # timeout: 5000
mkdir -p "$RUN_DIR/scripts"  # timeout: 3000
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/retro-run-dir"  # T3 + fallback path reload from temp file
```

### Step T2: Statistical significance analysis

Run the Wilcoxon signed-rank test via the bundled bin/ script — pure Python with scipy.stats:

```bash
ALPHA="${ALPHA:-0.05}"
METRIC_DIRECTION=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/read_state_field.py" ".experiments/state/$RUN_ID/state.json" "config.metric.direction" --default "higher" 2>/dev/null || echo "higher")  # loads: read_state_field.py
RETRO_RESULT=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/retro_analyze.py" --jsonl ".experiments/state/$RUN_ID/experiments.jsonl" --baseline "baseline" --alpha "$ALPHA" --direction "$METRIC_DIRECTION")  # timeout: 30000
```

**Contract** — script reads JSONL, extracts metric values for ALL iterations with `status == "kept"`, pairs each against the baseline record (`status == "baseline"`), runs a one-sided Wilcoxon signed-rank test, and prints a single line of JSON to stdout:

- `{"significant": bool, "p_value": float, "statistic": float, "n": int}` on success
- `{"significant": false, "p_value": null, "statistic": null, "n": <N>, "reason": "<msg>"}` when `N < 6` or scipy missing
- `{"error": "<msg>"}` on input error (exit 2 — missing file, malformed JSON, no baseline record)

Exit codes: `0` = significant · `1` = not significant (or insufficient data) · `2` = input error.

**Direction handling** — script branches on `--direction`:

- `higher` → `alternative = "greater"` (improvement = candidate > baseline)
- `lower` → `alternative = "less"` (improvement = candidate < baseline — for loss, latency, error)

Read `direction` from `state.json` config (or infer from goal text); pass via `$METRIC_DIRECTION`.

**Effect size** — script does not return rank-biserial `r` directly. Compute via the bundled bin/ script:

```bash
EFFECT_R=$(echo "$RETRO_RESULT" | python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/compute_effect_size.py")  # timeout: 5000
```

**If `--compare`**: invoke the script a second time on the second run's `experiments.jsonl`; downstream report renders a second row.

Write the combined results (parsed JSON plus computed `r`) to `$RUN_DIR/stats-results.json` via Write tool.

### Step T3: Dead iteration detection

**Definition**: dead iteration window = 3+ consecutive iterations (any status) where `abs(metric_delta) < threshold` (default `--threshold 0.001`).

**Scale check** (after loading baseline_metric in T1): if `baseline_metric > 100 * threshold`, print:
```text
! Threshold advisory: baseline_metric=[value] is >100x the default threshold (0.001).
  For this metric scale, consider: --threshold [baseline_metric * 0.0001:.4f]
  Proceeding with --threshold [threshold] — override with: /research:retro <run-id> --threshold <value>
```
Apply advisory threshold automatically only when `--threshold` not explicitly provided by user.

**Timeout detection**: when scanning reverted iterations, check `status` field. If `status == "timeout"`: classify as `timeout-as-revert` (see Notes). Otherwise: flag any reverted iteration where `delta` is in the correct improvement direction (i.e., metric moved toward goal) as "possible timeout — verify commit [sha]"; do not count delta as valid.

Scan `experiments.jsonl` sequentially, skipping iteration 0 (baseline). For each window of 3+ consecutive iterations where `abs(delta) < threshold`:

- Record: `start_iter`, `end_iter`, `count`
- Classify type: `dead-plateau` if all iterations in window have `status: kept`; `dead-churn` if mixed `kept`/`reverted`/other
- Compute `wasted_iters` = total iterations in all dead windows

Re-hydrate cross-Bash state at the start of every separate Bash invocation in T3 (each Bash call is a fresh shell — `$RUN_DIR` / `$RUN_ID_ARG` lost across calls; ADV-H18 / ADV-L16):

```bash
RUN_DIR=$(cat "${TMPDIR:-/tmp}/retro-run-dir" 2>/dev/null)
RUN_ID_ARG=$(cat "${TMPDIR:-/tmp}/retro-run-id" 2>/dev/null)
RUN_ID=$(cat "${TMPDIR:-/tmp}/retro-run-id-resolved" 2>/dev/null)
# Guard: any of these empty means T1 didn't run — surface and exit rather than write to a bare /
[ -z "$RUN_DIR" ] || [ -z "$RUN_ID" ] && { echo "retro T3: state files missing — T1 must run first" >&2; exit 1; }
```

Write summary to `$RUN_DIR/dead-iters.json` via Write tool. Format:

```json
{
  "windows": [{"start": 5, "end": 8, "count": 4, "type": "dead-churn"}],
  "total_dead": 4,
  "total_iterations": 20,
  "dead_pct": 20.0
}
```

Write dead-iteration scan script to `$RUN_DIR/scripts/dead-iter-scan.py` via Write tool, then execute in a separate Bash call. Never inline Python in the Bash command. (Different from T2: T3 writes a fresh dynamic script per invocation; T2 invokes a static bin/ script.)

### Step T4: Suspicious jump detection

Compute per-iteration absolute metric deltas for kept iterations only. Build sliding window of 5 kept iterations to compute running mean and std of deltas.

Flag any single-step improvement where `abs(delta) > running_mean + 2 * running_std`:

| Severity | Condition |
| --- | --- |
| HIGH | `abs(delta) > running_mean + 3 * running_std` |
| MEDIUM | `abs(delta) > running_mean + 2 * running_std` (and not HIGH) |

For each flagged jump, record:

- `iteration`, `delta`, `sigma` (how many std above mean), `commit` SHA, `files` changed (from experiments.jsonl `files` field)
- Label: `"suspicious — investigate"` — NEVER auto-label `"data leakage"` or imply causation
- Include corresponding `diary.md` entry for that iteration if present

**Minimum data**: require at least 6 kept iterations before flagging (need 5 for window + 1 to test). Fewer → skip suspicious-jump detection entirely and write `"⚠ Insufficient data for trend analysis (need ≥6 data points, have <N>)"` in the Suspicious Metric Jumps section of the report.

Write to `$RUN_DIR/suspicious-jumps.json` via Write tool.

### Step T5: Scientist learning summary

Pre-compute all file paths before spawning. Verify `$RUN_DIR/stats-results.json`, `$RUN_DIR/dead-iters.json`, `$RUN_DIR/suspicious-jumps.json` exist (T2–T4 must complete first).

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")`:

```markdown
Act as a research retrospective analyst.

Read:
- experiments.jsonl at <path> (full iteration history)
- diary.md at <path> (if exists — for qualitative context)
- stats results at <RUN_DIR>/stats-results.json
- dead iteration summary at <RUN_DIR>/dead-iters.json
- suspicious jumps at <RUN_DIR>/suspicious-jumps.json

Produce a retrospective analysis covering:

1. **Strategy effectiveness**: which agent types (perf/code/ml/arch) had highest kept-rate and average delta? Rank them. Include per-agent iteration count, kept count, and mean delta.
2. **Failure pattern analysis**: what approaches were repeatedly tried and reverted? Common failure modes? Group by pattern, not individual iteration.
3. **Diminishing returns**: at which iteration did improvement rate drop below 0.5% per iteration? Was the stopping point appropriate?
4. **Next hypotheses**: based on what worked and failed, generate 3–5 concrete next hypotheses. Write them as a hypotheses.jsonl-compatible file to <RUN_DIR>/hypotheses.jsonl — one JSON object per line with fields: hypothesis (str), rationale (str), confidence (float 0–1), expected_delta (str like "+2%"), priority (int 1=highest), source: "retro". Do NOT include feasible/blocker/codebase_mapping — feasibility annotation is optional in this context; /research:run treats absent feasibility fields as feasible:true. Note: full feasibility-annotation workflow is defined in research:scientist — see that agent for complete annotation spec.
5. **Cross-run insights** (only if compare data present in stats-results.json): which run's strategy was more effective and why?

Write full retrospective to <RUN_DIR>/retrospective.md using Write tool.
Include ## Confidence block per quality-gates rules.
Return ONLY: {"status":"done","hypotheses":N,"file":"<RUN_DIR>/retrospective.md","confidence":0.N}
```

**Health monitoring note** (CLAUDE.md §6 deviation): the research:scientist agent here is spawned synchronously (not `run_in_background=true`), so CLAUDE.md §6 sentinel polling is unreachable mid-call. Health monitoring is approximated post-hoc: if the Agent() call returns after >15 min with no output file, treat as timed out. CLAUDE.md §6 full protocol applies only to background agents.

**Post-call timeout check**: after Agent() returns, verify:
- File `$RUN_DIR/retrospective.md` exists and has content → success
- File missing or empty → set `scientist_status = "timed_out"`, continue to T6; surface with ⏱ in report

Parse returned JSON envelope. Record `hypotheses` count and `confidence` for T6.

### Step T6: Write retro report

Pre-compute branch (already done in T1).

```bash
mkdir -p .reports/research  # timeout: 3000
```

Write full report to `.reports/research/retro-$BRANCH-$(date +%Y-%m-%d).md` via Write tool. Anti-overwrite: `BASE=".reports/research/retro-$BRANCH-$(date +%Y-%m-%d).md"; OUT="$BASE"; COUNT=2; while [ -f "$OUT" ]; do OUT="${BASE%.md}-${COUNT}.md"; COUNT=$((COUNT+1)); done`

```markdown
---
Retro — [goal]
Date:          [YYYY-MM-DD]
Scope:         [run-id] / [total] iterations
Focus:         retrospective analysis of ML optimization run
Agents:        research:scientist (T5)
Outcome:       IMPROVED | STALLED | PLATEAU | DIVERGED
Significance:  p=[value] ([significant|not significant] at alpha=[alpha])
Hypotheses:    [N] next steps generated
Confidence:    [score] — [key gaps]
Next steps:    /research:run … --hypothesis | /research:fortify
Path:          → .reports/research/retro-<branch>-<date>.md
---

## Retrospective: <goal>

**Run**: <run-id>
**Date**: <date>
**Iterations**: <total> (<kept> kept, <reverted> reverted, <other> other)
**Baseline**: <metric_key> = <baseline>
**Best**: <metric_key> = <best> (<delta>% improvement)

### Statistical Significance

| Test | N | Statistic | p-value | Significant? | Effect size |
| --- | --- | --- | --- | --- | --- |
| Wilcoxon vs baseline | N | ... | ... | YES/NO (alpha=<alpha>) | r=... (<small/medium/large>) |
| Wilcoxon run-1 vs run-2 | N | ... | ... | YES/NO | r=... |

(Second row only if `--compare` used. If N < 6: replace table with descriptive stats table — mean, median, min, max, std — and note "Insufficient data for significance testing (N=<N>)".)

**Effect size interpretation**: |r| < 0.3 = small, 0.3–0.5 = medium, > 0.5 = large.

### Dead Iterations

| Start | End | Count | Type | Notes |
| --- | --- | --- | --- | --- |
| ... | ... | ... | dead-plateau / dead-churn | ... |

Total dead: <N> of <total> (<pct>% of compute)

(If no dead windows: "No dead iteration windows detected (threshold=<threshold>)")

### Suspicious Metric Jumps

| Iteration | Delta | Sigma | Severity | Commit | Files Changed |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | HIGH/MEDIUM | <sha> | <files> |

(If none: "No suspicious jumps detected")
(If insufficient data: "Insufficient data for jump detection (N=<N>)")

### Strategy Effectiveness

| Strategy | Kept | Tried | Keep-rate | Avg Delta | Best Delta |
| --- | --- | --- | --- | --- | --- |
| ... | ... | ... | ...% | ... | ... |

(From scientist retrospective. If scientist timed out: "Scientist agent timed out — strategy analysis unavailable")

### Failure Patterns
<From scientist retrospective — grouped failure modes>

### Diminishing Returns
<Iteration where improvement rate dropped below 0.5% per iteration, or "not applicable">

### Suggested Next Hypotheses

| # | Hypothesis | Rationale | Expected Delta | Confidence |
| --- | --- | --- | --- | --- |
| 1 | ... | ... | ... | 0.N |

Full retrospective: <RUN_DIR>/retrospective.md
Next hypotheses queue: <RUN_DIR>/hypotheses.jsonl

## Confidence
**Score**: 0.N — [high|moderate|low]
**Gaps**:
- Finding confidence (dead windows, suspicious jumps, classification errors, pattern detection): [high|moderate|low] — independent of statistical test availability
- Statistical confidence (Wilcoxon p-value): [available: p=X | unavailable: scipy not installed — descriptive stats only]
- [other specific limitations]
```

### Step T7: Terminal summary and follow-up gate

Print compact summary to terminal only — do NOT repeat full report:

```text
---
Retro — <goal>
Run:           <run-id> (<total> iterations, <kept> kept)
Significance:  p=<value> (<significant|not significant> at alpha=<alpha>)  [or: N=<N> insufficient]
Effect size:   r=<value> (<small|medium|large>)  [or: n/a]
Dead iters:    <N>/<total> (<pct>%)  [or: none]
Suspicious:    <N> jumps (<severity> — investigate: <sha1>, <sha2>)  [or: none]
Hypotheses:    <N> next steps generated
-> saved to .reports/research/retro-<branch>-<date>.md
---
Next: /research:run <program.md> --hypothesis <RUN_DIR>/hypotheses.jsonl
     /research:fortify <run-id>    ← stress-test top hypothesis before full re-run
```

Call `AskUserQuestion` tool after summary — do NOT write options as plain text:
- question: "What next?"
- (a) label: `/research:run … --hypothesis` — description: run next hypotheses from generated queue
- (b) label: `/research:fortify` — description: stress-test top components via ablation study
- (c) label: `skip` — description: no further action

</workflow>

<notes>

- Retro read-only — never modifies code, commits, or writes to `.experiments/state/<run-id>/`
- `.experiments/retro-<timestamp>/` stores analysis scripts, intermediate JSON, scientist output, hypotheses.jsonl
- Retro run dirs don't write `result.jsonl` — exempt from automated 30-day TTL cleanup (exempt per `.claude/rules/artifact-lifecycle.md` — no `result.jsonl` = cleanup skipped); remove manually when done (`rm -rf .experiments/retro-*/`)
- `hypotheses.jsonl` uses `source: "retro"` — compatible with `--hypothesis` flag of `/research:run`; `"retro"` extends oracle schema (see `protocol.md`); feasibility fields omitted, treated as feasible:true by run
- `--compare` requires both runs use same metric; if metric names differ, stop: `"Cannot compare runs with different metrics: <metric-1> vs <metric-2>"`
- Dead iteration threshold (`--threshold`) should match metric's noise floor — default 0.001 for normalized metrics; adjust for raw values (e.g. `--threshold 0.1` for loss in hundreds)
- Statistical tests assume metric values are independent samples — if iterations highly correlated (e.g. cumulative optimization), note limitation in report
- **Named anomaly patterns** (use consistently across reports):
  - `kept-regression`: a kept iteration where metric moved in wrong direction (positive delta for higher-is-better, negative delta for lower-is-better)
  - `reverted-improvement`: a reverted iteration where metric moved in correct direction — reverted for non-metric reasons (performance, OOM, instability); flag as "improvement-when-reverted — consider revisiting with adjusted constraints"
  - `timeout-as-revert`: a reverted iteration with `status: "timeout"` — metric value unreliable; never count delta as valid improvement
  - `config-repetition`: same agent + same file(s) attempted 3+ times without crossing threshold — flag as "repeated-failure pattern"

</notes>
