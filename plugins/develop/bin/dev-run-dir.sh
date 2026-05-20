#!/usr/bin/env bash
# Computes an ISO timestamp, creates .developments/<timestamp>/ dir.
# With --sentinel <name>: also touches /tmp/<name>-<timestamp>.
# Usage: dev-run-dir.sh [--sentinel <name>]
# Output: the created directory path.
# Exits 0 always.
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR=".developments/${TS}"
mkdir -p "$RUN_DIR"
if [ "${1:-}" = "--sentinel" ] && [ -n "${2:-}" ]; then
    # Strip path-unsafe chars to prevent /tmp/ path traversal via argv[2].
    SENTINEL_NAME="${2//[^a-zA-Z0-9_-]/}"
    if [ -n "$SENTINEL_NAME" ]; then
        touch "/tmp/${SENTINEL_NAME}-${TS}"
    fi
fi
echo "$RUN_DIR"
