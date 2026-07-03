---
name: kaggle
description: "Generate a Kaggle competition notebook as a Jupytext `# %%` Python script following the user's established ML research style: PTL for DNN training, best-fit tool selection, EDA→Baseline→Train→Inference pipeline with per-stage lens cells. Writes output to .experiments/kaggle/<name>.py."
argument-hint: "<competition-name> [<url-or-description>] [--type classification|regression|segmentation|detection|tabular] [--eda-only] [--inference-only] [--offline-setup] [--resume <existing.py>]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, Agent, WebFetch, WebSearch, AskUserQuestion, TaskCreate, TaskUpdate, TaskList
disable-model-invocation: true
effort: high
---

<objective>

Generate a Kaggle competition notebook script in Jupytext `# %%` format.

Follows the user's ML research style distilled from past notebooks:
- **PTL always for DNN training** (PyTorch Lightning + torchmetrics) — even simple baselines
- **Tool agnostic** — pick best-fit library for the problem; use PTL when training loop needed
- **Stages with lenses** — each major stage includes a quick sanity check cell (show one batch, print shapes, verify submission format)
- **`# !` bash over subprocess** — package installs, `nvidia-smi`, `ls -lh`, `# ! head submission.csv`
- **EDA is visual** — distribution plots, sample grids, dimension scatters before any model
- **Inference included** — model save pattern + separate load-and-infer cells
- **CSVLogger + seaborn** — metrics plotted from `metrics.csv` after every training run

NOT for writing Python packages, modules, or production code — notebook scripts only.
NOT a research literature survey — use `/research:topic` for SOTA literature search.

</objective>

<inputs>

- **$ARGUMENTS**: one of:
  - `<competition-name>` — short slug used for output filename; generates blank template
  - `<competition-name> <url>` — fetches competition overview from URL before generating
  - `<competition-name> "<description>"` — uses inline description of problem and data
  - `--type <type>` — hint: `classification`, `regression`, `segmentation`, `detection`, `tabular` (auto-detected when omitted)
  - `--eda-only` — generate only EDA sections (no model/training/submission); always online (no offline setup)
  - `--inference-only` — generate inference notebook from checkpoint (no EDA, no training); always offline (frozen packages pattern); loads checkpoint from `PATH_CHECKPOINT` constant; output suffix `-inference.py`
  - `--offline-setup` — include offline package setup (frozen_packages pattern) in setup cell; auto-applied when `--inference-only`; ignored when `--eda-only` (EDA always online)
  - `--resume <path>` — read existing `.py` script and extend/improve it

Output: `.experiments/kaggle/<competition-name>.py`

</inputs>

<constants>

```yaml
OUTPUT_DIR:    .experiments/kaggle/
CELL_MARK:     "# %%"
MD_CELL_MARK:  "# %% [markdown]"
```

</constants>

<workflow>

**Task hygiene**: call `TaskList` first; close orphaned tasks. Create tasks for each phase.

## Step 1: Parse arguments and gather context

```bash
ARGS="$ARGUMENTS"
COMPETITION_NAME=$(echo "$ARGS" | awk '{print $1}')
RESUME_FLAG=""
EDA_ONLY=false
INFERENCE_ONLY=false
OFFLINE_SETUP=false
PROBLEM_TYPE=""

[[ "$ARGS" == *"--eda-only"* ]]      && EDA_ONLY=true
[[ "$ARGS" == *"--inference-only"* ]] && INFERENCE_ONLY=true
[[ "$ARGS" == *"--offline-setup"* ]]  && OFFLINE_SETUP=true
[[ "$ARGS" =~ --type[[:space:]]([a-z]+) ]] && PROBLEM_TYPE="${BASH_REMATCH[1]}"
[[ "$ARGS" =~ --resume[[:space:]]([^[:space:]]+) ]] && RESUME_FLAG="${BASH_REMATCH[1]}"

# inference always offline; EDA always online (overrides --offline-setup)
[ "$INFERENCE_ONLY" = "true" ] && OFFLINE_SETUP=true
[ "$EDA_ONLY" = "true" ]       && OFFLINE_SETUP=false

echo "Competition: $COMPETITION_NAME"
echo "Type: ${PROBLEM_TYPE:-auto-detect}"
echo "EDA only: $EDA_ONLY | Inference only: $INFERENCE_ONLY | Offline setup: $OFFLINE_SETUP"

# Persist for Steps 3+4 (bash state lost across Bash() calls)
echo "$COMPETITION_NAME" > "${TMPDIR:-/tmp}/kaggle-competition-name"
echo "$EDA_ONLY"         > "${TMPDIR:-/tmp}/kaggle-eda-only"
echo "$INFERENCE_ONLY"   > "${TMPDIR:-/tmp}/kaggle-inference-only"
echo "$OFFLINE_SETUP"    > "${TMPDIR:-/tmp}/kaggle-offline-setup"

mkdir -p .experiments/kaggle/  # timeout: 3000
```

