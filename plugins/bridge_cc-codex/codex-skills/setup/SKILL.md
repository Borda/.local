---
name: setup
description: Diagnose Claude Code availability and the bridge MCP bridge from Codex.
---

# Diagnose the Claude Code Bridge

Use bridge tools only after they appear in the MCP inventory. Before static diagnosis, require `python --version` >= 3.10; when the plugin root is shell-visible, run `python "${PLUGIN_ROOT}/bin/bridge_diagnose.py" --direction claude`. Static diagnosis checks command help and retained health records, not provider authentication, structured-output schema compatibility, or inference success. A live probe uses paid authenticated inference: run it only on explicit user request. Never repair authentication or edit CLI configuration.
