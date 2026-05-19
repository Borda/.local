#!/usr/bin/env bash
# Creates a UTC-timestamped run directory under the given base dir.
# Prints the created directory path to stdout.
# Usage: make-run-dir.sh <base-dir>
#   <base-dir>  e.g. .reports/audit, .reports/distill, .temp/investigate
# Exit codes: 0 = success, 1 = bad args
set -euo pipefail

base_dir="${1:?base-dir required}"
ts=$(date -u +%Y-%m-%dT%H-%M-%SZ)
run_dir="${base_dir}/${ts}"
mkdir -p "$run_dir"
echo "$run_dir"
