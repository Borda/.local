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
```

</constants>

<workflow>

## Agent Resolution

<!-- Foundry plugin check retained for resilience: run `Glob(pattern="foundry*", path="$HOME/.claude/plugins/cache/")` to confirm foundry installed before dispatching foundry:* agents (not used in fortify directly, but Glob kept for consistency with other research skills that do). If check fails, proceed — fortify only dispatches research:scientist (same plugin). -->

`research:scientist` in same plugin as this skill — no fallback needed if research plugin installed.

## CRITICAL: Worktree-based isolation

**Do NOT use `git checkout -b <branch>` for ablations** — dirties main working tree, corrupts concurrent tool calls. Each ablation gets own git worktree under `$FORTIFY_DIR/worktrees/<variant>`, created from `best_commit`. Main working tree NEVER modified. Cleanup: `git worktree remove --force` per variant; `git worktree prune` on interrupt.

## Fortify Mode (Steps F1–F8)

Triggered by `fortify` or `fortify <run-id|program.md>`.

**Task tracking**: create tasks for F1, F2, F3, F4, F5, F6, F7, F8 at start — before any tool calls.

## Step F1: Locate source run, parse flags, and validate judge approval

Extract flags: `--venue <VENUE>`, `--max-ablations <N>`, `--skip-run`.

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--venue\`, \`--max-ablations\`, \`--skip-run\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

**Input resolution** (priority order):

1. Explicit `<run-id>` argument → read `$STATE_DIR_BASE/<run-id>/state.json`
2. Explicit `<program.md>` argument → scan `$STATE_DIR_BASE/*/state.json` for matching `program_file`, pick latest with `status: completed` or `status: goal-achieved`
3. No argument → scan `$STATE_DIR_BASE/`, pick latest with `status: completed` or `status: goal-achieved`
4. None found → stop:
   ```text
   fortify: No completed run found. Run /research:run first.
   ```

**Guard: judge approval required.** Judge skill writes verdict to `.reports/research/judge-<branch>-<date>.md` — scan for APPROVED verdict line:

```bash
JUDGE_VERDICT_FILE=$(ls -t .reports/research/judge-*.md 2>/dev/null | head -1)  # timeout: 5000
if [ -z "$JUDGE_VERDICT_FILE" ]; then
  echo "fortify: BLOCKED — no judge verdict found in .reports/research/."
  echo "Ablation studies require an approved baseline. Run: /research:judge <program.md>"
  exit 1
fi
# Preserve multi-word verdicts (e.g. "NEEDS REVISION") — strip trailing whitespace only, not internal spaces
JUDGE_VERDICT=$(grep -i '^[*]*[Vv]erdict[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*[Vv]erdict[: ]+//' | sed 's/[[:space:]]*$//')

# Program cross-match: confirm verdict was issued for the current experiment's program, not a different one
PROGRAM_FILE=$(grep -iE '^[*]*(Program(_file)?|Program file)[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*:[[:space:]]*//' | sed 's/[[:space:]]*$//')
STATE_PROGRAM=$(python -c "import json; d=json.load(open('state.json')); print(d.get('program_file',''))" 2>/dev/null)
if [ -n "$STATE_PROGRAM" ] && [ -n "$PROGRAM_FILE" ] && [ "$PROGRAM_FILE" != "$STATE_PROGRAM" ]; then
    printf "! BLOCKED — judge verdict references program '%s' but current experiment is for '%s'\n" "$PROGRAM_FILE" "$STATE_PROGRAM"
    printf "Run: /research:judge %s\n" "$STATE_PROGRAM"
    exit 1
fi
# Confirm program file still exists on disk
if [ -n "$PROGRAM_FILE" ] && [ ! -f "$PROGRAM_FILE" ]; then
    printf "! BLOCKED — program file %s referenced by judge verdict not found on disk\n" "$PROGRAM_FILE"
    exit 1
fi
```

Verify `JUDGE_VERDICT == "APPROVED"`. The program cross-match above guarantees the verdict was issued for the current experiment — fortify cannot ablate against a different program's verdict. If not APPROVED:

```text
fortify: BLOCKED — no APPROVED judge verdict found for this program.
Ablation studies require an approved baseline. Run: /research:judge <program.md>
```

> Note: do NOT infer from `methodology.md` alone — `methodology_rating: sound` is one input to verdict, not verdict itself. Only `## Verdict` line in judge output file is authoritative.

Read from `state.json`: `goal`, `best_metric`, `best_commit`, `config` (including `metric_cmd`, `guard_cmd`, `compute`), `program_file`.

Also read `baseline_commit` — iteration 0 commit from `experiments.jsonl` (first line, `status: "baseline"`, field `"commit"`).

**Pre-compute run directory** (each in separate Bash call):

```bash
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')  # timeout: 3000
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)                                           # timeout: 3000
FORTIFY_DIR="$FORTIFY_DIR_BASE/fortify-$TS"                                  # timeout: 5000
WORKTREE_BASE="$FORTIFY_DIR/worktrees"
mkdir -p "$FORTIFY_DIR" "$WORKTREE_BASE"
```

