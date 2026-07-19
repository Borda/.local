---
name: agent-shims
description: Diagnose, inspect, install, update, or remove the complete Codex Rig user-agent shim roster. Use when the user invokes agent-shims with exactly one action—doctor, status, install, or remove—or asks to manage Codex Rig role agents safely.
---

# Agent Shims

Accept exactly one action: `doctor`, `status`, `install`, or `remove`. Reject missing, extra, or unknown arguments without writes.

Locate `../../scripts/manage_role_agents.py` relative to this installed `SKILL.md`. Run it with the current Python 3.10+ interpreter and the selected action. Do not copy the manager, resolve it through a source checkout, or edit generated agent files directly.

- `doctor`: run the read-only live prerequisite check and report its JSON result.
- `status`: run the read-only health and installed-roster summary and report its JSON result.
- `install`: run the whole-roster plan. Show the exact target root, operations, and approval digest. At the manager prompt, enter the digest only after the user explicitly approves that exact displayed plan. Never approve on the user's behalf.
- `remove`: use the same exact-digest flow to remove every intact managed shim. Never delete by filename prefix or marker alone.

Preserve the manager's exit contract: `0` success/converged, `2` usage, `3` cancelled, `4` drift/conflict, `5` prerequisite blocked, `6` untrusted state, `7` internal/recovery failure. Do not retry a mutating action after codes `4`, `6`, or `7`; report the evidence and keep files untouched.

After successful install, update, or removal, tell the user to start a fresh Codex session. Thin shims intentionally depend on the installed plugin cache; uninstalling the plugin makes remaining shims unavailable until safely removed or reinstalled.
