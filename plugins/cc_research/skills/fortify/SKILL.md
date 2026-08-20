---
name: fortify
description: Systematic ablation study runner. After research:run finds improvements, fortify identifies component candidates from git diff + diary, creates isolated git worktrees per ablation (main repo never modified), runs metric+guard in each worktree, ranks component importance, and optionally generates reviewer Q&A calibrated to a target venue.
argument-hint: '[<run-id>|<program.md>] [--venue <CVPR|NeurIPS|ICML|workshop>] [--max-ablations <N>] [--skip-run] [--keep "<items>"]'
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
METRIC_TIMEOUT_MS:        360000 (6 min — deliberately larger than run's 120s/300s VERIFY_TIMEOUT_SEC, to accommodate slower ablation-variant runs)
GUARD_TIMEOUT_MS:         360000
GIT_OP_TIMEOUT_MS:        15000
SANITY_DIVERGENCE_PCT:    2.0 (full-variant vs best_metric mismatch threshold)
IMPORTANCE_CLASS_CRITICAL: 50.0 (% of full metric lost)
IMPORTANCE_CLASS_SIGNIFICANT: 10.0
FORTIFY_DIR_BASE:         .experiments
STATE_DIR_BASE:           .experiments/state
METRIC_CMD_SOURCE:        state.json .config.metric_cmd (campaign's real metric — no fail-open default; env METRIC_CMD overrides)
GUARD_CMD_SOURCE:         state.json .config.guard_cmd (campaign's real guard — no fail-open default; env GUARD_CMD overrides)
```

</constants>

**Environment overrides** — set these before invoking the skill to override per-variant defaults:

- `METRIC_CMD` — command run inside each variant worktree to measure the ablation metric (override; default sourced from source-run `state.json` `.config.metric_cmd`)
- `GUARD_CMD` — command run inside each variant worktree to detect regressions (override; default sourced from source-run `state.json` `.config.guard_cmd`)
- `STATE_DIR_BASE` — base directory for source-run state lookups (default: `.experiments/state`)
- `FORTIFY_DIR_BASE` — base directory for per-run fortify artifacts (default: `.experiments`)

The constants block defaults above are YAML-only — bash blocks read environment variables (with `${VAR:-default}` fallback) and never source values directly from YAML.

<compaction>

- Key boundaries: end of F2 — ablation candidates identified by scientist; end of F4 — all ablation variant worktrees completed.
- Preserve at F2: FORTIFY_DIR (TMPDIR key), RUN_ID (TMPDIR key), ablation-candidates.jsonl path, best_metric from source run.
- Preserve at F4: FORTIFY_DIR, RUN_ID, results.jsonl path — ready for F5 importance ranking.
- F4 loop is resume-safe: 4a-guard skips variants already terminal (non-timeout) in results.jsonl, so a mid-loop compaction resumes at the first pending variant — never re-runs a completed ablation; a timed-out variant still retries.
- Clear at F1 start (stale prior run) and at start of F8 terminal summary.

</compaction>

<workflow>

<!-- Agent resolution: see _RESEARCH_SHARED/agent-resolution.md -->

## Agent Resolution

**Agent resolution**: load and follow the protocol below. Contains foundry check + fallback table. If foundry not installed: use table to substitute each `foundry:X` with `general-purpose`. Agent this skill dispatches: `research:scientist` (same plugin — no fallback if research plugin installed).

```bash
# loads: compaction-contract.md
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_RESEARCH_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/resolve_shared.py" 2>/dev/null)  # timeout: 5000
[ -z "$_RESEARCH_SHARED" ] && { echo "! Plugin path resolution failed — ensure research plugin installed and CLAUDE_PLUGIN_ROOT set, or invoke /research:fortify from project root."; exit 1; }
echo "$_RESEARCH_SHARED" > "${TMPDIR:-/tmp}/research-shared-${CSID}"  # cold resolve — every later site reads this sentinel instead of re-running python
cat "$_RESEARCH_SHARED/agent-resolution.md"
```

| Agent | Fallback if absent |
| -- | -- |
| `research:scientist` | `general-purpose` (ablation candidate identification and reviewer Q&A quality reduced — **⚠ general-purpose agent may not emit the JSON envelope this skill parses; surface partial output and surface ⚠ in F7 report**) |

## CRITICAL: Worktree-based isolation

**Do NOT use `git checkout -b <branch>` for ablations** — dirties main working tree, corrupts concurrent tool calls. Each ablation gets own git worktree under `$FORTIFY_DIR/worktrees/<variant>`, created from `best_commit`. Main working tree NEVER modified. Cleanup: `git worktree remove --force` per variant; `git worktree prune` on interrupt.

## Fortify Mode (Steps F1–F8)

Triggered by `fortify` or `fortify <run-id|program.md>`.

**Task tracking**: create tasks for F1, F2, F3, F4, F5, F6, F7, F8 at start — before any tool calls.

## Step F1: Locate source run, parse flags, and validate judge approval

Extract flags: `--venue <VENUE>`, `--max-ablations <N>`, `--skip-run`, `--keep "<items>"`.

```bash
# --keep value (compaction-contract.md §keep)
KEEP_ITEMS=""
if [[ "$ARGUMENTS" =~ --keep[[:space:]]\"([^\"]+)\" ]]; then
    KEEP_ITEMS="${BASH_REMATCH[1]}"
fi
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# stale contract cleanup (compaction-contract.md §Lifecycle)
rm -f .temp/state/skill-contract.md  # timeout: 5000
echo "${KEEP_ITEMS:-}" > "${TMPDIR:-/tmp}/fortify-keep-items-${CSID}"  # for F2/F4 contract

# empty = no --venue → F6 skip rule fires; no default venue
VENUE=""
if [[ "$ARGUMENTS" =~ --venue[[:space:]]+([^[:space:]]+) ]]; then
    VENUE="${BASH_REMATCH[1]}"
fi
case "$VENUE" in
  ""|CVPR|NeurIPS|ICML|workshop) ;;
  *) echo "fortify: invalid --venue '$VENUE' — valid: CVPR, NeurIPS, ICML, workshop"; exit 2 ;;
esac
echo "$VENUE" > "${TMPDIR:-/tmp}/fortify-venue-${CSID}"  # for F6 (Check 41)
```

**Unsupported flag check**: load and follow the protocol below. Supported flags for this skill: `--venue`, `--max-ablations`, `--skip-run`, `--keep`.

```bash
# loads: unsupported-flag-protocol.md
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _RESEARCH_SHARED < "${TMPDIR:-/tmp}/research-shared-${CSID}" 2>/dev/null || _RESEARCH_SHARED=""  # warm read (Check 41)
cat "$_RESEARCH_SHARED/unsupported-flag-protocol.md"
```

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
```

> `METRIC_CMD`/`GUARD_CMD` are NOT defaulted here — they are sourced from the source-run `state.json` after `$RUN_ID` resolves (see block below). No fail-open default: `git diff --stat HEAD` always exits 0, so a defaulted guard would be a no-op that never catches ablation regressions.

**Assign `$RUN_ID`** from input resolution above (must be set before guard block uses it):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"  # default (Check 41)
_ARG1=$(echo "$ARGUMENTS" | awk '{print $1}')
if [ -n "$_ARG1" ] && [ "${_ARG1#-}" = "$_ARG1" ] && [ ! -f "$_ARG1" ] && [ -d "$STATE_DIR_BASE/$_ARG1" ]; then
  RUN_ID="$_ARG1"
elif [ -n "$_ARG1" ] && [ -f "$_ARG1" ]; then
  # program.md path  <!-- loads: find_run_id.py -->
  RUN_ID=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/find_run_id.py" "$STATE_DIR_BASE" --match-program "$_ARG1" 2>/dev/null)
else
  RUN_ID=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/find_run_id.py" "$STATE_DIR_BASE" 2>/dev/null)
fi
[ -z "$RUN_ID" ] && { echo "fortify: No completed run found. Run /research:run first."; exit 1; }
echo "$RUN_ID" > "${TMPDIR:-/tmp}/fortify-run-id-${CSID}"  # for later blocks (Check 41)
```

**Source `metric_cmd`/`guard_cmd` from the campaign** — env override first, then source-run `state.json` `.config`; fail closed if neither present (a defaulted `git diff --stat HEAD` guard always exits 0 → no-op that never catches regressions):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"  # default (Check 41)
IFS= read -r RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || RUN_ID=""  # reload (Check 41)
STATE_JSON="$STATE_DIR_BASE/$RUN_ID/state.json"
METRIC_CMD="${METRIC_CMD:-$(jq -r '.config.metric_cmd // empty' "$STATE_JSON" 2>/dev/null)}"
GUARD_CMD="${GUARD_CMD:-$(jq -r '.config.guard_cmd // empty' "$STATE_JSON" 2>/dev/null)}"
if [ -z "$METRIC_CMD" ] || [ -z "$GUARD_CMD" ]; then
  echo "fortify: BLOCKED — $STATE_JSON .config missing metric_cmd/guard_cmd; ablation needs the campaign's real metric and guard commands."
  echo "Re-run /research:run to regenerate state.json, or set METRIC_CMD/GUARD_CMD in the environment."
  exit 1
fi
# echo not printf — 4d/4e reload via `read -r VAR<f||VAR=""`; no trailing newline → read fails → || wipes value → false BLOCK
echo "$METRIC_CMD" > "${TMPDIR:-/tmp}/fortify-metric-cmd-${CSID}"  # for 4d (Check 41)
echo "$GUARD_CMD" > "${TMPDIR:-/tmp}/fortify-guard-cmd-${CSID}"    # for 4e (Check 41)
```

**Guard: judge approval required.** Judge skill writes verdict to `.reports/research/judge-<branch>-<date>.md` — scan for APPROVED verdict line:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"  # default (Check 41)
IFS= read -r RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || RUN_ID=""  # reload (Check 41)
JUDGE_VERDICT_FILE=$(ls -t .reports/research/judge-*.md 2>/dev/null | head -1)  # timeout: 5000
if [ -z "$JUDGE_VERDICT_FILE" ]; then
  echo "fortify: BLOCKED — no judge verdict found in .reports/research/."
  echo "Ablation studies require an approved baseline. Run: /research:judge <program.md>"
  exit 1
fi
JUDGE_VERDICT=$(grep -i '^[*]*[Vv]erdict[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*[Vv]erdict[: ]+//' | sed 's/[[:space:]]*$//')  # trailing strip only — keep internal spaces ("NEEDS REVISION")

PROGRAM_FILE=$(grep -iE '^[*]*(Program(_file)?|Program file)[*]*:' "$JUDGE_VERDICT_FILE" | head -1 | sed 's/\*\*//g' | sed -E 's/.*:[[:space:]]*//' | sed 's/[[:space:]]*$//')
# F-02: empty PROGRAM_FILE — no program metadata, can't verify
if [ -z "$PROGRAM_FILE" ]; then
    echo "fortify: BLOCKED — judge verdict missing Program: field; cannot verify verdict applies to current experiment."
    echo "Re-run: /research:judge <program.md> to generate a fresh verdict with required metadata."
    exit 1
fi
# explicit state.json path — never CWD-relative
STATE_PROGRAM=$(jq -r '.program_file // ""' "$STATE_DIR_BASE/$RUN_ID/state.json" 2>/dev/null)
# realpath both — judge report may be relative, state.json absolute; raw compare would false-BLOCK
_PF_ABS=$(realpath "$PROGRAM_FILE" 2>/dev/null || echo "$PROGRAM_FILE")
_SP_ABS=$(realpath "$STATE_PROGRAM" 2>/dev/null || echo "$STATE_PROGRAM")
if [ -n "$STATE_PROGRAM" ] && [ -n "$PROGRAM_FILE" ] && [ "$_PF_ABS" != "$_SP_ABS" ]; then
    printf "! BLOCKED — judge verdict references program '%s' but current experiment is for '%s'\n" "$PROGRAM_FILE" "$STATE_PROGRAM"
    printf "Run: /research:judge %s\n" "$STATE_PROGRAM"
    exit 1
fi
if [ -n "$PROGRAM_FILE" ] && [ ! -f "$PROGRAM_FILE" ]; then
    printf "! BLOCKED — program file %s referenced by judge verdict not found on disk\n" "$PROGRAM_FILE"
    exit 1
fi
echo "$PROGRAM_FILE" > "${TMPDIR:-/tmp}/fortify-program-file-${CSID}"  # for F6 (Check 41)
echo "$JUDGE_VERDICT" > "${TMPDIR:-/tmp}/fortify-judge-verdict-${CSID}"  # for gate block; echo not printf — newline keeps read exit 0 (Check 41)
```

Verify `JUDGE_VERDICT == "APPROVED"`. The program cross-match above guarantees the verdict was issued for the current experiment — fortify cannot ablate against a different program's verdict. Apply explicit bash gate — prose alone never halts execution:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# REJECTED default = fail closed; gate appends actual verdict itself, message never interpolates it
_GATE_MSG="fortify: BLOCKED — no APPROVED judge verdict found for this program; stopping before implementation (F1–F7).
Ablation studies require an approved baseline. Run: /research:judge <program.md>"
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/gate-on-sentinel.py" "${TMPDIR:-/tmp}/fortify-judge-verdict-${CSID}" APPROVED REJECTED "$_GATE_MSG" || exit 1
```

> Note: do NOT infer from `methodology.md` alone — `methodology_rating: sound` is one input to verdict, not verdict itself. Only `## Verdict` line in judge output file is authoritative.

Read from `state.json`: `goal`, `best_metric`, `best_commit`, `config` (including `metric_cmd`, `guard_cmd`, `compute`), `program_file`.

Also read `baseline_commit` — iteration 0 commit from `experiments.jsonl` (first line, `status: "baseline"`, field `"commit"`).

**Pre-compute run directory** (each in separate Bash call):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
FORTIFY_DIR=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/make_run_dir.py" "fortify" ".experiments" 2>/dev/null)  # timeout: 5000
[ -z "$FORTIFY_DIR" ] && { echo "! make_run_dir.py failed — ensure research plugin installed"; exit 1; }
mkdir -p "$FORTIFY_DIR"
echo "$FORTIFY_DIR" > "${TMPDIR:-/tmp}/fortify-dir-${CSID}"  # for F2/F4-loop/F6; make_run_dir non-idempotent (Check 41)
WORKTREE_BASE="$FORTIFY_DIR/worktrees"
mkdir -p "$WORKTREE_BASE"
STATE_DIR="${STATE_DIR_BASE:-.experiments/state}/fortify-$(basename "$FORTIFY_DIR")"
mkdir -p "$STATE_DIR"
```

## Step F2: Identify ablation candidates via scientist

Gather two inputs for scientist:

1. **Git diff**: run `git diff <baseline_commit>...<best_commit> --stat` (summary) and full `git diff <baseline_commit>...<best_commit>`. If full diff exceeds ~200 lines, write to `$FORTIFY_DIR/diff.txt` via Write tool; otherwise inline in prompt.
2. **Experiment history**: paths to `experiments.jsonl` and `diary.md` from source run directory.

> **Agent budget** — each spawn costs ~120,851 tok of fixed overhead (~73 tool-calls' worth) plus ~12.0 s/call, so work under ~73 calls is cheaper done inline: spawn nothing. Keep each agent near ~55 tool-calls; past ~60 they stall without returning an envelope, forcing reconstruction from disk. Every spawn prompt must require an envelope even on exhaustion — `partial: true` plus what was finished.

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")` with health monitoring (15-min cutoff, one 5-min extension — same pattern as judge J3).

Before building the prompt, substitute all bash variables into a single concrete string — never pass literal `<FORTIFY_DIR>` or `<path>` placeholders to the agent:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"  # default (Check 41)
IFS= read -r RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || RUN_ID=""  # reload (Check 41)
IFS= read -r FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || FORTIFY_DIR=""  # reload (Check 41)
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

**Synchronous spawn note**: the F2 scientist is spawned synchronously (not `run_in_background=true`), so CLAUDE.md §6 sentinel polling is unreachable mid-call. Timeout is handled post-hoc — after Agent() returns, check `$FORTIFY_DIR/ablation-candidates.jsonl`; if missing or empty, stop with `"fortify: Scientist timed out. Check $FORTIFY_DIR/ for partial output."` and surface with ⏱.

Read `ablation-candidates.jsonl` after scientist completes. If `--max-ablations <M>` specified and component count + 1 (for full variant) exceeds M: sort by `expected_importance` (HIGH first, then MEDIUM, then LOW), keep top M-1 components plus always include `full` sanity-check variant. **Log dropped components**: print a warning listing each dropped component by `component_id` and `expected_importance` so users can verify the scientist's importance estimates before proceeding. Include this list in the F7 report under `## Dropped Variants`.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# boundary 1: F2 done, candidates ready (compaction-contract.md §Lifecycle)
IFS= read -r _RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || _RUN_ID=""
IFS= read -r _FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || _FORTIFY_DIR=""
IFS= read -r _KEEP < "${TMPDIR:-/tmp}/fortify-keep-items-${CSID}" 2>/dev/null || _KEEP=""
_KEEP_APPEND=""; [ -n "$_KEEP" ] && _KEEP_APPEND="; user-keep: $_KEEP"
mkdir -p .temp/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: research:fortify · phase: ablation-execution (after F2 candidates identified)"
    echo "- run-dir: ${_FORTIFY_DIR}"
    echo "- preserve: run-id=${_RUN_ID}, fortify-dir=${_FORTIFY_DIR}, candidates=${_FORTIFY_DIR}/ablation-candidates.jsonl, variants=${_FORTIFY_DIR}/variants.jsonl${_KEEP_APPEND}"
    echo "- next: F3 generate variants → F4 run worktrees sequentially"
} > .temp/state/skill-contract.md  # timeout: 5000
```

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
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
ORIG_DIR="$(pwd)"  # timeout: 3000
echo "$ORIG_DIR" > "${TMPDIR:-/tmp}/fortify-orig-dir-${CSID}"  # for 4f cleanup cd (Check 41)
WORKTREE_PATHS_FILE=$(mktemp -t fortify-XXXX) || { echo "! BLOCKED — mktemp failed (tmpfs full or permission denied); cannot create cleanup accumulator. Aborting."; exit 1; }  # timeout: 3000
echo "$WORKTREE_PATHS_FILE" > "${TMPDIR:-/tmp}/fortify-paths-ptr-${CSID}"
echo 1 > "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}"  # 1-based cursor — loop's only identity across fences (Check 41)

STATE_DIR_BASE="${STATE_DIR_BASE:-.experiments/state}"  # default (Check 41)
IFS= read -r RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || RUN_ID=""  # reload (Check 41)
best_commit=$(jq -r '.best_commit // empty' "$STATE_DIR_BASE/$RUN_ID/state.json" 2>/dev/null)
echo "$best_commit" > "${TMPDIR:-/tmp}/fortify-source-best-commit-${CSID}"  # raw value (Check 41)

# F-04: must be concrete SHA — branch tip would advance + pollute history on later revert
if ! best_commit_sha=$(git rev-parse --verify "$best_commit^{commit}" 2>/dev/null); then
    echo "! BLOCKED — best_commit '$best_commit' does not resolve to a commit. Re-run source experiment or correct state.json."
    exit 1
fi
best_commit="$best_commit_sha"  # worktree add always sees a SHA → detached HEAD
echo "$best_commit" > "${TMPDIR:-/tmp}/fortify-best-commit-${CSID}"  # for 4a worktree-add (Check 41)
```

**On interrupt** (user abort or unexpected error mid-loop): `cd "$ORIG_DIR"` first, then `git worktree prune` (`timeout: 15000`) to clean up partially created worktrees before exiting. Interrupt cleanup is manual by necessity — a shell `trap` cannot survive the Bash call that registers it (see 4a-register), so the accumulator file is the durable record of what needs removing; re-run the post-loop sweep block below to drain it.

**Loop control**: run 4a-init through 4g once per line of `variants.jsonl`, in file order. The iteration cursor lives in the `fortify-variant-idx-${CSID}` sentinel (initialized to 1 above, advanced at 4g) — never in a shell variable, which would die between blocks. Stop the loop when 4a-init reports the cursor is past the last line.

**4a-init. Read the current variant's spec from `variants.jsonl` by cursor** (must run before any 4a/4b/4c/4d/4e block, which all read the name it persists):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || FORTIFY_DIR=""  # reload (Check 41)
IFS= read -r _VIDX < "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}" 2>/dev/null || _VIDX=1
_TOTAL=$(grep -c . "$FORTIFY_DIR/variants.jsonl" 2>/dev/null) || _TOTAL=0  # `|| echo 0` appends a second 0: grep -c prints 0 *and* exits 1 on zero matches, and the 2>/dev/null below then hides the resulting bad-number error
if [ "$_VIDX" -gt "$_TOTAL" ] 2>/dev/null; then
    echo "FORTIFY_LOOP_DONE=1 — all $_TOTAL variants processed; proceed to post-loop delta computation"
    exit 0
fi
_RAW_NAME=$(sed -n "${_VIDX}p" "$FORTIFY_DIR/variants.jsonl" 2>/dev/null | jq -r '.variant_name // empty' 2>/dev/null)
# no invented fallback — synthesized name would collapse every iteration onto one worktree path
if [ -z "$_RAW_NAME" ] || [ "$_RAW_NAME" = "null" ]; then
    echo "! BLOCKED — variants.jsonl line ${_VIDX} has no readable .variant_name; check F3 output. Halting F4."
    exit 1
fi
VARIANT_NAME="variant-$(echo "$_RAW_NAME" | tr ' ' '-' | tr '[:upper:]' '[:lower:]' | sed 's/^variant-//')"
echo "$VARIANT_NAME" > "${TMPDIR:-/tmp}/fortify-variant-name-${CSID}"  # for 4a–4f this iteration (Check 41)
echo "→ variant ${_VIDX}/${_TOTAL}: $VARIANT_NAME"
```

`! BLOCKED` or `FORTIFY_LOOP_DONE=1` printed → do NOT run 4a–4g for this iteration; halt the loop and continue at the post-loop step.

**4a-guard. Resume guard — skip variants already recorded terminal in `results.jsonl`:**

```bash
# resume guard — w/o it, compact+resume re-runs completed ablations. Non-timeout terminal only; timeout still retries.
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r VARIANT_NAME < "${TMPDIR:-/tmp}/fortify-variant-name-${CSID}" 2>/dev/null || VARIANT_NAME=""  # reload (Check 41)
_VN_RAW="${VARIANT_NAME#variant-}"
IFS= read -r _FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || _FORTIFY_DIR=""; _RESULTS="$_FORTIFY_DIR/results.jsonl"
if [ -f "$_RESULTS" ] && grep -E "\"variant\":\"(variant-)?$_VN_RAW\"" "$_RESULTS" 2>/dev/null | grep -qE '"status":"(completed|revert-conflict|revert-missing|metric-failed)"'; then
    # no shell loop here (F4 is orchestrated) — advance cursor + emit token so skip is real, not just printed
    IFS= read -r _VIDX < "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}" 2>/dev/null || _VIDX=1
    echo "$((_VIDX + 1))" > "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}"
    echo "→ $_VN_RAW already terminal (non-timeout) in results.jsonl — skipping (resume)"
    echo "FORTIFY_SKIP_VARIANT=1"
    exit 0
fi
```

`FORTIFY_SKIP_VARIANT=1` printed → the cursor is already advanced: go straight back to 4a-init for the next variant. Do NOT run 4a–4g for this one.

**4a. Create isolated worktree at best_commit:**

```bash
# inline: `git` stays first token (allow-list match); CSID inlined, same reason (Check 41)
git worktree add "$(cat "${TMPDIR:-/tmp}/fortify-dir-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)/worktrees/$(cat "${TMPDIR:-/tmp}/fortify-variant-name-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)" "$(cat "${TMPDIR:-/tmp}/fortify-best-commit-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)"  # timeout: 15000
```

**4a-register. Record the worktree path in the cleanup accumulator** immediately after creation:

```bash
# reload — shell var dies between Bash calls (Check 41)
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r WORKTREE_PATHS_FILE < "${TMPDIR:-/tmp}/fortify-paths-ptr-${CSID}" 2>/dev/null || WORKTREE_PATHS_FILE=""
[ -z "$WORKTREE_PATHS_FILE" ] && WORKTREE_PATHS_FILE="${TMPDIR:-/tmp}/fortify-worktree-paths-fallback-${CSID}"
IFS= read -r FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || FORTIFY_DIR=""; WORKTREE_BASE="$FORTIFY_DIR/worktrees"  # reload (Check 41)
IFS= read -r VARIANT_NAME < "${TMPDIR:-/tmp}/fortify-variant-name-${CSID}" 2>/dev/null || VARIANT_NAME=""  # reload (Check 41)
WORKTREE_PATH="${FORTIFY_WORKTREE:-$WORKTREE_BASE/$VARIANT_NAME}"
echo "$WORKTREE_PATH" >> "$WORKTREE_PATHS_FILE"  # file persists across Bash calls; array vars don't
```

**No `trap` here — deliberate.** A `trap ... EXIT` registered in this fence fires when *this block* ends, moments after `git worktree add` created the worktree: it would delete the worktree the loop is about to use, 4b's `cd` would fail, and 4c's `git revert` would then execute in the **main working tree** — the exact outcome the worktree-isolation invariant exists to prevent. Trap disposition is per-process and cannot outlive its own Bash call, so it can neither cover a later interrupt nor survive to the next block. Cleanup is therefore explicit: 4f per variant (happy path), plus the post-loop sweep and `git worktree prune` below (interrupted or skipped variants). The accumulator is pre-created via `mktemp` before the loop; `mktemp` ensures collision-free naming across concurrent invocations.

**4b. Navigate into worktree** (two separate Bash calls — cd first, then command):

```bash
# inline: `cd` stays first token; CSID inlined, same reason (Check 41)
cd "$(cat "${TMPDIR:-/tmp}/fortify-dir-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)/worktrees/$(cat "${TMPDIR:-/tmp}/fortify-variant-name-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)"  # timeout: 3000
```

**4b-assert. Confirm the `cd` actually landed inside a worktree** — run before 4c, in its own Bash call so CWD carries over:

```bash
pwd | grep -q '/worktrees/' || { echo "! BLOCKED — not inside a variant worktree (4b cd failed); refusing to run revert/metric/guard against the main repo"; exit 1; }  # timeout: 3000
```

`! BLOCKED` printed → do NOT run 4c/4d/4e. Nothing was created to clean up beyond the worktree itself: go to 4f, then 4g. Without this assertion a failed `cd` leaves CWD at the repo root and 4c's `git revert` commits into the user's checked-out branch.

**4c. Apply revert (skip for `full` variant):**

For `full` variant: no changes — proceed to 4d.

For `no-<component>` variant: revert component's commits.

**IMPORTANT — order matters**: revert in **reverse chronological order** (newest first) to avoid conflicts. If `revert_commits` from `variants.jsonl` is chronological (oldest first), reverse before reverting.

**Bash call 1 — extract and sort revert_commits via jq + awk** (no python; jq-based JSONL filter avoids per-iteration approval prompt):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || FORTIFY_DIR=""  # reload (Check 41)
IFS= read -r VARIANT_NAME < "${TMPDIR:-/tmp}/fortify-variant-name-${CSID}" 2>/dev/null || VARIANT_NAME=""  # reload (Check 41)
REVERT_COMMITS_RAW=$(jq -r --arg vn "$VARIANT_NAME" 'select(.variant_name==$vn) | .revert_commits[]' "$FORTIFY_DIR/variants.jsonl" 2>/dev/null | tr '\n' ' ')  # timeout: 5000
# no shell loop — emit skip token so 4d/4e are genuinely bypassed
[ -z "$REVERT_COMMITS_RAW" ] && { echo "⚠ No revert_commits for $VARIANT_NAME — skipping"; echo '{"variant":"'$VARIANT_NAME'","status":"revert-missing"}' >> "$FORTIFY_DIR/results.jsonl"; echo "FORTIFY_SKIP_VARIANT=1"; exit 0; }
# newest-first, portable awk reverse — no tac on macOS
REVERT_COMMITS_SORTED=$(echo "$REVERT_COMMITS_RAW" | tr ' ' '\n' | awk '{lines[NR]=$0} END{for(i=NR;i>=1;i--) print lines[i]}' | tr '\n' ' ')
echo "$REVERT_COMMITS_SORTED" > "${TMPDIR:-/tmp}/fortify-revert-sorted-${CSID}"  # for git-revert (Check 41)
```

**Bash call 2 — apply revert** (separated so first-token allow-list matches `git`):

```bash
# inline, unquoted (multi-SHA word-split); `git` stays first token (Check 41)
git revert $(cat "${TMPDIR:-/tmp}/fortify-revert-sorted-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null) --no-edit  # timeout: 15000
```

`FORTIFY_SKIP_VARIANT=1` printed by the block above → the worktree exists and must still be removed: jump to 4f (cleanup) then 4g, skipping 4d/4e.

If revert produces merge conflicts: append `{"variant":"<name>","status":"revert-conflict",...}` to `results.jsonl`, jump to 4f (cleanup).

**4d. Run metric_cmd in worktree:**

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r METRIC_CMD < "${TMPDIR:-/tmp}/fortify-metric-cmd-${CSID}" 2>/dev/null || METRIC_CMD=""  # reload (Check 41)
[ -z "$METRIC_CMD" ] && { echo "fortify: BLOCKED — metric_cmd not initialized in F1"; exit 1; }
$METRIC_CMD  # timeout: 360000 (state.json .config.metric_cmd)
METRIC_EXIT=$?
```

Parse stdout for numeric metric value. If command fails or no numeric output: record `status: "metric-failed"`, jump to 4f.

**4e. Run guard_cmd in worktree:**

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r GUARD_CMD < "${TMPDIR:-/tmp}/fortify-guard-cmd-${CSID}" 2>/dev/null || GUARD_CMD=""  # reload (Check 41)
[ -z "$GUARD_CMD" ] && { echo "fortify: BLOCKED — guard_cmd not initialized in F1"; exit 1; }
$GUARD_CMD  # timeout: 360000 (state.json .config.guard_cmd)
GUARD_EXIT=$?
```

Record guard result: `"pass"` (exit 0) or `"fail"` (non-zero).

**4f. Cleanup worktree (INVARIANT — must execute even if 4c/4d/4e fail):**

```bash
# inline: `cd` stays first token; CSID inlined, same reason (Check 41)
cd "$(cat "${TMPDIR:-/tmp}/fortify-orig-dir-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)"  # timeout: 3000
```

```bash
# inline: `git` stays first token; CSID inlined, same reason (Check 41)
git worktree remove --force "$(cat "${TMPDIR:-/tmp}/fortify-dir-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)/worktrees/$(cat "${TMPDIR:-/tmp}/fortify-variant-name-${CLAUDE_CODE_SESSION_ID:-$PPID}" 2>/dev/null)"  # timeout: 15000
```

**4g. Record result** — append one JSON line to `$FORTIFY_DIR/results.jsonl`:

```json
{"variant":"<name>","component_removed":"<name or null>","metric":0.0,"delta_from_full":0.0,"delta_pct":0.0,"guard":"pass|fail","status":"completed|revert-conflict|metric-failed|timeout","timestamp":"<ISO>"}
```

`delta_from_full` and `delta_pct` are placeholders — computed in post-loop step below.

**4g-advance. Move the cursor to the next variant**, then return to 4a-init:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _VIDX < "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}" 2>/dev/null || _VIDX=1
echo "$((_VIDX + 1))" > "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}"
```

After all variants processed (4a-init printed `FORTIFY_LOOP_DONE=1`) — sweep any worktree the per-variant 4f missed, then prune:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r WORKTREE_PATHS_FILE < "${TMPDIR:-/tmp}/fortify-paths-ptr-${CSID}" 2>/dev/null || WORKTREE_PATHS_FILE=""
# replaces removed 4a-trap — same accumulator, read once worktrees are finished
if [ -n "$WORKTREE_PATHS_FILE" ] && [ -f "$WORKTREE_PATHS_FILE" ]; then
    while IFS= read -r _wt; do
        [ -n "$_wt" ] && [ -d "$_wt" ] && git worktree remove --force "$_wt" 2>/dev/null
    done < "$WORKTREE_PATHS_FILE"
    rm -f "$WORKTREE_PATHS_FILE"
fi
rm -f "${TMPDIR:-/tmp}/fortify-variant-idx-${CSID}" "${TMPDIR:-/tmp}/fortify-paths-ptr-${CSID}"
```

```bash
git worktree prune  # timeout: 15000
```

`prune` only drops registrations whose directory is already gone. The inverse — directory present, never removed because the accumulator entry was never written (interrupt between `worktree add` and the append) — is invisible to it and to `git worktree list`. Sweep the variant root for those:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _FDIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || _FDIR=""
[ -n "$_FDIR" ] && python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_research}/bin/heal_git_artifacts.py" worktrees --root "$_FDIR/worktrees" --managed-prefix '*' --min-age-days 1 --apply  # timeout: 30000
```

> `--managed-prefix '*'` is safe **only** because `--root` is fortify's own variant directory — every child there is fortify's. Never widen it to a shared root. Variants holding uncommitted work are reported, not deleted. `--apply` is unattended here for parity with the `git worktree remove --force` above (same trees, same run) — but print the output verbatim whenever it removed anything, so the sweep is never silent.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# boundary 2: F4 all variants complete (compaction-contract.md §Lifecycle)
IFS= read -r _RUN_ID < "${TMPDIR:-/tmp}/fortify-run-id-${CSID}" 2>/dev/null || _RUN_ID=""
IFS= read -r _FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || _FORTIFY_DIR=""
IFS= read -r _KEEP < "${TMPDIR:-/tmp}/fortify-keep-items-${CSID}" 2>/dev/null || _KEEP=""
_KEEP_APPEND=""; [ -n "$_KEEP" ] && _KEEP_APPEND="; user-keep: $_KEEP"
mkdir -p .temp/state  # timeout: 5000
{
    echo "## Active Skill Contract"
    echo "- skill: research:fortify · phase: post-ablation (after F4 worktrees complete)"
    echo "- run-dir: ${_FORTIFY_DIR}"
    echo "- preserve: run-id=${_RUN_ID}, fortify-dir=${_FORTIFY_DIR}, results=${_FORTIFY_DIR}/results.jsonl${_KEEP_APPEND}"
    echo "- next: F5 rank importance → F6 reviewer Q&A → F7 report"
} > .temp/state/skill-contract.md  # timeout: 5000
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
  - **MARGINAL**: importance < 10% **Sign convention check** — after computing signed_delta for all variants, verify:

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

Spawn `research:scientist` via `Agent(subagent_type="research:scientist", prompt="...")`. **Synchronous spawn note**: spawned synchronously (not `run_in_background=true`) — CLAUDE.md §6 sentinel polling is unreachable mid-call. After Agent() returns, check `$FORTIFY_DIR/reviewer-qa.md`; if missing or empty, treat as timed out and surface with ⏱.

Before building the prompt, substitute all bash variables into a single concrete string — never pass literal `<FORTIFY_DIR>`, `<path>`, or `<venue>` placeholders to the agent:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r VENUE < "${TMPDIR:-/tmp}/fortify-venue-${CSID}" 2>/dev/null || VENUE=""  # reload F1 --venue parse (Check 41)
[ -z "$VENUE" ] && { echo "fortify: F6 skipped — no --venue flag"; exit 0; }  # no default venue: an unset flag must skip, not silently review at workshop bar
IFS= read -r PROGRAM_FILE < "${TMPDIR:-/tmp}/fortify-program-file-${CSID}" 2>/dev/null || PROGRAM_FILE=""  # reload (Check 41)
IFS= read -r FORTIFY_DIR < "${TMPDIR:-/tmp}/fortify-dir-${CSID}" 2>/dev/null || FORTIFY_DIR=""  # reload (Check 41)
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
Title:       Fortify — [goal]
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

```bash
rm -f .temp/state/skill-contract.md  # contract done (compaction-contract.md §Lifecycle)  # timeout: 5000
```

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
_FOUNDRY_CALIBRATE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/skills/calibrate/modes 2>/dev/null | head -1); [ -z "$_FOUNDRY_CALIBRATE" ] && _FOUNDRY_CALIBRATE="plugins/cc_foundry/skills/calibrate/modes"
# See: $_FOUNDRY_CALIBRATE/skills.md
```

