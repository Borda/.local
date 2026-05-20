#!/usr/bin/env bash
# run_audit_checks.sh — pre-release readiness data gathering for /oss:release audit.
#
# Prints data sections separated by `--- check: <name> ---` banners so the
# release agent can extract per-check output for the readiness table. Interpretive
# steps (README alignment, CHANGELOG coverage judgement, severity assignment)
# remain in templates/audit-checks.md — this script only emits raw evidence.
#
# Usage:
#   run_audit_checks.sh --repo <owner/repo> [--tag <version>] [--range <git-range>]
#
# Defaults:
#   range = $LAST_TAG..HEAD where LAST_TAG falls back to last stable tag or initial commit.
#
# Exit codes:
#   0 — all data-gathering checks ran (warnings on optional/missing tools)
#   1 — bad args
#   2 — gh CLI not authenticated (critical for several checks)
set -euo pipefail

REPO=""
TAG=""
RANGE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --repo) REPO="$2"; shift 2 ;;
        --tag) TAG="$2"; shift 2 ;;
        --range) RANGE="$2"; shift 2 ;;
        *) echo "run_audit_checks: unknown arg '$1'" >&2; exit 1 ;;
    esac
done

# Resolve range when caller did not supply one. Skill's Shared setup normally
# provides $LAST_TAG; fall back to stable-tag-only describe if absent.
if [ -z "$RANGE" ]; then
    LAST_TAG="${LAST_TAG:-$(git describe --tags --abbrev=0 \
        --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null \
        || git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)}"
    # Reject tags starting with `-` to prevent git option injection (F-05).
    if [[ "$LAST_TAG" == -* ]]; then
        echo "run_audit_checks: invalid tag: '$LAST_TAG'" >&2; exit 2
    fi
    RANGE="$LAST_TAG..HEAD"
fi

# --- Pre-flight: gh authentication --------------------------------------------
printf -- '--- check: gh-auth ---\n'
if ! gh auth status 2>&1; then
    echo "gh not authenticated — run 'gh auth login' first"
    exit 2
fi

# --- Check 1: Repository state ------------------------------------------------
printf -- '--- check: repo-state ---\n'
echo "## uncommitted changes:"
git status --short || true
echo "## unreleased commits in range $RANGE:"
git log --oneline --no-merges "$RANGE" -- 2>/dev/null || true

# --- Check 2: CI health -------------------------------------------------------
printf -- '--- check: ci-health ---\n'
gh run list --branch "$(git rev-parse --abbrev-ref HEAD)" --limit 5 \
    --json status,conclusion,name 2>/dev/null || echo "[]"

# --- Check 3: Open issues and PRs ---------------------------------------------
printf -- '--- check: open-issues-prs ---\n'
echo "## open issues with high-severity labels:"
gh issue list --state open --limit 100 \
    --json number,title,labels 2>/dev/null || echo "[]"

TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' \
    | { read -r _ _ val; echo "${val:-main}"; })
echo "## open PRs targeting ${TRUNK:-main}:"
gh pr list --state open --base "${TRUNK:-main}" --limit 20 \
    --json number,title,draft,reviewDecision 2>/dev/null || echo "[]"

# --- Check 4: Documentation alignment (data only — interpretation in template) ---
printf -- '--- check: docs-alignment ---\n'
echo "## files changed since $RANGE:"
git diff --name-only "$RANGE" -- 2>/dev/null || true
echo "## docs/README touched:"
git diff --name-only "$RANGE" -- 2>/dev/null | grep -iE 'readme|\.md$|docs/' || echo "no docs changed"

# --- Check 5: Version consistency ---------------------------------------------
printf -- '--- check: version-consistency ---\n'
grep -rn '__version__\|^version\s*=' \
    --include="*.py" --include="*.toml" --include="*.cfg" --include="*.json" \
    . 2>/dev/null | grep -v ".git" | head -15 || true
[ -n "$TAG" ] && echo "## target version: $TAG"

# --- Check 6: Critical code signals -------------------------------------------
printf -- '--- check: code-signals ---\n'
echo "## release-blocking TODOs / FIXME / HACK / XXX (outside tests):"
grep -rn "TODO.*release\|FIXME\|HACK\|XXX" --include="*.py" \
    --exclude-dir=".git" --exclude-dir="tests" . 2>/dev/null | head -10 || true

echo "## dependency CVE scan:"
if command -v pip-audit >/dev/null 2>&1; then
    pip-audit --format=json 2>/dev/null \
        | python "${OSS_BIN_DIR:-$(dirname "$0")}/parse_audit_json.py" \
        || echo "pip-audit ran but JSON parsing failed"
else
    echo "pip-audit not installed — CVE scan skipped; install with: pip install pip-audit"
fi

printf -- '--- check: end ---\n'
