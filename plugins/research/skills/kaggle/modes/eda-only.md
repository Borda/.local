<!-- file: eda-only.md — consumers: kaggle/SKILL.md -->

## Required sections — EDA ONLY (--eda-only mode)

Generate ONLY sections 1–3 below. Do not generate Dataset/DataModule, Model, Training, Inference, or Submission sections.

### Section 1: Header + Setup
`# %% [markdown]` cell:
  - Title: `# 🔬 <Competition Title> — EDA` (emoji fitting domain)
  - 2–3 sentences: what competition is about, approach chosen
  - Link: `Competition: <url-if-known>`

`# %%` cell (setup — EDA online; downloads packages to `frozen_packages/` for offline reuse):
  - `# ! pip download -q <library> --dest frozen_packages/`
  - `# ! pip install -q --no-index --find-links frozen_packages/ <library> 2>/dev/null || pip install -q <library>`
  - `# ! pip list | grep -E 'torch|lightning|timm'`

### Section 2: Imports + Path Constants
Single `# %%` cell — global imports and paths only; **EDA config lives JIT in Section 3**:
  - stdlib: `import os, glob` (same line for short ones)
  - domain libraries grouped loosely: numpy/pandas first, then torch/timm, then sklearn
  - `from tqdm.auto import tqdm` (not `tqdm.tqdm`)
  - `import warnings; warnings.simplefilter("ignore", UserWarning)` when noisy libs used
  - PATH constants only: `PATH_DATASET = "/kaggle/input/<competition>"`, `PATH_OUTPUT = "."` — ALL_CAPS
  - Version print block: `print(f"PyTorch: {torch.__version__}")`, `print(f"Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")`

### Section 3: EDA
`# %% [markdown]` header: `## EDA` — include explanation of what/why/how it contributes to solution.

**EDA config block** — first `# %%` in this section (JIT constants):
```python
# %%
SAMPLE_N   = 9          # images shown in sample grid
TARGET_COL = "<col>"    # label column name in df_train
```

Sub-cells in narrative order (each a separate `# %%`):

**3a. Dataset overview**
```python
# %%
df_train = pd.read_csv(os.path.join(PATH_DATASET, "train.csv"))
print(f"Train size: {len(df_train):,}  |  Columns: {list(df_train.columns)}")
display(df_train.head())
display(df_train.dtypes.to_frame("dtype"))
print(f"\nMissing values:\n{df_train.isnull().sum()[df_train.isnull().sum() > 0]}")
display(df_train.describe())
```

**3b. Label / target distribution** — bar or pie chart with axis labels, grid, legend when >1 class; `_=` suppression.

**3c. Hypothesis validation** — `# %% [markdown]` cell listing hypotheses gating design decisions, then one `# %%` per hypothesis:

Generate from `problem_type` + `input_modality` — examples:
- *class balance* → affects loss choice; code: `df_train[TARGET_COL].value_counts(normalize=True)`
- *image resolution consistency* → affects resize strategy; code: sample (H, W) scatter
- *label noise / duplicates* → affects augmentation strength; code: check duplicate ids
- *missing files* → affects DataModule robustness; code: `sum(not os.path.exists(p) for p in paths)`

Each hypothesis cell pattern:
```python
# %% [markdown]
# ### Hypothesis: <name>
# <one sentence why this matters for the solution>
# %%
<code to test>
print(f"→ <finding> — design implication: <implication>")
```

**3d. Helper definition (JIT)** — define visualization helpers in `# %%` cell immediately before cell that uses them. Never at top of notebook.

**3e. Sample display** — dispatch by `input_modality`; see `modality-dispatch.md`; uses helper from 3d.

> loads: modality-dispatch.md

**Sample display dispatch** — read `modality-dispatch.md`, apply branch matching `input_modality`:
- `image` → 2D image grid helper
- `image-3d` → volumetric 3-plane viewer + stats (adds tifffile/ipywidgets to setup cell)
- `tabular` → describe + correlation heatmap + target distribution
- `point-cloud` → open3d scatter (adds open3d to setup cell)

**3f. Dimension / size analysis** (image modalities) — scatter of (width, height); axis labels + grid.

Modality-specific installs required by chosen branch go at top of setup `# %%` cell, not inline in Section 3.

## Style enforcement rules for the generator

> loads: style-rules.md

Apply all 11 base rules from `style-rules.md`.

## Output format

Write file at: `.experiments/kaggle/<competition-name>.py`

**Stop after Section 3 (EDA). Do not generate model, training, inference, or submission sections.**

Use Write tool. File must start with:
```python
# %% [markdown]
# # 🔬 <Title>
# Short description of the competition and chosen approach.
```

Return ONLY on the final line:
{"status":"done","file":".experiments/kaggle/<competition-name>.py","lines":N,"sections":3,"problem_type":"<type>","mode":"eda-only","confidence":0.N}
