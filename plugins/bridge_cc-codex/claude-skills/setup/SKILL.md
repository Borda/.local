---
name: setup
description: Diagnose the local Claude Code and Codex bridge without paid calls by default, with an explicit opt-in live probe.
argument-hint: "[--live] [--direction codex|claude|both]"
allowed-tools: Bash
---

# Diagnose the Bridge

First run `python --version` and report a prerequisite failure if the launcher is unavailable or older than Python 3.10. Then run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_diagnose.py"` with optional `--direction` and `--workspace` values parsed from `$ARGUMENTS`. The default static check verifies CLI availability and required help-surface commands and flags against the shipped baseline, then summarizes bridge health records. It does not verify provider authentication, structured-output schema compatibility, or successful inference.

Pass `--live` only when the user explicitly requests a paid authenticated probe. State before running it that one minimal call per selected direction can use network access, credentials managed by the installed CLI, and paid inference. Treat its result as point-in-time diagnostic evidence, not a guarantee that a later task will succeed. Never attempt to repair authentication or modify CLI configuration.
