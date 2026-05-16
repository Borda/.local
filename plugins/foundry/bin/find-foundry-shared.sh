#!/usr/bin/env bash
# Resolves the foundry plugin's _shared/ directory path.
# Prints resolved path to stdout; exits 0 always (caller validates file existence).
# Usage: find-foundry-shared.sh
path=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry" -maxdepth 3 -type d -name "_shared" 2>/dev/null | sort -Vr | head -1)
[ -n "$path" ] && echo "$path" && exit 0
echo "plugins/foundry/skills/_shared"
