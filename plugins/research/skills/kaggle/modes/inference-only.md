<!-- file: inference-only.md — consumers: kaggle/SKILL.md -->

## Required sections — INFERENCE ONLY (--inference-only mode)

Generate sections 1–7 below. Skip EDA, Dataset/DataModule training setup, Training sections.
Assume trained checkpoint already exists (prior training run or Kaggle input dataset).

> **Package API note**: patterns below based on past notebooks — some packages may be at older API versions
> (rfdetr, older pytorch_lightning, MONAI). Use most current available API; prefer `pytorch_lightning` over
> `lightning` for Kaggle kernel compatibility. Check with `! pip list | grep -E 'torch|lightning|monai'` in setup cell.

### Section 1: Header + Setup

`# %% [markdown]` cell:
  - Title: `# 🔬 <Competition Title> — Inference` (no PTL/model tag in title for inference-only)
  - 1–2 sentences: checkpoint being loaded, what notebook produces
  - `Checkpoint: <path-or-input-dataset>`

`# %%` cell (setup — inference-only subset):
  - `# ! cp -r ../input/python-packages/frozen_packages .` (frozen offline packages pattern)
  - Install only inference-relevant libs: model architecture lib (timm, monai, rfdetr etc.) + tqdm
  - NO: lightning training callbacks, csv_logger, torchmetrics train_* metrics
  - `# ! pip list | grep -E 'torch|lightning|timm|monai'`

### Section 2: Imports + Constants

Single `# %%` cell:
  - stdlib: `import os, glob` (same line for short ones)
  - `import pandas as pd`, `import numpy as np`, `import matplotlib.pyplot as plt`
  - `from pathlib import Path`
  - `from tqdm.auto import tqdm`
  - `import torch` (always — required for `torch.cuda`, `torch.no_grad`, `torch.tensor`, `torch.argmax`)
  - Domain inference libs — pick by problem type:
    - Classification/regression: `import timm`, `import pytorch_lightning as pl`, `import torch.nn.functional as F`, `from torch.utils.data import Dataset, DataLoader`, `from torchvision import transforms`, `from PIL import Image`
    - Detection: `from torchvision.ops import batched_nms`, `from PIL import Image`, `from torch.utils.data import DataLoader`
    - 3D segmentation: `import torch.nn.functional as F`, `from monai import transforms as MT`, `from monai.networks.nets import SegResNet, SwinUNETR`, `import tifffile`
  - `import warnings; warnings.simplefilter("ignore", UserWarning)`
  - PATH constants: `PATH_DATASET = "/kaggle/input/<competition>"`, `PATH_OUTPUT = "."` (Kaggle working dir — submission and output files land here), `PATH_CHECKPOINT` — ALL_CAPS
  - Inference-only config: `BATCH_SIZE`, `IMAGE_SIZE`, `DEVICE = "cuda" if torch.cuda.is_available() else "cpu"`
  - Version print: `print(f"PyTorch: {torch.__version__}, CUDA: {torch.cuda.is_available()}")`

### Section 3: Load Checkpoint

`# %% [markdown]` header: `## Load Model`

**First: check for `{COMPETITION_NAME}_model.py`** — training notebook used `%%writefile` → import from it instead of redefining class:

```python
# %%
from {competition_name}_model import <Name>Model  # written by training notebook %%writefile cell
```

`{COMPETITION_NAME}_model.py` exists: use this import — do NOT redefine class inline. Absent: choose pattern below, define class fully in this notebook (all required imports).

Choose ONE pattern based on `<recommended_model>` and checkpoint format:

**Pattern A — PTL LightningModule checkpoint (`.ckpt`):**
```python
# %% [markdown]
# ### Load from PTL checkpoint
# %%
PATH_CHECKPOINT = sorted(glob.glob(os.path.join(PATH_DATASET, "checkpoints", "*.ckpt")))[-1]
print(f"Loading: {PATH_CHECKPOINT}")
model = <Name>Model.load_from_checkpoint(PATH_CHECKPOINT)
model.eval().to(DEVICE)
```
(Use when model class defined in this notebook or importable; `load_from_checkpoint` restores hparams automatically.)

**Pattern B — bare torch.load (`.pt` or `.pth`):**
```python
# %%
model = torch.load(PATH_CHECKPOINT, map_location=DEVICE)
# OR when only weights saved:
# model = <Name>Model(**hparams)
# model.load_state_dict(torch.load(PATH_CHECKPOINT, map_location=DEVICE))
model.eval()
```
(Use for non-PTL models or when checkpoint is state_dict only.)

