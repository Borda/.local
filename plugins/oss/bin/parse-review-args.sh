#!/usr/bin/env bash
# parse-review-args.sh — parse oss:review $ARGUMENTS, emit shell variable assignments
# Usage (Claude Code plugin — CLAUDE_PLUGIN_ROOT is set automatically):
#   eval "$(bash "${CLAUDE_PLUGIN_ROOT}/bin/parse-review-args.sh" "$ARGUMENTS")"
# Emits: REPLY_MODE, CHALLENGE_ENABLED, CODEMAP_ENABLED, SEMBLE_ENABLED, CLEAN_ARGS

ARGS="$*"
REPLY_MODE=false
CHALLENGE_ENABLED=true
CODEMAP_ENABLED=false
SEMBLE_ENABLED=false

if [[ "$ARGS" == *"--reply"* ]]; then
    REPLY_MODE=true
    ARGS="${ARGS//--reply/}"
fi
if [[ "$ARGS" == *"--no-challenge"* ]]; then
    CHALLENGE_ENABLED=false
    ARGS="${ARGS//--no-challenge/}"
fi
if [[ "$ARGS" == *"--codemap"* ]]; then
    CODEMAP_ENABLED=true
    ARGS="${ARGS//--codemap/}"
fi
if [[ "$ARGS" == *"--semble"* ]]; then
    SEMBLE_ENABLED=true
    ARGS="${ARGS//--semble/}"
fi

# Trim leading whitespace, then strip leading '#' so both '123' and '#123' work
ARGS="${ARGS#"${ARGS%%[![:space:]]*}"}"
ARGS="${ARGS#\#}"

printf 'REPLY_MODE=%q\n' "$REPLY_MODE"
printf 'CHALLENGE_ENABLED=%q\n' "$CHALLENGE_ENABLED"
printf 'CODEMAP_ENABLED=%q\n' "$CODEMAP_ENABLED"
printf 'SEMBLE_ENABLED=%q\n' "$SEMBLE_ENABLED"
printf 'CLEAN_ARGS=%q\n' "$ARGS"
