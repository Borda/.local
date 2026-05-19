#!/usr/bin/env bash
# commit_all_items.sh PR_NUMBER N_AS_SUGGESTED N_SELF_RESOLVED N_REJECTED [SUMMARIES_FILE] [--codex]
# Create a single bulk commit referencing all resolved review items.
# Extracted from oss:resolve action-item-dispatch COMMIT_MODE=all block (AI9).
#
# Args:
#   $1  PR_NUMBER         — pull request number
#   $2  N_AS_SUGGESTED    — count of items applied as-suggested
#   $3  N_SELF_RESOLVED   — count of items self-resolved (suggestion rejected)
#   $4  N_REJECTED        — count of items whose evidence was rejected (skipped)
#   $5  SUMMARIES_FILE    — optional path to file with bullet-list item summaries
#   --codex               — include OpenAI Codex co-author trailer (pass anywhere)
set -euo pipefail

PR_NUMBER=""
N_AS_SUGGESTED=0
N_SELF_RESOLVED=0
N_REJECTED=0
SUMMARIES_FILE=""
INCLUDE_CODEX=0

_POS=0
for _ARG in "$@"; do
    case "$_ARG" in
        --codex) INCLUDE_CODEX=1 ;;
        *)
            _POS=$(( _POS + 1 ))
            case $_POS in
                1) PR_NUMBER="$_ARG" ;;
                2) N_AS_SUGGESTED="$_ARG" ;;
                3) N_SELF_RESOLVED="$_ARG" ;;
                4) N_REJECTED="$_ARG" ;;
                5) SUMMARIES_FILE="$_ARG" ;;
            esac
            ;;
    esac
done

[ -z "$PR_NUMBER" ] && { echo "Usage: $0 PR_NUMBER N_AS N_SELF N_REJECTED [SUMMARIES_FILE] [--codex]" >&2; exit 1; }

BULLET_LIST=""
if [ -n "$SUMMARIES_FILE" ] && [ -f "$SUMMARIES_FILE" ]; then
    BULLET_LIST=$(<"$SUMMARIES_FILE")
fi

CODEX_TRAILER=""
[ "$INCLUDE_CODEX" = "1" ] && CODEX_TRAILER="Co-authored-by: OpenAI Codex <codex@openai.com>"

timeout 3 git commit -m "$(cat <<EOF
Resolve review items for PR #${PR_NUMBER}

${BULLET_LIST}
Challenge log: ${N_AS_SUGGESTED} as-suggested, ${N_SELF_RESOLVED} self-resolved, ${N_REJECTED} rejected

---
Co-authored-by: Claude Code <noreply@anthropic.com>
${CODEX_TRAILER}
EOF
)"
