---
name: advise
description: Ask Claude Code a read-only question from Codex through the sandbox-external bridge.
---

# Ask Claude Code for Advice

Call the `bridge_advise` MCP tool with a required `task` and any caller-supplied `model`, `effort`, `timeout_seconds`, `depth`, or `run_id` values. When effort is omitted, classify the complete question and pass the selected level explicitly; never replace a caller-supplied level. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only. The MCP server binds the request to its host-provided launch workspace. Return the compact envelope and preserve its workspace-relative `transcript_path` and `incident` references without copying verbose peer `details`. Use a fresh call for follow-up; do not request session resume.
