<!-- file: eda-only.md — consumers: kaggle/SKILL.md -->

## Required sections — EDA ONLY (--eda-only mode)

Generate ONLY sections 1–3 below. Do not generate Dataset/DataModule, Model, Training, Inference, or Submission sections.

### Section 1: Header + Setup
`# %% [markdown]` cell:
  - Title: `# 🔬 <Competition Title> ⚡PTL + <ModelLibrary>` (emoji fitting the domain)
  - 2–3 sentences: what the competition is about, approach chosen
  - Link: `Competition: <url-if-known>`

`# %%` cell (setup — EDA always online, no frozen packages):
  - `! pip install -q <library>`
  - `! pip list | grep -E 'torch|lightning|timm'`

### Section 2: Imports + Constants
Single `# %%` cell:
  - stdlib: `import os, glob` (same line for short ones)
  - domain libraries grouped loosely by concern
  - `import warnings; warnings.simplefilter("ignore", UserWarning)` when noisy libs used
  - PATH constants: `PATH_DATASET`, `PATH_OUTPUT`, `PATH_MODELS` — ALL_CAPS, string values
  - Config constants: `BATCH_SIZE`, `MAX_EPOCHS`, `LEARNING_RATE`, `MODEL_NAME`, `IMAGE_SIZE`
  - Version print block: `print(f"PyTorch: {torch.__version__}")` etc.
  - `pl.seed_everything(42)` (DL notebooks only)

### Section 3: EDA
`# %% [markdown]` header: `## EDA`

Sub-cells (each a separate `# %%`):
1. Load metadata CSV: `df_train = pd.read_csv(...)`, `print(f"size: {len(df_train)}")`, `display(df_train.head())`
2. Label/target distribution: pie or bar chart, value_counts; `_=` suppression pattern
3. Sample display — dispatch by `input_modality`; see `modality-dispatch.md`
4. Dimension/size analysis if `image`: scatter of (width, height) with marginal histograms

> loads: modality-dispatch.md

**Sample display dispatch** — read `modality-dispatch.md` and apply the branch matching `input_modality`:
- `image` → 2D image grid helper
- `image-3d` → volumetric 3-plane viewer + stats (adds tifffile/ipywidgets to setup cell)
- `tabular` → describe + correlation heatmap + target distribution
- `point-cloud` → open3d scatter (adds open3d to setup cell)

Any modality-specific installs required by the chosen branch go at the top of the setup `# %%` cell, not inline in Section 3.

## Style enforcement rules for the generator

Apply ALL of these in the generated script:

1. **`!` for ALL shell commands — never `subprocess`, never `get_ipython().system()`**: write `! cmd` verbatim; `%matplotlib inline` not `get_ipython().run_line_magic(...)`; if a linter rejects these, fix the linter config — NEVER rewrite the magic syntax
2. `# ==============================` between logical blocks within a cell (not every line — only at major breaks)
3. `_=` to suppress matplotlib/pandas return values: `_= df["col"].plot(...)`
4. ALL_CAPS for paths and config constants
5. Version print block right after imports
6. No `if __name__ == '__main__':` guards
7. No argparse, no dataclasses for config

## Output format

Write the file at: `.experiments/kaggle/<competition-name>.py`

**Stop after Section 3 (EDA). Do not generate model, training, inference, or submission sections.**

Use the Write tool. The file must start with:
```python
# %% [markdown]
# # 🔬 <Title>
# ...
```

Return ONLY on the final line:
{"status":"done","file":".experiments/kaggle/<competition-name>.py","lines":N,"sections":3,"problem_type":"<type>","mode":"eda-only","confidence":0.N}
