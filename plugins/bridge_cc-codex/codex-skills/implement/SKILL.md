---
name: implement
description: Ask Claude Code to implement one bounded write-capable change through the sandbox-external bridge.
---

# Implement with Claude Code

Call the `bridge_implement` MCP tool with a required `task` and any caller-supplied `model`, `effort`, `timeout_seconds`, `depth`, or `run_id` values. Do not replace explicit caller choices with defaults. When effort is omitted, classify the complete task and pass the selected level explicitly. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only. The MCP server binds the request to its host-provided launch workspace and does not accept model-controlled workspace, background, or session fields.

Return the compact public envelope. Keep `verdict`, `findings`, `files_touched`, `remaining`, and `blockers` decision-critical: incomplete work and blockers must be stated there, while verbose supporting evidence belongs only in the workspace-relative transcript referenced by `transcript_path`. Do not inline transcript-only `details` or accept a consequential change without re-reading the reported files and running the relevant project checks. Refuse another cross-host dispatch when the trusted inherited depth is already one.
