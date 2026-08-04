# `codex-agentic`

**Manifest SHA-256**: `939d64d1328d0e9167a2ca1bc0586c173186836f2e549787a88b29ee34ee6070`

## Status

- No model or credentials were used to build this manifest.
- Review-ready; human execution is pending.
- Paid execution is admitted only when the caller supplies the exact reviewed machine-manifest SHA-256.
- The 48-cell default scope is exploratory and non-poolable.

## Locked experiment

- Revision: `codex-agentic-shared-suite-2026-08-04`
- Model: `gpt-5.6-luna`, effort `high`.
- Target: `2.6.5` at `be98784a1a03581b7051a355ae1084fd352d7cea`.
- Frozen index SHA-256: `2d48a5ea4ddc3830f83de950713580bbc2e2dd3b43d1326f047cd3e21acec1eb`.
- Suite: `benchmarks/suites/tasks-agentic.json`; raw SHA-256 `adb94fde72b085119ae7ce082078bc86c76f89ed04bd1f27b7146dc3a01b5cfe`.

## Task identities

- Ordered task IDs: `['BA-01', 'BA-02', 'BA-03', 'BA-04', 'BA-05', 'BA-06', 'BA-07', 'BA-08', 'BA-09', 'BA-10', 'BA-11', 'BA-12', 'BA-13', 'BA-14', 'BA-15', 'BA-16']`.
- Each task locks canonical and prompt SHA-256 plus its provider-neutral answer contract.

## Scope and arms

- Tasks: `['BA-01', 'BA-02', 'BA-03', 'BA-04', 'BA-05', 'BA-06', 'BA-07', 'BA-08', 'BA-09', 'BA-10', 'BA-11', 'BA-12', 'BA-13', 'BA-14', 'BA-15', 'BA-16']`; repetitions: `1`; arms: `['A_plain', 'B_auto', 'C_required']`.
- Cells: `48`; coordinate budget: `600s`; complete-run ceiling: `28800s`.
- `A_plain`: Codemap absent; no-call is valid.
- `B_auto`: Codemap CLI available; use is optional, and adoption is measured.
- `C_required`: exact Skill read must precede a successful compact query; noncompliant rows remain scored but are excluded from pooling.

## Artifact and stop contract

- Required package: `run.log`, raw `telemetry.jsonl`, `telemetry-canonical.jsonl`, `run-metadata.json`, frozen `inputs/`, and `checksums.sha256`.
- Stop on the first runtime or admission-integrity failure or complete-run wall-clock exhaustion; ordinary model/task/treatment-nonadherence rows do not stop scheduling; preserve partial artifacts and never pool partial/nonpoolable evidence.

## Shared scoring

- `SCORE` is the mean component score for every declared answer-contract field.
- `CORRECT` requires every declared answer-contract field to score 1.0.

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
CODEX_MAX_WALL_CLOCK_SECONDS=28800 \
  bash benchmarks/run-all.sh codex --agentic
```

Replace `<MANIFEST_SHA256>` with the machine-manifest SHA-256 shown above. The caller supplies authorization; no credential bytes are stored in this manifest.
