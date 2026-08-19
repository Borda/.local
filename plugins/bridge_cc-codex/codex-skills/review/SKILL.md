---
name: review
description: Request a read-only adversarial review from Claude Code through the sandbox-external bridge.
---

# Ask Claude Code to Review

Call the `bridge_review` MCP tool with a required `task` and any caller-supplied `model`, `effort`, `timeout_seconds`, `depth`, or `run_id` values. When effort is omitted, classify the complete review scope and pass the selected level explicitly; never replace a caller-supplied level. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only. The MCP server binds the request to its host-provided launch workspace. Return only the compact envelope and preserve the reported workspace-relative transcript and incident references for detailed inspection; do not inline verbose peer `details`.
