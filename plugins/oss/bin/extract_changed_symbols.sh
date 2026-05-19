#!/usr/bin/env bash
# bin/ — extract_changed_symbols.sh
#
# Extract added/removed public Python symbols (class/def names) from
# __init__.py diffs in a given commit range. Used by `oss:shepherd`
# downstream-impact assessment to find names that callers may import.
#
# Usage:
#   extract_changed_symbols.sh [<git_diff_range>]
#
# Args:
#   git_diff_range: any range git diff understands (e.g. HEAD~1..HEAD,
#                   origin/main..HEAD, a..b). Defaults to HEAD~1..HEAD.
#
# Output:
#   Newline-separated, sort -u'd list of symbol names. Prints nothing
#   (exit 0) when:
#     - the diff range is empty or invalid (e.g. initial commit, no parent)
#     - no __init__.py files exist
#     - no class/def symbols changed
#
# Caller pattern (shepherd.md):
#   CHANGED_SYMBOLS=$("${OSS_SHARED:-plugins/oss/bin}/extract_changed_symbols.sh" "$RANGE")
#   [ -z "$CHANGED_SYMBOLS" ] && echo "No changed symbols — skipping ecosystem check"
#
# Scope: deterministic transform only (per plugins/CLAUDE.md bin/ language
# policy). Branching decisions and AskUserQuestion live in the caller.

set -u

RANGE="${1:-HEAD~1..HEAD}"

# Guard: validate range — git diff with non-existent ref returns non-zero
# silently in some shells; check by resolving both ends.
case "$RANGE" in
    *..*)
        LEFT="${RANGE%%..*}"
        RIGHT="${RANGE##*..}"
        [ -z "$RIGHT" ] && RIGHT="HEAD"
        if ! git rev-parse "$LEFT" >/dev/null 2>&1 || ! git rev-parse "$RIGHT" >/dev/null 2>&1; then
            # invalid range (e.g. HEAD~1 on initial commit) — output nothing
            exit 0
        fi
        ;;
    *)
        # Single ref form (e.g. HEAD) — diff against working tree; only
        # valid if ref resolves
        if ! git rev-parse "$RANGE" >/dev/null 2>&1; then
            exit 0
        fi
        ;;
esac

# Collect __init__.py paths excluding hidden dirs and node_modules.
# head -50 caps pathological monorepos; preserves prior behaviour.
INIT_FILES=$(find . -name '__init__.py' -not -path '*/\.*' -not -path '*/node_modules/*' 2>/dev/null | head -50)

# No __init__.py present — nothing to extract.
[ -z "$INIT_FILES" ] && exit 0

# Pass paths as separate arguments via xargs (handles >ARG_MAX and
# preserves multi-file diffs — prior `"$INIT_FILES"` quoting collapsed
# them into a single argument; see M28).
# shellcheck disable=SC2086  # word-splitting intentional — INIT_FILES is newline-separated paths
printf '%s\n' $INIT_FILES \
    | xargs git diff "$RANGE" -- 2>/dev/null \
    | grep -E '^[+-][^+-]' \
    | grep -oE '(class|def)[[:space:]]+[A-Za-z_][A-Za-z0-9_]*' \
    | awk '{print $2}' \
    | sort -u
