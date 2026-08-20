---
name: result
description: Read a completed detached Codex bridge job's compact result.
argument-hint: JOB_ID
allowed-tools: Bash
---

# Read Bridge Job Result

Require one job identifier. Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" result --job-id "<job-id>"`; pass `--workspace` only when explicitly supplied. Return compact JSON envelope. Preserve workspace-relative `transcript_path` and `incident` references; never inline raw transcript or verbose peer `details`.
