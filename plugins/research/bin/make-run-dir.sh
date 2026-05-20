#!/usr/bin/env bash
# Creates a timestamped run directory under the given base dir.
# Prints the created directory path to stdout.
# Usage: make-run-dir.sh <skill-slug> <base-dir>
SKILL_SLUG="${1:?skill-slug required}"
BASE_DIR="${2:?base-dir required}"
if ! [[ "$BASE_DIR" =~ ^[a-zA-Z0-9_./-]+$ ]] || [[ "$BASE_DIR" == *".."* ]]; then
    echo "make-run-dir: invalid BASE_DIR: '$BASE_DIR'" >&2; exit 2
fi
if ! [[ "$SKILL_SLUG" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "make-run-dir: invalid SKILL_SLUG: '$SKILL_SLUG'" >&2; exit 2
fi
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
RUN_DIR="${BASE_DIR}/${SKILL_SLUG}-${TS}"
mkdir -p "$RUN_DIR"
echo "$RUN_DIR"
