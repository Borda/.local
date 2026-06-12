<!-- file: full.md — consumers: kaggle/SKILL.md -->

## Required sections — generate ALL (unless --eda-only: stop after EDA)

### Section 1: Header + Setup
`# %% [markdown]` cell:
  - Title: `# 🔬 <Competition Title> ⚡PTL + <ModelLibrary>` (emoji fitting the domain)
  - 2–3 sentences: what the competition is about, approach chosen
  - Link: `Competition: <url-if-known>`

`# %%` cell (setup):
  - **When `OFFLINE_SETUP=true`** (i.e. `--offline-setup` flag passed, or inference is bundled in this notebook):
    - `! cp -r ../input/python-packages/frozen_packages .`
    - `! pip install -q <library> --no-index --find-links frozen_packages/ 2>/dev/null || pip install -q <library>`
  - **When `OFFLINE_SETUP=false`** (default — training-only, internet available):
    - `! pip install -q <library>`
  - `! pip list | grep -E 'torch|lightning|timm'`

### Section 2: Imports + Constants
Single `# %%` cell:
  - stdlib: `import os, glob` (same line for short ones)
  - domain libraries grouped loosely by concern
  - `import warnings; warnings.simplefilter("ignore", UserWarning)` when noisy libs used
  - PATH constants: `PATH_DATASET`, `PATH_OUTPUT`, `PATH_MODELS` — ALL_CAPS, string values
  - Config constants: `BATCH_SIZE`, `MAX_EPOCHS`, `LEARNING_RATE`, `MODEL_NAME`, `IMAGE_SIZE`
  - `nb_epochs = MAX_EPOCHS if torch.cuda.is_available() else 2` (GPU check)
  - Version print block: `print(f"PyTorch: {torch.__version__}")` etc.
  - `pl.seed_everything(42)` (DL notebooks only) — covers torch/numpy/random; no separate manual seeds needed

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

Any modality-specific installs required by the chosen branch go at the top of the setup `# %%` cell.

**Training sanity check** (Section 5 lens cell) also uses the same modality dispatch — call `show_images()` / `show_volume()` / `show_pcd()` on one batch from `train_dataloader()` to verify shapes before first epoch.

### Section 4: Dataset & DataModule (DL) or Feature Engineering (tabular)

**For DL:**
`# %% [markdown]`: `## Dataset & DataModule`

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
  - Missing value handling
  - Categorical encoding
  - Feature creation
  - `# ==============================` separator between steps
  - Train/val split: `X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)`

### Section 5: Model
`# %% [markdown]`: `## Model`

**For DL + PTL:**
`# %%` — LightningModule:
  - `class <Name>Model(pl.LightningModule):`
  - `__init__`: `save_hyperparameters()`, `timm.create_model(arch, pretrained=True, num_classes=<N>)` (`num_classes=0` for regression), one `train_<metric>` + `val_<metric>` TorchMetric
  - `forward(x)`: single line `return self.net(x)`
  - `training_step` / `validation_step`: compute loss, `self.log(..., prog_bar=True)`, metric via `.update()` then `.log()` (not `.compute()` at epoch end)
  - `configure_optimizers`: AdamW + CosineAnnealingLR(`T_max=MAX_EPOCHS`); always include 1–2 commented-out alternatives (e.g. OneCycleLR)

**For tabular XGBoost:**
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
      callbacks=[ckpt, pl.callbacks.LearningRateMonitor()],
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
  plt.gcf().set_size_inches(12, 4)
  plt.grid()
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
  ! head submission.csv
  ```

## Style enforcement rules for the generator

Apply ALL of these in the generated script:

1. **`!` for ALL shell commands — never `subprocess`, never `get_ipython().system()`**: write `! cmd` verbatim; `%matplotlib inline` not `get_ipython().run_line_magic(...)`; if a linter rejects these, fix the linter config — NEVER rewrite the magic syntax
2. `# ==============================` between logical blocks within a cell (not every line — only at major breaks)
3. `_=` to suppress matplotlib/pandas return values: `_= df["col"].plot(...)`
4. ALL_CAPS for paths and config constants
5. Version print block right after imports
6. `! head submission.csv` at the very end — always
7. No `if __name__ == '__main__':` guards
8. No argparse, no dataclasses for config

## Output format

Write the file at: `.experiments/kaggle/<competition-name>.py`

Use the Write tool. The file must start with:
```python
# %% [markdown]
# # 🔬 <Title>
# ...
```

Return ONLY on the final line:
{"status":"done","file":".experiments/kaggle/<competition-name>.py","lines":N,"sections":N,"problem_type":"<type>","confidence":0.N}
