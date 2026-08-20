---
name: setup
description: Diagnose Claude Code and Codex bridge statically by default; live probe requires explicit opt-in.
argument-hint: "[--live] [--direction codex|claude|both]"
allowed-tools: Bash
---

# Diagnose the Bridge

Run `python --version` first; report prerequisite failure if unavailable or older than Python 3.10. Then run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_diagnose.py"` with optional `--direction` and `--workspace` parsed from `$ARGUMENTS`. Default static check verifies CLI availability plus required help-surface commands/flags against shipped baseline, then summarizes bridge health records. It does not verify provider authentication, structured-output schema compatibility, or successful inference.

Pass `--live` only on explicit user request for paid authenticated probe. Before execution, state: one minimal call per selected direction can use network, installed-CLI-managed credentials, and paid inference. Result is point-in-time evidence, not later-task guarantee. Never repair authentication or modify CLI configuration.
