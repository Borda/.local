#!/usr/bin/env bash
# Creates a timestamped run directory under the given base dir.
# Prints the created directory path to stdout.
# Usage: make-run-dir.sh <skill-slug> <base-dir>
SKILL_SLUG="${1:?skill-slug required}"
BASE_DIR="${2:?base-dir required}"
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR="${BASE_DIR}/${SKILL_SLUG}-${TS}"
mkdir -p "$RUN_DIR"
echo "$RUN_DIR"
