# Codex Rig 0.2

Codex plugin from [Borda/AI-Rig](https://github.com/Borda/AI-Rig). Ships 14 workflow skills and 15 canonical specialist role cards. Apache-2.0 licensed.

Plugin contains no MCP server and no native bundled agent registrations. Skills use built-in agents when suitable, or inject role cards into blank agents as fallback. Optional thin shims expose all 15 roles through Codex user-agent configuration.

## Requirements

- Codex CLI with plugin support
- Python 3.10+
- POSIX local filesystem for agent-shim management; currently acceptance-tested on macOS
- Public GitHub access to pushed repository state

Local, unpushed changes are not installable from GitHub. No official marketplace is assumed.

## Install from GitHub

```bash
codex plugin marketplace add Borda/AI-Rig --ref main
codex plugin add codex-rig@borda-ai-rig
```

Start a fresh Codex session after installation. This loads plugin skills, role cards, and current hook configuration.

## Optional SessionStart diagnostic

`hooks/hooks.json` defines a read-only diagnostic for `startup` and `resume`. It runs the same shim doctor used by the manager; it does not install, update, or remove shims.

Review the hook command before trusting it. Enable it only when wanted. Declining hook trust leaves this diagnostic inactive; skills remain usable.

## Agent shims

Invoke exactly one action:

```text
$codex-rig:agent-shims doctor
$codex-rig:agent-shims status
$codex-rig:agent-shims install
$codex-rig:agent-shims remove
```

- `doctor`: read-only runtime, active-package, manifest, helper, role-card, and filesystem checks.
- `status`: read-only installed-roster, lifecycle-state, target, and recovery summary.
- `install`: plan full 15-role roster creation or relink. No partial-roster mode.
- `remove`: plan removal of intact, authenticated Codex Rig shims. No prefix-based cleanup.

`install` and `remove` print exact target root, operations, and SHA-256 approval digest. Review displayed plan. Type that exact digest only after explicit approval. Wrong or missing digest causes cancellation without authorized writes.

Interrupted recognized transactions use a separate recovery digest. Approved recovery rolls back partial mutation or finalizes durable committed state. Repeat original action after recovery.

Start a fresh Codex session after every successful shim install, update, or removal.

## Update or reinstall

```bash
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
```

Then:

1. Start fresh Codex session.
2. Run `$codex-rig:agent-shims doctor`.
3. Run `$codex-rig:agent-shims install` and approve exact new plan.
4. Start another fresh session.

Plugin reinstall does not update external user-agent files automatically. Existing thin shims still bind recorded package identity; rerunning `install` safely converges intact managed shims to active compatible package.

## Uninstall

Remove shims while plugin manager still exists:

1. Run `$codex-rig:agent-shims remove` and approve exact plan.
2. Run `codex plugin remove codex-rig@borda-ai-rig`.
3. Start fresh Codex session.

Removing plugin first deliberately leaves thin shim files behind. Those shims break because role cards and verifier live in removed plugin cache. They are not auto-deleted.

Recovery: reinstall `codex-rig@borda-ai-rig`, start fresh session, run `doctor`, then run approved `remove` or `install`. Compatible historical state can authenticate guarded migration. Verification failure remains blocked; no force cleanup is provided.

## Lifecycle safety limits

- Foreign or marker-only `codex-rig-*.toml` files are never adopted, overwritten, or removed.
- Modified managed shims, concurrent drift, unsafe links/nodes, ambiguous package selection, or changed runtime binaries block mutation.
- Missing, malformed, oversized, aliased, or identity-inconsistent lifecycle state blocks cleanup. Manual evidence recovery is required.
- Only one exact recognized interrupted transaction can be recovered. Unknown, conflicting, or multiple residue remains blocked.
- Manager owns only authenticated Codex Rig shim roster and state under current user's Codex home. It does not clean unrelated agents.
- Thin shims require active compatible plugin cache. Offline cached use may work; update, reinstall, and active-package validation depend on Codex CLI state.
- Hook trust, plugin install, shim install, and shim removal are separate lifecycle decisions.
