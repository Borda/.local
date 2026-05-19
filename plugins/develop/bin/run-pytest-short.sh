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

# shellcheck disable=SC2086 -- $PYTEST_CMD intentionally word-split (may be "uv run pytest").
$PYTEST_CMD --tb=short "$TARGET" -v 2>&1 | tail -"$TAIL_N"
GATE_EXIT=${PIPESTATUS[0]}
exit "$GATE_EXIT"
