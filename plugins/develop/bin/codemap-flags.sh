#!/usr/bin/env bash
# Resolves CODEMAP_ENABLED value from the arguments string.
# Usage: codemap-flags.sh "$ARGUMENTS"
# Output: prints resolved value — "off" | "strict" | "auto" (default when neither flag present).
# Exits 0 always.
ARGS="${1:-}"
if [[ "$ARGS" == *"--no-codemap"* ]]; then
    echo "off"
elif [[ "$ARGS" == *"--codemap"* ]]; then
    echo "strict"
else
    echo "auto"
fi
