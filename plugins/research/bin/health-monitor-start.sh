#!/usr/bin/env bash
# Creates health monitoring checkpoint for a research skill agent spawn.
# Prints LAUNCH_AT and SENTINEL variables to stdout.
# Usage: health-monitor-start.sh <skill-id>
SKILL_ID="${1:?skill-id required}"
TS=$(date +%s)
SENTINEL="/tmp/research-${SKILL_ID}-check-${TS}"
touch "$SENTINEL"
echo "LAUNCH_AT=${TS}"
echo "SENTINEL=${SENTINEL}"
