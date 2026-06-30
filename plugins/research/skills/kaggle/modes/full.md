<!-- file: full.md — consumers: kaggle/SKILL.md -->

## Required sections — generate ALL (unless --eda-only: stop after EDA)

### Section 1: Header + Setup
`# %% [markdown]` cell:
  - Title: `# 🔬 <Competition Title> ⚡PTL + <ModelLibrary>` (emoji fitting the domain)
  - 2–3 sentences: what the competition is about, approach chosen
  - Link: `Competition: <url-if-known>`

`# %%` cell (setup):
  - **When `OFFLINE_SETUP=true`** (i.e. `--offline-setup` flag passed, or inference is bundled in this notebook):
    - `# ! cp -r ../input/python-packages/frozen_packages .`
    - `# ! pip install -q <library> --no-index --find-links frozen_packages/ 2>/dev/null || pip install -q <library>`
  - **When `OFFLINE_SETUP=false`** (default — training-only, internet available):
    - `# ! pip download -q <library> --dest frozen_packages/`
    - `# ! pip install -q --no-index --find-links frozen_packages/ <library> 2>/dev/null || pip install -q <library>`
  - `# ! pip list | grep -E 'torch|lightning|timm'`

### Section 2: Imports + Path Constants
Single `# %%` cell — global imports and paths only; **config constants live JIT in their section**:
  - stdlib: `import os, glob` (same line for short ones)
  - domain libraries grouped loosely: numpy/pandas first, then torch/timm/pl, then sklearn/xgb
  - `from tqdm.auto import tqdm` (not `tqdm.tqdm` — auto selects notebook vs terminal bar)
  - `import warnings; warnings.simplefilter("ignore", UserWarning)` when noisy libs used
  - PATH constants only: `PATH_DATASET = "/kaggle/input/<competition>"`, `PATH_OUTPUT = "."`, `PATH_MODELS` — ALL_CAPS
  - Version print block: `print(f"PyTorch: {torch.__version__}")`, `print(f"Device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")`
  - `pl.seed_everything(42)` (DL notebooks only) — covers torch/numpy/random; no separate manual seeds needed

> **JIT constants rule**: do NOT dump all constants here. Each major section opens with its own config block — EDA constants before EDA, DataModule constants before Dataset class, Model constants before Model class. Reader sees config exactly when it becomes relevant.

### Section 3: EDA
`# %% [markdown]` header: `## EDA` — include explanation of what/why/how it contributes to the solution.

**EDA config block** — first `# %%` cell in this section (JIT constants):
```python
# %%
SAMPLE_N = 9          # images shown in sample grid
TARGET_COL = "<col>"  # label column name in df_train
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

**3b. Label / target distribution**
- bar or pie chart with axis labels, grid, legend when >1 class; `_=` suppression

**3c. Hypothesis validation** — `# %% [markdown]` cell listing hypotheses that gate design decisions, then one `# %%` per hypothesis:

Generate hypotheses from `problem_type` + `input_modality` — examples:
- *class balance* → affects loss function choice (BCE vs weighted cross-entropy); code: `df_train[TARGET_COL].value_counts(normalize=True)`
- *image resolution consistency* → affects whether fixed-resize is safe; code: read a sample of images, collect (H, W), plot scatter
- *label noise / duplicates* → affects augmentation strength; code: check duplicate `image_id` rows
- *missing modality files* → affects DataModule robustness; code: `sum(not os.path.exists(p) for p in paths)`

Each hypothesis cell pattern:
```python
# %% [markdown]
# ### Hypothesis: <name>
# <one-sentence why this matters for the solution>
# %%
<code to test hypothesis>
# conclusion printed inline: print(f"→ Imbalance ratio: {ratio:.2f} — use weighted loss: {ratio > 3}")
```

**3d. Helper definition (JIT)** — define visualization helpers in a `# %%` cell immediately before the cell that uses them. Never define helpers at top of notebook. Pattern:
```python
# %%
def show_images(imgs, titles=None, cols=3):
    """Display a grid of tensors or PIL images."""
    ...
```

**3e. Sample display** — dispatch by `input_modality`; see `modality-dispatch.md`
- uses helper defined in 3d

> loads: modality-dispatch.md

