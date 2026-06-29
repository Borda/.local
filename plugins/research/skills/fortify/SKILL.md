---
name: fortify
description: "Systematic ablation study runner. After research:run finds improvements, fortify identifies component candidates from git diff + diary, creates isolated git worktrees per ablation (main repo never modified), runs metric+guard in each worktree, ranks component importance, and optionally generates reviewer Q&A calibrated to a target venue."
argument-hint: "[<run-id>|<program.md>] [--venue <CVPR|NeurIPS|ICML|workshop>] [--max-ablations <N>] [--skip-run]"
effort: high
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, TaskCreate, TaskUpdate, AskUserQuestion
disable-model-invocation: true
---

<objective>

Ablation study runner — after `/research:run` finds improvements, fortify identifies which components contributed, generates ablation variants (remove one component at a time), runs each in **isolated git worktrees** (main repo never modified), ranks component importance, optionally generates reviewer Q&A calibrated to venue.

NOT for: initial optimization loop (use `/research:run`); methodology validation (use `/research:judge`); paper-vs-code consistency (use `/research:verify`); hypothesis generation (use `research:scientist` directly). Fortify runs ablation studies on completed runs only.

</objective>

<constants>

```yaml
MAX_ABLATION_CANDIDATES:  8 (ceiling — scientist produces 3–8; --max-ablations caps further)
METRIC_TIMEOUT_MS:        360000 (6 min — same as run SKILL.md)
GUARD_TIMEOUT_MS:         360000
GIT_OP_TIMEOUT_MS:        15000
SANITY_DIVERGENCE_PCT:    2.0 (full-variant vs best_metric mismatch threshold)
IMPORTANCE_CLASS_CRITICAL: 50.0 (% of full metric lost)
IMPORTANCE_CLASS_SIGNIFICANT: 10.0
FORTIFY_DIR_BASE:         .experiments
STATE_DIR_BASE:           .experiments/state
METRIC_CMD_DEFAULT:       "python -m pytest -x --tb=no -q"
GUARD_CMD_DEFAULT:        "git diff --stat HEAD"
```

</constants>

**Environment overrides** — set these before invoking the skill to override per-variant defaults:

- `METRIC_CMD` — command run inside each variant worktree to measure the ablation metric (default: `python -m pytest -x --tb=no -q`)
- `GUARD_CMD` — command run inside each variant worktree to detect regressions (default: `git diff --stat HEAD`)
- `STATE_DIR_BASE` — base directory for source-run state lookups (default: `.experiments/state`)
- `FORTIFY_DIR_BASE` — base directory for per-run fortify artifacts (default: `.experiments`)

The constants block defaults above are YAML-only — bash blocks read environment variables (with `${VAR:-default}` fallback) and never source values directly from YAML.

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

```bash
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
[ -z "$_RESEARCH_SHARED" ] && { echo "! Plugin path resolution failed — ensure research plugin installed and CLAUDE_PLUGIN_ROOT set, or invoke /research:fortify from project root."; exit 1; }
```

Read `$_RESEARCH_SHARED/agent-resolution.md`. Contains foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agent this skill dispatches: `research:scientist` (same plugin — no fallback if research plugin installed).

| Agent | Fallback if absent |
| --- | --- |
| `research:scientist` | `general-purpose` (ablation candidate identification and reviewer Q&A quality reduced — **⚠ general-purpose agent may not emit the JSON envelope this skill parses; surface partial output and surface ⚠ in F7 report**) |

## CRITICAL: Worktree-based isolation

**Do NOT use `git checkout -b <branch>` for ablations** — dirties main working tree, corrupts concurrent tool calls. Each ablation gets own git worktree under `$FORTIFY_DIR/worktrees/<variant>`, created from `best_commit`. Main working tree NEVER modified. Cleanup: `git worktree remove --force` per variant; `git worktree prune` on interrupt.

## Fortify Mode (Steps F1–F8)

Triggered by `fortify` or `fortify <run-id|program.md>`.

**Task tracking**: create tasks for F1, F2, F3, F4, F5, F6, F7, F8 at start — before any tool calls.

## Step F1: Locate source run, parse flags, and validate judge approval

Extract flags: `--venue <VENUE>`, `--max-ablations <N>`, `--skip-run`.

<!-- loads: unsupported-flag-protocol.md -->
**Unsupported flag check**: follow `$_RESEARCH_SHARED/unsupported-flag-protocol.md`. Supported flags for this skill: `--venue`, `--max-ablations`, `--skip-run`.

