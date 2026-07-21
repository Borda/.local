<!-- file: inference.md — selected by composition.md -->

# Inference section contract

Use the context selected by `composition.md`:

- `attached`: Section 7 of a full notebook, after training.
- `standalone`: Sections 3–6 of an inference-only notebook, starting from a grounded checkpoint.

## Attached context

Include both paths:

1. Run inference with the trained in-memory model under `torch.no_grad()`.
2. Load the best saved checkpoint/model artifact in a separate cell and run an equivalent prediction smoke check.

Use the test loader from the training pipeline, move only inference outputs to CPU, retain stable sample identifiers, and verify prediction count/shape before submission.

## Standalone context

### Section 3: Load model

Ground checkpoint path, format, model class, and required constructor arguments. Prefer importing `<competition>_model.py` emitted by training. If unavailable, define the complete model class with verified imports rather than inventing an API.

Choose the loader by evidence:

- Lightning `.ckpt`: `Model.load_from_checkpoint(...)` with the importable class.
- State dict `.pt`/`.pth`: construct the verified architecture, load the state dict, and check missing/unexpected keys.
- Serialized module: use `torch.load(..., map_location=DEVICE)` only when the artifact is known to contain a full trusted module.
- Custom detector/MONAI model: verify the installed constructor and checkpoint contract first.

Fail clearly when no checkpoint matches; never index `sorted(...)[-1]` without an empty-match guard. Set evaluation mode, move to the selected device, and print model type, device, and parameter count.

### Section 4: Test data

Build a label-free test Dataset/DataLoader or grounded modality equivalent:

- preserve sample ordering and stable IDs;
- use evaluation transforms matching training;
- set `shuffle=False`;
- assert batch shape and dtype;
- print sample and batch counts;
- handle empty test data explicitly.

Detection may use single-image iteration when required by the verified predictor API. Volumetric pipelines must preserve original shape metadata for output restoration.

### Section 5: Inference loop

Run under `torch.no_grad()` and choose output activation/decoding from the grounded task:

- binary classification: sigmoid only when the model returns logits;
- multiclass: softmax/argmax according to submission requirements;
- regression: retain scalar/vector predictions without classification transforms;
- detection: apply verified confidence filtering and class-aware NMS when the model does not already do so;
- segmentation: restore predictions to grounded original dimensions with appropriate interpolation.

Collect predictions and IDs, then assert count, shape, dtype, finiteness, and expected range before post-processing. CPU transfer is allowed here, outside the training loop.

### Section 6: Post-processing

Apply only post-processing justified by the metric and output contract:

- threshold calibration for classification;
- box rescaling and formatting for detection;
- morphology/component filtering for segmentation;
- inverse transforms for normalized regression targets.

Keep parameters in a just-in-time config cell. Define helpers immediately before use.

## Inference lens

Show a small prediction sample, print prediction/ID counts and shapes, check NaN/Inf and range constraints, and compare the attached in-memory versus reloaded path when both exist.
