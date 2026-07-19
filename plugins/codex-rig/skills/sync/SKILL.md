---
name: sync
description: Dry-run-first Codex Rig installation drift and update workflow. Use to inspect the active plugin cache, refresh its GitHub marketplace, or reinstall the current plugin while coordinating separately managed agent shims.
---

# Sync

Inspect and refresh the public-GitHub Codex Rig plugin through supported Codex CLI operations. Never copy files into
an installed cache, edit Codex configuration by hand, or treat cached package directories as mutable source trees.

Sync never mutates external agent files. Before plugin removal, run `agent-shims remove` while the manager is still
available. After refresh or reinstall, run `agent-shims doctor` to report prior shim residue; new installation and
relinking remain platform-blocked. Report unknown or modified `codex-rig-*.toml` files without removing, adopting, or
repairing them.

## Input Schema

```json
{
  "mode": "check|refresh",
  "marketplace": "borda-ai-rig",
  "plugin": "codex-rig@borda-ai-rig",
  "done_when": "active selection and package identity are recorded; an approved refresh is reinstalled and rechecked"
}
```

Only the frozen marketplace and plugin identifiers are accepted. `check` is the default and is read-only. `refresh`
requires explicit user approval because it fetches marketplace state and changes the local plugin cache.

## Workflow

### 01: Create the result directory

Create `.reports/codex/sync/<timestamp>/` in the consuming project. Record the Codex CLI version, resolved executable,
`CODEX_HOME` presence without secret values, operating system, and requested mode.

### 02: Inspect current state without mutation

Run the authoritative help for the available CLI, then collect:

```bash
codex plugin marketplace list --json
codex plugin list --marketplace borda-ai-rig --json
```

If a documented `--json` option is absent, capture the text form and mark structured comparison unavailable. Never
invent a flag. Record exactly one of: `not-configured`, `not-installed`, `disabled`, `active`, `ambiguous`, or
`cli-unsupported`.

For one active installation, resolve the selected cache path reported or implied by the observed CLI contract. Require
a regular `.codex-plugin/plugin.json` and `package-manifest.json`; reject symlinks, path escape, duplicate selections,
name/version disagreement, unsupported manifest schema, and package-file hash mismatch. Do not select a cache by
lexical or modification-time "latest" rules.

### 03: Report external-agent residue without touching it

Read-only scan the user agent directory for exact `codex-rig-*.toml` names. Record names and hashes, never file bodies.
Classify every match `unmanaged-or-unknown` unless a compatible lifecycle manager and its ownership state are
available and verified. Plugin-only sync never deletes or overwrites a match.

### 04: Stop after dry run unless refresh was explicitly approved

Show the installed state, marketplace source, current version, package verification result, possible external-agent
residue, proposed commands, network/cache effects, and rollback limit. Ask for approval before `refresh`. A check-only
request, missing approval, ambiguous source, foreign marketplace, or unverified active package stops without mutation.

### 05: Refresh through the Codex CLI

After approval, use only commands confirmed by authoritative help:

```bash
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
```

Do not use `git clone`, edit marketplace configuration, delete old cache directories, or force an update. A failed
refresh must preserve and report the prior installation state; never claim rollback unless the CLI evidence proves it.

### 06: Recheck exact active identity

Repeat the read-only inspection and package validation. Pass only when exactly one enabled selection is reported and
its manifest plus all recorded payload hashes agree. Record old/new version and package-manifest hashes. Same version
with different package bytes is a cache-identity failure.

### 07: Write the validated artifact

Follow `../../shared/helper-cli-contract.md`. Write `SYNC_METADATA`, gate logs, `state-before.json`,
`proposed-actions.json`, and, for refresh, `state-after.json`. Promote only the candidate accepted by the shared
validator.

## Fail-Fast Rules

1. Unknown marketplace/plugin identifier => fail before command execution.
2. Refresh without explicit approval => stop without mutation.
3. Missing, ambiguous, disabled, escaped, symlinked, or hash-invalid active package => fail.
4. Manual cache/config/source-tree mutation => fail.
5. External agent mutation or cleanup claim => fail.
6. Same version with different package bytes => fail.
7. Refresh command failure or post-refresh identity mismatch => fail; report prior state without invented rollback.
8. Result artifact missing => fail.

## Quality Gates

Required: CLI-help evidence, before-state identity, complete package hash validation, external-agent residue summary,
clean diff review, and validated result JSON. Refresh also requires explicit approval evidence, exact command/exit logs,
and after-state identity.

## Calibration Hooks

Behavioral coverage includes dry-run default, missing approval, unavailable JSON output, duplicate active selections,
same-version byte drift, source-unavailable cache validation, failed marketplace refresh, stale thin links, and
preservation of unknown external agent files.

## Output Contract

Use `../../shared/quality-gates.md` and `result-template.json`. Report state, version/package hash, commands run,
possible external-agent residue, verified changes, unresolved lifecycle limits, artifact path, and confidence.
