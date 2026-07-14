---
name: sync
description: Agent-led project/home Codex mirror workflow. Use to report manifest-scoped drift and apply approved changes with backups.
---

# Sync

Dry-run-first, agent-led sync between project `.codex` mirror and active home `~/.codex`. No dedicated sync runtime. Agent reads exact manifest, reasons about config differences, applies only approved actions, produces auditable artifacts.

Dry-run default mandatory. Managed docs: `.codex/AGENTS.md`, `.codex/README.md`. Keep `commit_attribution` in manifest-managed root config so project/home commit trailers align. Never delete home-only state; retire only explicitly approved manifest `retired_paths` after backup.

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

Create `.reports/codex/sync/<timestamp>/`: `backup/`, `drift.json`, `drift.md`, `actions.json`, `post-sync.json`. Read `.codex/sync-manifest.json` as JSON. Reject unknown target groups, wildcard paths, missing source files, symlinked roots/parents, paths escaping either `.codex` root.

Manifest authoritative. Do not recursively inventory, compare, or copy either `.codex` tree. Never include `.system`, auth, secrets, projects/trust, plugins, marketplaces, sessions, history, databases, logs, caches, memories, goals, desktop state.

### 02: Agent-led dry run

For every exact file in selected manifest groups:

1. Verify source and destination containment.
2. Record existence and SHA-256 on both sides.
3. Classify `identical`, `changed`, `source-only`, or `destination-only`.
4. Record the proposed direction and whether an overwrite, creation, retirement, or semantic merge would occur.

For `config.toml`, read both; compare only manifest-declared managed root/feature keys, `[agents]` setting keys, registered agent names, skill paths. Treat TOML as structured config; never broad regex replacement. Preserve every destination-only key/table/registration unless user explicitly selects removal.

For `hooks.json`, inspect only `retired_hook_command_substrings`. Preserve unrelated hook events/groups/commands.

Check every `retired_paths` entry; record `retired-present`/`retired-absent`. `check` writes reports only; never changes home files.

### 03: Approval boundary

Before `apply`, require explicit direction, selected target groups, home-write approval, separate approval for each present retired path. Missing-home-`.codex` bootstrap requires separate decision. Stop on ambiguous two-sided edits; show both versions and recommend one.

### 04: Apply approved actions

For every mutation:

1. Copy current destination to matching `$OUT_DIR/backup/` path.
2. Verify backup exists and SHA-256 matches pre-change destination.
3. Copy exact ordinary files or generate narrow semantic edit for `config.toml`/`hooks.json`.
4. Immediately reread destination; record action + post-change hash in `actions.json`.

Delete only manifest-listed retired paths, after backup + explicit retirement approval. Never delete unlisted home-only file.

### 05: Post-check

Repeat exact dry-run comparison after apply. `post-sync.json` passes only when:

- every selected ordinary managed file identical
- managed root keys, agent settings/registrations, features, skills match selected source
- destination-only config/unrelated hooks remain
- every approved retired path absent
- every action has verified backup + post-change hash
- active-home calibration passes when agents, skills, shared helpers, calibration changed

Whole-tree equality neither required nor desired.

### 06: Quality gates and result

Follow `../_shared/helper-cli-contract.md` and authoritative help. For agent-led sync without implementation changes, mark lint, format, types inapplicable with concrete reasons; tests runs calibration; review requires non-empty drift/post-sync evidence + clean diff check. Write candidate with sync metadata, validate as `sync`, promote only validated candidate. Include confidence gaps for semantic merge agent cannot independently validate.

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

Required: manifest-scoped drift matrix, backup hashes, action log, semantic config/hook-preservation review, post-check, active-home calibration for behavior change, `git diff --check`.

## Calibration Hooks

Update behavioral coverage when manifest/agent-led safety contract changes. Calibration validates manifest presence + shared artifact/result contracts; each run's drift, backup, action, post-check, home-calibration evidence proves sync correctness.

## Output Contract

Use `../_shared/quality-gates.md` and `result-template.json`. Report exact changed paths, preserved home-only state, retired paths, backup locations, post-check status, confidence, material limits.
