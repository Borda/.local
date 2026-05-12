Before cycle 1 of review loop, run Codex pre-pass if diff meaningful:

```bash
{ [ -n "$CLAUDE_PLUGIN_DATA" ] && echo "$CLAUDE_PLUGIN_DATA" | grep -q 'codex-openai-codex'; } || echo "codex (openai-codex) not available — skipping pre-pass"
git diff HEAD --stat
```

**Skip** if:

- `codex@openai-codex` plugin not installed
- `git diff HEAD --stat` shows only 1–3 lines changed, or changes are formatting, comments, whitespace, or variable renames only

**Run** when changes include new logic, functions, conditionals, error paths, or restructured code:

```text
Agent(subagent_type="codex:codex-rescue", prompt="Review the current working-tree changes for bugs, missed edge cases, and inconsistencies. Read-only: do not apply fixes.")
```

**Inline fallback**: bash check printed "not available" → skip Agent dispatch entirely. No codex spawn. Go to cycle 1 from scratch.

Codex findings = pre-flagged issues entering cycle 1. Codex found nothing or skipped → start cycle 1 from scratch.
