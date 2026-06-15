---
<!-- Loaded by research:scientist (opus + xhigh) -->
# ML Concepts Reference — research:scientist

Loaded on demand for ML-domain experiments. CPU/non-ML or basic experiments do not need this file — keep base agent context lean.

## Evaluation Pitfalls

Test set used for model selection → optimistic bias; max over seeds instead of mean → cherry picking; outdated baselines → unfair advantage; missing error bars; metric doesn't match task.

## Common Architectural Patterns

Attention: self/cross/sparse/Flash; Norm: BatchNorm vs LayerNorm vs RMSNorm; Scaling — Chinchilla optimal (Hoffmann et al. 2022): for a fixed pre-training compute budget C, the compute-optimal model size scales as N ∝ C^0.5 (more tokens on smaller model beats fewer tokens on larger). Scope: pre-training from scratch ONLY — does NOT apply to fine-tuning or inference-time compute allocation. For capability-maximizing (not compute-optimal) training, the Chinchilla point is a floor not a ceiling — longer training past it still improves downstream tasks (LLaMA/Mistral). Transfer: pretraining objectives, fine-tuning, prompt tuning; Uncertainty: ensembles, MC Dropout, conformal prediction.

## Foundation Model Adaptation

Evaluate all four before committing: full fine-tune (large labeled dataset, domain shift) · LoRA/PEFT (moderate data, 1 GPU) · prompt/few-shot (few examples, quick iteration) · RAG (knowledge-intensive, no training data). PEFT techniques (LoRA, IA³, prefix tuning) are primarily designed for transformer attention layers — verify library support (`peft`, `loralib`) for target architecture BEFORE committing: CNNs (ResNet/EfficientNet) require custom adapter insertion at conv layers, state-space models (Mamba/S4) need non-trivial reparameterization, fused-attention decoders may not expose KV cache to prefix tuning. Compare ≥2-3 options from Papers With Code and confirm each is supported on the chosen base model. Evaluation: task-specific metric (exact match, ROUGE-L, pass@k, F1, mAP) + capability retention (forgetting on general benchmarks) + efficiency (latency, memory, throughput).

## Implementing from Papers

1. Read methods section twice + appendix (hyperparams always there)
2. Read official code — papers omit weight init, LR schedule, warmup, gradient clipping
3. Map to existing code; prefer extending over rewriting
4. Verify: gradient clipping, warmup schedule, EMA decay, augmentation order, loss weighting
5. Run paper's own baseline first — can't reproduce baseline = can't reproduce result
6. Validate incrementally: baseline → add component → check metrics

## Connecting Theory to Code

- Paper claims SOTA on benchmark X? Check Papers With Code leaderboard — results may be superseded
- Theoretical proof assumes IID data? Check if dataset violates assumption
- Paper uses specific initialization scheme? Default PyTorch init often different
- Paper reports results at specific resolution or crop size? Ensure dataloader matches

## Computer Vision

Metrics: Detection → mAP@[.5:.95]; Instance Seg → mask mAP + boundary AP; Semantic Seg → mIoU + per-class IoU; Medical Cls → AUC-ROC + sensitivity@specificity; Medical Seg → Dice + Hausdorff@95. Medical: patient splits + annotation consistency → `research:data-steward`. Calibration: ECE + reliability diagrams.

## Framework & Model Agnosticism

Compare from task's Papers With Code leaderboard across PyTorch, JAX/Flax, HuggingFace/timm/Lightning; recommend smallest model meeting accuracy target; check HuggingFace Hub before suggesting training from scratch.

## LLM Evaluation & Benchmarking

Standard benchmarks (MMLU, HumanEval/MBPP, MT-Bench, GSM8K) + `lm-evaluation-harness`; validate LLM-as-judge against human preferences; always include task-specific downstream eval. **Contamination check** (training data leaking into benchmark test sets) — apply by data-access tier:
- **Open training corpus**: run n-gram overlap (≥13-gram exact match is the common threshold) between the corpus and each benchmark test set; EleutherAI's decontamination scripts or `lm-evaluation-harness --check_integrity` are the standard tools.
- **Opaque/proprietary training data**: run the model on PARAPHRASED versions of benchmark questions — large accuracy drop vs originals indicates likely contamination. This is the only viable proxy without training-data access.
- Always report whether a contamination check was possible (and which tier) plus its result; "we did not check" is itself a finding.
**Benchmark scores are proxies** — test on actual task distribution.

## Experiment Tracking & Reproducibility

Track with wandb/MLflow/Comet; pin deps (`uv lock` preferred, `uv pip compile requirements.in` legacy); seed all sources (framework + numpy + random + PYTHONHASHSEED); log git hash, dataset version/hash, hardware, framework version.
