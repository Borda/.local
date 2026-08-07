# 🔬 research — Claude Code Plugin

ML research plugin: two specialist agents, nine slash-command skills — literature search, experiment design, methodology review, metric-driven improvement loops, automated research sweeps, Kaggle competition notebook generation. Profile-first, judge-gated pipeline: compute spent only on experiments worth running.

> Works standalone — `foundry` not required. Without it: agent dispatches fall back to `general-purpose` with role descriptions (lower quality); `research:run` commit-sentinel guard (foundry's `commit-guard.js` hook) inert — atomic-commit protection off. Installing `foundry` unlocks specialized agents (`foundry:sw-engineer`, `foundry:perf-optimizer`, etc.) plus commit guard — strongly recommended.

______________________________________________________________________

<details>

<summary><strong>📋 Contents</strong></summary>

- [What is research?](#what-is-research)
- [Why research?](#why-research)
- [Install](#install)
- [Quick start](#quick-start)
- [Skills reference](#skills-reference)
  - [`/research:topic`](#researchtopic--sota-literature-search)
  - [`/research:plan`](#researchplan--experiment-configuration-wizard)
  - [`/research:judge`](#researchjudge--methodology-gate)
  - [`/research:run`](#researchrun--metric-improvement-loop)
  - [`/research:sweep`](#researchsweep--non-interactive-end-to-end-pipeline)
  - [`/research:verify`](#researchverify--paper-vs-code-consistency-audit)
  - [`/research:fortify`](#researchfortify--ablation-study-runner)
  - [`/research:retro`](#researchretro--post-run-retrospective)
  - [`/research:kaggle`](#researchkaggle--kaggle-competition-notebook)
  - [`/research:setup`](#researchsetup--post-install-rule-delivery)
- [Agents reference](#agents-reference)
  - [`research:scientist`](#researchscientist)
  - [`research:data-steward`](#researchdata-steward)
- [Workflow overview](#workflow-overview)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing and feedback](#contributing-and-feedback)
- [Acknowledgments](#acknowledgments)

</details>

______________________________________________________________________

## 🤔 What is research?

`research` turns messy iterative ML improvement into structured pipeline. Start with literature evidence, write machine-readable experiment spec, get methodology review before spending GPU time, run automated improvement loop — commits every change atomically, rolls back anything that regresses target metric.

For ML engineers and researchers tired of ad-hoc experiment management — runs never properly scoped, no record of what was tried, 20 GPU-hours lost to design flaw catchable in 5 minutes.

______________________________________________________________________

## 🎯 Why research?

Without: intuition → experiment → no help → unclear why → next person blind to what was tried. Baselines drift. GPU hours vanish. Papers implemented with subtle hyperparameter mismatches that invalidate results.

With `research`:

1. Search literature before writing code (`/research:topic`).
2. Write hypothesis, metric, success criterion in one file (`/research:plan`).
3. Methodology reviewer checks experiment well-formed before run (`/research:judge`).
4. Automated loop proposes changes, commits, measures metric, rolls back regressions — unattended (`/research:run`).
5. Post-run: statistical significance, dead iteration detection, next-hypothesis queue (`/research:retro`).
6. Verify implementation matches source paper (`/research:verify`).
7. Ablations reveal which components mattered (`/research:fortify`).

Nothing lost. Every iteration logged. Every rollback reversible `git revert`. Stop, resume, hand off — full history in `.experiments/`.

______________________________________________________________________

## 📦 Install

**Prerequisite**: Claude Code with plugin support.

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install research@borda-ai-rig
```

Then run `/research:setup` once to link this plugin's rules into `~/.claude/rules/`. Re-run it after every upgrade; `bash sync.sh claude` does it for you.

Full suite best (`foundry` unlocks specialist agents):

```bash
claude plugin install foundry@borda-ai-rig
claude plugin install oss@borda-ai-rig
claude plugin install develop@borda-ai-rig
claude plugin install research@borda-ai-rig
```

<details>

<summary><strong>Upgrade</strong></summary>

```bash
claude plugin install research@borda-ai-rig
```

</details>

<details>

<summary><strong>Uninstall</strong></summary>

```bash
claude plugin uninstall research
```

</details>

All skills use `research:` prefix: `/research:topic`, `/research:plan`, `/research:judge`, `/research:run`, `/research:sweep`, `/research:verify`, `/research:fortify`, `/research:retro`, `/research:kaggle`.

______________________________________________________________________

## ⚡ Quick start

One command, immediate value on existing project:

```text
/research:plan "improve F1 from 0.82 to 0.87"
```

Interactive wizard: scans codebase, proposes metric command, guard command, iteration budget, writes `program.md` at project root. Then:

```text
/research:judge          # validate methodology before spending compute
/research:run program.md # run the improvement loop
```

Run output:

```text
Baseline: f1_score = 0.820
[-> Iter 1/20 — best so far: 0.820 (D0.0% vs baseline)]
[✓ Iter 1/20 — kept · metric=0.831 (D1.3%) · agent=research:scientist]
[-> Iter 2/20 — best so far: 0.831 (D1.3% vs baseline)]
[✓ Iter 2/20 — reverted · metric=0.818 (D-0.2%) · agent=research:scientist]
```

Every kept iteration = commit. Every reverted iteration = `git revert` — history preserved, baseline never damaged.

______________________________________________________________________

## 🔧 Skills reference

### `/research:topic` — SOTA literature search

Searches AI/ML literature for topic, builds method comparison table, produces recommendation plus implementation plan mapped to your codebase. Broad SOTA search end-to-end via `foundry:web-explorer`; codebase mapping delegated to `foundry:solution-architect`. Deep single-paper analysis with named paper anchor → use `research:scientist` directly.

**Invocation**:

```text
/research:topic "<topic>"
/research:topic "<topic>" --team
/research:topic plan                       # produce implementation plan from most recent output
/research:topic plan <path/to/output.md>   # produce plan from a specific output file
```

**Flags**:

- `--team`: spawn 2–3 researcher instances on competing method families in parallel. Use when 3+ distinct method families, no clear SOTA consensus. ~7x token cost vs single-agent.
- `--keep "<items>"`: preserve extra items through context compaction. Named items appended to compaction contract — survive auto-compaction during Step 2 literature gather.

**Output**: full report → `.reports/research/topic-<branch>-<date>.md`; compact summary → terminal. The `---` header of that report always reaches the terminal before the follow-up question — `enforce-topic-header.js` denies the question until the report file exists (see [Hooks](#hooks)).

**Plan mode**: after `/research:topic`, run `/research:topic plan` → phased implementation roadmap (written to `.reports/research/topic-plan-<branch>-<date>.md`), ready for `/develop:feature`.

**Realistic example**:

```text
/research:topic "efficient fine-tuning methods for LLMs"
# comparison table: LoRA, IA3, prefix tuning, full fine-tune
# recommendation: LoRA given your single-GPU budget
# 3-phase implementation plan with file-level tasks

/research:topic plan   # convert recommendation into phased roadmap
```

______________________________________________________________________

### `/research:plan` — experiment configuration wizard

Interactive wizard: scans codebase, proposes `metric_cmd`, `guard_cmd`, experiment config, writes `program.md`. Also accepts Python file path — profile-first: runs `cProfile`, shows top bottlenecks, asks what to optimize.

**Invocation**:

```text
/research:plan "<goal>"          # interactive wizard from a goal string
/research:plan src/train.py      # profile-first: run cProfile, then wizard
/research:plan "<goal>" out.md   # write to a specific output path
```

**What it writes** (`program.md`):

```markdown
# Program: <title>

## Goal
## Metric      <- metric_cmd, direction, optional target
## Guard       <- guard_cmd (must exit 0 to keep a commit)
## Config      <- max_iterations, agent_strategy, scope_files, compute
## Notes       <- human-readable hints for the ideation agent
```

Wizard dry-runs both commands before writing file; dispatches expert agents (architect, scientist, perf-optimizer per goal type) to review config first.

After writing, wizard suggests:

```text
Next steps:
  /research:judge program.md   <- validate plan before running (recommended)
  /research:run program.md     <- start iteration loop directly
```

**Profile-first example**:

```text
/research:plan src/train.py
# runs cProfile, shows top 5 bottleneck functions
# "What would you like to optimize?"
# wizard continues from your selection
```

______________________________________________________________________

### `/research:judge` — methodology gate

Validates `program.md` before expensive run. Research supervisor reviewing experimental protocol across seven dimensions. Read-only — never modifies code or state.

**Invocation**:

```text
/research:judge                            # auto-detect program.md at project root
/research:judge path/to/plan.md            # review a specific file
/research:judge --skip-validation          # skip dry-run of metric/guard commands
/research:judge --keep "<items>"           # persist named items through compaction
```

Use `--skip-validation` when writing `program.md` on one machine, running on remote GPU where commands not locally executable.

`--keep "<items>"`: preserve extra items through compaction. Named items appended to compaction contract — survive auto-compaction during J3 parallel review agent fan-out.

**What it checks**:

- **Completeness audit** (12 items): Goal present, Metric has command + direction, Guard has command, scope_files exist on disk, max_iterations in bounds, more.
- **Methodology review** (7 dimensions via `foundry:solution-architect`): hypothesis clarity, measurement validity, control adequacy, experimental scope, protocol consistency, stopping criteria, reproducibility.
- **Scientific rigor** (4 dimensions via `research:scientist`): hypothesis falsifiability, Goodhart's Law risk, missing baselines, reproducibility risks.
- **Dry-run validation**: runs `metric_cmd` + `guard_cmd` once — must produce numeric output, exit 0.
- **Codex adversarial review**: `codex` plugin installed → second adversarial pass on top findings.

**Verdicts**:

| Verdict          | Meaning                                       |
| ---------------- | --------------------------------------------- |
| `APPROVED`       | Protocol sound — proceed to `/research:run`   |
| `NEEDS-REVISION` | Fixable issues — see Required Changes section |
| `BLOCKED`        | Fundamental design flaw — redesign before run |

Verdict deterministic: computed from finding counts + methodology rating, not inferred from prose.

**Output**: full report → `.temp/output-judge-<branch>-<date>.md`.

**Example**:

```text
/research:judge program.md
# Verdict: NEEDS-REVISION
# Finding: C7 — target not set; campaign will run to max_iterations
# Finding: measurement validity — metric_cmd measures proxy, not actual F1
# Required Changes: (1) add target: 0.87 to ## Metric  (2) replace metric_cmd
```

______________________________________________________________________

### `/research:run` — metric-improvement loop

Core loop. Reads `program.md`, establishes baseline, iterates: spawn ideation agent, implement change, commit, measure metric, run guard, keep or revert. All changes atomic git commits. Regressions `git revert`ed automatically — history preserved, baseline never damaged.

**Invocation**:

```text
/research:run program.md
/research:run program.md "focus on attention layers"   # clarification hint to ideation agent
/research:run program.md --team                        # parallel hypothesis exploration
/research:run program.md --compute=docker              # run metric/guard in Docker sandbox
/research:run program.md --colab                       # route metric verification to Colab
/research:run program.md --colab=H100                  # request specific GPU type
/research:run program.md --codex                       # Codex co-pilot every iteration
/research:run program.md --researcher                  # pre-generate hypotheses via scientist
/research:run program.md --architect                   # pre-generate hypotheses via solution-architect
/research:run program.md --researcher --journal        # also log every iteration to journal
/research:run program.md --hypothesis path/to/hypotheses.jsonl  # consume a pre-built queue
/research:run program.md --no-codemap                  # skip codemap structural context
/research:run program.md --codemap                     # strict: fail if codemap index missing
/research:run --resume                                 # resume latest interrupted run
/research:run program.md --resume                      # resume a specific run
/research:run program.md --keep "<items>"              # persist named items through compaction
```

**Agent strategy** (via `agent_strategy` in `program.md` or auto-detected from goal/metric keywords):

| Strategy | Agent                        | Use when goal contains         |
| -------- | ---------------------------- | ------------------------------ |
| `perf`   | `foundry:perf-optimizer`     | latency, throughput, memory    |
| `code`   | `foundry:sw-engineer`        | coverage, complexity, coupling |
| `ml`     | `research:scientist`         | accuracy, loss, F1, AUC        |
| `arch`   | `foundry:solution-architect` | modularity, cohesion           |
| `auto`   | inferred from keywords       | default                        |

**Keep/revert logic per iteration**:

| Condition                                | Action                                 |
| ---------------------------------------- | -------------------------------------- |
| Metric improved AND guard passes         | Keep commit                            |
| Metric improved AND guard fails          | Rework (up to 2 attempts), then revert |
| Improvement < 0.1% AND change > 50 lines | Discard (simplicity override)          |
| No improvement                           | Revert                                 |

**Stuck detection**: 5 consecutive discards → skill rotates to different agent type automatically. Still stuck after two rotations → surfaces to you, stops — no blind looping.

**State**: default run state → `.experiments/state/<run-id>/` — `state.json`, `experiments.jsonl` (one JSONL record per iteration), `diary.md` (human-readable hypothesis-outcome log). Hypothesis-pipeline artifacts separate: with `--researcher`, `--architect`, `--hypothesis`, or `--journal` active, queue + learning files live in `.experiments/<run-id>/` as `hypotheses.jsonl`, `checkpoint.json`, optionally `journal.md`. Resume uses both: state for iteration progress, checkpoint entries to skip already-tested hypotheses.

**Hypothesis pipeline** (`--researcher`, `--architect`, `--hypothesis`, `--journal`):

- `--researcher`: spawns `research:scientist` — 5-10 ML experiment hypotheses grounded in SOTA literature + metric goal.
- `--architect`: spawns `foundry:solution-architect` — 5-10 architecture/refactoring hypotheses; used alone, feasibility considered already validated.
- `--researcher --architect`: runs both generators, merges JSONL queues by priority, then feasibility annotation pass.
- `--hypothesis <path>`: reads pre-built `hypotheses.jsonl` queue, skips oracle generation.
- `--journal`: requires `--researcher` or `--architect`; appends every kept + reverted iteration to `.experiments/<run-id>/journal.md` — future ideation avoids repeating failed approaches.

**Limits**: default 20 iterations; max 50 (never exceeded without explicit override in `program.md`).

`--keep "<items>"`: preserve extra items through compaction. Named items appended to compaction contract written after each Phase 8 iteration — survive auto-compaction during long loops.

**Example**:

```text
/research:run program.md --codex
# Baseline: f1_score = 0.820
# [-> Iter 1/20 — best so far: 0.820 (D0.0% vs baseline)]
# [✓ Iter 1/20 — kept · metric=0.831 (D1.3%) · agent=research:scientist]
# [✓ Iter 2/20 — reverted · metric=0.818 (D-0.2%) · agent=codex]
```

______________________________________________________________________

### `/research:sweep` — non-interactive end-to-end pipeline

Chains plan, judge (with auto-refinement), run into single non-interactive command. For unattended runs — safe overnight.

**Invocation**:

```text
/research:sweep "<goal>"
/research:sweep "<goal>" --team
/research:sweep "<goal>" --compute=docker
/research:sweep "<goal>" --colab=H100
/research:sweep "<goal>" --codex --researcher
/research:sweep "<goal>" --skip-validation --out path/to/program.md
```

**Flags**: sweep passes through run flags supported in sweep mode: `--team`, `--colab[=HW]`, `--compute`, `--codex`, `--researcher`, `--architect`. `--journal` and `--hypothesis` run-only — use `/research:run` directly when needed. Sweep-specific:

- `--skip-validation`: skip dry-run in judge step (cross-machine workflows)
- `--out <path>`: write `program.md` to specific path instead of project root
- `--keep "<items>"`: preserve extra items through compaction. Named items appended to compaction contracts written after S2 (plan written) and S3 (judge verdict) — survive auto-compaction during unattended runs.

**Judge refinement loop**: judge runs up to 3 times, applying Required Changes between iterations. `APPROVED` → run starts automatically. `BLOCKED` → sweep stops, shows critical findings. `NEEDS-REVISION` unresolved after 3 iterations → asks proceed or abort.

**Sweep vs manual pipeline**: sweep = single command, auto-configured defaults OK. `/research:plan` + `/research:judge` + `/research:run` = review and tune config yourself.

**Example**:

```text
/research:sweep "increase test coverage to 90%" --codex
# sweep: auto-config -> program.md
# sweep: judge iteration 1/3 -> NEEDS-REVISION
# sweep: applied 2 fix(es) to program.md — re-judging
# sweep: judge iteration 2/3 -> APPROVED
# sweep: plan approved (2/3 iteration(s))
# [-> Iter 1/20 — ...]
```

______________________________________________________________________

### `/research:verify` — paper-vs-code consistency audit

After implementing method from paper, verify implementation matches paper claims. Audits five dimensions, produces fidelity score, flags mismatches with severity + fix instructions.

**Invocation**:

```text
/research:verify paper.pdf
/research:verify paper.pdf --scope "src/model/**/*.py"
/research:verify paper.pdf --program program.md         # use scope_files from program.md
/research:verify paper.pdf --strict                     # stop on HIGH severity formula/eval mismatch
/research:verify paper.pdf --dim F,H                    # audit only specific dimensions
/research:verify paper.pdf --no-codemap                # skip codemap structural context
```

**Five audit dimensions**:

| Code | Dimension             | What it checks                                                                                 |
| ---- | --------------------- | ---------------------------------------------------------------------------------------------- |
| F    | Formula matching      | Every equation — loss functions, forward passes, reductions (mean vs sum)                      |
| H    | Hyperparameter parity | LR, batch size, weight decay, scheduler, warmup steps — code defaults match paper values?      |
| E    | Eval protocol         | Same metric (e.g. mAP@0.5 vs mAP@[0.5:0.95]), same test split, same preprocessing at inference |
| N    | Notation consistency  | Variable names in code vs paper notation — confusing mappings flagged                          |
| C    | Citation chain        | Code implements cited paper, or derivative from different paper?                               |

**Fidelity score**: `(MATCH + 0.5 * PARTIAL) / total_verified_claims`

| Score     | Rating            |
| --------- | ----------------- |
| >= 0.9    | HIGH fidelity     |
| 0.7 – 0.9 | MODERATE fidelity |
| < 0.7     | LOW fidelity      |

**Strict mode** (`--strict`): any HIGH severity mismatch in F or E → stops immediately with BREAKING notice. Use before expensive experiments.

**Codemap** (`run`, `verify`): on by default when `codemap` plugin installed and project index exists — supplies blast-radius, importer, coverage context to ideation agent (`run`) and fidelity auditor (`verify`). Missing/stale index → prompt to build/rebuild (Gate A/B); `--no-codemap` skips silently, `--codemap` strict.

**Output**: full report → `.temp/output-verify-<branch>-<date>.md`.

**Example**:

```text
/research:verify paper.pdf --strict
# Fidelity: MODERATE (0.74)
# ! BREAKING — HIGH severity mismatch in F (formula)
# Fix: src/model.py:42 — loss uses 'mean' reduction but paper specifies 'sum'
```

______________________________________________________________________

### `/research:fortify` — ablation study runner

After `/research:run` finds improvements, fortify identifies which components actually mattered. Detects component candidates from git diff + run diary, creates isolated git worktree per ablation (main repo never touched), runs metric + guard in each worktree, ranks components by importance, optionally generates reviewer Q&A for conference submission.

**Invocation**:

```text
/research:fortify                                # auto-detect latest completed run
/research:fortify <run-id>
/research:fortify program.md
/research:fortify --venue NeurIPS               # ablations + reviewer Q&A
/research:fortify --venue CVPR
/research:fortify --max-ablations 5             # cap at N ablation variants
/research:fortify --skip-run                    # identify candidates only, no execution
/research:fortify --compute=colab               # run metric/guard via Colab
/research:fortify --keep "<items>"              # persist named items through compaction
```

**Prerequisites**: completed `/research:run` AND `APPROVED` `/research:judge` verdict for same `program.md`. Refuses to run without both.

**Importance classification**:

| Class       | Condition                                     |
| ----------- | --------------------------------------------- |
| CRITICAL    | Removing component costs > 50% of full metric |
| SIGNIFICANT | 10–50% of full metric                         |
| MARGINAL    | < 10% of full metric                          |

`--keep "<items>"`: preserve extra items through compaction. Named items appended to compaction contracts written after F2 (candidates identified) and F4 (worktrees complete) — survive auto-compaction during parallel worktree loop.

Each ablation runs in own git worktree from `best_commit`. Main working tree never modified. `git revert` conflicts (two components touched same lines) → variant recorded `revert-conflict`, reported — not treated as error.

`full` variant (all components present) runs as sanity check — must reproduce `best_metric` within 2%. Divergence warning in report — catches non-deterministic metrics or environment drift between runs.

**Output**: full report → `.temp/output-fortify-<branch>-<date>.md`.

**Example**:

```text
/research:fortify --venue NeurIPS
# Components: 4 identified, 4 ablations completed
# Top:   learning-rate-warmup (importance: 62.3% CRITICAL)
# Other: label-smoothing (14.1% SIGNIFICANT)
#        dropout-schedule (7.2% MARGINAL)
#        weight-init (3.1% MARGINAL)
# Reviewer Q&A: generated for NeurIPS
```

______________________________________________________________________

### `/research:retro` — post-run retrospective

Analyzes experiment history after `/research:run` completes. Computes statistical significance (Wilcoxon signed-rank test), detects dead iteration windows, flags suspicious metric jumps, generates next-hypothesis queue compatible with `--hypothesis` flag of `/research:run`.

**Invocation**:

```text
/research:retro                                         # auto-detect latest completed run
/research:retro <run-id>
/research:retro <run-id> --compare <run-id-2>           # statistical comparison of two runs
/research:retro --threshold 0.005                       # dead iteration threshold (default 0.001)
/research:retro --alpha 0.01                            # significance level (default 0.05)
```

**What it produces**:

- **Statistical significance**: Wilcoxon signed-rank, kept iteration metrics vs baseline. Direction-aware: lower-is-better metrics (loss, latency) flip comparison. Needs N >= 6 kept iterations; else descriptive stats. Requires `scipy` — `pip install scipy` if missing.
- **Dead iteration detection**: windows of 3+ consecutive iterations with `abs(delta) < threshold`. Classes: `dead-plateau` (kept iterations going nowhere) or `dead-churn` (mixed kept/reverted, no progress).
- **Suspicious jump detection**: single-iteration improvement > 2 standard deviations above running mean. Flagged "suspicious — investigate"; never auto-labeled data leakage.
- **Strategy effectiveness**: which agent type (perf/code/ml/arch) had highest keep-rate + mean delta.
- **Next hypotheses**: 3–5 concrete hypotheses → `.experiments/retro-<ts>/hypotheses.jsonl`, compatible with `/research:run program.md --hypothesis <path>`.

**Output**: full report → `.temp/output-retro-<branch>-<date>.md`.

**Example**:

```text
/research:retro
# Significance:  p=0.031 (significant at alpha=0.05)
# Effect size:   r=0.71 (large)
# Dead iters:    4/20 (20% of compute)
# Suspicious:    1 jump (MEDIUM — investigate: abc1234)
# Hypotheses:    4 next steps generated
# Next: /research:run program.md --hypothesis .experiments/retro-<ts>/hypotheses.jsonl
```

______________________________________________________________________

### `/research:kaggle` — Kaggle competition notebook

Generates Kaggle competition notebook as Jupytext `# %%` Python script (compatible with VS Code Jupyter, JupyterLab, `jupytext --to notebook`). Distills competition context from Kaggle API or URL, asks for missing facts via grounding protocol, generates structured notebook via `foundry:sw-engineer`. Tuned to win — leakage-safe CV, metric-aligned modeling — as much as to teach: small single-purpose cells, each carrying a why.

**Invocation**:

```text
/research:kaggle <competition-name>
/research:kaggle <competition-name> <url-or-description>
/research:kaggle <competition-name> --type classification|regression|segmentation|detection|tabular
/research:kaggle <competition-name> --eda-only
/research:kaggle <competition-name> --inference-only
/research:kaggle <competition-name> --resume <existing.py>
/research:kaggle <competition-name> --keep "<items>"     # persist named items through compaction
```

**What it generates** (per mode):

Full mode (`<name>.py`): Header + Setup, Imports + Constants, EDA, Dataset + DataModule, Model, Training, Inference, Submission.

`--eda-only` (`<name>.py`): Header, Imports, EDA. 3D volumetric data (`image-3d`) adds interactive `ipywidgets` slice viewer — 3 orthogonal planes + 3D wireframe + multi-class mask overlay.

`--inference-only` (`<name>-inference.py`): Header, Imports, Load Checkpoint (PTL `load_from_checkpoint` / bare `torch.load` / custom constructor), Test DataLoader (no labels), Inference Loop (classification, detection+NMS, or 3D segmentation), Post-processing, Submission. Patterns grounded in past notebooks (`amia-x-ray`, `plant-pathology`, `surface-3d-segm`).

**Style conventions** (auto-enforced):

- All bash commands as `! cmd` — never `subprocess`, never `get_ipython().system()`
- PyTorch Lightning (`pl`) + `torchmetrics` for all DNN training, even simple baselines
- `timm.create_model(...)` for image classification; SMP for segmentation; XGBoost for tabular
- Small, single-purpose cells — one load/transform/plot/check/train call per cell, never bundled
- Every cell carries a why — inline comment or preceding markdown sentence names the specific reason (metric, leakage risk, memory limit), never restates the code
- Long comments (multi-line, paragraph-length) never sit inside a code cell — extracted to a markdown cell; mid-cell → split into code → markdown → code
- Section markdown is extensive, structured (tables/lists/blockquotes, not dense prose), and reads like a lecture — every plot framed by a "what to expect" cell before and a "finding + implication" cell after
- Commented-out hyperparameter alternatives for every tunable value
- `del` + `gc.collect()` + `time.sleep(9)` for GPU memory management

**Grounding protocol**: all competition-specific facts (input modality, eval metric, submission format) must come from fetched URL, user answer, or past notebook. Skill asks via `AskUserQuestion` for ungroundable required facts — never hallucinates competition details.

**Bare-`#` heading-spacer check**: Step 4 verify mechanically greps the generated file for bare `#`/`##`/... lines used as spacers inside markdown cells (renders as an empty heading + oversized margin in Jupyter/Kaggle, not whitespace) and auto-fixes them to true blank lines — prose-only compliance with the style rule proved insufficient in practice.

**Competitor context**: `resources/competitors/` contains `.ipynb` or `.py` files → skill reads each, summarises approach (model choice, preprocessing, augmentation strategy) before profiling problem. Findings inform detection method + domain-specific preprocessing.

**Package distillation gate**: after notebook verified, skill offers to extract reusable helpers (data loading, submission builder, metric utilities) into `src/<package>/` with Google-style docstrings + tests. Refactored notebook written as new file (`notebooks/01_<name>_pkg.py`) — validated baseline never modified.

`--keep "<items>"`: preserve extra items through compaction. Named items appended to compaction contract written after Step 3 (notebook generated) — survive auto-compaction if `foundry:sw-engineer` spawn takes long.

**Requires**: `foundry` plugin (`foundry:sw-engineer`).

**Output**: `.experiments/kaggle/<competition-name>.py`

**Example**:

```text
/research:kaggle rsna-breast-cancer https://www.kaggle.com/competitions/rsna-breast-cancer-detection
# Grounding: fetching competition page...
# Problem type: binary classification (mammogram images)
# Eval metric: pF1 (probabilistic F1)
# Generating notebook...
# Output: .experiments/kaggle/rsna-breast-cancer.py (574 lines)
```

______________________________________________________________________

### `/research:setup` — post-install rule delivery

**Purpose**: Deliver this plugin's `rules/*.md` into Claude's user-level rule namespace. Maintenance command, not part of any research workflow.

**When to use**: after installing research on a new machine, or after upgrading it. `bash sync.sh claude` runs it automatically for every installed managed plugin that ships a setup skill, so a normal sync needs no manual step.

**Invocation**:

```text
/research:setup            # interactive — asks before replacing anything it does not own
/research:setup --approve  # non-interactive — used by sync.sh
```

Each rule installs as a symlink at `~/.claude/rules/research-<source-name>.md`. The `research-` prefix keeps the flat rule namespace collision-free — four plugins ship a `rules/quality-gates.md`. A filename prefix does not change how Claude loads a rule or how its `paths:` frontmatter matches.

Only links this plugin provably owns are replaced or removed: the existing target must resolve under the current plugin root or under the same install-cache lineage. A real file, a link into another marketplace, a source checkout, or a dotfiles tree is reported as a conflict and left alone unless you approve replacing it.

**Uninstall leaves rule links behind**: Claude Code runs no cleanup hook on uninstall, so `~/.claude/rules/research-*.md` survives both `claude plugin uninstall` and `bash sync.sh clear`. Delete those symlinks by hand — once the plugin cache version is gone they dangle.

______________________________________________________________________

## 🤖 Agents reference

### `research:scientist`

**Role**: AI/ML researcher bridging theory and practice. Reads papers critically, implements methods from descriptions, generates falsifiable hypotheses, designs rigorous experiments, reasons whether results support conclusions.

**Model**: `opus`

**When to use directly**:

- Deep analysis of specific paper — method details, reproducibility check, appendix hyperparameters
- Falsifiable hypothesis generation + ablation design
- Implementing method from publication, including non-obvious details (gradient clipping, weight init, EMA decay) papers often omit
- Reviewing whether reported result meaningful — mean ± std over multiple seeds, or just best run?

**When NOT to use**:

- Broad SOTA survey across methods -> `/research:topic`
- Dataset acquisition, split validation, leakage detection -> `research:data-steward`
- General Python unrelated to paper -> `foundry:sw-engineer`
- Fetching library docs or web content -> `foundry:web-explorer`

**Example dispatch**:

```text
use scientist to analyze the methodology in this paper and suggest ablations
```

Scientist enforces strict experiment design: one hypothesis per experiment, random seed averaging over >= 3 runs, ablation per component, mean ± std reported (never best run alone). Flags cherry-picked results, missing confidence intervals, test set reuse.

______________________________________________________________________

### `research:data-steward`

**Role**: Data lifecycle specialist. Everything between "I need this dataset" and "data feeding experiment is correct": dataset acquisition from external sources, completeness verification from paginated APIs, DVC versioning, train/val/test split audits, data leakage detection.

**Model**: `sonnet`

**When to use directly**:

- Verify train/val/test splits don't overlap (critical for patient-level or session-level grouped data)
- Detect leakage — normalizer fit on full dataset before split, stochastic augmentation on val/test, SMOTE before split
- Acquire dataset from external API with completeness verification (not just first page)
- Set up DVC for dataset versioning + provenance
- Audit DataLoader correctness (num_workers seeding, pin_memory, shuffle disabled on val/test)

**When NOT to use**:

- ML hypothesis generation or experiment design -> `research:scientist`
- DataLoader throughput optimization -> `foundry:perf-optimizer`
- URL discovery or web scraping -> `foundry:web-explorer` (data-steward validates what it returns)

**Example dispatch**:

```text
use data-steward to verify train/val split integrity and check for data leakage
```

Data-steward runs six parallel grep patterns against codebase — top ML data bugs general code review misses:

| Pattern searched                   | Bug class                                                 |
| ---------------------------------- | --------------------------------------------------------- |
| `fit_transform(`                   | Pre-split normalization leakage                           |
| `Random*` transforms               | Stochastic augmentation on val/test                       |
| `train_test_split(`                | Ungrouped split candidate (checked for missing `groups=`) |
| `patient_id`, `subject_id` columns | Grouped data not split on group ID                        |
| `random_split(`                    | Shared-transform risk (torch Subsets)                     |
| `augment_images(`, `.augment(`     | Pre-split augmentation                                    |

______________________________________________________________________

## 🗺️ Workflow overview

Skills chain naturally. Standard full-session pipeline:

```markdown
1. /research:topic "<method>"          <- understand SOTA before coding
2. /research:plan "<goal>"             <- configure experiment, write program.md
3. /research:judge                     <- validate methodology cheaply
4. /research:run program.md            <- run improvement loop with auto-rollback
5. /research:retro                     <- analyze results, generate next hypotheses
6. /research:verify paper.pdf          <- confirm implementation matches the paper
7. /research:fortify                   <- run ablations to find what mattered
```

Not all seven steps every time. Common paths:

**Fast iteration** (clear goal, no paper to verify):

```text
/research:plan "reduce inference latency by 30%"
/research:judge
/research:run program.md
```

**Paper implementation**:

```text
/research:topic "flash attention variants"
/research:plan "reduce training step time by 20%"
/research:judge
/research:run program.md --researcher
/research:verify paper.pdf --strict
/research:retro
```

**Overnight unattended run**:

```text
/research:sweep "increase test coverage to 90%" --codex
```

**Conference submission prep**:

```text
/research:fortify --venue NeurIPS
```

**Resuming after interruption**:

```text
/research:run --resume
```

### How the loop works inside `/research:run`

Each iteration, fixed sequence:

1. Build context from git log, JSONL history, recent diff — written to file, not accumulated in memory
2. Spawn specialist agent with context, scope files, program constraints — agent proposes one atomic change
3. Verify files actually changed (skip no-ops)
4. Commit before measuring (enables clean revert)
5. Measure `metric_cmd`
6. Run `guard_cmd` (tests, lint, type check)
7. Keep if metric improved AND guard passes; rework up to 2 times if guard fails; revert otherwise
8. Write diary entry + JSONL record
9. Check stuck runs, diminishing returns, early stop

Key design choice: commit before verify. Every revert = clean `git revert HEAD --no-edit`, history preserved. Never lose track of what was tried.

______________________________________________________________________

## ⚙️ Configuration

### `program.md` — the research contract

All skills read this file. Write with `/research:plan`, or by hand. Required sections:

```markdown
## Goal        one paragraph describing what to improve and why
## Metric      command that prints a single float, direction (higher|lower), optional target
## Guard       command that must exit 0 on every kept commit
## Config      max_iterations, agent_strategy, scope_files, compute
## Notes       optional hints for the ideation agent (not parsed by skill, read by agents)
```

<details>

<summary>

Config fields reference

</summary>

Config fields:

| Field             | Values                               | Default  | Notes                                                        |
| ----------------- | ------------------------------------ | -------- | ------------------------------------------------------------ |
| `max_iterations`  | 1–50                                 | 20       | Hard ceiling at 50; never exceeded without explicit override |
| `agent_strategy`  | `auto`, `perf`, `code`, `ml`, `arch` | `auto`   | Auto infers from goal/metric keywords                        |
| `scope_files`     | list of paths/globs                  | required | Ideation agent reads and modifies only these                 |
| `compute`         | `local`, `colab`, `docker`           | `local`  | Routing for metric/guard execution                           |
| `colab_hw`        | `H100`, `L4`, `T4`, `A100`           | none     | Hardware preference for Colab runs                           |
| `sandbox_network` | `none`, `bridge`                     | `none`   | Network isolation in Docker sandbox                          |

</details>

### Colab MCP integration (`--colab`)

Routes metric verification + GPU code testing to Google Colab runtime via `colab-mcp` server. Use for ML training metrics, CUDA benchmarks, any GPU workload.

Setup (before running `--colab`):

1. Add `"colab-mcp"` to `enabledMcpjsonServers` in `settings.local.json`:
   ```json
   {
     "enabledMcpjsonServers": [
       "colab-mcp"
     ]
   }
   ```
2. Ensure `colab-mcp` defined in `.mcp.json` under `mcpServers`.
3. Open Colab notebook with runtime connected, execute MCP connection cell.

`--colab=H100` specified → run validates GPU identity via `torch.cuda.get_device_name()` each iteration; halts on hardware mismatch.

<a id="hooks"></a>

### Hooks

**Hooks** register automatically from `hooks/hooks.json` when the plugin is enabled — no `settings.json` edits needed:

| Hook                      | Event                            | Behaviour                                                                                                                                                                                                            |
| ------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent-router.js`         | `PreToolUse` (`Agent`)           | Reroutes `Agent()` calls when the requested agent is not installed: exact match → semantic match → `general-purpose`.                                                                                                |
| `sentinel-read-allow.js`  | `PreToolUse` (`Bash`)            | Auto-allows the pre-canned TMPDIR sentinel-read and `$(date +FMT)` idioms inside read-only commands, so skill bash blocks stop raising "Contains expansion" prompts. Everything else falls through to normal checks. |
| `enforce-topic-header.js` | `PreToolUse` (`AskUserQuestion`) | Denies `/research:topic`'s follow-up question until its report file exists under `.reports/research/`, so the report header always reaches the terminal first. Silent unless a topic run is in flight.               |

### Artifact layout

All outputs under `.experiments/`, `.reports/research/`, and `.temp/` at project root. Gitignored.

```text
.experiments/
  state/<run-id>/          <- per-run state, JSONL log, diary (research:run)
  judge-<ts>/              <- methodology review artifacts (research:judge)
  verify-<ts>/             <- scientist audit output (research:verify)
  fortify-<ts>/            <- ablation worktrees and results (research:fortify)
  retro-<ts>/              <- analysis scripts, hypotheses.jsonl (research:retro)
.reports/research/
  topic-*.md               <- topic reports and plan-mode roadmaps
.temp/
  output-research-*.md     <- topic agent/teammate handover files
  output-judge-*.md        <- judge reports
  output-optimize-run-*.md <- run final reports
  output-verify-*.md       <- verify reports
  output-fortify-*.md      <- fortify reports
  output-retro-*.md        <- retro reports
```

Directories without `result.jsonl` (judge, verify, fortify, retro run dirs) exempt from automated 30-day TTL cleanup. Remove manually when done: `rm -rf .experiments/judge-*/`.

______________________________________________________________________

<details>

<summary>

## 🔍 Troubleshooting

</summary>

## 🔍 Troubleshooting

**"No program.md found" when running `/research:judge` or `/research:run`**

Run `/research:plan "<goal>"` first — writes `program.md` to project root by default. Wrote manually or saved elsewhere → pass path explicitly: `/research:judge path/to/plan.md`.

**A question is blocked with "research:topic report gate"**

`enforce-topic-header.js` denied an `AskUserQuestion` call because the report file under `.reports/research/` does not exist — the topic run reached its follow-up question without writing a report, so no report header could have been printed. Write the report to that exact path and render its `---` header as the two-column terminal table; the question then goes through. The gate deactivates two hours after a run resolves its report path, so an aborted run never blocks later questions permanently.

**"Metric command failed or produced no numeric output" during judge or run**

`metric_cmd` must print single float to stdout. Test in terminal first. Label alongside number (e.g., `F1: 0.82`) — skill parses it. Table or structured output — need wrapper extracting number: `python eval.py | grep f1 | awk '{print $2}'`.

**"Guard command exited non-zero" in judge**

`guard_cmd` failing on current codebase before any changes. Fix underlying issue first. Use `--skip-validation` when writing `program.md` on one machine, running on another.

**`--colab` check fails: "Colab MCP not available"**

Colab MCP server not enabled. Follow three-step setup in Configuration section. Most common miss: MCP connection cell not executed in Colab notebook after connecting runtime.

**Run stops after 5 consecutive reverts (stuck detection triggered)**

Skill rotates to different agent type automatically on first occurrence, then surfaces to you if still stuck after two rotations. Intentional — no infinite looping. Review `.experiments/state/<run-id>/diary.md` for what was tried, then adjust `scope_files`, change `agent_strategy` in `program.md`, or refine goal.

**"fortify: BLOCKED — no APPROVED judge verdict found"**

Run `/research:judge <program.md>`, get `APPROVED` verdict before fortify. Gate prevents ablation studies on methodologically unsound baselines.

**`/research:verify` returns LOW fidelity for a correct implementation**

Some paper claims unverifiable from code alone — training infrastructure decisions, dataset-specific tuning, supplementary-appendix-only details. Unverifiable claims excluded from fidelity denominator. Many unverifiable claims → score may not be representative. Check Dimension Summary table in report for proportion of unverifiable claims per dimension.

______________________________________________________________________

</details>

## 🙏 Contributing and feedback

Plugin part of Borda-AI-Rig project. Skills + agents in `plugins/cc_research/` in repository.

Skill files (`plugins/cc_research/skills/*/SKILL.md`) and agent files (`plugins/cc_research/agents/*.md`) = canonical source of truth — README must stay in sync. Any skill behavior change (flags, NOT-for scope, trigger conditions) requires update here.

Version bumps per project policy: new capability → minor bump; fixes, wording, refactors → patch bump.

**Mode-dispatch layout**: large conditional sections externalised under `skills/<skill>/modes/*.md`, loaded on demand. Run's hypothesis pipeline, team, report modes under `skills/run/modes/`. ML-concepts reference for `research:scientist` under `agents/scientist/ml-concepts.md` — loaded only for ML-domain tasks.

**Shared bin/ scripts** (`plugins/cc_research/bin/`) — all 13 referenced from at least one skill or agent:

- `resolve_shared.py` — resolve research plugin `_shared/` directory (Windows-portable).
- `make_run_dir.py` — create slug-prefixed, UTC-timestamped run directory.
- `health_monitor_start.py` — create research health-monitoring sentinel for background agents.
- `git_slugs.sh` — emit sourceable `REPO_SLUG`/`BRANCH_SLUG` for `research:run` commit-sentinel path (falls back to `no-repo`/`detached` sentinels outside repo or on detached HEAD).
- `docker_sandbox_run.py` — `--mode explore|verify`: sandboxed metric + script execution under `python:3.11-slim` (verify mode rejects shell metacharacters + destructive binaries that could wipe read-write `.experiments` mount).
- `check_output_within_root.py` — verify candidate output path stays within project root.
- `codemap-resolve` — resolve `CODEMAP_ENABLED` (`auto`/`strict`/`off` → `true`/`false`), record index currency.
- `compute_effect_size.py` — rank-biserial correlation effect size for retro signed-rank result (reads JSON on stdin).
- `find_run_id.py` — locate latest completed run id under state-dir base.
- `read_state_field.py` — read dotted-path field from JSON state file.
- `resolve-quality-gates.sh` — resolve path to foundry's `quality-gates.md` (project-local copy preferred, plugin cache fallback).
- `retro_analyze.py` — one-sample signed-rank significance test, kept iterations vs baseline metric, for `research:retro`.
- `verify_patient_split.py` — detect `patient_id` overlap between train/test CSV splits (leakage guard).

______________________________________________________________________

## 🙏 Acknowledgments

Plugin draws on two open-source research automation projects:

- **fcakyon/phd-skills** — Claude Code plugin built from real PhD mistakes. Hook-first guardrail philosophy + visual output inspection directly influenced `verify` and `fortify` design. `--venue` reviewer Q&A in fortify = direct port of its `fortify` command concept.

- **karpathy/autoresearch** — Autonomous overnight ML experiment runner inverting human/agent roles: agents touch code, humans shape direction via `program.md`. Core loop design of `run` (single metric, atomic commits, wall-clock budgets, `program.md` as research contract) traces directly to this work.
