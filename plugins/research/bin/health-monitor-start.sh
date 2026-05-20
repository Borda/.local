#!/usr/bin/env bash
# Creates health monitoring checkpoint for a research skill agent spawn.
# Prints LAUNCH_AT and SENTINEL variables to stdout.
# Usage: health-monitor-start.sh <skill-id>
SKILL_ID="${1:?skill-id required}"
if ! [[ "$SKILL_ID" =~ ^[a-zA-Z0-9_-]+$ ]]; then
    echo "health-monitor-start: invalid SKILL_ID: '$SKILL_ID'" >&2; exit 2
fi
TS=$(date +%s)
SENTINEL="/tmp/research-${SKILL_ID}-check-${TS}"
touch "$SENTINEL"
echo "LAUNCH_AT=${TS}"
echo "SENTINEL=${SENTINEL}"
