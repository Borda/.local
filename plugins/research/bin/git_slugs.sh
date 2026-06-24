#!/usr/bin/env bash
# Emit REPO_SLUG and BRANCH_SLUG for commit-sentinel paths, sourceable via eval.
# Bash state is lost between Claude Code tool calls — re-source at each use site.
# This is the single authorized slug form; consumers: research/skills/run/SKILL.md.
REPO_SLUG=$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
BRANCH_SLUG=$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
printf 'REPO_SLUG=%s\n' "$REPO_SLUG"
printf 'BRANCH_SLUG=%s\n' "$BRANCH_SLUG"
