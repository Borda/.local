---
name: cancel
description: Request cancellation of a running detached Codex bridge job.
argument-hint: "JOB_ID"
allowed-tools: Bash
---

# Cancel a Bridge Job

Require one job identifier. Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" cancel --job-id "<job-id>"`; pass `--workspace` only when explicitly supplied. Report returned cancellation-request state; do not claim termination complete. Direct caller to poll `/bridge:status` or `/bridge:result` for final state. Preserve returned incident, transcript, or workspace-delta paths.
