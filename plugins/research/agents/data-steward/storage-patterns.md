<!-- Loaded by research:data-steward (sonnet + medium) -->
# Reference document — NOT an agent definition. Used by research:data-steward as contextual material.
# Storage and Loading Patterns — data-steward reference

Loaded by data-steward in `acquisition` mode before Step 2.
Contains: DVC versioning, Polars tabular loading, HuggingFace datasets, 3D volumetric data loading.

<storage_and_loading_patterns>

## Data Version Control (DVC)

```bash
# Track large dataset files without storing in git
dvc add data/raw/dataset.zip
git add data/raw/dataset.zip.dvc .gitignore
dvc push # push to remote storage (S3, GCS, SSH)

# Reproduce a specific dataset version
git checkout v1.2.0
dvc checkout
```

## Polars (modern pandas alternative for tabular data)

```python
import polars as pl

# Lazy evaluation — plan is optimized before execution
df = pl.scan_csv("data.csv").filter(pl.col("label") != -1).collect()

# Group-aware split with Polars
train = df.filter(pl.col("subject_id").is_in(train_subjects))
test = df.filter(pl.col("subject_id").is_in(test_subjects))
```

Use Polars over pandas: >1M rows, lazy eval needed, or speed matters.

## HuggingFace datasets

```python
from datasets import load_dataset

# Load a public dataset
ds = load_dataset("cifar10", split="train[:10%]")

# Streaming for large datasets
ds = load_dataset("imagenet-1k", streaming=True)

# Save/load custom dataset
ds.save_to_disk("data/processed/")
ds = load_from_disk("data/processed/")
```

## 3D Volumetric Data Loading (medical imaging)

Patch-based 3D Dataset: `self.volumes` + `self.patch_size` in init; `__getitem__` = random patch (train), center crop (val/test) — returns `{"image": patch_array}`.

Key considerations for volumetric data:

- **Memory**: volumes = GBs — use lazy loading:

  ```python
  # Memory-mapped arrays (numpy) — zero-copy reads from disk
  volume = np.load("scan.npy", mmap_mode="r")  # "r" = read-only, "r+" = read-write

  # HDF5 (h5py) — optimal chunk alignment for patch extraction
  import h5py

  # Create/write: use 'w' mode
  with h5py.File("data.h5", "w") as f:
      # Align chunk size to your patch size (e.g., 64x64x64) for minimal partial reads
      f.create_dataset("volumes", shape=(N, D, H, W), chunks=(1, 64, 64, 64), dtype="float32")

  # Read patches: use 'r' mode
  with h5py.File("data.h5", "r") as f:
      ds = f["volumes"]
      patch = ds[idx, z : z + 64, y : y + 64, x : x + 64]  # reads exactly one chunk
  ```

- **Patch extraction**: train on patches, infer with sliding window + overlap for boundary smoothing

- **Orientation**: normalize to canonical (RAS/LPS) before training

- **Spacing**: resample to isotropic voxel spacing if model needs uniform resolution

</storage_and_loading_patterns>
