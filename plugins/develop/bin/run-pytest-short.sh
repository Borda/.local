#!/usr/bin/env bash
# run-pytest-short.sh — run pytest with --tb=short on a target, tail the output, expose PIPESTATUS as exit code.
# Usage: run-pytest-short.sh <pytest_cmd> <target> [tail_lines]
# Example: run-pytest-short.sh "uv run pytest" tests/ 20
# Output: tailed pytest output on stdout.
# Exit codes: pytest's exit code (0 = pass, 1-4 = failures, 5 = no tests collected).
set -euo pipefail

PYTEST_CMD="${1:-pytest}"
TARGET="${2:-.}"
TAIL_N="${3:-20}"

# Validate PYTEST_CMD against allowlist before word-split exec.
case "$PYTEST_CMD" in
    pytest|"uv run pytest"|"python -m pytest") ;;
    *) echo "run-pytest-short: rejected unsafe PYTEST_CMD: $PYTEST_CMD" >&2; exit 2 ;;
esac
# Validate TAIL_N is a positive integer; fall back to default on bad input.
[[ "$TAIL_N" =~ ^[0-9]+$ ]] || TAIL_N=20
# SECURITY: PYTEST_CMD validated against allowlist above
# shellcheck disable=SC2086 -- allowlisted PYTEST_CMD intentionally word-split.
$PYTEST_CMD --tb=short "$TARGET" -v 2>&1 | tail -"$TAIL_N"
GATE_EXIT=${PIPESTATUS[0]}
exit "$GATE_EXIT"
