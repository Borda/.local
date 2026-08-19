---
name: review
description: Request a read-only adversarial Codex review from Claude Code with explicit model, effort, budget, and compact findings.
argument-hint: "[--model MODEL] [--effort LEVEL] [--timeout-seconds N] REVIEW_INSTRUCTIONS"
allowed-tools: Bash
---

# Ask Codex to Review

Parse `$ARGUMENTS` into optional review instructions and optional `model`, `effort`, `timeout-seconds`, `depth`, `run-id`, and `workspace` values. When effort is omitted, classify the complete review scope and pass the selected level explicitly; never replace a caller-supplied level. Tiers: `low` = narrow mechanical change or settled factual question; `medium` = bounded implementation, diagnosis, or review; `high` = cross-file, adversarial, architectural, or security judgment; `xhigh` = unusually broad and consequential; `max` = explicit caller request only.

Run `python "${CLAUDE_PLUGIN_ROOT}/bin/bridge_call.py" review --task "<instructions>"` with each supplied option passed as its own argument. When the instructions quote text you did not author, write it to a scratch file and pass `--task-file <path>` instead of `--task`; the two are mutually exclusive. The bridge invokes a read-only, ephemeral general Codex execution with an explicit adversarial-review prompt and uses a 300-second soft budget by default. Never resume a review session.

Return the compact JSON envelope and keep the raw transcript at the workspace-relative artifact path reported by the bridge. Do not inline verbose peer `details`.