**Input resolution** (priority order):

1. Explicit `<run-id>` argument → read `$STATE_DIR_BASE/<run-id>/state.json`
2. Explicit `<program.md>` argument → scan `$STATE_DIR_BASE/*/state.json` for matching `program_file`, pick latest with `status: completed` or `status: goal-achieved`
3. No argument → scan `$STATE_DIR_BASE/`, pick latest with `status: completed` or `status: goal-achieved`
4. None found → stop:
   ```text
   fortify: No completed run found. Run /research:run first.
   ```

**Initialize base directory bash variables** (constants YAML is not auto-exported; environment overrides honored):

```bash
STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"
FORTIFY_DIR_BASE="${FORTIFY_DIR_BASE:-.experiments}"
METRIC_CMD="${METRIC_CMD:-python -m pytest -x --tb=no -q}"
GUARD_CMD="${GUARD_CMD:-git diff --stat HEAD}"
```

**Assign `$RUN_ID`** from input resolution above (must be set before guard block uses it):

```bash
_ARG1=$(echo "$ARGUMENTS" | awk '{print $1}')
if [ -n "$_ARG1" ] && [ "${_ARG1#-}" = "$_ARG1" ] && [ ! -f "$_ARG1" ] && [ -d "$STATE_DIR_BASE/$_ARG1" ]; then
  RUN_ID="$_ARG1"
elif [ -n "$_ARG1" ] && [ -f "$_ARG1" ]; then
  # program.md path — find latest completed run matching program_file  <!-- loads: find_run_id.py -->
  RUN_ID=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/find_run_id.py" "$STATE_DIR_BASE" --match-program "$_ARG1" 2>/dev/null)
else
  RUN_ID=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/find_run_id.py" "$STATE_DIR_BASE" 2>/dev/null)
fi
[ -z "$RUN_ID" ] && { echo "fortify: No completed run found. Run /research:run first."; exit 1; }
```

**Guard: judge approval required.** Judge skill writes verdict to `.reports/research/judge-<branch>-<date>.md` — scan for APPROVED verdict line:

```bash
JUDGE_VERDICT_FILE=$(ls -t .reports/research/judge-*.md 2>/dev/null | head -1)  # timeout: 5000
if [ -z "$JUDGE_VERDICT_FILE" ]; then
  echo "fortify: BLOCKED — no judge verdict found in .reports/research/."
  echo "Ablation studies require an approved baseline. Run: /research:judge <program.md>"
  exit 1
fi
JUDGE_VERDICT=$(grep -i '^[*]*[Vv]erdict[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*[Vv]erdict[: ]+//' | sed 's/[[:space:]]*$//')  # strip trailing only; preserve internal spaces (e.g. "NEEDS REVISION")

PROGRAM_FILE=$(grep -iE '^[*]*(Program(_file)?|Program file)[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*:[[:space:]]*//' | sed 's/[[:space:]]*$//')
# F-02 guard: empty PROGRAM_FILE means verdict lacks program metadata — cannot verify applicability
if [ -z "$PROGRAM_FILE" ]; then
    echo "fortify: BLOCKED — judge verdict missing Program: field; cannot verify verdict applies to current experiment."
    echo "Re-run: /research:judge <program.md> to generate a fresh verdict with required metadata."
    exit 1
fi
# Use explicit run-specific state.json path (resolved during F1 input resolution) — never CWD-relative
STATE_PROGRAM=$(jq -r '.program_file // ""' "$STATE_DIR_BASE/$RUN_ID/state.json" 2>/dev/null)
if [ -n "$STATE_PROGRAM" ] && [ -n "$PROGRAM_FILE" ] && [ "$PROGRAM_FILE" != "$STATE_PROGRAM" ]; then
    printf "! BLOCKED — judge verdict references program '%s' but current experiment is for '%s'\n" "$PROGRAM_FILE" "$STATE_PROGRAM"
    printf "Run: /research:judge %s\n" "$STATE_PROGRAM"
    exit 1
fi
if [ -n "$PROGRAM_FILE" ] && [ ! -f "$PROGRAM_FILE" ]; then
    printf "! BLOCKED — program file %s referenced by judge verdict not found on disk\n" "$PROGRAM_FILE"
    exit 1
fi
```

Verify `JUDGE_VERDICT == "APPROVED"`. The program cross-match above guarantees the verdict was issued for the current experiment — fortify cannot ablate against a different program's verdict. Apply explicit bash gate — prose alone never halts execution:

