---
name: status
description: Read a detached Codex bridge job's current state.
argument-hint: JOB_ID
allowed-tools: Bash
---

# Read Bridge Job Status

Require one job identifier. Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" status --job-id "<job-id>"`; pass `--workspace` only when explicitly supplied. Return JSON status unchanged.
