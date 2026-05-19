#!/usr/bin/env bash
# stage_item_changes.sh <item_id>
# Pop any pre-item stash for item_id, then stage all changed tracked and
# source-extension untracked files.  Extracted from oss:resolve
# action-item-dispatch Phase 2 staging block (AI7).
set -euo pipefail

ITEM_ID="${1:?item_id required}"

if git stash list --quiet | grep -q "resolve-pre-item-${ITEM_ID}"; then
    timeout 3 git stash pop || {
        echo "⚠ stash pop conflict — resolve conflicts in $(git stash list | head -1) before item #${ITEM_ID}"
        exit 1
    }
fi

CHANGED=$(timeout 3 git diff HEAD --name-only 2>/dev/null) || true
[ -n "$CHANGED" ] && echo "$CHANGED" | timeout 3 xargs git add --

UNTRACKED=$(git ls-files --others --exclude-standard \
    | grep -E '\.(py|md|yaml|yml|toml|cfg|ini|json|txt|sh|js|ts|go|rs|rb|java|c|cpp|h|hpp)$' \
    2>/dev/null) || true
[ -n "$UNTRACKED" ] && echo "$UNTRACKED" | timeout 3 xargs git add -- 2>/dev/null || true
