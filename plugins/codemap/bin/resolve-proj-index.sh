#!/usr/bin/env bash
# resolve-proj-index.sh — compute project name and codemap index path from current git root.
# Usage: resolve-proj-index.sh [--check]
# Output (no --check): two lines — line 1 = PROJ, line 2 = INDEX path.
# Output (--check): same two lines plus a third '✓ index: exists' / '✗ index: not found' status line.
# Exit codes: 0 = success (index resolved; existence reported only when --check requested).
#             1 = --check requested AND index file missing (matches the inline guard's original semantics).
set -euo pipefail

GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
PROJ=${GIT_ROOT:+$(basename "$GIT_ROOT")}
PROJ=${PROJ:-$(basename "$PWD")}
INDEX="${GIT_ROOT:-.}/.cache/scan/${PROJ}.json"

echo "$PROJ"
echo "$INDEX"

[ "${1:-}" != "--check" ] && exit 0
[ -f "$INDEX" ] && { echo "✓ index: exists"; exit 0; }
echo "✗ index: not found"
exit 1
