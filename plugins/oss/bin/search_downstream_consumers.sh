#!/usr/bin/env bash
# search_downstream_consumers.sh — find GitHub repos importing changed symbols.
#
# Loops over symbol names on stdin (one per line — output of
# extract_changed_symbols.sh) and queries the GitHub code-search API for
# Python import statements that name both the package and the symbol. Prints
# the union of repo full_names (sorted, deduplicated) so the caller can warn
# downstream maintainers before shipping a breaking change.
#
# Usage:
#   search_downstream_consumers.sh --package <name> [<symbol> ...]
#   echo -e "Symbol1\nSymbol2" | search_downstream_consumers.sh --package <name>
#
# Exit codes:
#   0 — search ran (empty result acceptable — no downstream consumers found)
#   1 — bad args (missing --package, no symbols on stdin or argv)
#   2 — gh CLI failure on every symbol query
set -euo pipefail

PACKAGE=""
SYMBOLS=()

while [ $# -gt 0 ]; do
    case "$1" in
        --package) PACKAGE="$2"; shift 2 ;;
        *)
            SYMBOLS+=("$1")
            shift
            ;;
    esac
done

[ -n "$PACKAGE" ] || { echo "search_downstream_consumers: --package required" >&2; exit 1; }

# Symbols not on argv → read from stdin (newline-separated).
if [ "${#SYMBOLS[@]}" -eq 0 ] && [ ! -t 0 ]; then
    while IFS= read -r line; do
        [ -n "$line" ] && SYMBOLS+=("$line")
    done
fi

if [ "${#SYMBOLS[@]}" -eq 0 ]; then
    echo "search_downstream_consumers: no symbols provided (argv or stdin)" >&2
    exit 1
fi

SUCCESS=0
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT INT TERM

for symbol in "${SYMBOLS[@]}"; do
    if gh api "search/code" \
        --field "q=from $PACKAGE import $symbol language:python" --paginate \
        --jq '.items[].repository.full_name' 2>/dev/null >>"$TMPDIR/results"; then
        SUCCESS=$((SUCCESS + 1))
    else
        echo "⚠ search failed for symbol '$symbol' (non-fatal)" >&2
    fi
done

if [ "$SUCCESS" -eq 0 ]; then
    echo "search_downstream_consumers: all symbol queries failed" >&2
    exit 2
fi

# Deduplicate and print.
sort -u "$TMPDIR/results"
