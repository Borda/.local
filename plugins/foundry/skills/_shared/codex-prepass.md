Before cycle 1 of review loop, run Codex pre-pass if diff meaningful:

```bash
# canonical codex availability check — align develop:review:190 and vitality.md:97 with this pattern.
# Two-source check: (1) plugin installed in installed_plugins.json; (2) not explicitly disabled in ~/.claude/settings.json
CODEX_AVAILABLE=false
if jq -e 'to_entries[] | select(.key | contains("codex")) | .value[].installPath' ~/.claude/plugins/installed_plugins.json 2>/dev/null | grep -q .; then
    if ! jq -e '.enabledPlugins["codex@openai-codex"] == false' ~/.claude/settings.json >/dev/null 2>&1; then
        CODEX_AVAILABLE=true
    fi
fi
[ "$CODEX_AVAILABLE" = "true" ] || echo "codex (openai-codex) not available or disabled — skipping pre-pass"
git diff HEAD --stat
```

**Skip** if:

- `codex@openai-codex` plugin not installed, OR explicitly disabled via `enabledPlugins["codex@openai-codex"] = false` in `~/.claude/settings.json` (i.e. `CODEX_AVAILABLE` resolved to `false` above)
- `git diff HEAD --stat` shows only 1–3 lines changed, or changes are formatting, comments, whitespace, or variable renames only

**Run** when changes include new logic, functions, conditionals, error paths, or restructured code (requires `codex` plugin):

```text
Agent(subagent_type="codex:codex-rescue", prompt="Review the current working-tree changes for bugs, missed edge cases, and inconsistencies. Read-only: do not apply fixes.")
```

**Inline fallback**: bash check printed "not available or disabled" → skip Agent dispatch entirely. No codex spawn. Go to cycle 1 from scratch.

Codex findings = pre-flagged issues entering cycle 1. Codex found nothing or skipped → start cycle 1 from scratch.
