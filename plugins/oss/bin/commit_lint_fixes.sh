#!/usr/bin/env bash
# commit_lint_fixes.sh
# Stage all tracked changed files and commit with standard lint-fix message.
# Extracted from oss:resolve lint-qa-gate Step 9 auto-fix commit block (LQ3).
# No-ops cleanly when there are no changed files to stage.
set -euo pipefail

CHANGED=$(git diff HEAD --name-only 2>/dev/null) || true
if [ -z "$CHANGED" ]; then
    echo "[lint] no changed files to commit"
    exit 0
fi

git diff HEAD -z --name-only 2>/dev/null | timeout 3 xargs -0 git add --

timeout 3 git commit -m "$(cat <<'EOF'
lint: auto-fix violations after resolve cycle

---
Co-authored-by: Claude Code <noreply@anthropic.com>
EOF
)"
