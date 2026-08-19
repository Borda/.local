---
name: status
description: Read the current state of a detached Codex bridge job.
argument-hint: "JOB_ID"
allowed-tools: Bash
---

# Read Bridge Job Status

Require one job identifier, then run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" status --job-id "<job-id>"`. Pass `--workspace` only when explicitly supplied. Return the JSON status unchanged.
