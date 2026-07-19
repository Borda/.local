# Codex Rig 0.2.1

Codex plugin from [Borda/AI-Rig](https://github.com/Borda/AI-Rig). Ships 13 workflow skills, 15 canonical specialist role cards, and one experimental agent-shim manager skill. Apache-2.0 licensed.

Plugin contains no MCP server and no native bundled agent registrations. Its supported parallel route injects an exact role card into a blank runtime agent; inline role execution remains the serial fallback. Persistent named-agent routing is platform-blocked until Codex exposes a verifiable custom-agent selector.

## Requirements

- Codex CLI with plugin support
- Python 3.10+
- POSIX local filesystem for agent-shim management; currently acceptance-tested on macOS
- Public GitHub access to pushed repository state

Local, unpushed changes are not installable from GitHub. No official marketplace is assumed.

## Install from GitHub

```bash
codex plugin marketplace add Borda/AI-Rig --ref codex-rig-v0.2.1
codex plugin add codex-rig@borda-ai-rig
```

Start a fresh Codex session after installation. This loads plugin skills and current hook configuration; workflows and shims consume bundled role cards on demand.

## Optional SessionStart diagnostic

`hooks/hooks.json` defines a read-only diagnostic for `startup` and `resume`. It runs the same shim doctor used by the manager; it does not install, update, or remove shims.

Review the hook command before trusting it. Enable it only when wanted. Declining hook trust leaves this diagnostic inactive; skills remain usable.

## Experimental agent shims

The manager diagnoses prior development installations and safely removes authenticated standalone TOML files. New installation is platform-blocked because current collaboration tooling does not expose a verifiable custom-agent selector. Do not infer selection from a matching task name, child path, or file name. Blank-agent role-card injection can still run independent work in parallel but does not guarantee the card's requested model, reasoning effort, sandbox, approval policy, or nesting profile.

Invoke exactly one action:

```text
$codex-rig:agent-shims doctor
$codex-rig:agent-shims status
$codex-rig:agent-shims install
$codex-rig:agent-shims remove
```

- `doctor`: read-only runtime, active-package, manifest, helper, role-card, and filesystem checks.
- `status`: read-only installed-roster, lifecycle-state, target, and recovery summary.
- `install`: report the platform block without creating or relinking files.
- `remove`: plan removal of intact, authenticated Codex Rig shims. No prefix-based cleanup.

Prior lifecycle files use authenticated names such as `codex-rig-linting-expert.toml`. `remove` prints the exact target root, operations, and SHA-256 approval digest. Review the displayed plan. Type that exact digest only after explicit approval. Wrong or missing digest causes cancellation without authorized writes.

Interrupted recognized transactions use a separate recovery digest. Approved recovery rolls back partial mutation or finalizes durable committed state. Repeat original action after recovery.

Use `remove` to recover prior interrupted transactions; blocked `install` never enters recovery or mutation planning.

Start a fresh Codex session after successful shim removal.

## Update or reinstall

```bash
codex plugin marketplace upgrade borda-ai-rig
codex plugin add codex-rig@borda-ai-rig
```

Then start a fresh Codex session. Plugin reinstall does not update external user-agent files automatically. Use the manager's authenticated `remove` action to clean prior development shims; new installation remains platform-blocked.

## Uninstall

Remove shims while plugin manager still exists:

1. Run `$codex-rig:agent-shims remove` and approve exact plan.
2. Run `codex plugin remove codex-rig@borda-ai-rig`.
3. Start fresh Codex session.

Removing plugin first deliberately leaves thin shim files behind. Those shims break because role cards and verifier live in removed plugin cache. They are not auto-deleted.

Recovery: reinstall `codex-rig@borda-ai-rig`, start fresh session, run `doctor`, then run approved `remove`. Compatible historical state can authenticate guarded cleanup. Verification failure remains blocked; no force cleanup is provided.

## Lifecycle safety limits

- Foreign or marker-only `codex-rig-*.toml` files are never adopted, overwritten, or removed.
- Modified managed shims, concurrent drift, unsafe links/nodes, ambiguous package selection, or changed runtime binaries block mutation.
- Missing, malformed, oversized, aliased, or identity-inconsistent lifecycle state blocks cleanup. Manual evidence recovery is required.
- Only one exact recognized interrupted transaction can be recovered. Unknown, conflicting, or multiple residue remains blocked.
- Manager owns only authenticated Codex Rig shim roster and state under current user's Codex home. It does not clean unrelated agents.
- Thin shims require active compatible plugin cache. Offline cached use may work; update, reinstall, and active-package validation depend on Codex CLI state.
- Hook trust, plugin install, shim install, and shim removal are separate lifecycle decisions.
- A successful shim transaction proves file ownership and link integrity, not runtime profile selection.