## Step F2: Identify ablation candidates via scientist

Gather two inputs for scientist:

1. **Git diff**: run `git diff <baseline_commit>...<best_commit> --stat` (summary) and full `git diff <baseline_commit>...<best_commit>`. If full diff exceeds ~200 lines, write to `$FORTIFY_DIR/diff.txt` via Write tool; otherwise inline in prompt.
2. **Experiment history**: paths to `experiments.jsonl` and `diary.md` from source run directory.

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")` with health monitoring (15-min cutoff, one 5-min extension — same pattern as judge J3):

```markdown
Act as an ML ablation study designer.

Read:
- git diff at <FORTIFY_DIR>/diff.txt (or inline if small)
- experiments.jsonl at <path> (filter for entries with status: "kept")
- diary.md at <path> (if exists)

Identify 3–8 distinct logical components that were changed during this run.
A component = a logically independent change that can be removed independently.

For each component produce one JSON line to <FORTIFY_DIR>/ablation-candidates.jsonl:
{
  "component_id": <int>,
  "name": "<descriptive name, e.g. 'learning rate warmup'>",
  "description": "<what it does and why it was introduced>",
  "files": ["<file:line range>"],
  "revert_commits": ["<commit SHA>"],
  "expected_importance": "HIGH|MEDIUM|LOW"
}

Write your analysis to <FORTIFY_DIR>/candidates-analysis.md.
Include ## Confidence block.
Return ONLY: {"status":"done","components":N,"file":"<FORTIFY_DIR>/ablation-candidates.jsonl","confidence":0.N}
```

**Health monitoring** (CLAUDE.md §8):

```bash
# audit-skip: resilience-replication
# Per-phase checkpoint required — F2 + F6 dispatch independent scientist agents that may both be in scope; separate variables prevent cross-phase masking.
_HM_F2=$("${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health-monitor-start.sh" "fortify-f2" 2>/dev/null)  # timeout: 5000
LAUNCH_AT_F2=$(echo "$_HM_F2" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT_F2=$(echo "$_HM_F2" | grep '^SENTINEL=' | cut -d= -f2)
```

Poll every 5 min: `find <FORTIFY_DIR> -newer "$CHECKPOINT_F2" -type f | wc -l` (`timeout: 5000`) — new files = alive; zero = stalled.

- **Hard cutoff: 15 min** no file activity → timed out
- **One extension (+5 min)**: if `tail -20 <FORTIFY_DIR>/candidates-analysis.md` shows active progress, grant one extension; second stall = hard cutoff
- **On timeout**: stop with `"fortify: Scientist timed out. Check <FORTIFY_DIR>/ for partial output."`; surface with ⏱

Read `ablation-candidates.jsonl` after scientist completes. If `--max-ablations <M>` specified and component count + 1 (for full variant) exceeds M: sort by `expected_importance` (HIGH first, then MEDIUM, then LOW), keep top M-1 components plus always include `full` sanity-check variant. **Log dropped components**: print a warning listing each dropped component by `component_id` and `expected_importance` so users can verify the scientist's importance estimates before proceeding. Include this list in the F7 report under `## Dropped Variants`.

**`--skip-run` early exit**: if `--skip-run` flag present, print candidate table (component_id, name, description, files, expected_importance) and exit. No ablation execution. Mark tasks F3, F4, F5, F6, F7 as `skipped` via TaskUpdate. Print: `"fortify: --skip-run — <N> candidates identified. Next: /research:fortify without --skip-run"`. Jump to F8 (skip-run variant).

## Step F3: Generate ablation variants

For each component from F2, one ablation variant: `no-<component-name>` (slugified — lowercase, spaces to hyphens). Plus one `full` variant (sanity check — should reproduce `best_metric`).

Write variant configs to `$FORTIFY_DIR/variants.jsonl` via Write tool — one JSON line per variant:

```json
{"variant_name": "full", "component_removed": null, "revert_commits": [], "revert_strategy": "none"}
{"variant_name": "no-<name>", "component_removed": "<name>", "revert_commits": ["<sha1>", "<sha2>"], "revert_strategy": "git-revert"}
```

## Step F4: Run ablation variants via worktrees

Run each variant **sequentially** — parallel worktrees would conflict.

**Before loop — store original working directory:**

```bash
ORIG_DIR="$(pwd)"  # timeout: 3000
```

**On interrupt** (user abort or unexpected error mid-loop): `cd "$ORIG_DIR"` first, then `git worktree prune` (`timeout: 15000`) to clean up partially created worktrees before exiting. The trap below makes interrupt cleanup automatic — never rely on prose-only cleanup discipline.

For each variant in `variants.jsonl`:

**4a. Create isolated worktree at best_commit:**

```bash
git worktree add "$WORKTREE_BASE/<variant_name>" <best_commit>  # timeout: 15000
```

**4a-trap. Register cleanup trap immediately after worktree creation** (guarantees removal on EXIT / INT / TERM, even on uncaught error):

