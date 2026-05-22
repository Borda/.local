#!/usr/bin/env bash
# Resolves the path to foundry's quality-gates.md rules file.
# Prefers the project-local .claude/rules/ copy; falls back to the foundry plugin cache.
# Prints resolved path to stdout, or empty string + nonzero exit if neither location exists.
# Usage: resolve-quality-gates.sh
local_path="${GIT_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null)}/.claude/rules/quality-gates.md"
if [ -f "$local_path" ]; then
    echo "$local_path"
    exit 0
fi
cached=$(find "${HOME}/.claude/plugins/cache" -name "quality-gates.md" -path "*foundry*/rules/*" 2>/dev/null | head -1)
if [ -n "$cached" ]; then
    echo "$cached"
    exit 0
fi
printf "resolve-quality-gates: quality-gates.md not found in .claude/rules/ or foundry plugin cache\n" >&2
exit 1
