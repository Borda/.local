---
name: result
description: Read the compact result of a completed detached Codex bridge job.
argument-hint: "JOB_ID"
allowed-tools: Bash
---

# Read Bridge Job Result

Require one job identifier, then run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" result --job-id "<job-id>"`. Pass `--workspace` only when explicitly supplied. Return the compact JSON envelope and preserve its workspace-relative `transcript_path` and `incident` references; do not inline raw transcript or verbose peer `details`.
