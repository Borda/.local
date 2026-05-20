#!/usr/bin/env bash
# release_setup.sh — Shared setup block for /oss:release modes.
#
# Resolves skill directory (installed cache → source tree fallback), repo root,
# branch slug, current UTC date, and the branch-aware last-stable-tag baseline.
# Stable-branch detection: when current branch has its own stable tag in
# first-parent history, baseline is that tag (no cherry-pick handling needed);
# otherwise baseline is most recent stable tag reachable from a common
# ancestor between HEAD and the source-tag commit — cherry-picked subjects
# are captured for later annotation.
#
# Output:
#   stdout — KEY=value lines (caller does: eval "$(... release_setup.sh)")
#            SKILL_DIR, REPO_ROOT, BRANCH, DATE, LAST_TAG,
#            CHERRY_PICK_SUBJECTS (may be empty), SOURCE_TAG_REF (may be empty)
#   stderr — informational notes (stable-branch banner, fallback warnings)
#
# Exit: 0 always — caller validates resolved values.
set -euo pipefail

log() { printf '%s\n' "$*" >&2; }

# --- skill directory (installed first; source tree fallback) ------------------
SKILL_DIR=$(find ~/.claude/plugins -path "*/oss/skills/release" -type d 2>/dev/null | head -1 || true)
[ -z "$SKILL_DIR" ] && SKILL_DIR="plugins/oss/skills/release"

# --- repo / branch / date -----------------------------------------------------
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo "main")
DATE=$(date -u +%Y-%m-%d)

# --- branch-aware tag detection (excludes rc/dev/alpha/beta) ------------------
# Stable-branch mode: branch's first-parent history already includes a stable
# tag — that tag is the baseline; no cherry-pick handling needed.
BRANCH_TAG=$(git describe --tags --abbrev=0 --first-parent \
    --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null || true)

CHERRY_PICK_SUBJECTS=""
SOURCE_TAG_REF=""

if [ -n "$BRANCH_TAG" ]; then
    LAST_TAG="$BRANCH_TAG"
else
    # No tag reachable via first-parent: branch is not stable-tag-aligned.
    # Find latest stable tag reachable from HEAD, then anchor baseline at
    # the common ancestor between HEAD and that tag.
    SOURCE_TAG=$(git describe --tags --abbrev=0 \
        --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null || true)
    if [ -z "$SOURCE_TAG" ]; then
        SOURCE_TAG=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
        log "ℹ No stable tags found — using initial commit as range base (first release; range covers full history)"
    fi

    SOURCE_COMMIT=$(git rev-list -n1 "refs/tags/$SOURCE_TAG" 2>/dev/null || echo "$SOURCE_TAG")
    COMMON_COMMIT=$(git merge-base HEAD "$SOURCE_COMMIT" 2>/dev/null || true)
    if [ -z "$COMMON_COMMIT" ]; then
        log "Warning: no common ancestor found — range may span full history"
        COMMON_COMMIT=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1 || true)
    fi

    LAST_TAG=$(git describe --tags --abbrev=0 \
        --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' \
        "$COMMON_COMMIT" 2>/dev/null || echo "$COMMON_COMMIT")
    CHERRY_PICK_SUBJECTS=$(git log "$LAST_TAG..$SOURCE_TAG" --no-merges --format="%s" 2>/dev/null || true)
    SOURCE_TAG_REF="$SOURCE_TAG"
    log "ℹ Stable-branch mode: base=$LAST_TAG  source=$SOURCE_TAG"
fi

# --- emit KEY=value to stdout -------------------------------------------------
# Quote values that may contain spaces or shell-special characters.
# Note: printf '%q' is bash-specific ($'...' ANSI-C quoting) — caller must
# `eval` this output under bash, not POSIX sh (F-06 in security audit 2026-05-19).
printf 'SKILL_DIR=%q\n' "$SKILL_DIR"
printf 'REPO_ROOT=%q\n' "$REPO_ROOT"
printf 'BRANCH=%q\n' "$BRANCH"
printf 'DATE=%q\n' "$DATE"
printf 'LAST_TAG=%q\n' "$LAST_TAG"
printf 'CHERRY_PICK_SUBJECTS=%q\n' "$CHERRY_PICK_SUBJECTS"
printf 'SOURCE_TAG_REF=%q\n' "$SOURCE_TAG_REF"
