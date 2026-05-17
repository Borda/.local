#!/usr/bin/env bash
# Strips leading '#' from issue number in arguments and fetches the GitHub issue.
# Usage: issue-fetch.sh "$ARGUMENTS"
# Output: gh issue view output (stdout + stderr combined).
# Exits with gh exit code.
ISSUE_NUM="${1#\#}"
gh issue view "$ISSUE_NUM" --comments 2>&1
