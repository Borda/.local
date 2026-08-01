# `codex-integration-v1`

**Manifest SHA-256**: `2a08c44e084dbbcd2d331a6788d3a54c875a84d8579178abb348412f6a7bd499`

## Purpose

Codex-only A/B/C experiment over the immutable provider-parity task and scoring identities.

## Arms

- `A_plain`: no Codemap package or query access.
- `B_direct_required`: one dedicated successful `"$CODEMAP_BIN" query --compact <subcommand> <arguments>` command item.
- `C_skill_required`: one dedicated exact `cat "$CODEMAP_SKILL_FILE"` item, then one dedicated canonical compact query item.
- B/C may use additional reads and shell commands as separate items; those actions are ignored for attribution.

## Estimands

- `C_skill_required-A_plain`: product effect.
- `B_direct_required-A_plain`: direct CLI effect.
- `C_skill_required-B_direct_required`: integration effect.

## Execution controls

- The 600-second coordinate budget is shared by the initial attempt and any eligible zero-token transport retries.
- Paid execution requires a positive, human-approved `--max-wall-clock-seconds` value recorded in every result row.

## Locked candidates

- `codemap-py` `0.27.0`.
  Package manifest SHA-256: `c47f58ff4bdef34630925e969815d59c331e7cc1675b3cb3e6ab889ab0f6a6db`.
- `codex-rig` `0.4.1`.
- Codex CLI: `{'available': True, 'path': '/opt/homebrew/bin/codex', 'version': 'codex-cli 0.146.0'}`.
- Source manifest: `benchmarks/manifests/provider-parity-methodology.json` SHA-256 `1acecdbf6d58d3380075bbbaf3915b6c43165c1cce1143564ba319651c952394`.

## Study scope

- Execution tasks: `55`.
- Independently scored headline tasks: `45`.
- Diagnostic tasks: `10`.
- Repetitions: `1`.
- Total cells: `165` (`55 tasks × 1 repetition × 3 arms`).
- Model-cell failures are recorded and do not stop the study after admission; integrity, interruption, and 
  complete-run ceiling failures preserve a partial artifact and stop execution.

## Execution

Run the no-model admission smoke first:

```bash
bash benchmarks/run-all.sh smoke
```

After reviewing this manifest and separately authorizing credential use and paid execution:

```bash
CODEX_PAID_APPROVAL=2a08c44e084dbbcd2d331a6788d3a54c875a84d8579178abb348412f6a7bd499 \
    CODEX_AUTH_SOURCE=/private/path/to/auth.json \
    CODEX_RUN_DIR=benchmarks/results/codex-integration-human-run \
    CODEX_MAX_WALL_CLOCK_SECONDS=86400 \
    bash benchmarks/run-all.sh codex
```

The run directory must not already exist. Runtime logs, telemetry, metadata, and checksums stay under the 
ignored `benchmarks/results/` directory unless the user deliberately exports them for review.

## Status

Runtime smoke and exact coordinate-plan validation are required before paid execution. Human review is required before any further paid execution. This manifest rebuild used no model cell or authentication source.
