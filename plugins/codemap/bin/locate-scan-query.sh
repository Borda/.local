#!/usr/bin/env bash
# locate-scan-query.sh — resolve the scan-query executable via a three-tier fallback.
# Usage: locate-scan-query.sh
# Inputs (env): CLAUDE_PLUGIN_ROOT — optional plugin install root used by tier 2.
# Tiers (first hit wins):
#   1. command -v scan-query                              — installed on PATH
#   2. ${CLAUDE_PLUGIN_ROOT}/bin/scan-query                — current plugin install root
#   3. ~/.claude/plugins/cache/*/codemap/*/bin/scan-query  — newest cached install (sort -V | tail -1)
# Output: resolved absolute path on stdout; nothing else.
# Exit codes: 0 = found and executable, 1 = not found (error message on stderr).
set -euo pipefail

SQ=""

if command -v scan-query >/dev/null 2>&1; then
    SQ=$(command -v scan-query)
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/bin/scan-query" ]; then
    SQ="${CLAUDE_PLUGIN_ROOT}/bin/scan-query"
else
    SQ=$(ls "$HOME/.claude/plugins/cache"/*/codemap/*/bin/scan-query 2>/dev/null | sort -V | tail -1)
fi

if [ -n "$SQ" ] && [ -x "$SQ" ]; then
    printf "%s\n" "$SQ"
    exit 0
fi

printf "locate-scan-query: scan-query binary not found (PATH, CLAUDE_PLUGIN_ROOT, cache glob all empty)\n" >&2
exit 1