**Sample display dispatch** — read `modality-dispatch.md` and apply the branch matching `input_modality`:
- `image` → 2D image grid helper
- `image-3d` → volumetric 3-plane viewer + stats (adds tifffile/ipywidgets to setup cell)
- `tabular` → describe + correlation heatmap + target distribution
- `point-cloud` → open3d scatter (adds open3d to setup cell)

**3f. Dimension / size analysis** (image modalities) — scatter of (width, height) with marginal histograms; axis labels + grid.

Any modality-specific installs required by the chosen branch go at the top of the setup `# %%` cell.

**Training sanity check** (Section 5 lens cell) also uses the same modality dispatch — call `show_images()` / `show_volume()` / `show_pcd()` on one batch from `train_dataloader()` to verify shapes before first epoch.

### Section 4: Dataset & DataModule (DL) or Feature Engineering (tabular)

**For DL:**
`# %% [markdown]`: `## Dataset & DataModule` — include explanation.

**DataModule config block** — first `# %%` in this section (JIT constants derived from EDA findings):
```python
# %%
IMAGE_SIZE  = 224    # from EDA: median image dimension; set to nearest power-of-2 ≥ median
BATCH_SIZE  = 32
VAL_SPLIT   = 0.2
NUM_WORKERS = os.cpu_count()
```

`# %%` — Dataset class:
  - `class <Name>Dataset(Dataset):`
  - `__init__` accepts pre-split df + optional transforms (no mode arg — splitting done in DataModule only)
  - `__getitem__` returns `(image_tensor, label_tensor)` or `(image_tensor, label_tensor, id_str)`

`# %%` — DataModule class:
  - `class <Name>DM(pl.LightningDataModule):`
  - `__init__` accepts path, batch_size, num_workers (defaults to `os.cpu_count()`)
  - `setup()` shuffles + splits via `sample(frac=1, random_state=42)` — sole split mechanism
  - standard dataloader methods defined

`# %%` — **Lens cell** (sanity check):
  ```python
  dm = <Name>DM(PATH_DATASET, batch_size=BATCH_SIZE)
  dm.setup()
  batch = next(iter(dm.train_dataloader()))
  print(f"Batch shapes: x={batch[0].shape}, y={batch[1].shape}")
  show_images(batch[0][:9])  # show first 9 images from batch
  ```

**For tabular:**
`# %% [markdown]`: `## Feature Engineering`

`# %%` cells for:
  - CSV load: `pd.read_csv(...)` + `display(df.head())`; parquet: `pd.read_parquet(path)` or multi-file merge: `pd.concat([pd.read_parquet(p) for p in glob.glob(str(folder / "*.parquet"))])`
  - Missing value handling
  - Categorical encoding
  - Feature creation
  - `# ==============================` separator between steps
  - Train/val split: `X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)`

**Image preprocessing (when needed before Dataset):**
```python
# %%
from joblib import Parallel, delayed
_ = Parallel(n_jobs=os.cpu_count())(delayed(preprocess_fn)(p) for p in tqdm(image_paths))
```

### Section 5: Model
`# %% [markdown]`: `## Model` — include explanation.

**Model config block** — first `# %%` in this section (JIT constants):
```python
# %%
MODEL_NAME     = "efficientnet_b0"  # timm model name — swap to compare architectures
MAX_EPOCHS     = 10
LEARNING_RATE  = 1e-3
nb_epochs      = MAX_EPOCHS if torch.cuda.is_available() else 2  # safe CPU fallback
```

**For DL + PTL — `%%writefile` pattern (mandatory for DL models):**

Write the model class to a standalone file using `%%writefile` so inference notebooks can import without duplication:

```python
# %%
%%writefile {COMPETITION_NAME}_model.py

# ALL imports the class needs — this file is standalone
import torch
import torch.nn as nn
import pytorch_lightning as pl
from torchmetrics import <Metric>
# ... other imports required by the class (no notebook globals available here)


class <Name>Model(pl.LightningModule):
    # __init__: save_hyperparameters(); timm.create_model(arch, pretrained=True, num_classes=<N>)
    #           (num_classes=0 for regression); one train_<metric> + val_<metric> TorchMetric
    # forward(x): single line return self.net(x)
    # training_step / validation_step: compute loss, self.log("...", logger=True, prog_bar=True),
    #           metric via .update() then .log() (not .compute() at epoch end)
    # configure_optimizers: AdamW + CosineAnnealingLR(T_max=MAX_EPOCHS);
    #           always 1–2 commented-out alternatives (e.g. OneCycleLR)
    ...
```