```bash
JUDGE_VERDICT="${JUDGE_VERDICT:-REJECTED}"
if [ "$JUDGE_VERDICT" != "APPROVED" ]; then
    echo "fortify: BLOCKED — no APPROVED judge verdict found for this program."
    echo "Judge verdict: $JUDGE_VERDICT — stopping before implementation (F1–F7)."
    echo "Ablation studies require an approved baseline. Run: /research:judge <program.md>"
    exit 1
fi
```

> Note: do NOT infer from `methodology.md` alone — `methodology_rating: sound` is one input to verdict, not verdict itself. Only `## Verdict` line in judge output file is authoritative.

Read from `state.json`: `goal`, `best_metric`, `best_commit`, `config` (including `metric_cmd`, `guard_cmd`, `compute`), `program_file`.

Also read `baseline_commit` — iteration 0 commit from `experiments.jsonl` (first line, `status: "baseline"`, field `"commit"`).

**Pre-compute run directory** (each in separate Bash call):

```bash
FORTIFY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/make_run_dir.py" "fortify" ".experiments" 2>/dev/null)  # timeout: 5000
[ -z "$FORTIFY_DIR" ] && { echo "! make_run_dir.py failed — ensure research plugin installed"; exit 1; }
mkdir -p "$FORTIFY_DIR"
WORKTREE_BASE="$FORTIFY_DIR/worktrees"
mkdir -p "$WORKTREE_BASE"
STATE_DIR="${STATE_DIR_BASE:-/tmp}/fortify-$(basename "$FORTIFY_DIR")"
mkdir -p "$STATE_DIR"
```

## Step F2: Identify ablation candidates via scientist

Gather two inputs for scientist:

1. **Git diff**: run `git diff <baseline_commit>...<best_commit> --stat` (summary) and full `git diff <baseline_commit>...<best_commit>`. If full diff exceeds ~200 lines, write to `$FORTIFY_DIR/diff.txt` via Write tool; otherwise inline in prompt.
2. **Experiment history**: paths to `experiments.jsonl` and `diary.md` from source run directory.

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")` with health monitoring (15-min cutoff, one 5-min extension — same pattern as judge J3).

Before building the prompt, substitute all bash variables into a single concrete string — never pass literal `<FORTIFY_DIR>` or `<path>` placeholders to the agent:

```bash
EXPERIMENTS_PATH="$STATE_DIR_BASE/$RUN_ID/experiments.jsonl"
DIARY_PATH="$STATE_DIR_BASE/$RUN_ID/diary.md"
F2_PROMPT="Act as an ML ablation study designer.

Read:
- git diff at ${FORTIFY_DIR}/diff.txt (or inline if small)
- experiments.jsonl at ${EXPERIMENTS_PATH} (filter for entries with status: 'kept')
- diary.md at ${DIARY_PATH} (if exists)

Identify 3-8 distinct logical components that were changed during this run.
A component = a logically independent change that can be removed independently.

For each component produce one JSON line to ${FORTIFY_DIR}/ablation-candidates.jsonl:
{
  \"component_id\": <int>,
  \"name\": \"<descriptive name, e.g. 'learning rate warmup'>\",
  \"description\": \"<what it does and why it was introduced>\",
  \"files\": [\"<file:line range>\"],
  \"revert_commits\": [\"<commit SHA>\"],
  \"expected_importance\": \"HIGH|MEDIUM|LOW\"
}

Write your analysis to ${FORTIFY_DIR}/candidates-analysis.md.
Include ## Confidence block.
Return ONLY: {\"status\":\"done\",\"components\":N,\"file\":\"${FORTIFY_DIR}/ablation-candidates.jsonl\",\"confidence\":0.N}"
```

Pass `$F2_PROMPT` (fully expanded) as the `prompt=` argument to `Agent(...)`.

**Health monitoring** (CLAUDE.md §6):

```bash
# audit-skip: resilience-replication
# Per-phase checkpoint: F2 + F6 dispatch independent scientist agents; separate vars prevent cross-phase masking.
_HM_F2=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health_monitor_start.py" "fortify-f2" 2>/dev/null)  # timeout: 5000
LAUNCH_AT_F2=$(echo "$_HM_F2" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT_F2=$(echo "$_HM_F2" | grep '^SENTINEL=' | cut -d= -f2)
```

