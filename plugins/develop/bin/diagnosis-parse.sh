#!/usr/bin/env bash
# Parses --diagnosis path from $ARGUMENTS string.
# Usage: diagnosis-parse.sh "$ARGUMENTS"
# Output: resolved path to diagnosis file, or empty string if not provided.
# Exit 0 always; caller handles empty result.
# Exits 1 with message if --diagnosis given but file not found.
ARGUMENTS="${1:-}"
DIAG_FILE=""
while [ $# -gt 1 ]; do
    shift
done
# Re-parse from the original ARGUMENTS string safely
_rest="$ARGUMENTS"
while [ -n "$_rest" ]; do
    _token="${_rest%% *}"
    _rest="${_rest#"$_token"}"
    _rest="${_rest# }"
    case "$_token" in
        --diagnosis=*) DIAG_FILE="${_token#--diagnosis=}" ;;
        --diagnosis)
            _diag_val="${_rest%% *}"
            case "$_diag_val" in
                --*) ;;  # next token is another flag — no value
                *) DIAG_FILE="$_diag_val"; _rest="${_rest#"$_diag_val"}"; _rest="${_rest# }" ;;
            esac
            ;;
    esac
done
if [ -n "$DIAG_FILE" ] && [ ! -f "$DIAG_FILE" ]; then
    printf "! BREAKING — diagnosis file not found: %s\n" "$DIAG_FILE" >&2
    printf "Fix: run /develop:debug first to produce a diagnosis file, or omit --diagnosis\n" >&2
    exit 1
fi
printf "%s\n" "$DIAG_FILE"
