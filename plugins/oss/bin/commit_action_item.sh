#!/usr/bin/env bash
# commit_action_item.sh — sentinel-aware commit helper for /oss:resolve Step 8.
#
# Touches the commit-auth sentinel for the current repo+branch (required by
# git-commit.md Gate 1) immediately before `git commit`, so the pre-commit
# hook approves the commit. Cleans the sentinel afterwards regardless of exit
# status. Accepts the fully-formed commit message via --message-file so the
# caller can embed Codex/Claude co-author trailers and per-item attribution.
#
# Usage:
#   commit_action_item.sh --message-file <path> --files <file1> [<file2>...]
#
# Exit codes:
#   0 — commit succeeded
#   1 — bad args, message file missing, or commit failed (pre-commit hook,
#       empty staging area, branch protection, etc.)
set -euo pipefail

MSG_FILE=""
FILES=()

while [ $# -gt 0 ]; do
    case "$1" in
        --message-file) MSG_FILE="$2"; shift 2 ;;
        --files)
            shift
            # Collect everything until next --flag or end of args.
            while [ $# -gt 0 ] && [[ "$1" != --* ]]; do
                FILES+=("$1")
                shift
            done
            ;;
        *) echo "commit_action_item: unknown arg '$1'" >&2; exit 1 ;;
    esac
done

[ -n "$MSG_FILE" ] || { echo "commit_action_item: --message-file required" >&2; exit 1; }
[ -f "$MSG_FILE" ] || { echo "commit_action_item: message file not found: $MSG_FILE" >&2; exit 1; }
[ "${#FILES[@]}" -gt 0 ] || { echo "commit_action_item: --files requires at least one path" >&2; exit 1; }

# Compute Gate 1 sentinel path (matches git-commit.md slug algorithm).
_slug() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//'
}
REPO_SLUG=$(_slug "$(basename "$(git rev-parse --show-toplevel)")")
BRANCH_SLUG=$(_slug "$(git branch --show-current)")
SENTINEL="/tmp/claude-commit-auth-${REPO_SLUG}-${BRANCH_SLUG}"

touch "$SENTINEL"
trap 'rm -f "$SENTINEL"' EXIT INT TERM

# Stage explicit file list — never `git add -A`.
git add -- "${FILES[@]}"

# Empty index after add → nothing to commit (e.g. agent reported changes but
# left tree clean). Skip commit and surface message.
if git diff --cached --quiet; then
    echo "commit_action_item: staging area empty after add — no commit created" >&2
    exit 0
fi

git commit -F "$MSG_FILE"
