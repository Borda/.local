<!-- Loaded by foundry:perf-optimizer (opus + high) -->
# ML / GPU Profiling (foundry:perf-optimizer specialized guidance)

Read this file only when the workload involves GPU/ML profiling (CUDA, PyTorch training, model inference, DataLoader bottlenecks, mixed precision). Skip for pure CPU/IO profiling.

## PyTorch Profiler

```python
import torch
from torch.profiler import profile, record_function, ProfilerActivity

with profile(
    activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA],
    record_shapes=True,
    profile_memory=True,
    with_stack=True,
) as prof:
    with record_function("model_inference"):
        output = model(input_batch)

# Print top operations
print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=20))

# Export for TensorBoard
prof.export_chrome_trace("trace.json")
# tensorboard --logdir=./log --bind_all
```

## GPU Utilization Monitoring

```bash
# Real-time GPU stats
nvidia-smi dmon -s u # utilization stream
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.free \
    --format=csv -l 1 # CSV every second

# nvitop — interactive GPU process monitor (better than nvidia-smi)
pip install nvitop
nvitop
```

## DataLoader Bottleneck Detection

`data_fraction = data_time / step_time > 0.3` → pipeline CPU-bound.
Fix: increase `num_workers` or switch to faster augmentations (e.g. albumentations).

## DataLoader Optimization

Throughput checklist: `num_workers > 0`, `pin_memory=True`, `persistent_workers=True`, `prefetch_factor=2`.
(Boundary with `research:data-steward` (requires `research` plugin) stated in frontmatter NOT-for clause.)

## Mixed Precision (torch.amp — PyTorch 2.0+)

```python
# PyTorch 2.0+: device-agnostic API (torch.cuda.amp deprecated in 2.4)
from torch.amp import autocast, GradScaler

scaler = GradScaler("cuda")
for batch in loader:
    with autocast("cuda", dtype=torch.float16):
        output = model(batch)
        loss = criterion(output, targets)

    scaler.scale(loss).backward()
    scaler.step(optimizer)
    scaler.update()

# Memory reduction: ~50% for fp16; also faster on Tensor Core GPUs
# Measure: torch.cuda.memory_allocated() / torch.cuda.max_memory_allocated()
# For bfloat16 (better numerical stability on Ampere+): dtype=torch.bfloat16
```

## Distributed Training Profiling

Profile DDP overhead by measuring all-reduce time. Common bottlenecks:

- Gradient bucket too small → too many all-reduce calls: `DDP(model, bucket_cap_mb=25)` (increase for large models)
- Uneven data distribution → fast workers wait for slow: `DistributedSampler(drop_last=True)` equalizes batches
- SyncBatchNorm overhead in small-batch regime: only use `sync_batchnorm` when `batch_per_gpu < 16`

## 3D Volumetric Data Performance

See `research:data-steward` (requires `research` plugin) — contains mmap (`np.load(..., mmap_mode="r")`), HDF5 chunk alignment, patch extraction patterns.

## torch.compile

```python
# PyTorch 2.0+: JIT compilation for significant speedup
model = torch.compile(model)  # default (inductor backend)
model = torch.compile(model, mode="reduce-overhead")  # for small batches
model = torch.compile(model, mode="max-autotune")  # max speed, slower compile

# When it helps: repeated forward passes, simple/regular ops, training loops
# When it hurts: very dynamic shapes, lots of Python control flow, first inference
```
