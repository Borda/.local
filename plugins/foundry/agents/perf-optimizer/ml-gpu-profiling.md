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

> **Platform notes** — nvidia-smi and CUDA-specific calls above apply to NVIDIA GPUs only:
> - **Apple MPS**: use `torch.profiler` with `torch.device("mps")`; no nvidia-smi; monitor via Activity Monitor (GPU History) or Instruments (Metal System Trace)
> - **AMD ROCm**: replace `nvidia-smi` with `rocm-smi`; `torch.profiler` with `ProfilerActivity.CPU` works; omit `ProfilerActivity.CUDA`
> - **Intel Arc**: use Intel VTune Profiler or `torch.profiler` with XPU backend; no nvidia-smi

## DataLoader Bottleneck Detection

`data_fraction = data_time / step_time > 0.3` → pipeline CPU-bound.
Fix: increase `num_workers` or switch to faster augmentations (e.g. albumentations).

## DataLoader Optimization

DataLoader pipeline config (`num_workers`, `persistent_workers`, `pin_memory`, `prefetch_factor`): see `research:data-steward` (requires `research` plugin).

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

# Variable batch sizes: torch.compile(model, dynamic=True) prevents per-shape recompilation.

# When it helps: repeated forward passes, simple/regular ops, training loops
# When it hurts: very dynamic shapes, lots of Python control flow, first inference
```
