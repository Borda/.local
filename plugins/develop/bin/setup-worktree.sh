#!/usr/bin/env bash
# setup-worktree.sh — create a `.temp/develop/<TS>/` run directory and optional health-sentinel.
# Usage: setup-worktree.sh [--sentinel <name>]
# Output: two lines — line 1 = $TS (timestamp), line 2 = run directory path (relative to git root).
# Exit codes: 0 always.
#
# Note: this differs from dev-run-dir.sh (which creates `.developments/<TS>/` for skill checkpoints).
# setup-worktree.sh is the team-mode subagent handoff directory under `.temp/`, per artifact-lifecycle.md.
set -euo pipefail

TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".temp/develop/${TS}"
mkdir -p "$RUN_DIR"

if [ "${1:-}" = "--sentinel" ] && [ -n "${2:-}" ]; then
    # Strip path-unsafe chars to prevent /tmp/ path traversal via argv[2].
    SENTINEL_NAME="${2//[^a-zA-Z0-9_-]/}"
    if [ -n "$SENTINEL_NAME" ]; then
        touch "/tmp/${SENTINEL_NAME}-${TS}"
    fi
fi

echo "$TS"
echo "$RUN_DIR"