Follow with an import cell to make the class available in the training notebook:
```python
# %%
from {competition_name}_model import <Name>Model
```

The inference notebook then imports the same file — zero duplication, zero divergence.

**For tabular XGBoost (no writefile needed — no inference notebook reuse):**
  - `xgb.XGBClassifier`/`XGBRegressor` with `device="cuda"` (XGBoost 2.0+ API — not deprecated `tree_method`), `enable_categorical=True`, `random_state=42`

### Section 6: Training
`# %% [markdown]`: `## Training`

`# %%`:
  ```python
  model = <Name>Model(arch=MODEL_NAME)
  dm = <Name>DM(PATH_DATASET, batch_size=BATCH_SIZE)

  # ==============================
  logger = pl.loggers.CSVLogger(save_dir="logs/", name=MODEL_NAME)
  ckpt = pl.callbacks.ModelCheckpoint(
      monitor="valid_<metric>",
      save_top_k=1,
      mode="max",  # or "min" for loss/RMSE
      filename="{epoch}-{valid_<metric>:.3f}",
  )
  # ==============================
  trainer = pl.Trainer(
      # fast_dev_run=True,  # debug
      accelerator="auto",
      devices="auto",
      max_epochs=nb_epochs,
      precision="16-mixed",
      accumulate_grad_batches=4,
      callbacks=[
          ckpt,
          pl.callbacks.LearningRateMonitor(),
          pl.callbacks.EarlyStopping(monitor="valid_<metric>", patience=5, mode="max"),
          # pl.callbacks.StochasticWeightAveraging(swa_lrs=1e-2),  # SWA alternative
      ],
      logger=logger,
      log_every_n_steps=5,
      # val_check_interval=0.5,  # check val twice per epoch
  )
  trainer.fit(model=model, datamodule=dm)
  print(f"Best model: {ckpt.best_model_path}")
  ```

**Lens cell** (training log visualization):
  ```python
  metrics = pd.read_csv(f"{logger.log_dir}/metrics.csv")
  del metrics["step"]
  metrics.set_index("epoch", inplace=True)
  display(metrics.dropna(axis=1, how="all").head())
  g = sns.relplot(data=metrics, kind="line")
  g.set_axis_labels("epoch", "value")
  plt.gcf().set_size_inches(12, 4)
  plt.grid(True)
  plt.legend()
  ```

### Section 7: Inference
`# %% [markdown]`: `## Inference`

Two sub-patterns — BOTH present in same script:

**7a. Inline inference** (use trained model directly):
  ```python
  model.eval()
  preds = []
  with torch.no_grad():
      for batch in tqdm(dm.test_dataloader(), desc="Predicting"):
          x = batch[0].to(model.device)
          y_hat = model(x)
          preds.extend(y_hat.cpu().numpy())
  ```

**7b. Load-from-checkpoint** (separate notebook pattern):
  ```python
  # %% [markdown]
  # ## Inference from saved checkpoint
  # Load trained model — attach this notebook to a previous training run.
  # Previous notebook output: logs/<model-name>/version_0/checkpoints/*.ckpt
  # %%
  PATH_CHECKPOINT = sorted(glob.glob("logs/<model-name>/version_0/checkpoints/*.ckpt"))[-1]
  model_loaded = <Name>Model.load_from_checkpoint(PATH_CHECKPOINT)
  model_loaded.eval()
  ```

### Section 8: Submission
`# %% [markdown]`: `## Submission`

`# %%`:
  ```python
  df_sub = pd.read_csv(os.path.join(PATH_DATASET, "sample_submission.csv"))
  df_sub["<target_col>"] = preds
  df_sub.to_csv("submission.csv", index=False)
  # ! head submission.csv
  ```

## Style enforcement rules for the generator

> loads: style-rules.md

Apply all 11 base rules from `style-rules.md`, plus:

11. `# ! head submission.csv` at the very end — always

## Output format

Write the file at: `.experiments/kaggle/<competition-name>.py`

Use the Write tool. The file must start with:
```python
# %% [markdown]
# # 🔬 <Title>
# Short description of the competition and the chosen approach.
```

Return ONLY on the final line:
{"status":"done","file":".experiments/kaggle/<competition-name>.py","lines":N,"sections":N,"problem_type":"<type>","confidence":0.N}
