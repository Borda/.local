---
name: cancel
description: Cancel a detached Codex bridge job whose process is still running.
argument-hint: "JOB_ID"
allowed-tools: Bash
---

# Cancel a Bridge Job

Require one job identifier, then run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" cancel --job-id "<job-id>"`. Pass `--workspace` only when explicitly supplied. Report the returned cancellation-request state without claiming termination is already complete, then direct the caller to poll `/bridge:status` or `/bridge:result` for the final state and preserve any incident, transcript, or workspace-delta paths returned by the bridge.
