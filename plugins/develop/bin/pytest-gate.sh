#!/usr/bin/env bash
# pytest-gate.sh — run pytest with --tb=short on a target (no tail), surface exit code directly.
# Usage: pytest-gate.sh <pytest_cmd> <target>
# Example: pytest-gate.sh "uv run pytest" tests/test_foo.py::test_bar
# Output: full pytest output on stdout.
# Exit codes: pytest's exit code (0 = pass, 1-4 = failures, 5 = no tests collected).
#
# This is the no-tail inner-loop variant used in TDD cycles where the caller wants to inspect full
# output. Use run-pytest-short.sh when the caller wants a tail-truncated summary.
set -euo pipefail

PYTEST_CMD="${1:-pytest}"
TARGET="${2:-.}"

# shellcheck disable=SC2086 -- $PYTEST_CMD intentionally word-split (may be "uv run pytest").
exec $PYTEST_CMD --tb=short "$TARGET" -v
