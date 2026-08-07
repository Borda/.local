#!/usr/bin/env bash
# Emit REPO_SLUG and BRANCH_SLUG for commit-sentinel paths, sourceable via eval.
# Bash state is lost between Claude Code tool calls — re-source at each use site.
# Scope: commit-sentinel paths only (claude-commit-auth-*); the single authorized
# slug form for those. Consumers: research/skills/run/SKILL.md.
#
# NOT the slug form for report paths. Report filenames (.reports/**, .temp/output-*)
# use a separate sanctioned idiom, mandated verbatim by global quality-gates.md
# §Output Routing and used across every plugin:
#     BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')
#
# The two are NOT interchangeable. This helper lowercases and collapses every run of
# non-alphanumerics; the report idiom rewrites '/' only, and falls back to 'main',
# not 'detached'. Routing report paths through here renames outputs on any branch
# carrying uppercase, '.', '_', or a doubled '-':
#     branch            this helper       report idiom
#     feature/ABC-123   feature-abc-123   feature-ABC-123
#     release/v1.2.0    release-v1-2-0    release-v1.2.0
#     (non-repo)        detached          main
#
# Audit 2026-08-07 Check-33 cluster C8 flagged the report idiom in fortify/judge/retro
# as a "bypass" of this helper and proposed rerouting it here. False finding: it merged
# two clusters — run/SKILL.md legitimately uses both forms, this one for sentinels and
# the report idiom for its own report path. Verified non-equivalent, no call site
# changed. Do not re-file it.
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
