#!/usr/bin/env bash
# Resolves a plugin's _shared/ (or named subdir) from the installed cache with source-tree fallback.
# Prints resolved path to stdout; exits 0 always (caller validates file/dir existence).
# Usage: resolve-shared-path.sh <plugin-name> <subdir>
#   plugin-name: e.g. oss, foundry
#   subdir:      e.g. skills/_shared
PLUGIN="${1:?Usage: resolve-shared-path.sh <plugin-name> <subdir>}"
SUBDIR="${2:?Usage: resolve-shared-path.sh <plugin-name> <subdir>}"
path=$(ls -d "${HOME}/.claude/plugins/cache/borda-ai-rig/${PLUGIN}/"*/"${SUBDIR}" 2>/dev/null | sort -V | tail -1)
[ -n "$path" ] && echo "$path" && exit 0
echo "plugins/${PLUGIN}/${SUBDIR}"