Poll every 5 min: `find "$FORTIFY_DIR" -newer "$CHECKPOINT_F2" -type f | wc -l` (`timeout: 5000`) — new files = alive; zero = stalled.

- **Hard cutoff: 15 min** no file activity → timed out
- **One extension (+5 min)**: if `tail -20 "$FORTIFY_DIR"/candidates-analysis.md` shows active progress, grant one extension; second stall = hard cutoff
- **On timeout**: stop with `"fortify: Scientist timed out. Check $FORTIFY_DIR/ for partial output."`; surface with ⏱

Read `ablation-candidates.jsonl` after scientist completes. If `--max-ablations <M>` specified and component count + 1 (for full variant) exceeds M: sort by `expected_importance` (HIGH first, then MEDIUM, then LOW), keep top M-1 components plus always include `full` sanity-check variant. **Log dropped components**: print a warning listing each dropped component by `component_id` and `expected_importance` so users can verify the scientist's importance estimates before proceeding. Include this list in the F7 report under `## Dropped Variants`.

**`--skip-run` early exit**: if `--skip-run` flag present, print candidate table (component_id, name, description, files, expected_importance) and exit. No ablation execution. Mark tasks F3, F4, F5, F6, F7 as `skipped` via TaskUpdate. Print all three lines (no `.reports/research/fortify-*.md` is written in `--skip-run` mode — only `ablation-candidates.jsonl` lives under `$FORTIFY_DIR`; surface `$FORTIFY_DIR` explicitly so the user can locate the candidate list):

```text
fortify: --skip-run — <N> candidates identified.
Candidates artifact: $FORTIFY_DIR/ablation-candidates.jsonl
Next: /research:fortify without --skip-run to execute ablations
```

Jump to F8 (skip-run variant).

## Step F3: Generate ablation variants

For each component from F2, one ablation variant: `no-<component-name>` (slugified — lowercase, spaces to hyphens). Plus one `full` variant (sanity check — should reproduce `best_metric`).

Write variant configs to `$FORTIFY_DIR/variants.jsonl` via Write tool — one JSON line per variant:

```json
{"variant_name": "full", "component_removed": null, "revert_commits": [], "revert_strategy": "none"}
{"variant_name": "no-<name>", "component_removed": "<name>", "revert_commits": ["<sha1>", "<sha2>"], "revert_strategy": "git-revert"}
```

## Step F4: Run ablation variants via worktrees

Run each variant **sequentially** — parallel worktrees would conflict.

**Before loop — store original working directory and pre-create worktree-paths accumulator:**

```bash
ORIG_DIR="$(pwd)"  # timeout: 3000
WORKTREE_PATHS_FILE=$(mktemp -t fortify-XXXX) || { echo "! BLOCKED — mktemp failed (tmpfs full or permission denied); cannot create cleanup accumulator. Aborting."; exit 1; }  # timeout: 3000
echo "$WORKTREE_PATHS_FILE" > "${TMPDIR:-/tmp}/fortify-paths-ptr"

# F-04: validate best_commit is a concrete SHA — `git worktree add` with a branch tip
# would advance the branch and pollute shared history on subsequent `git revert`.
if ! best_commit_sha=$(git rev-parse --verify "$best_commit^{commit}" 2>/dev/null); then
    echo "! BLOCKED — best_commit '$best_commit' does not resolve to a commit. Re-run source experiment or correct state.json."
    exit 1
fi
best_commit="$best_commit_sha"  # downstream `git worktree add` always sees a SHA → detached HEAD
```

**On interrupt** (user abort or unexpected error mid-loop): `cd "$ORIG_DIR"` first, then `git worktree prune` (`timeout: 15000`) to clean up partially created worktrees before exiting. The trap below makes interrupt cleanup automatic — never rely on prose-only cleanup discipline.

For each variant in `variants.jsonl`:

**4a-init. Derive `VARIANT_NAME` from the current iteration** (must be set before any 4a/4b/4c/4d/4e block uses it):