**Pattern C — custom model constructor (e.g. detection models):**
```python
# %%
# rfdetr example — API may differ in current version; check: # ! rfdetr --version
predictor = RFDETRLarge(
    pretrain_weights=str(PATH_CHECKPOINT),
    num_classes=NUM_CLASSES,
    resolution=IMAGE_SIZE,
    device=DEVICE,
)
# predictor.optimize_for_inference(compile=False, batch_size=BATCH_SIZE)  # optional, API version-dependent
```

**Pattern D — MONAI 3D model:**
```python
# %%
net = SegResNet(spatial_dims=3, in_channels=1, out_channels=NUM_CLASSES, init_filters=16)
# net = SwinUNETR(img_size=(128,128,128), in_channels=1, out_channels=NUM_CLASSES)  # alternative
model = <Name>SegModel.load_from_checkpoint(PATH_CHECKPOINT, net=net)
model.eval().to(DEVICE)
```

Lens cell after load — always include:
```python
# %%
print(f"Model: {type(model).__name__}")
print(f"Device: {next(model.parameters()).device}")
print(f"Params: {sum(p.numel() for p in model.parameters()):,}")
```

### Section 4: Test Dataset & DataLoader

`# %% [markdown]` header: `## Test Data`

Build test dataloader WITHOUT labels. Choose by problem type:

**For image classification/regression (no DataModule needed):**
- `class <Name>TestDataset(Dataset)`: loads from df, applies test transforms (Resize(IMAGE_SIZE), ToTensor, Normalize with ImageNet stats), returns `(tensor, image_id_str)`
- `DataLoader`: `shuffle=False`, `num_workers=os.cpu_count()`, `pin_memory=True`
- print sample count + batch count after construction

**For detection (single-image inference, no DataLoader):**
```python
# %%
df_test = pd.read_csv(os.path.join(PATH_DATASET, "test.csv"))
test_image_paths = [os.path.join(PATH_DATASET, "test_images", f"{row.image_id}.jpg") for _, row in df_test.iterrows()]
print(f"Test images: {len(test_image_paths)}")
```

**For 3D segmentation:**
```python
# %%
test_ids = sorted(os.listdir(os.path.join(PATH_DATASET, "test")))
val_transforms = MT.Compose([
    MT.Resized(keys=["image"], spatial_size=(160, 160, 160), mode="trilinear"),
])
print(f"Test volumes: {len(test_ids)}")
```

### Section 5: Inference Loop

`# %% [markdown]` header: `## Inference`

Choose by problem type:

**Classification/regression — standard loop:**
```python
# %%
all_preds, all_ids = [], []
model.eval()
for imgs, img_ids in tqdm(test_loader, desc="Inference"):
    with torch.no_grad():
        logits = model(imgs.to(DEVICE))
        preds = torch.sigmoid(logits).cpu().numpy()  # for binary; use softmax for multi-class
    all_preds.extend(preds.tolist())
    all_ids.extend(img_ids)
print(f"Predictions: {len(all_preds)}")
```

**Detection — per-image, with NMS:**
```python
# %%
results = []
for img_path in tqdm(test_image_paths, desc="Detecting"):
    img = Image.open(img_path).convert("RGB")
    image_id = Path(img_path).stem
    # Pattern A (rfdetr-style):
    dets = predictor.predict(img, threshold=PRE_THRESHOLD)
    if len(dets) == 0:
        results.append({"image_id": image_id, "PredictionString": NEGATIVE_PRED})
        continue
    boxes = torch.tensor(dets.xyxy, dtype=torch.float32)
    scores = torch.tensor(dets.confidence, dtype=torch.float32)
    labels = torch.tensor(dets.class_id, dtype=torch.long)
    # Per-class NMS
    keep = batched_nms(boxes, scores, labels, iou_threshold=NMS_IOU)
    boxes, scores, labels = boxes[keep].numpy(), scores[keep].numpy(), labels[keep].numpy()
    results.append({"image_id": image_id, "boxes": boxes, "scores": scores, "labels": labels})
```

**3D segmentation — sliding window or full-volume:**
```python
# %%
predictions = {}
for vol_id in tqdm(test_ids, desc="Segmenting"):
    vol = tifffile.imread(os.path.join(PATH_DATASET, "test", vol_id))
    original_shape = vol.shape
    vol_tensor = torch.from_numpy(vol.astype(np.float32)).unsqueeze(0).unsqueeze(0).to(DEVICE)
    # Resize to model input size
    vol_resized = F.interpolate(vol_tensor, size=(160, 160, 160), mode='trilinear', align_corners=False)
    with torch.no_grad():
        logits = model(vol_resized)
        pred = torch.argmax(logits, dim=1).squeeze(0)
    # Restore to original shape
    pred_restored = F.interpolate(
        pred.float().unsqueeze(0).unsqueeze(0), size=original_shape, mode='nearest'
    ).squeeze().byte().cpu().numpy()
    predictions[vol_id] = pred_restored
print(f"Segmented: {len(predictions)} volumes")
```

