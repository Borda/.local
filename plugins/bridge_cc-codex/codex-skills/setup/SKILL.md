---
name: setup
description: Diagnose Claude Code availability and the bridge MCP bridge from Codex.
---

# Diagnose the Claude Code Bridge

Use the bridge tools only after confirming they appear in the MCP tool inventory. Confirm that `python --version` reports Python 3.10 or newer before static diagnosis. Then run `python "${PLUGIN_ROOT}/bin/bridge_diagnose.py" --direction claude` when the plugin root is available to the shell. Static diagnosis checks command help and retained health records; it does not prove provider authentication, structured-output schema compatibility, or successful inference. A live probe uses paid authenticated inference and must run only after the user explicitly requests it. Never attempt to repair authentication or edit CLI configuration.
