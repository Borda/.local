# `codex-integration-v1`

**Manifest SHA-256**: `0809a7f087eb3c2343048f848615690b704a79323fc919f3a4b5ec8b897a72be`

## Purpose

Codex-only A/B/C experiment over the immutable provider-parity task and scoring identities.

## Arms

- `A_plain`: no Codemap package or query access.
- `B_direct_required`: one dedicated successful `"$CODEMAP_BIN" query --compact <subcommand> [arguments]` command item.
- `C_skill_required`: one dedicated exact `cat "$CODEMAP_SKILL_FILE"` item, then one dedicated canonical compact query item.
- B/C may use additional reads and shell commands as separate items; those actions are ignored for attribution.

## Estimands

- `C_skill_required-A_plain`: product effect.
- `B_direct_required-A_plain`: direct CLI effect.
- `C_skill_required-B_direct_required`: integration effect.

## Execution controls

- The 600-second coordinate budget is shared by the initial attempt and any eligible zero-token transport retries.
- Paid execution requires a positive, human-approved `--max-wall-clock-seconds` value recorded in every result row.
- Arm order uses deterministic six-permutation counterbalancing by frozen structural task ordinal; across the 55-task single-repetition execution suite, every arm occupies every ordinal 18 or 19 times.
- Console and primary efficiency reports use gross provider input tokens only. Cached and fresh input counts are retained as raw telemetry diagnostics.
- The Codex CLI exposes no supported per-cell provider prompt-cache reset or disable control. Deterministic arm-order counterbalancing mitigates order exposure without claiming cache elimination.

## Credential safety

- Use an immutable, user-owned `0600` auth source. Do not run a concurrent Codex session with it; use an independently authenticated benchmark credential instead.
- The runner keeps private run state and atomically propagates valid refreshes between cells. A private sequential refresh can invalidate an unchanged source, so reauthenticate after the run if needed.
- Known refresh-token authentication failures stop immediately; three matching unknown zero-token pre-response failures preserve partial artifacts and stop scheduling.

## Locked candidates

- `codemap-py` `0.28.3`.
  Package manifest SHA-256: `6ffd24dbeff5e45771e11d61e0e6f527deda8fd3cbecbbdfd338222318db3e38`.
- `codex-rig` `0.4.1`.
- Codex CLI: `{'available': True, 'path': '/opt/homebrew/bin/codex', 'version': 'codex-cli 0.146.0'}`.
- Source manifest: `benchmarks/manifests/provider-parity-methodology.json` SHA-256 `9738d21d607bbe16551a61e49a9ae82b586b7fc7fd29914f589486f260471054`.

## Study scope

- Execution tasks: `55`.
- Independently scored headline tasks: `45`.
- Diagnostic tasks: `10`.
- Repetitions: `1`.
- Total cells: `165` (`55 tasks × 1 repetition × 3 arms`).
- Model-cell failures are recorded and do not stop the study after admission; integrity, interruption, and complete-run ceiling failures preserve a partial artifact and stop execution.

## Selected-task scope

- Use `--tasks=DI,GR` for family selection, `--tasks=DI-01,GR-03` for exact IDs, or `--tasks=DI,GR-03` for a mixed selection.
- Exact task IDs are resolved before family tokens; family tokens select all matching frozen IDs.
- Empty or unknown selectors fail closed; duplicate tokens and overlapping expansions are evaluated once.
- Resolved IDs always follow frozen manifest order, independent of selector order.
- Omit --tasks for the full confirmatory scope; providing --tasks requires separate targeted approval and cannot authorize or replace the full scope.
- Selected-task runs use `3` repetitions × `3` arms and `600` seconds per coordinate.
- The complete-run ceiling is derived at runtime as `resolved tasks × repetitions × arms × coordinate seconds`.
- Selected-task runs are explicitly nonpoolable and ineligible for confirmatory or product acceptance.
- The runtime scope digest covers the active manifest SHA-256, resolved ordered IDs, and execution controls; it is derived at runtime and is not stored in this manifest.

## Paid selected-task command

Replace `DI,GR` with an approved family, exact-ID, or mixed selector. The same selector must be used for dry-run and paid execution.

Run the matching no-model dry-run first and copy its `selection scope` SHA-256 (or the `scope_sha256` field from the resolver output) into the placeholder below. This targeted scope digest is distinct from the machine-manifest SHA-256.

```bash
bash benchmarks/run-all.sh codex --tasks=DI,GR --dry-run
```

Alternatively, resolve the selector directly and copy its `scope_sha256` value:

```bash
python3 benchmarks/run-codex-structural.py --manifest-path benchmarks/manifests/codex-integration.json --resolve-tasks DI,GR
```

```bash
CODEX_PAID_APPROVAL=<resolved-scope-sha256> \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    CODEX_RUN_DIR="benchmarks/results/codex-integration-selected-$(date -u +%Y%m%dT%H%M%SZ)" \
    CODEX_MAX_WALL_CLOCK_SECONDS=<derived-ceiling> \
    bash benchmarks/run-all.sh codex --tasks=DI,GR
```

## Confirmatory execution

Run the exact no-model Codex smoke and 165-coordinate plan first:

```bash
bash benchmarks/run-all.sh codex --dry-run
```

After reviewing this manifest, launch the separate paid confirmatory study with the manifest-bound command:

```bash
CODEX_PAID_APPROVAL=0809a7f087eb3c2343048f848615690b704a79323fc919f3a4b5ec8b897a72be \
    CODEX_AUTH_SOURCE="$HOME/.codex/auth.json" \
    CODEX_RUN_DIR="benchmarks/results/codex-integration-$(date -u +%Y%m%dT%H%M%SZ)" \
    CODEX_MAX_WALL_CLOCK_SECONDS=86400 \
    bash benchmarks/run-all.sh codex
```

Setting `CODEX_PAID_APPROVAL` to this exact machine-manifest SHA-256 in the launch command is the human authorization and stale-manifest lock; no separate chat authorization is required. The run directory must not already exist. Runtime logs, telemetry, metadata, and checksums stay under the ignored `benchmarks/results/` directory unless the user deliberately exports them for review.

## Status

Runtime smoke and exact coordinate-plan validation are required before paid execution. This manifest rebuild used no model cell or authentication source.
