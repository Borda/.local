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
    touch "/tmp/${2}-${TS}"
fi
echo "$RUN_DIR"
