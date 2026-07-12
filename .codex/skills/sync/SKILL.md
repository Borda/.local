---
name: sync
description: Agent-led project/home Codex mirror workflow. Use to report manifest-scoped drift and apply approved changes with backups.
---

# Sync

Run a dry-run-first, agent-led sync between the project `.codex` mirror and the active home `~/.codex`. No dedicated sync runtime is required. The agent reads the exact manifest, reasons about config differences, applies only approved actions, and produces auditable artifacts.

The dry-run default is mandatory. Managed documentation includes `.codex/AGENTS.md` and `.codex/README.md`. Keep `commit_attribution` in the manifest-managed root config so project and home commit trailers remain aligned. Agents never delete home-only state; only explicitly approved manifest `retired_paths` may be retired after backup.

## Input Schema

```json
{
  "mode": "check|apply",
  "source": "project|home",
  "targets": [
    "skills",
    "agents",
    "config",
    "calibration",
    "docs",
    "shared"
  ],
  "done_when": "manifest-scoped drift is recorded and every approved action is backed up and rechecked"
}
```

## Workflow

### 01: Scope and artifact directory

Create `.reports/codex/sync/<timestamp>/` with `backup/`, `drift.json`, `drift.md`, `actions.json`, and `post-sync.json`. Read `.codex/sync-manifest.json` as JSON. Reject unknown target groups, wildcard paths, missing source files, symlinked roots/parents, and paths escaping either `.codex` root.

The manifest is authoritative. Do not recursively inventory, compare, or copy either `.codex` tree. Never include `.system`, auth, secrets, projects/trust, plugins, marketplaces, sessions, history, databases, logs, caches, memories, goals, or desktop state.

### 02: Agent-led dry run

For every exact file in the selected manifest groups:

1. Verify source and destination containment.
2. Record existence and SHA-256 on both sides.
3. Classify `identical`, `changed`, `source-only`, or `destination-only`.
4. Record the proposed direction and whether an overwrite, creation, retirement, or semantic merge would occur.

For `config.toml`, read both files and compare only the managed root keys, feature keys, `[agents]` setting keys, registered agent names, and skill paths declared in the manifest. Treat TOML as structured configuration in reasoning; never use broad regex replacement. Preserve every destination-only key/table/registration unless the user explicitly selects it for removal.

For `hooks.json`, inspect only `retired_hook_command_substrings`. Preserve unrelated hook events, groups, and commands.

Check every `retired_paths` entry and record `retired-present` or `retired-absent`. Check mode writes reports only and never changes home files.

### 03: Approval boundary

Before `apply`, require explicit direction, selected target groups, home-write approval, and separate approval for every present retired path. Bootstrap of a missing home `.codex` requires a separate decision. Stop on ambiguous two-sided edits; show both versions and recommend one.

### 04: Apply approved actions

For every mutation:

1. Copy the current destination to the matching path under `$OUT_DIR/backup/`.
2. Verify the backup exists and its SHA-256 matches the pre-change destination.
3. Copy exact ordinary files or generate a narrow semantic edit for `config.toml`/`hooks.json`.
4. Re-read the destination immediately and record the action plus post-change hash in `actions.json`.

Only manifest-listed retired paths may be deleted, and only after backup plus explicit retirement approval. Never delete an unlisted home-only file.

### 05: Post-check

Repeat the exact dry-run comparison after apply. `post-sync.json` passes only when:

- every selected ordinary managed file is identical
- managed root keys, agent settings/registrations, features, and skills match the selected source
- destination-only config and unrelated hooks remain present
- every approved retired path is absent
- every action has a verified backup and post-change hash
- active-home calibration passes when agents, skills, shared helpers, or calibration changed

Whole-tree equality is neither required nor desired.

### 06: Quality gates and result

Follow `../_shared/helper-cli-contract.md` and authoritative help. For an agent-led sync without implementation changes, mark lint, format, and types not applicable with concrete reasons; tests run calibration, and review requires non-empty drift/post-sync evidence plus a clean diff check. Write the candidate with sync metadata, validate as skill `sync`, and promote only the validated candidate. Include confidence gaps for any semantic merge the agent could not independently validate.

## Fail-Fast Rules

1. Missing/invalid manifest or source file => stop before mutation.
2. Apply without explicit direction, targets, and approval => stop.
3. Symlink/path escape or suspected credential material => stop.
4. Missing or mismatched backup => stop.
5. Ambiguous two-sided change => stop and ask.
6. Unlisted deletion or broad recursive copy/diff => stop.
7. Config merge that would drop destination-only state => stop.
8. Retired path present without explicit retirement approval => stop.
9. Post-check or active-home calibration failure => fail the result.

## Quality Gates

Required: manifest-scoped drift matrix, backup hashes, action log, semantic config/hook preservation review, post-check, active-home calibration when behavior changed, and `git diff --check`.

## Calibration Hooks

Update behavioral coverage when the manifest or agent-led safety contract changes. Calibration validates manifest presence and the shared artifact/result contracts; sync correctness is proven by each run's drift, backup, action, post-check, and home-calibration evidence.

## Output Contract

Use `../_shared/quality-gates.md` and `result-template.json`. Report exact changed paths, preserved home-only state, retired paths, backup locations, post-check status, confidence, and material limits.
