<!-- file: training.md — selected by composition.md -->

# Training section contract

Generate data/features, model, and training. Derive configuration from EDA evidence.

## Section 4: Dataset/DataModule or feature engineering

Open with a markdown header and a just-in-time config cell for batch size, input size, validation fraction, and workers.

For neural pipelines:

- Make the Dataset accept a pre-split table/index plus transforms; do not hide splitting in a mode argument.
- Return tensors and stable identifiers needed by inference.
- Assert tensor shape and dtype at the Dataset/DataLoader boundary.
- Make the LightningDataModule the sole owner of a seeded, leakage-aware split.
- Use grouped or stratified splitting when grounded EDA requires it; do not default blindly to row shuffling.
- Define train/validation/test loaders with explicit shuffle and worker behavior.

For tabular/non-neural pipelines:

- Build a reproducible sklearn/XGBoost pipeline for missing values, categoricals, and feature transforms.
- Use a seeded split appropriate to target and group structure.
- Keep preprocessing fitted on training data only.

Add a lens cell that creates the pipeline, asserts a non-empty batch/sample, prints shapes and dtypes, and visualizes a representative batch through the selected modality helper when meaningful. Do not conditionally skip this required check.

## Section 5: Model

Open with a markdown header and just-in-time model constants such as `MODEL_NAME`, `MAX_EPOCHS`, and `LEARNING_RATE`.

For neural training:

- Use a LightningModule and current verified package APIs.
- Save hyperparameters needed for checkpoint restoration.
- Keep `forward` shallow; validate model input/output shape and dtype.
- Choose loss and TorchMetrics from the grounded competition metric and EDA findings.
- Log separate train/validation metrics without manual epoch-end metric misuse.
- Use AdamW plus a justified scheduler; commented alternatives are optional, not mandatory clutter.
- Write the reusable model definition with `%%writefile <competition>_model.py` when a companion inference notebook must import it, then import it in the training notebook.

For pure tabular baselines, use a verified sklearn/XGBoost API and fixed random seed; do not wrap it in Lightning.

## Section 6: Training

For Lightning training:

- Use `CSVLogger`, `ModelCheckpoint`, `LearningRateMonitor`, and justified early stopping.
- Set `accelerator="auto"`, `devices="auto"`, and a supported mixed-precision setting.
- Match checkpoint/early-stopping direction to the grounded metric.
- Keep a visible `fast_dev_run` option for debugging without claiming it was executed.
- Call `trainer.fit` after the training configuration and lens checks are ready.
- Print the actual best checkpoint path after training.

For non-neural training, fit the pipeline and evaluate the grounded metric on validation data with the correct direction.

### Training lens

Read `metrics.csv` for neural runs, display metric columns, and plot train/validation curves. For non-neural runs, display validation metrics and relevant diagnostics.
