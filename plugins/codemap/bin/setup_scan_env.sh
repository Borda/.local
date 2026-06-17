#!/usr/bin/env bash
# setup_scan_env.sh — derive scan-codebase setup state in one place.
#
# Consolidates the per-invocation setup previously inlined in scan-codebase/SKILL.md:
#   1. Derive PROJ_SLUG (hostname-shortname + repo basename, alphanumeric-safe).
#   2. Validate scan-index binary exists at $CLAUDE_PLUGIN_ROOT/bin/scan-index.
#   3. Run parse_scan_args.py against the raw $ARGUMENTS string and capture the
#      resulting `--root <quoted> [--incremental]` token list.
#   4. Derive PROJ_NAME — basename of --root value when --root is present,
#      otherwise basename of git toplevel (or $PWD when outside a repo).
#   5. Drop a sentinel tmpfile when --incremental was requested but no prior
#      index exists, so Step 2 can report the silent full-scan fallback.
#   6. Write a sourceable KEY=VAL state file and the individual per-PROJ_SLUG
#      tmpfiles consumed by the second Step 1 block + Step 2.
#
# Usage:
#   setup_scan_env.sh --arguments "$ARGUMENTS"
#
# Exit codes:
#   0  success — state file path on stdout
#   1  scan-index binary missing (message on stderr)
#   2  parse_scan_args.py failed (message on stderr)
#   3  bad CLI arguments (message on stderr)
set -euo pipefail

ARGUMENTS=""

while [ $# -gt 0 ]; do
    case "$1" in
        --arguments)
            shift
            [ $# -gt 0 ] || { printf "setup_scan_env.sh: --arguments needs a value\n" >&2; exit 3; }
            ARGUMENTS="$1"
            shift
            ;;
        --arguments=*)
            ARGUMENTS="${1#--arguments=}"
            shift
            ;;
        *)
            printf "setup_scan_env.sh: unknown argument: %s\n" "$1" >&2
            exit 3
            ;;
    esac
done

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/codemap}"
SCAN_BIN="${PLUGIN_ROOT}/bin/scan-index"
PARSE_BIN="${PLUGIN_ROOT}/bin/parse_scan_args.py"

if [ ! -x "$SCAN_BIN" ]; then
    printf "! scan-index binary not found at %s — reinstall: claude plugin install codemap@borda-ai-rig\n" "$SCAN_BIN" >&2
    exit 1
fi

# Run parse_scan_args.py — yields `--root <quoted>` and/or `--incremental` tokens.
if ! SCAN_ARGS_RAW="$(python "$PARSE_BIN" "$ARGUMENTS")"; then
    printf "! parse_scan_args.py failed — check Python availability and plugin installation\n" >&2
    exit 2
fi

# Hostname short-name + repo basename, sanitised to alphanumerics + dashes.
# Falls back to PWD basename when outside a git repo.
HOSTNAME_SLUG="$(hostname -s 2>/dev/null | tr -cd '[:alnum:]-')"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")"
REPO_SLUG="$(basename "$REPO_ROOT" | tr -cd '[:alnum:]-')"
PROJ_SLUG="${HOSTNAME_SLUG}-${REPO_SLUG}"

# PROJ_NAME — when --root provided, basename(--root); else basename(git-root|PWD).
# Mirrors scan-index's own project-name derivation so the cache lookup stays consistent.
if [[ " $ARGUMENTS " == *" --root "* ]]; then
    # Same extraction strategy as parse_scan_args.py but bash-only — no PCRE dependency.
    # Strip everything up to the literal `--root ` marker, then take the first whitespace
    # delimited token. Strip surrounding single/double quotes if present.
    ROOT_TAIL="${ARGUMENTS#*--root }"
    ROOT_ARG="${ROOT_TAIL%%[[:space:]]*}"
    ROOT_ARG="${ROOT_ARG#\'}"; ROOT_ARG="${ROOT_ARG%\'}"
    ROOT_ARG="${ROOT_ARG#\"}"; ROOT_ARG="${ROOT_ARG%\"}"
    PROJ_NAME="$(basename "$ROOT_ARG")"
else
    PROJ_NAME="$(basename "$REPO_ROOT")"
fi

TMPDIR_DIR="${TMPDIR:-/tmp}"

# Per-PROJ_SLUG tmpfiles — survive across Bash tool calls; consumed by Step 1's
# second block + Step 2 of scan-codebase/SKILL.md. PID-qualified to prevent
# concurrent same-project scan runs from racing on shared state.
printf '%s' "$PROJ_SLUG"      > "${TMPDIR_DIR}/codemap-proj-slug-$$"
printf '%s' "$SCAN_BIN"       > "${TMPDIR_DIR}/codemap-scan-bin-${PROJ_SLUG}-$$"
printf '%s' "$SCAN_ARGS_RAW"  > "${TMPDIR_DIR}/codemap-scan-args-${PROJ_SLUG}-$$"
printf '%s' "$PROJ_NAME"      > "${TMPDIR_DIR}/codemap-proj-name-${PROJ_SLUG}-$$"
# Keep non-PID versions as fallback for callers that predate this change
printf '%s' "$PROJ_SLUG"      > "${TMPDIR_DIR}/codemap-proj-slug"
printf '%s' "$SCAN_BIN"       > "${TMPDIR_DIR}/codemap-scan-bin-${PROJ_SLUG}"
printf '%s' "$SCAN_ARGS_RAW"  > "${TMPDIR_DIR}/codemap-scan-args-${PROJ_SLUG}"
printf '%s' "$PROJ_NAME"      > "${TMPDIR_DIR}/codemap-proj-name-${PROJ_SLUG}"

# --incremental requested but no prior index ⇒ scan-index will fall back to full scan.
# Drop a sentinel so Step 2 can report the fallback after stats.
if [[ " $ARGUMENTS " == *" --incremental "* ]]; then
    _INDEX_DIR="${CODEMAP_INDEX_DIR:-.cache/codemap}"
    if [ ! -f "${_INDEX_DIR}/${PROJ_NAME}.json" ]; then
        # stderr — keeps stdout reserved for the state file path so the caller
        # can capture only that path via $(...).
        printf '[codemap] No prior index: falling back to full scan\n' >&2
        touch "${TMPDIR_DIR}/codemap-incremental-noop-${PROJ_SLUG}"
    fi
fi

# State file — sourceable KEY=VAL form for in-block use by the caller.
# Single-quote values to survive `source` even when paths contain shell metachars.
# Embedded single quotes are escaped via the standard '\'' shell idiom.
escape_sq() {
    # Replace each ' with '\''
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

STATE_FILE="${TMPDIR_DIR}/codemap-scan-state-$$"
{
    printf "PROJ_SLUG='%s'\n"     "$(escape_sq "$PROJ_SLUG")"
    printf "SCAN_BIN='%s'\n"      "$(escape_sq "$SCAN_BIN")"
    printf "SCAN_ARGS_RAW='%s'\n" "$(escape_sq "$SCAN_ARGS_RAW")"
    printf "PROJ_NAME='%s'\n"     "$(escape_sq "$PROJ_NAME")"
} > "$STATE_FILE"

printf '%s\n' "$STATE_FILE"
