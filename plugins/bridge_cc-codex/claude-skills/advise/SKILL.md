---
name: advise
description: Ask Codex a read-only question from Claude Code with explicit model, effort, budget, and compact results.
argument-hint: "[--model MODEL] [--effort LEVEL] [--timeout-seconds N] QUESTION"
allowed-tools: Bash
---

# Ask Codex for Advice

Parse `$ARGUMENTS` into a required question and optional `model`, `effort`, `timeout-seconds`, `depth`, `run-id`, and `workspace` values. Reject an empty question. When effort is omitted, classify the complete question and pass the selected level explicitly; never replace a caller-supplied level. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only.

Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" advise --task "<question>"` with each supplied option passed as its own argument. The bridge uses a read-only, ephemeral Codex run and a 120-second soft budget by default. Never resume an advice session; send a fresh request containing any prior `remaining` items when follow-up is needed.

Return the compact JSON envelope and preserve its workspace-relative `transcript_path` and `incident` references without copying raw transcript or verbose peer `details` into the conversation.
