#!/usr/bin/env bash
# Emit REPO_SLUG and BRANCH_SLUG for commit-sentinel paths, sourceable via eval.
# Bash state is lost between Claude Code tool calls — re-source at each use site.
# This is the single authorized slug form; consumers: research/skills/run/SKILL.md.
set -euo pipefail

# Slugify: lowercase, non-alphanumerics → '-', collapse runs, strip trailing '-'.
slugify() {
	printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//'
}

# Capture git output with fallbacks so a non-repo / detached HEAD never aborts the
# script (empty slug would otherwise collide commit-sentinel paths across sessions).
REPO_TOPLEVEL=$(git rev-parse --show-toplevel 2>/dev/null || true)
BRANCH_NAME=$(git branch --show-current 2>/dev/null || true)

REPO_SLUG=$(slugify "$(basename "${REPO_TOPLEVEL:-no-repo}")")
BRANCH_SLUG=$(slugify "${BRANCH_NAME:-detached}")

# Empty after slugify (all-punctuation names) → sentinel, never an empty component.
[ -z "$REPO_SLUG" ] && REPO_SLUG="no-repo"
[ -z "$BRANCH_SLUG" ] && BRANCH_SLUG="detached"

printf 'REPO_SLUG=%s\n' "$REPO_SLUG"
printf 'BRANCH_SLUG=%s\n' "$BRANCH_SLUG"