**Unsupported flag check** — scan `$ARGUMENTS` for remaining `--<token>` tokens after supported flags extracted (`--eda-only`, `--inference-only`, `--offline-setup`, `--type`, `--resume`). If found: print `` ! Unknown flag(s): `--<token>`. Supported: `--eda-only`, `--inference-only`, `--offline-setup`, `--type <type>`, `--resume <path>`. `` then invoke `AskUserQuestion` — (a) **Abort** · (b) **Continue ignoring**. On Abort: stop.

**Context collection** — run in parallel:
1. Check if style guide exists at `.temp/kaggle-style-distill.md`; read it if present
2. If URL provided in args: `WebFetch` competition page; extract problem description, target metric, data format, evaluation — read and quote actual text, never paraphrase from training knowledge
3. If `--resume`: read existing script (`Read` tool)
4. Scan `.experiments/kaggle/` (`Glob` pattern `*.py`) for prior scripts; read first 30 lines of each to find similar past competitions — use as structural reference
5. Check `resources/competitors/` for any `.ipynb` or `.py` files — if found, read each and summarise approach (model choice, preprocessing, feature engineering, augmentation). Use findings to inform detection method and domain-specific preprocessing decisions in Step 2.

**Grounding protocol — mandatory before Step 2:**

Build a fact table. Each fact must have a source: `[fetched]`, `[user]`, `[past-notebook:<file>]`, or `[inferred-from:<fact>]`. Never mark a fact `[inferred]` without citing the prior fact it derives from.

| Fact | Value | Source |
| --- | --- | --- |
| problem_type | ? | ? |
| input_modality | ? | ? |
| output_format | ? | ? |
| eval_metric | ? | ? |
| data schema (CSV columns / image format) | ? | ? |
| submission format | ? | ? |

**Gaps — ask before generating:**

After building fact table, count facts still marked `?` or `[inferred]` without a prior grounded fact. If ANY of these are unknown:
- `input_modality` — cannot generate Dataset class
- `eval_metric` — cannot choose torchmetric
- `submission format` — cannot generate Submission section

Invoke `AskUserQuestion` with up to 4 questions covering all unknown required facts. Never guess or hallucinate competition-specific details (column names, file paths, data schema). State "unknown — will use placeholder" if user skips.

Acknowledge past-notebook similarity explicitly: "Found similar past notebook: `<file>` — reusing `<pattern>` from it."

## Step 2: Determine problem profile

From gathered context, determine:

| Property | Value |
| --- | --- |
| `problem_type` | classification / regression / segmentation / detection / tabular |
| `input_modality` | image-2d / image-3d / tabular / time-series / point-cloud / mixed |
| `output_format` | label / scalar / mask / bboxes / rle |
| `eval_metric` | AUC / F1 / RMSE / Dice / IoU / mAP / ... |
| `recommended_model` | see §Model selection below |
| `use_ptl` | true if DNN training; false for pure XGBoost/sklearn pipelines |

**Model selection rules** (pick best-fit, not default):

- Image classification → `timm.create_model` (EfficientNetV2, ConvNeXt, ViT-B) + PTL
- Image regression → `timm.create_model` backbone (`num_classes=0`) + PTL regression head
- Image segmentation → `segmentation_models_pytorch` (UNet/UNet++) + PTL; MONAI for 3D
- Object detection → `torchvision.models.detection` or `ultralytics YOLO` + PTL wrapper if needed
- Tabular → `xgboost.XGBClassifier/Regressor` with sklearn Pipeline; PTL only if DNN features needed
- Point cloud → MONAI or `pytorch3d`; PTL always
- Time series → `torch.nn.LSTM` or `tsfresh` features + XGBoost; PTL when DNN

**PTL rule**: use PTL whenever a training loop is needed — even for simple single-layer models. Exception: pure sklearn/XGBoost pipelines with no neural network component.

## Step 3: Generate notebook script

**Foundry availability check** — verify before spawning:

```bash
FOUNDRY_AVAILABLE=$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/agents/sw-engineer.md 2>/dev/null | head -1)  # timeout: 5000
[ -z "$FOUNDRY_AVAILABLE" ] && { printf "⚠ foundry plugin not available — kaggle notebook generation requires foundry:sw-engineer\nInstall: claude plugin install foundry@borda-ai-rig\n"; exit 1; }
```

