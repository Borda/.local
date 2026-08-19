---
name: implement
description: Ask Codex to implement one bounded write-capable change from Claude Code with compact results.
argument-hint: "[--model MODEL] [--effort LEVEL] [--timeout-seconds N] [--background] [--session-id UUID] TASK"
allowed-tools: Bash
---

# Implement with Codex

Implement one bounded change in the selected workspace. Parse `$ARGUMENTS` into a required task and optional `model`, `effort`, `timeout-seconds`, `background`, `session-id`, `depth`, `run-id`, and `workspace` values. Reject an empty task. Use a session ID only for a follow-up to the same task in the same workspace. When effort is omitted, classify the complete task and pass the selected level explicitly; never replace a caller-supplied level. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only.

Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" implement --task "<task>"` with each supplied option passed as its own argument. Do not interpolate shell syntax from the task into the command. The default soft budget is 600 seconds; the bridge enforces the documented hard cutoff. The implementation call is write-capable under the peer host's normal permission mode and is never automatically retried after timeout.

Return the compact public envelope. Keep `verdict`, `findings`, `files_touched`, `remaining`, and `blockers` decision-critical: incomplete work and blockers must be stated there, while verbose supporting evidence belongs only in the workspace-relative transcript referenced by `transcript_path`. Do not copy transcript-only `details` into the conversation. If detached, return the job identifier and tell the caller to use `/bridge:status`, `/bridge:result`, or `/bridge:cancel`. While a detached implementation is running, do not edit paths named by its task. After completion, re-read every path in `files_touched` before making further edits.