```bash
VARIANT_NAME="variant-$(echo "$variant_spec" | jq -r '.variant_name' 2>/dev/null | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | sed 's/^variant-//')"
# Fallback when variant_spec is just the bare name (not full JSON object) OR jq returned empty/null/error.
# Covers: empty (`variant-`), JSON null (`variant-null`), plain-text input that jq cannot parse.
if [ -z "$VARIANT_NAME" ] || [ "$VARIANT_NAME" = "variant-null" ] || [ "$VARIANT_NAME" = "variant-" ]; then
    VARIANT_NAME="variant-$(echo "${variant_spec:-unnamed}" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | sed 's/^variant-//')"
fi
# Final hard guard: after both attempts, VARIANT_NAME must be non-trivial (more than just "variant-").
if [ "$VARIANT_NAME" = "variant-" ] || [ -z "$VARIANT_NAME" ]; then
    echo "! BLOCKED — could not derive non-empty VARIANT_NAME from variant_spec; check variants.jsonl format. Skipping iteration."
    continue
fi
```

**4a. Create isolated worktree at best_commit:**

```bash
git worktree add "$WORKTREE_BASE/$VARIANT_NAME" "$best_commit"  # timeout: 15000
```

**4a-trap. Register cleanup trap immediately after worktree creation** (guarantees removal on EXIT / INT / TERM, even on uncaught error):

```bash
# Reload (Check 41: shell var lost between Bash calls)
WORKTREE_PATHS_FILE=$(cat "${TMPDIR:-/tmp}/fortify-paths-ptr" 2>/dev/null)
[ -z "$WORKTREE_PATHS_FILE" ] && WORKTREE_PATHS_FILE="${TMPDIR:-/tmp}/fortify-worktree-paths-fallback"
WORKTREE_PATH="${FORTIFY_WORKTREE:-$WORKTREE_BASE/$VARIANT_NAME}"
echo "$WORKTREE_PATH" >> "$WORKTREE_PATHS_FILE"  # accumulator file persists across Bash calls; array vars do not
trap 'while IFS= read -r _wt; do git worktree remove --force "$_wt" 2>/dev/null; done < "$WORKTREE_PATHS_FILE" 2>/dev/null; rm -f "$WORKTREE_PATHS_FILE"' EXIT INT TERM
```

The accumulator file (`$WORKTREE_PATHS_FILE`) is pre-created via `mktemp` before the variant loop begins. Each variant appends its path and re-registers the trap to cover all paths added so far. The explicit `git worktree remove` in 4f remains for happy-path cleanup; the trap is a safety net for interrupted loops only. `mktemp` ensures collision-free naming across concurrent invocations.

**4b. Navigate into worktree** (two separate Bash calls — cd first, then command):

```bash
cd "$WORKTREE_BASE/$VARIANT_NAME"  # timeout: 3000
```

**4c. Apply revert (skip for `full` variant):**

For `full` variant: no changes — proceed to 4d.

For `no-<component>` variant: revert component's commits.

**IMPORTANT — order matters**: revert in **reverse chronological order** (newest first) to avoid conflicts. If `revert_commits` from `variants.jsonl` is chronological (oldest first), reverse before reverting.

**Bash call 1 — extract and sort revert_commits via jq + awk** (no python; jq-based JSONL filter avoids per-iteration approval prompt):

```bash
REVERT_COMMITS_RAW=$(jq -r --arg vn "$VARIANT_NAME" 'select(.variant_name==$vn) | .revert_commits[]' "$FORTIFY_DIR/variants.jsonl" 2>/dev/null | tr '\n' ' ')  # timeout: 5000
[ -z "$REVERT_COMMITS_RAW" ] && { echo "⚠ No revert_commits for $VARIANT_NAME — skipping"; echo '{"variant":"'$VARIANT_NAME'","status":"revert-missing"}' >> "$FORTIFY_DIR/results.jsonl"; continue; }
# Sort newest-first for conflict-free revert (portable awk reverse — tac not on macOS)
REVERT_COMMITS_SORTED=$(echo "$REVERT_COMMITS_RAW" | tr ' ' '\n' | awk '{lines[NR]=$0} END{for(i=NR;i>=1;i--) print lines[i]}' | tr '\n' ' ')
```

**Bash call 2 — apply revert** (separated so first-token allow-list matches `git`):

```bash
git revert $REVERT_COMMITS_SORTED --no-edit  # timeout: 15000
```

If revert produces merge conflicts: append `{"variant":"<name>","status":"revert-conflict",...}` to `results.jsonl`, jump to 4f (cleanup).

**4d. Run metric_cmd in worktree:**

```bash
$METRIC_CMD  # timeout: 360000  (initialized in F1 from env or default)
METRIC_EXIT=$?
```

Parse stdout for numeric metric value. If command fails or no numeric output: record `status: "metric-failed"`, jump to 4f.