```bash
WORKTREE_PATH="${FORTIFY_WORKTREE:-$WORKTREE_BASE/<variant_name>}"
# Append path to accumulator file — file persists across Bash calls; array variables do not
echo "$WORKTREE_PATH" >> /tmp/fortify-worktree-paths-$$.txt
# Trap reads full accumulator — covers all variants created so far, not just current
trap 'while IFS= read -r _wt; do git worktree remove --force "$_wt" 2>/dev/null; done < /tmp/fortify-worktree-paths-$$.txt 2>/dev/null; rm -f /tmp/fortify-worktree-paths-$$.txt' EXIT INT TERM
```

The accumulator file is initialized before the variant loop begins (first write creates it). Each variant appends its path and re-registers the trap to cover all paths added so far. The explicit `git worktree remove` in 4f remains for happy-path cleanup; the trap is a safety net for interrupted loops only. Use `$$` (parent PID) as suffix to avoid collision across concurrent invocations.

**4b. Navigate into worktree** (two separate Bash calls — cd first, then command):

```bash
cd "$WORKTREE_BASE/<variant_name>"  # timeout: 3000
```

**4c. Apply revert (skip for `full` variant):**

For `full` variant: no changes — proceed to 4d.

For `no-<component>` variant: revert component's commits.

**IMPORTANT — order matters**: revert in **reverse chronological order** (newest first) to avoid conflicts. If `revert_commits` from `variants.jsonl` is chronological (oldest first), reverse before reverting:

```bash
# Extract revert_commits for current variant from variants.jsonl (VARIANT_NAME set in loop)
REVERT_COMMITS_RAW=$(python -c "import sys,json; [print(*v['revert_commits']) for v in map(json.loads,open('$FORTIFY_DIR/variants.jsonl')) if v['variant_name']==sys.argv[1]]" "$VARIANT_NAME" 2>/dev/null)  # timeout: 5000
[ -z "$REVERT_COMMITS_RAW" ] && { echo "⚠ No revert_commits for $VARIANT_NAME — skipping"; echo '{"variant":"'$VARIANT_NAME'","status":"revert-missing"}' >> "$FORTIFY_DIR/results.jsonl"; continue; }
# Sort newest-first for conflict-free revert (portable awk reverse — avoids tac not available on macOS)
REVERT_COMMITS_SORTED=$(echo "$REVERT_COMMITS_RAW" | tr ' ' '\n' | awk '{lines[NR]=$0} END{for(i=NR;i>=1;i--) print lines[i]}' | tr '\n' ' ')
git revert $REVERT_COMMITS_SORTED --no-edit  # timeout: 15000
```

If revert produces merge conflicts: append `{"variant":"<name>","status":"revert-conflict",...}` to `results.jsonl`, jump to 4f (cleanup).

**4d. Run metric_cmd in worktree:**

```bash
<metric_cmd>  # timeout: 360000
```

Parse stdout for numeric metric value. If command fails or no numeric output: record `status: "metric-failed"`, jump to 4f.

**4e. Run guard_cmd in worktree:**

```bash
<guard_cmd>  # timeout: 360000
```

Record guard result: `"pass"` (exit 0) or `"fail"` (non-zero).

**4f. Cleanup worktree (INVARIANT — must execute even if 4c/4d/4e fail):**

```bash
cd "$ORIG_DIR"  # timeout: 3000
```

```bash
git worktree remove --force "$WORKTREE_BASE/<variant_name>"  # timeout: 15000
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
_HM_F6=$("${CLAUDE_PLUGIN_ROOT:-plugins/research}/bin/health-monitor-start.sh" "fortify-f6" 2>/dev/null)  # timeout: 5000
LAUNCH_AT_F6=$(echo "$_HM_F6" | grep '^LAUNCH_AT=' | cut -d= -f2)
CHECKPOINT_F6=$(echo "$_HM_F6" | grep '^SENTINEL=' | cut -d= -f2)
```

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")` with health monitoring (same 15-min cutoff, one 5-min extension — poll `find <FORTIFY_DIR> -name "reviewer-qa.md" -newer "$CHECKPOINT_F6" | wc -l`):

```markdown
Act as a peer reviewer for <venue>.

Read:
- ablation results at <FORTIFY_DIR>/results.jsonl
- importance ranking at <FORTIFY_DIR>/importance-ranking.json
- original program.md at <path>

Generate:
1. 5–7 likely reviewer questions calibrated to <venue> standards
   (CVPR/NeurIPS/ICML: expect thorough ablations, statistical significance, compute budget justification; workshop: lighter bar)
2. For each question: a data-backed answer referencing specific ablation results
3. A supplementary material draft section with the ablation table (LaTeX-ready)

Write to <FORTIFY_DIR>/reviewer-qa.md.
Include ## Confidence block.
Return ONLY: {"status":"done","questions":N,"file":"<FORTIFY_DIR>/reviewer-qa.md","confidence":0.N}
```

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
