# `codex-agentic-ba01`

**Manifest SHA-256**: `b81e9a9574d150179396478b06b3afb0339bf41abd71f4cf7cd3c6ed364cfdf2`

## Status

- No model or credentials were used to build this manifest.
- Review-ready; human execution is pending.
- Paid execution is admitted only when the caller supplies the exact reviewed machine-manifest SHA-256.
- The 9-cell scope is exploratory and non-poolable.

## Locked experiment

- Revision: `codex-agentic-ba01-review-ready-2026-08-04`
- Model: `gpt-5.6-luna`, effort `high`.
- Target: `2.6.5` at `be98784a1a03581b7051a355ae1084fd352d7cea`.
- Frozen index SHA-256: `2d48a5ea4ddc3830f83de950713580bbc2e2dd3b43d1326f047cd3e21acec1eb`.
- Suite: `benchmarks/suites/tasks-agentic.json`; raw SHA-256 `97e762235b57cd819ca5710052ab34426f96141c50b65717e58467a08dc503e9`.

## BA-01 identity

- `BA-01` `blast_radius_analysis` / `simple` on `lightning.pytorch.callbacks.timer`.
- Canonical task SHA-256: `81593f20e4ba763226145cb9e3d56414c9f341f87086bbd551ea5375a542143f`.
- Prompt SHA-256: `6f184b152622b43506fc561cbc080a0fbc8093c1b475c7c3664f26a0be086479`.
- Oracle: `independent`; Claude `GroundTruth.score` is reused.

## Scope and arms

- Tasks: `['BA-01']`; repetitions: `3`; arms: `['A_plain', 'B_auto', 'C_required']`.
- Cells: `9`; coordinate budget: `600s`; complete-run ceiling: `5400s`.
- `A_plain`: Codemap absent; no-call is valid.
- `B_auto`: Codemap CLI available; use is optional, and adoption is measured.
- `C_required`: exact Skill read must precede a successful compact query; noncompliant rows remain scored but are excluded from pooling.

## Artifact and stop contract

- Required package: `run.log`, raw `telemetry.jsonl`, `telemetry-canonical.jsonl`, `run-metadata.json`, frozen `inputs/`, and `checksums.sha256`.
- Stop on the first runtime or admission-integrity failure or complete-run wall-clock exhaustion; ordinary model/task/treatment-nonadherence rows do not stop scheduling; preserve partial artifacts and never pool partial/nonpoolable evidence.

## Shared scoring

- `EREC = erec_tp / max(len(expected), 1)`; `E@10 = top10_tp / max(len(top10), 1)`.
- `RREC = rrec_tp / max(len(expected), 1)`; `DEFF = erec_tp / max(tool_calls, 1)`.

## Runner

- `benchmarks/run-codex-agentic.py`
- No credential path or auth material is recorded in the machine lock; the caller supplies a private source at execution time.

## Human execution and approval

Review the no-model plan first:

```bash
bash benchmarks/run-all.sh codex --agentic --dry-run
```

Then run the exact reviewed scope with a fresh run directory:

```bash
CODEX_AGENTIC_PAID_APPROVAL=<MANIFEST_SHA256> \
CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
CODEX_RUN_DIR="benchmarks/results/codex-agentic-$(date -u +%Y%m%dT%H%M%SZ)" \
CODEX_MAX_WALL_CLOCK_SECONDS=5400 \
  bash benchmarks/run-all.sh codex --agentic
```

Replace `<MANIFEST_SHA256>` with the machine-manifest SHA-256 shown above. The caller supplies authorization; no credential bytes are stored in this manifest.
