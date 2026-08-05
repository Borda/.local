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

PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}"
SCAN_BIN="${PLUGIN_ROOT}/bin/scan-index"
PARSE_BIN="${PLUGIN_ROOT}/bin/parse_scan_args.py"

if [ ! -x "$SCAN_BIN" ]; then
    printf "! scan-index binary not found at %s — reinstall: claude plugin install codemap-py@borda-ai-rig\n" "$SCAN_BIN" >&2
    exit 1
fi

# Run parse_scan_args.py — yields `--root <quoted>` and/or `--incremental` tokens.
if ! SCAN_ARGS_RAW="$(python3 "$PARSE_BIN" "$ARGUMENTS")"; then
    printf "! parse_scan_args.py failed — check Python availability and plugin installation\n" >&2
    exit 2
fi

# Hostname short-name + repo basename, sanitised to alphanumerics + dashes.
# Falls back to PWD basename when outside a git repo.
HOSTNAME_SLUG="$(hostname -s 2>/dev/null | tr -cd '[:alnum:]-')"
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")"
REPO_SLUG="$(basename "$REPO_ROOT" | tr -cd '[:alnum:]-')"
PROJ_SLUG="${HOSTNAME_SLUG}-${REPO_SLUG}"

# PROJ_NAME — delegate to parse_scan_args.py --print-root so quoted/spaced paths are
# handled correctly. Falls back to git-root basename when --root is absent.
ROOT_DIR="$(python3 "$PARSE_BIN" "$ARGUMENTS" --print-root 2>/dev/null || echo ".")"
if [ "$ROOT_DIR" = "." ]; then
    PROJ_NAME="$(basename "$REPO_ROOT")"
else
    PROJ_NAME="$(basename "$ROOT_DIR")"
fi