The spawn prompt is assembled from the inline problem profile (below) plus the section template loaded from the appropriate mode file:

```bash
# Re-hydrate flags persisted in Step 1 (bash state lost between Bash calls)
COMPETITION_NAME=$(cat "${TMPDIR:-/tmp}/kaggle-competition-name" 2>/dev/null || echo "$COMPETITION_NAME")
EDA_ONLY=$(cat "${TMPDIR:-/tmp}/kaggle-eda-only" 2>/dev/null || echo "false")
INFERENCE_ONLY=$(cat "${TMPDIR:-/tmp}/kaggle-inference-only" 2>/dev/null || echo "false")
_KAGGLE_MODES="${CLAUDE_PLUGIN_ROOT:-plugins/research}/skills/kaggle/modes"
TEMPLATE_FILE="$_KAGGLE_MODES/full.md"
[ "$EDA_ONLY" = "true" ] && TEMPLATE_FILE="$_KAGGLE_MODES/eda-only.md"
[ "$INFERENCE_ONLY" = "true" ] && TEMPLATE_FILE="$_KAGGLE_MODES/inference-only.md"

# Derive output filename from mode — must match template contract before spawning
OUTPUT_SUFFIX=""
[ "$INFERENCE_ONLY" = "true" ] && OUTPUT_SUFFIX="-inference"
OUTFILE=".experiments/kaggle/${COMPETITION_NAME}${OUTPUT_SUFFIX}.py"
echo "Output: $OUTFILE"
```

> loads: full.md
> loads: eda-only.md
> loads: inference-only.md

Read `$TEMPLATE_FILE` — contains the required sections template. Pass to foundry:sw-engineer as continuation of the spawn prompt after the problem profile block below.

Spawn **foundry:sw-engineer** with this prompt preamble (inline, then continue with content from `$TEMPLATE_FILE`):

```markdown
Write a complete Kaggle competition notebook script to `<OUTFILE>` (substitute expanded path from bash block above).

Format: Jupytext `# %%` Python script — every cell separated by `# %%` (code) or `# %% [markdown]` (markdown).

Formatting rules (strict):
- `[markdown]` blank lines: empty line only — never `#` alone (bare `#` = H1 in Kaggle)
- Shell commands: write as `# ! cmd` (Python comment) — valid syntax, visible in Jupyter; never bare `! cmd` lines
- Markdown cell headers: describe only what the cell CONTAINS now — never hint at future refactoring or package destinations (e.g. never `## Helpers (inlined — distill to src/X/ after validation)`)

## Problem profile
- Competition: <competition-name>
- Problem type: <problem_type>
- Input: <input_modality>
- Output: <output_format>
- Metric: <eval_metric>
- Model: <recommended_model>
- Use PTL: <use_ptl>
- Description: <competition description if available>

[Continue with section template from $TEMPLATE_FILE]
```

**Synchronous spawn note**: `foundry:sw-engineer` is spawned synchronously (not `run_in_background=true`), so CLAUDE.md §6 poll-based monitoring is unreachable mid-call. After Agent() returns, check the agent's output under `.experiments/kaggle/`; if missing or empty, treat as timed out and surface with ⏱ marker — do not silently omit.

## Step 4: Verify and report

After agent completes:

1. Read first 30 lines of generated file to verify `# %%` structure
2. Count cell markers: `grep -c "^# %%" .experiments/kaggle/<name>.py`
3. Check all required sections present: `grep "^# %% \[markdown\]" <file>`

```bash
# Re-derive OUTFILE from flags persisted in Step 1 (bash state lost between steps)
COMPETITION_NAME=$(cat "${TMPDIR:-/tmp}/kaggle-competition-name" 2>/dev/null || echo "$COMPETITION_NAME")
INFERENCE_ONLY=$(cat "${TMPDIR:-/tmp}/kaggle-inference-only" 2>/dev/null || echo "false")
OUTPUT_SUFFIX=""; [ "$INFERENCE_ONLY" = "true" ] && OUTPUT_SUFFIX="-inference"
OUTFILE=".experiments/kaggle/${COMPETITION_NAME}${OUTPUT_SUFFIX}.py"
echo "=== Cell count ==="; grep -c "^# %%" "$OUTFILE"  # timeout: 5000
echo "=== Sections ===";   grep "^# %% \[markdown\]" "$OUTFILE"  # timeout: 5000
echo "=== File size ===";  wc -l "$OUTFILE"  # timeout: 5000
```

Print to terminal:
- Output path (`$OUTFILE`)
- Problem type + recommended model
- Cell count and section list
- Any missing required sections flagged with `⚠`