**4e. Run guard_cmd in worktree:**

```bash
$GUARD_CMD  # timeout: 360000  (initialized in F1 from env or default)
GUARD_EXIT=$?
```

Record guard result: `"pass"` (exit 0) or `"fail"` (non-zero).

**4f. Cleanup worktree (INVARIANT — must execute even if 4c/4d/4e fail):**

```bash
cd "$ORIG_DIR"  # timeout: 3000
```

```bash
git worktree remove --force "$WORKTREE_BASE/$VARIANT_NAME"  # timeout: 15000
```

**4g. Record result** — append one JSON line to `$FORTIFY_DIR/results.jsonl`:

```json
{"variant":"<name>","component_removed":"<name or null>","metric":0.0,"delta_from_full":0.0,"delta_pct":0.0,"guard":"pass|fail","status":"completed|revert-conflict|metric-failed|timeout","timestamp":"<ISO>"}
```

`delta_from_full` and `delta_pct` are placeholders — computed in post-loop step below.

After all variants processed:

```bash
git worktree prune  # timeout: 15000
```

**Post-loop delta computation**: read `results.jsonl`, find `full` variant metric. For each completed `no-<component>` variant:

- `delta_from_full = ablated_metric - full_metric`
- `delta_pct = (delta_from_full / abs(full_metric)) * 100` (signed — negative means removing component hurt). If `full_metric == 0`: set `delta_pct = 0` (avoid division by zero).

Update `results.jsonl` with computed deltas via Write tool (rewrite full file).

## Step F5: Rank component importance

For each `no-<component>` variant with `status: "completed"`:

- Read `metric_direction` from `## Metric` block in `program_file` (`higher` or `lower`). If absent, default to `higher`.
- Compute **signed delta** (positive = removal hurt metric → component helpful):
  ```python
  signed_delta = (full_metric - ablated_metric) * (1 if direction == 'higher' else -1)
  importance = signed_delta / abs(full_metric) * 100 if full_metric != 0 else 0
  ```
- Importance class (helpful components — `signed_delta >= 0`):
  - **CRITICAL**: importance > 50%
  - **SIGNIFICANT**: importance 10–50%
  - **MARGINAL**: importance < 10%
**Sign convention check** — after computing signed_delta for all variants, verify:
- For `direction == 'higher'`: all helpful components should have `signed_delta >= 0` (ablated metric < full)
- For `direction == 'lower'`: all helpful components should have `signed_delta >= 0` (ablated metric > full; removing component worsened metric)
- Any component where `signed_delta` has unexpected sign: flag explicitly in report as "sign anomaly — verify ablation ran correctly"

- **Potentially Harmful** class: `signed_delta < -5%` — removing component IMPROVED metric. Surface in dedicated `Potentially Harmful Components` report section; not ranked in main table.

**Borderline components** (CI spans zero): if a confidence interval is available and spans zero (includes both positive and negative values), do NOT classify as MARGINAL. Instead:
- Add to a "Borderline Components" subsection in the F7 report
- Note: "CI spans zero — component may be neutral or harmful; additional runs required before including in model"
- Do not rank these in the main importance table; surface separately

**Coupling check** — before sorting, scan the ablation candidates (from `ablation-candidates.jsonl`) for notes on architectural dependencies. For any pair where one component explicitly requires the other (noted in `description` field or `candidates-analysis.md`):
- Mark both components in the ranking with `[COUPLED]` suffix
- Add a note: "Independent ablation unreliable — recommend joint ablation of [A + B]"
- Add to the "Skipped Variants" section: `joint-[A]-[B] — not run (joint ablation recommended)`
- Surface as a `! WARNING` in the F7 report before the ranking table

Sort by importance descending (helpful components only). Write to `$FORTIFY_DIR/importance-ranking.json` via Write tool — JSON array with fields: `rank`, `component`, `full_metric`, `ablated_metric`, `signed_delta_pct`, `importance_pct`, `class` (`CRITICAL`/`SIGNIFICANT`/`MARGINAL`/`HARMFUL`).

**Sanity check**: compare `full` variant metric against `best_metric` from `state.json`. If divergence exceeds 2%:

```text
Warning: Sanity check failed: full-variant metric=<X> differs from best_metric=<Y> by <Z>%. Results may be unreliable (non-deterministic metric or environment change).
```

Include warning prominently in F7 report.

## Step F6: Reviewer Q&A (optional — `--venue` only)