# SEC-M1: validate TMPDIR before using it for state files.
# An attacker-controlled TMPDIR could redirect state writes outside expected dirs.
_RAW_TMPDIR="${TMPDIR:-}"
if [ -n "$_RAW_TMPDIR" ]; then
    # Must be absolute (no relative traversal)
    case "$_RAW_TMPDIR" in
        /*) ;;
        *) printf "setup_scan_env.sh: TMPDIR is not an absolute path — ignoring: %s\n" "$_RAW_TMPDIR" >&2
           _RAW_TMPDIR="" ;;
    esac
    # Must be owned by current user (UID match)
    if [ -n "$_RAW_TMPDIR" ]; then
        _TMPDIR_UID=$(stat -c '%u' "$_RAW_TMPDIR" 2>/dev/null || stat -f '%u' "$_RAW_TMPDIR" 2>/dev/null || echo "")
        _CURRENT_UID=$(id -u)
        if [ -n "$_TMPDIR_UID" ] && [ "$_TMPDIR_UID" != "$_CURRENT_UID" ]; then
            printf "setup_scan_env.sh: TMPDIR owner UID (%s) != current UID (%s) — ignoring: %s\n" \
                "$_TMPDIR_UID" "$_CURRENT_UID" "$_RAW_TMPDIR" >&2
            _RAW_TMPDIR=""
        fi
    fi
fi
TMPDIR_DIR="${_RAW_TMPDIR:-/tmp}"  # tmpdir-exempt: base-dir-fallback (directory root, not a sentinel filename)

# Session-scope suffix — caller (scan-codebase/SKILL.md Step 1 block 1) exports CSID
# before invoking this script; degrades to "shared" only if the caller forgot the export.
CSID="${CSID:-shared}"

# Per-PROJ_SLUG tmpfiles — legacy fallback surface, kept for callers that predate
# STATE_FILE (the sourced KEY=VAL handoff below, the actual consumed mechanism).
# PID-qualified to prevent concurrent same-project scan runs from racing on shared state.
#
# CWE-377: plain `printf > file` follows a pre-planted symlink at the target path and
# truncates whatever it points to. write-to-mktemp-then-rename is atomic (POSIX rename()
# replaces the destination inode outright, symlink or not, rather than writing through it)
# and preserves the exact byte content (no trailing newline) test_setup_scan_env_sh.py pins.
_cm_write_atomic() {
    local target="$1" content="$2"
    local tmp
    tmp="$(mktemp "${TMPDIR_DIR}/.codemap-setup-tmp.XXXXXX")"
    printf '%s' "$content" > "$tmp"
    mv -f "$tmp" "$target"
}
_cm_write_atomic "${TMPDIR_DIR}/codemap-proj-slug-$$-${CSID}" "$PROJ_SLUG"
_cm_write_atomic "${TMPDIR_DIR}/codemap-scan-bin-${PROJ_SLUG}-$$-${CSID}" "$SCAN_BIN"
_cm_write_atomic "${TMPDIR_DIR}/codemap-scan-args-${PROJ_SLUG}-$$-${CSID}" "$SCAN_ARGS_RAW"
_cm_write_atomic "${TMPDIR_DIR}/codemap-proj-name-${PROJ_SLUG}-$$-${CSID}" "$PROJ_NAME"

# Keep non-PID versions as fallback for callers that predate this change
_cm_write_atomic "${TMPDIR_DIR}/codemap-proj-slug-${CSID}" "$PROJ_SLUG"
_cm_write_atomic "${TMPDIR_DIR}/codemap-scan-bin-${PROJ_SLUG}-${CSID}" "$SCAN_BIN"
_cm_write_atomic "${TMPDIR_DIR}/codemap-scan-args-${PROJ_SLUG}-${CSID}" "$SCAN_ARGS_RAW"
_cm_write_atomic "${TMPDIR_DIR}/codemap-proj-name-${PROJ_SLUG}-${CSID}" "$PROJ_NAME"

# --incremental requested but no prior index ⇒ scan-index will fall back to full scan.
# Drop a sentinel so Step 2 can report the fallback after stats.
# SEC: [[ == ]] is pattern-match (not eval) — $ARGUMENTS interpolation is safe; spaces around token prevent prefix/suffix false-match.
if [[ " $ARGUMENTS " == *" --incremental "* ]]; then
    _INDEX_DIR="${CODEMAP_INDEX_DIR:-.cache/codemap}"
    if [ ! -f "${_INDEX_DIR}/${PROJ_NAME}.json" ]; then
        # stderr — keeps stdout reserved for the state file path so the caller
        # can capture only that path via $(...).
        printf '[codemap] No prior index: falling back to full scan\n' >&2
        touch "${TMPDIR_DIR}/codemap-incremental-noop-${PROJ_SLUG}-${CSID}"
    fi
fi

# State file — sourceable KEY=VAL form for in-block use by the caller.
# Single-quote values to survive `source` even when paths contain shell metachars.
# Embedded single quotes are escaped via the standard '\'' shell idiom.
#
# The caller `source`s this file (SKILL.md Step 1 block 2, Step 2), which means any
# integrity gap here is a code-execution hole, not just a data-corruption one. Two
# defences: `mktemp` creates the file atomically (O_CREAT|O_EXCL, mode 0600) with an
# unguessable suffix instead of the trivially-predictable `$$` (process id) this file
# used before — a co-located attacker in a shared TMPDIR can no longer pre-plant a
# symlink at the exact name this script is about to write. The caller additionally
# asserts `-O`/`! -L` immediately before each `source`, in case TMPDIR is shared and
# some other, unrelated file collides.
escape_sq() {
    # Replace each ' with '\''
    printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

STATE_FILE="$(mktemp "${TMPDIR_DIR}/codemap-scan-state-XXXXXX")"
{
    printf "PROJ_SLUG='%s'\n"     "$(escape_sq "$PROJ_SLUG")"
    printf "SCAN_BIN='%s'\n"      "$(escape_sq "$SCAN_BIN")"
    printf "SCAN_ARGS_RAW='%s'\n" "$(escape_sq "$SCAN_ARGS_RAW")"
    printf "PROJ_NAME='%s'\n"     "$(escape_sq "$PROJ_NAME")"
} > "$STATE_FILE"

printf '%s\n' "$STATE_FILE"