Invoke `AskUserQuestion` as follow-up gate:
- (a) Open in editor — `! code $OUTFILE`
- (b) Extend with additional sections
- (c) Regenerate with different model/approach
- (d) Done

On (a): run `! code "$OUTFILE"` via Bash.
On (b): re-enter Step 3 with extension directive.
On (c): re-enter Step 2 with user-specified changes.

**Package distillation gate** — invoke after follow-up gate resolves to Done:

Benefits to state before asking: shared helpers tested once, used everywhere; wheel attachment on Kaggle faster than re-inlining; subsequent notebooks shorter; package tests catch regressions before submission.

Invoke `AskUserQuestion`:
- (a) Yes — scaffold `src/<package>/` with extracted helpers + tests
- (b) Skip — keep everything inlined for now

If **(a)**:
1. Identify every function in the notebook with no hardcoded paths, no `plt.show()`, no `tqdm` calls
2. Write each to `src/<package>/<module>.py` with **full** Google-style docstring + `Example:` block — all standard coding patterns apply (doctests for pure functions, `Args:`/`Returns:` sections, full `if __name__ == "__main__":` guards where appropriate); these are package modules, not notebook cells
3. Create `tests/test_<module>.py` covering each function
4. Create `notebooks/01_<competition-name>_pkg.py` — inline definitions replaced by package imports; **never modify the validated baseline `$OUTFILE`**

If **(b)**: skip; repeat this gate offer after the next notebook is written.

</workflow>

<notes>

- **`# %%` format**: Jupytext light format — compatible with VS Code Jupyter extension, JupyterLab, and `jupytext --to notebook <file>.py`. Each `# %%` starts a new code cell; `# %% [markdown]` starts a markdown cell where lines prefixed `# ` are the markdown content. **Blank lines inside `[markdown]` cells must be actual empty lines** — no `#`, no `# `. A bare `#` renders as H1 heading in Kaggle. Pattern: `# Last sentence.` → empty line → `# Next paragraph.`
- **Shell commands — `# ! cmd`**: write every shell command as `# ! cmd` — valid Python comment, no syntax error, visible in Jupyter source. Example: `# ! head -5 {path}`. Do NOT write bare `! cmd` lines — they cause `SyntaxError` when running the `.py` file as a Python script.
- **`%` magic — NEVER convert**: write `%matplotlib inline` verbatim. Do NOT convert to `get_ipython().run_line_magic(...)`. Jupytext handles `%` magic natively; exclude `.experiments/` from linting (pyproject.toml) — never rewrite the magic syntax.
- **PTL version compat**: newer Lightning uses `accelerator="auto", devices="auto"` not `gpus=1`; use new API in generated code
- **Frozen packages pattern**: two-step offline setup — (1) download: `# ! pip download -q <pkg> --dest frozen_packages/` (run once online); (2) install: `# ! pip install -q --no-index --find-links frozen_packages/ <pkg> 2>/dev/null || pip install -q <pkg>` (works online and offline). When `OFFLINE_SETUP=true`, step 1 replaced by `# ! cp -r ../input/python-packages/frozen_packages .` (packages already stored as Kaggle input dataset)
- **Inference notebook pattern**: each training notebook saves checkpoints to `logs/`; a companion notebook loads from checkpoint for inference — the script includes both inline + load-from-ckpt cells so the same file works both ways
- **Style guide regeneration**: if `.temp/kaggle-style-distill.md` missing at Step 1, the style rules embedded in Step 3's generator prompt are the authoritative source — no style guide file required
- **Sharing context**: competition notebooks are meant to be shared publicly as learning resources; clarity and educational value matter alongside score
- **No forward-refs in headers**: markdown cell headers describe only what is present in the cell — never annotate with future refactoring plans (e.g. `## Helpers (distill to src/X/ later)` is forbidden); such notes belong in the distillation gate dialogue, not the notebook source
- **Storytelling structure**: notebook must read as a coherent narrative for a public audience — each section builds on findings of the previous; EDA conclusions motivate design decisions in Dataset/Model; hypothesis validation in EDA must explicitly connect to choices made downstream (loss function, augmentation, image size)
- **JIT constants**: never dump all config at the top; each major section opens with its own `# %%` config block containing only the constants needed by that section — reader sees config exactly when it becomes relevant; `IMAGE_SIZE` belongs in the DataModule section, `MODEL_NAME`/`LEARNING_RATE` belong in the Model section
- **JIT helpers**: define every helper function in a `# %%` cell immediately before the cell that calls it — never in a global "helpers" block at the top; reader learns the helper at the moment of use

</notes>