Skip entirely if no `--venue` flag. Supported venues: `CVPR`, `NeurIPS`, `ICML`, `workshop`.

**Health monitoring setup** (same pattern as F2 — create checkpoint before spawn):

```bash
# audit-skip: resilience-replication
# Per-phase checkpoint required — F6 reviewer Q&A is an independent scientist dispatch from F2; shared variables would mask phase-specific stalls.
_HM_F6=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health_monitor_start.py" "fortify-f6" 2>/dev/null)  # timeout: 5000
LAUNCH_AT_F6=$(echo "$_HM_F6" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT_F6=$(echo "$_HM_F6" | grep '^SENTINEL=' | cut -d= -f2)
```

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")` with health monitoring (same 15-min cutoff, one 5-min extension — poll `find "$FORTIFY_DIR" -name "reviewer-qa.md" -newer "$CHECKPOINT_F6" | wc -l`).

Before building the prompt, substitute all bash variables into a single concrete string — never pass literal `<FORTIFY_DIR>`, `<path>`, or `<venue>` placeholders to the agent:

```bash
VENUE="${VENUE:-workshop}"  # parsed from --venue flag in F1
[ -z "$PROGRAM_FILE" ] && { echo "! fortify: BLOCKED — PROGRAM_FILE not set; re-invoke from F1"; exit 1; }  # absolute path resolved in F1
F6_PROMPT="Act as a peer reviewer for ${VENUE}.

Read:
- ablation results at ${FORTIFY_DIR}/results.jsonl
- importance ranking at ${FORTIFY_DIR}/importance-ranking.json
- original program.md at ${PROGRAM_FILE}

Generate:
1. 5-7 likely reviewer questions calibrated to ${VENUE} standards
   (CVPR/NeurIPS/ICML: expect thorough ablations, statistical significance, compute budget justification; workshop: lighter bar)
2. For each question: a data-backed answer referencing specific ablation results
3. A supplementary material draft section with the ablation table (LaTeX-ready)

Write to ${FORTIFY_DIR}/reviewer-qa.md.
Include ## Confidence block.
Return ONLY: {\"status\":\"done\",\"questions\":N,\"file\":\"${FORTIFY_DIR}/reviewer-qa.md\",\"confidence\":0.N}"
```

Pass `$F6_PROMPT` (fully expanded) as the `prompt=` argument to `Agent(...)`.

**Health monitoring**: same as F2 (15-min cutoff, one extension). On timeout: note `"Reviewer Q&A: timed out"` in report, continue to F7.

## Step F7: Write fortify report

Pre-compute branch if not already set:

```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
```

```bash
mkdir -p .reports/research  # timeout: 3000
```

Write full report to `.reports/research/fortify-$BRANCH-$(date +%Y-%m-%d).md` via Write tool. Anti-overwrite: `BASE=".reports/research/fortify-$BRANCH-$(date +%Y-%m-%d).md"; OUT="$BASE"; COUNT=2; while [ -f "$OUT" ]; do OUT="${BASE%.md}-${COUNT}.md"; ((COUNT++)); done`

```markdown
---
Fortify — [goal]
Date:        [YYYY-MM-DD]
Scope:       [run-id] / [N] components identified
Focus:       ablation study / component importance ranking
Agents:      research:scientist (F2, F6)
Outcome:     [N] critical · [N] significant · [N] marginal components
Top:         [component-name] (importance: X.X% · CRITICAL|SIGNIFICANT|MARGINAL)
Confidence:  [score] — [key gaps]
Next steps:  simplify by removing marginal components, re-run /research:run
Path:        → .reports/research/fortify-<branch>-<date>.md
---

## Fortify Report: <goal>

**Source run**: <run-id>
**Date**: <date>
**Baseline commit**: <best_commit>
**Components identified**: <N>
**Ablations run**: <N completed> of <N+1 planned>

### Sanity Check (full variant)
Full metric: <value> (expected from run: <best_metric>) — PASS | Warning MISMATCH (<Z>% divergence)

### Component Importance Ranking

| Rank | Component | Full Metric | Ablated Metric | Signed Δ | Importance | Class |
|------|-----------|-------------|----------------|----------|------------|-------|
| 1    | ...       | ...         | ...            | +X.X%    | X.X%       | CRITICAL |

### Potentially Harmful or Borderline Components

Components that either:
- Improved the metric when removed (`signed_delta < -5%`) — **Potentially Harmful**
- Have CI spanning zero — **Borderline** (insufficient evidence of contribution)

| Component | Full Metric | Ablated Metric | Signed Δ | Status |
|-----------|-------------|----------------|----------|--------|
| ...       | ...         | ...            | -X.X%    | Potentially Harmful |
| ...       | ...         | CI [−a, +b]    | n/a      | Borderline |

(Omit section entirely if no harmful or borderline components found.)

### Ablation Matrix

| Variant       | Metric | Guard | Status           | Delta from Full |
|---------------|--------|-------|------------------|-----------------|
| full          | ...    | pass  | completed        | baseline        |
| no-component1 | ...    | pass  | completed        | -X.X%           |
| no-component2 | ...    | n/a   | revert-conflict  | n/a             |

### Skipped Variants
<list any revert-conflict, metric-failed, or timeout variants with reason>

### Reviewer Q&A
<section from F6 if --venue was specified; otherwise omit this section entirely>

Full artifacts: <FORTIFY_DIR>/

## Confidence
**Score**: 0.N — [high|moderate|low]
**Gaps**:
- [specific limitation]
```

