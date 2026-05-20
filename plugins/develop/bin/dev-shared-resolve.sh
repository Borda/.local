#!/usr/bin/env bash
# Resolves the develop plugin's _shared/ directory path.
# With --foundry: also resolves foundry plugin's _shared/ directory.
# Usage: dev-shared-resolve.sh [--foundry]
# Output (no --foundry): one line — resolved _DEV_SHARED path
# Output (--foundry): two lines — line 1 = _DEV_SHARED, line 2 = _FOUNDRY_SHARED
# Exits 0 always; caller validates file existence.
dev_path=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/develop" -maxdepth 3 -type d -name "_shared" 2>/dev/null | sort -Vr | head -1)
[ -z "$dev_path" ] && dev_path="plugins/develop/skills/_shared"
echo "$dev_path"
if [ "${1:-}" = "--foundry" ]; then
    foundry_path=$(find "${HOME}/.claude/plugins/cache/borda-ai-rig/foundry" -maxdepth 3 -type d -name "_shared" 2>/dev/null | sort -Vr | head -1)
    [ -z "$foundry_path" ] && { printf "dev-shared-resolve: foundry plugin not in cache — using source-tree fallback\n" >&2; foundry_path="plugins/foundry/skills/_shared"; }
    echo "$foundry_path"
fi
