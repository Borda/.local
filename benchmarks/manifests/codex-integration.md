# `codex-integration-v1`

**Manifest SHA-256**: `166aee12da65b4eac0a85114128ef78961dca60a79712d22510be5a4e23453a0`

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
- Source manifest: `benchmarks/manifests/provider-parity-methodology.json` SHA-256 `bfa7a196edda7709f9049b366a2ddc1128878498bd6ed58bbe524c5d30960269`.

## Study scope

- Execution tasks: `55`.
- Independently scored headline tasks: `45`.
- Diagnostic tasks: `10`.
- Repetitions: `1`.
- Total cells: `165` (`55 tasks × 1 repetition × 3 arms`).
- Model-cell failures are recorded and do not stop the study after admission; integrity, interruption, and 
  complete-run ceiling failures preserve a partial artifact and stop execution.

## Execution

Run the exact no-model Codex smoke and 165-coordinate plan first:

```bash
bash benchmarks/run-all.sh codex --dry-run
```

After reviewing this manifest, launch the paid study with the manifest-bound command:

```bash
CODEX_PAID_APPROVAL=166aee12da65b4eac0a85114128ef78961dca60a79712d22510be5a4e23453a0 \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    CODEX_RUN_DIR="benchmarks/results/codex-integration-$(date -u +%Y%m%dT%H%M%SZ)" \
    CODEX_MAX_WALL_CLOCK_SECONDS=86400 \
    bash benchmarks/run-all.sh codex
```

Setting `CODEX_PAID_APPROVAL` to this exact machine-manifest SHA-256 in the launch command is the human authorization and stale-manifest lock; no separate chat authorization is required. The run directory must not already exist. Runtime logs, telemetry, metadata, and checksums stay under the ignored `benchmarks/results/` directory unless the user deliberately exports them for review.

## Status

Runtime smoke and exact coordinate-plan validation are required before paid execution. This manifest rebuild used no model cell or authentication source.