## Step F8: Terminal summary

Print compact terminal summary:

```text
---
Fortify — <goal>
Source run:   <run-id>
Sanity:       full=<value> (expected <best_metric>) — PASS | Warning MISMATCH
Components:   <N> identified · <N> ablations completed
Top:          <component-name> (importance: X.X% · CRITICAL|SIGNIFICANT|MARGINAL)
Marginal:     <N> components < 10% each
Venue Q&A:    generated for <venue> | n/a
-> saved to .reports/research/fortify-<branch>-<date>.md
-> ablation artifacts: <FORTIFY_DIR>/
---
Next: simplify model by removing marginal components, re-run /research:run
```

If `--skip-run` used (early exit at F2): replace ablation lines with:

```text
---
Fortify — <goal> (--skip-run)
Source run:   <run-id>
Components:   <N> candidates identified — ablations not executed
-> candidates: <FORTIFY_DIR>/ablation-candidates.jsonl
-> analysis:   <FORTIFY_DIR>/candidates-analysis.md
---
Next: run /research:fortify without --skip-run to execute ablations
```

</workflow>

<calibration>

Calibratable: F1–F3 sub-steps only — synthetic ablation plan with known component importance order; score whether fortify correctly ranks components and identifies reviewer questions. Full F4–F6 execution loop (worktree creation, metric runs, real guard scripts) excluded — requires live git state and metric commands.

See the domain table entry for `/research:fortify` for the full ground-truth checklist. Path resolution:
```bash
_FOUNDRY_CALIBRATE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/calibrate/modes 2>/dev/null | head -1); [ -z "$_FOUNDRY_CALIBRATE" ] && _FOUNDRY_CALIBRATE="plugins/foundry/skills/calibrate/modes"
# See: $_FOUNDRY_CALIBRATE/skills.md
```

</calibration>

<notes>

- **Worktree invariant** — cleanup (`git worktree remove --force`) must run even if metric/guard fails. No stale worktrees. Final `git worktree prune` catches missed cleanup.
- **Main repo never modified** — all ablation work in worktrees. Main working tree stays clean.
- **Sequential execution** — variants run one at a time. Parallel worktrees would require separate detached HEADs and complicate cleanup.
- **No compound Bash commands** — always two separate Bash calls (cd then command). CWD persists between calls.
- **Bash tool `timeout` parameter** — never shell `timeout` wrapper. Pass `timeout: <ms>` on Bash tool call.
- **Judge prerequisite** — fortify refuses without APPROVED judge verdict. Prevents ablation on unapproved methodologies.
- **`--skip-run` for planning** — generates candidate list without running ablations. Useful for reviewing what would be ablated before committing compute.
- **`--skip-run` scope**: flag skips ablation *execution* only — source run (`research:run`) must already be complete. Does not affect source run.
- **Fortify run directories** don't write `result.jsonl` — exempt from 30-day TTL cleanup (no `result.jsonl` = cleanup skipped); remove manually when done (`rm -rf .experiments/fortify-*/`)
- **Compute mode**: local execution only. `--compute` and `--colab` passthrough not implemented — contributions welcome. Until then, fortify runs `metric_cmd`/`guard_cmd` directly in each worktree on local machine.
- **Revert conflicts expected** — when commits interleave (component A's commit touches same lines as B's), revert may conflict. Recorded as `revert-conflict`, not treated as error.

</notes>
