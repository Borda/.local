#!/usr/bin/env bash
# Resolves the research plugin's _shared/ directory path.
# Prints resolved path to stdout; exits 0 always (caller validates file existence).
# Usage: resolve-shared.sh
path=$(ls -td "${HOME}/.claude/plugins/cache/borda-ai-rig/research"/*/skills/_shared 2>/dev/null | head -1)
[ -n "$path" ] && echo "$path" && exit 0
echo "$(git rev-parse --show-toplevel 2>/dev/null)/plugins/research/skills/_shared"