</calibration>

<notes>

- **Worktree invariant** — cleanup (`git worktree remove --force`) must run even if metric/guard fails. No stale worktrees. Final `git worktree prune` catches missed cleanup.
- **Main repo never modified** — all ablation work in worktrees. Main working tree stays clean.
- **Sequential execution** — variants run one at a time. Parallel worktrees would require separate detached HEADs and complicate cleanup.
- **Bash tool `timeout` parameter** — never shell `timeout` wrapper. Pass `timeout: <ms>` on Bash tool call.
- **Judge prerequisite** — fortify refuses without APPROVED judge verdict. Prevents ablation on unapproved methodologies.
- **`--skip-run` for planning** — generates candidate list without running ablations. Useful for reviewing what would be ablated before committing compute.
- **`--skip-run` scope**: flag skips ablation *execution* only — source run (`research:run`) must already be complete. Does not affect source run.
- **Fortify run directories** don't write `result.jsonl` — exempt from 30-day TTL cleanup (no `result.jsonl` = cleanup skipped); remove manually when done (`rm -rf .experiments/fortify-*/`)
- **Compute mode**: local execution only. `--compute` and `--colab` passthrough not implemented — contributions welcome. Until then, fortify runs `metric_cmd`/`guard_cmd` directly in each worktree on local machine.
- **Revert conflicts expected** — when commits interleave (component A's commit touches same lines as B's), revert may conflict. Recorded as `revert-conflict`, not treated as error.

</notes>
