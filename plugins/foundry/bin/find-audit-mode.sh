#!/usr/bin/env bash
# Resolves a foundry:audit mode file path by name.
# Usage: find-audit-mode.sh <mode-name>
# Prints resolved path to stdout; exits 0 always (caller validates file existence).
mode="${1:?mode name required}"
path=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry" -maxdepth 5 -path "*/audit/modes/${mode}.md" 2>/dev/null | sort -Vr | head -1)
[ -f "$path" ] && echo "$path" && exit 0
echo "plugins/foundry/skills/audit/modes/${mode}.md"
