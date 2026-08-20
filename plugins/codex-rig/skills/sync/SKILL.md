---
name: sync
description: Dry-run active plugin cache drift; refresh/reinstall only with approval; keep shims separate.
---

# Sync

Inspect and refresh the public-GitHub Codex Rig plugin through supported Codex CLI operations. Never copy files into an installed cache, edit Codex configuration by hand, or treat cached package directories as mutable source trees.

Sync never mutates external agent files. Before plugin removal, run `agent-shims remove` while the manager is still available. After refresh or reinstall, run `agent-shims doctor` to report prior shim residue; new installation and relinking remain platform-blocked. Report unknown or modified `codex-rig-*.toml` files without removing, adopting, or repairing them.

## Input Schema

```json
{
  "mode": "check|refresh",
  "marketplace": "borda-ai-rig",
  "plugin": "codex-rig@borda-ai-rig",
  "ref": "optional Git ref; omitted follows the remote default branch",
  "done_when": "active selection and package identity are recorded; an approved refresh is reinstalled and rechecked"
}
```

Only the frozen marketplace and plugin identifiers are accepted. `check` is the default and is read-only. `refresh` requires explicit user approval because it fetches marketplace state and changes the local plugin cache.

## Workflow

### 01: Create the result directory

Create `.reports/codex/sync/<timestamp>/` in the consuming project. Record the Codex CLI version, resolved executable, `CODEX_HOME` presence without secret values, operating system, and requested mode.

### 02: Inspect current state without mutation

Run the authoritative help for the available CLI, then collect:

```bash
codex plugin marketplace list --json
codex plugin list --marketplace borda-ai-rig --json
```

If a documented `--json` option is absent, capture the text form and mark structured comparison unavailable. Never invent a flag. Record exactly one of: `not-configured`, `not-installed`, `disabled`, `active`, `ambiguous`, or `cli-unsupported`.

For one active installation, resolve the selected cache path reported or implied by the observed CLI contract. Require a regular `.codex-plugin/plugin.json` and `package-manifest.json`; reject symlinks, path escape, duplicate selections, name/version disagreement, unsupported manifest schema, and package-file hash mismatch. Do not select a cache by lexical or modification-time "latest" rules.

### 03: Report external-agent residue without touching it

Read-only scan the user agent directory for exact `codex-rig-*.toml` names. Record names and hashes, never file bodies. Classify every match `unmanaged-or-unknown` unless a compatible lifecycle manager and its ownership state are available and verified. Plugin-only sync never deletes or overwrites a match.

### 04: Stop after dry run unless refresh was explicitly approved

Show the installed state, marketplace source, configured ref or default-branch tracking, resolved revision when the marketplace checkout exposes it, current version, package verification result, possible external-agent residue, proposed commands, network/cache effects, and rollback limit. Ask for approval before `refresh`. A check-only request, missing approval, ambiguous source, foreign marketplace, or unverified active package stops without mutation.

### 05: Refresh through the Codex CLI

After approval, use only commands confirmed by authoritative help:

Apply the networked CLI approval contract in `../../shared/native-skill-contract.md` to each Git marketplace add/upgrade command or to the complete `sync_codex.py` wrapper that owns one: execute that complete owning command with external network approval from its first attempt. Before requesting it, state: `Action and purpose`: refresh the approved marketplace and reconcile the selected Codex Rig plugin; `External capability`: marketplace download and lifecycle refresh; `Credential behavior`: use configured Codex marketplace access without reading or changing credentials; `Filesystem and worktree effects`: change the local plugin cache and Codex-home plugin state, never the source worktree; `Retry policy and safe denial outcome`: do not repeat an equivalent lifecycle request in this turn, and leave the existing checked state without mutation. In a Codex exec call, set `sandbox_permissions="require_escalated"` with a narrow approved-marketplace lifecycle justification; never enable persistent workspace network access or request a broad `codex` prefix. This runtime permission is separate from the explicit lifecycle approval above and never expands the allowed marketplace, plugin, ref, or mutation scope. Denial aborts the active tool call and may end the assistant turn. Do not issue an equivalent approval request in the current turn. Do not switch to a broader command. Ask the user to send a new message to resume. Local marketplace/plugin listing remains sandboxed because it reads configured state without intentionally refreshing remote data. `codex plugin add` installs from the configured marketplace snapshot and receives no separate network escalation; when the complete sync wrapper runs it, the wrapper is already approved because it also owns marketplace add/upgrade.

```bash
codex plugin marketplace add Borda/AI-Rig
# Optional reproducible release pin:
# codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.3.0
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
```

Omitting `--ref` follows the remote default branch. An explicit ref pins it. Do not silently change an existing marketplace between pinned and unpinned modes: report the mismatch and require legacy shim cleanup before deliberate marketplace removal and re-addition. Do not use `git clone`, edit marketplace configuration, delete old cache directories, or force an update. A failed refresh must preserve and report the prior installation state; never claim rollback unless the CLI evidence proves it.

### 06: Recheck exact active identity

Repeat the read-only inspection and package validation. Pass only when exactly one enabled selection is reported and its manifest plus all recorded payload hashes agree. Record requested/configured ref, resolved revision when available, old/new version, and package-manifest hashes. Same version with different package bytes is a cache-identity failure.

### 07: Write the validated artifact

Follow `../../shared/helper-cli-contract.md`. Write `SYNC_METADATA`, gate logs, `state-before.json`, `proposed-actions.json`, and, for refresh, `state-after.json`. Promote only the candidate accepted by the shared validator.

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

Required: CLI-help evidence, before-state identity, complete package hash validation, external-agent residue summary, clean diff review, and validated result JSON. Refresh also requires explicit approval evidence, exact command/exit logs, and after-state identity.

## Calibration Hooks

Behavioral coverage includes dry-run default, missing approval, unavailable JSON output, duplicate active selections, same-version byte drift, source-unavailable cache validation, failed marketplace refresh, stale thin links, and preservation of unknown external agent files.

Networked CLI owning-command approval is required calibration coverage for Git marketplace add/upgrade behavior.

## Output Contract

Use `../../shared/quality-gates.md` and `result-template.json`. Report state, version/package hash, commands run, possible external-agent residue, verified changes, unresolved lifecycle limits, artifact path, and confidence.