### Section 6: Post-processing

`# %% [markdown]` header: `## Post-processing`

Choose by problem type:

**Classification — threshold + visualization:**
```python
# %%
THRESHOLD = 0.5
binary_preds = (np.array(all_preds) > THRESHOLD).astype(int)
# Distribution check
_= pd.Series(binary_preds).value_counts().plot(kind='bar', title='Prediction distribution')
plt.xlabel("class")
plt.ylabel("count")
plt.grid(True)
```

**Detection — coordinate rescaling (when model uses fixed resolution):**
```python
# %%
def rescale_boxes(boxes, src_size, dst_size):
    """Rescale xyxy boxes from src_size (W,H) to dst_size (W,H)."""
    sx, sy = dst_size[0] / src_size[0], dst_size[1] / src_size[1]
    return boxes * np.array([sx, sy, sx, sy])
```

**3D segmentation — morphological cleanup (GPU Conv3d or scipy):**
```python
# %%
from scipy.ndimage import binary_closing, label as scipy_label

def post_process_3d(vol: np.ndarray, min_size: int = 500, closing_radius: int = 3) -> np.ndarray:
    binary = vol > 0
    closed = binary_closing(binary, iterations=closing_radius)
    labeled, n = scipy_label(closed)
    sizes = np.bincount(labeled.ravel())
    small = np.where(sizes < min_size)[0]
    for s in small:
        closed[labeled == s] = 0
    return closed.astype(np.uint8)

predictions_clean = {vid: post_process_3d(mask) for vid, mask in tqdm(predictions.items())}
```

### Section 7: Submission

`# %% [markdown]` header: `## Submission`

Choose by output format:

**Classification/regression CSV:**
```python
# %%
df_sub = pd.read_csv(os.path.join(PATH_DATASET, "sample_submission.csv"))
df_sub["<target_col>"] = all_preds  # or binary_preds for classification
df_sub.to_csv("submission.csv", index=False)
# ! head submission.csv
```

**Detection — space-separated prediction string:**
```python
# %%
NEGATIVE_PRED = "<no-finding-class-id> 1.0 0 0 1 1"

def format_preds(boxes, scores, labels):
    if len(boxes) == 0:
        return NEGATIVE_PRED
    return " ".join(f"{int(c)} {s:.6f} {int(x1)} {int(y1)} {int(x2)} {int(y2)}"
                    for (x1,y1,x2,y2), s, c in zip(boxes, scores, labels))

df_sub = pd.read_csv(os.path.join(PATH_DATASET, "sample_submission.csv"))
df_sub["PredictionString"] = [format_preds(**r) if "boxes" in r else NEGATIVE_PRED for r in results]
df_sub.to_csv("submission.csv", index=False)
# ! head submission.csv
```

**3D segmentation — TIFF per volume:**
```python
# %%
os.makedirs(PATH_OUTPUT, exist_ok=True)
for vol_id, mask in predictions_clean.items():
    out_path = os.path.join(PATH_OUTPUT, f"{vol_id}.tif")
    tifffile.imwrite(out_path, mask)
    print(f"Saved: {out_path} shape={mask.shape}")
print(f"Saved {len(predictions_clean)} masks to {PATH_OUTPUT}")
```

## Style enforcement rules for the generator

> loads: style-rules.md

Apply all 11 base rules from `style-rules.md`, plus:

12. `# ! head submission.csv` at very end (or equivalent output confirmation for non-CSV formats)
13. **Package API note**: verify API compatibility before use — prefer `pytorch_lightning` over `lightning` for Kaggle; MONAI transforms dict-key API (`keys=["image"]`) is current; rfdetr/custom libs — check `# ! pip show <lib>` for installed version

## Output format

Write file at: `.experiments/kaggle/<competition-name>-inference.py`

Suffix `-inference` distinguishes from training notebook.

Use Write tool. File must start with:
```python
# %% [markdown]
# # 🔬 <Title> — Inference
# Short description: checkpoint loaded, what this notebook produces.
```

Return ONLY on the final line:
{"status":"done","file":".experiments/kaggle/<competition-name>-inference.py","lines":N,"sections":7,"problem_type":"<type>","mode":"inference-only","confidence":0.N}
