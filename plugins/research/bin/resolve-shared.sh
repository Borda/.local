#!/usr/bin/env bash
# Resolves the research plugin's _shared/ directory path.
# Prints resolved path to stdout; exits 0 always (caller validates file existence).
# Usage: resolve-shared.sh
path=$(ls -td "${HOME}/.claude/plugins/cache/borda-ai-rig/research"/*/skills/_shared 2>/dev/null | head -1)
[ -n "$path" ] && echo "$path" && exit 0
printf "resolve-shared: research plugin not found in cache — using source-tree fallback (local dev only)\n" >&2
echo "plugins/research/skills/_shared"
