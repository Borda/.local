#!/usr/bin/env bash
set -euo pipefail

TARGET=""
OUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --out)
      OUT_DIR="$2"
      shift 2
      ;;
    *)
      echo "unknown-arg:$1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$OUT_DIR" ]]; then
  echo "missing-required:--out" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
git status --short >"$OUT_DIR/status.txt" 2>/dev/null || true

PR_ARGS=()
if [[ -n "$TARGET" ]]; then
  PR_ARGS=("$TARGET")
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "missing-command:gh" >"$OUT_DIR/pr-error.txt"
  exit 2
fi

if ! gh pr view "${PR_ARGS[@]}" \
  --json number,title,url,author,baseRefName,headRefName,state,isDraft,reviewDecision,mergeable,comments,reviews,files \
  >"$OUT_DIR/pr.json"; then
  echo "gh-pr-view-failed:${TARGET:-current-branch}" >"$OUT_DIR/pr-error.txt"
  exit 2
fi

REPO_NAME_WITH_OWNER="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)"
if [[ -z "$REPO_NAME_WITH_OWNER" || "$REPO_NAME_WITH_OWNER" != */* ]]; then
  echo "gh-repo-view-failed" >"$OUT_DIR/pr-error.txt"
  exit 2
fi
OWNER="${REPO_NAME_WITH_OWNER%%/*}"
REPO="${REPO_NAME_WITH_OWNER#*/}"
PR_NUMBER="$(python3 - "$OUT_DIR/pr.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
number = payload.get("number")
if not isinstance(number, int):
    raise SystemExit("missing-pr-number")
print(number)
PY
)"

if ! gh api graphql \
  -f owner="$OWNER" \
  -f name="$REPO" \
  -F number="$PR_NUMBER" \
  -f query='
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          startLine
          originalLine
          originalStartLine
          diffSide
          comments(first: 100) {
            nodes {
              id
              author {
                login
              }
              body
              url
              path
              position
              originalPosition
              line
              originalLine
              diffHunk
              createdAt
              updatedAt
            }
          }
        }
      }
    }
  }
}' >"$OUT_DIR/review-threads.raw.json"; then
  echo "gh-review-threads-failed:${TARGET:-current-branch}" >"$OUT_DIR/pr-error.txt"
  exit 2
fi

if ! gh pr diff "${PR_ARGS[@]}" >"$OUT_DIR/diff.patch"; then
  echo "gh-pr-diff-failed:${TARGET:-current-branch}" >"$OUT_DIR/pr-error.txt"
  exit 2
fi

python3 - "$OUT_DIR/pr.json" "$OUT_DIR/review-threads.raw.json" "$OUT_DIR/files.txt" "$OUT_DIR/comments.json" "$OUT_DIR/reviews.json" "$OUT_DIR/review-threads.json" "$OUT_DIR/unresolved-review-threads.json" "$OUT_DIR/online-review-summary.json" "$OUT_DIR/pr-error.txt" <<'PY'
import json
import sys
from pathlib import Path

pr_path = Path(sys.argv[1])
threads_raw_path = Path(sys.argv[2])
files_path = Path(sys.argv[3])
comments_path = Path(sys.argv[4])
reviews_path = Path(sys.argv[5])
threads_path = Path(sys.argv[6])
unresolved_path = Path(sys.argv[7])
summary_path = Path(sys.argv[8])
error_path = Path(sys.argv[9])
payload = json.loads(pr_path.read_text(encoding="utf-8"))
threads_payload = json.loads(threads_raw_path.read_text(encoding="utf-8"))
threads_container = (
    threads_payload.get("data", {})
    .get("repository", {})
    .get("pullRequest", {})
    .get("reviewThreads", {})
)
threads = threads_container.get("nodes", []) or []
page_info = threads_container.get("pageInfo", {}) or {}
if page_info.get("hasNextPage"):
    error_path.write_text("review-thread-pagination-incomplete\n", encoding="utf-8")
    raise SystemExit(2)

files = []
for item in payload.get("files", []) or []:
    path = item.get("path")
    if path:
        files.append(path)
unresolved = [thread for thread in threads if thread.get("isResolved") is False]
outdated_unresolved = [thread for thread in unresolved if thread.get("isOutdated") is True]
active_unresolved = [thread for thread in unresolved if thread.get("isOutdated") is not True]
summary = {
    "review_thread_count": len(threads),
    "unresolved_review_thread_count": len(unresolved),
    "active_unresolved_review_thread_count": len(active_unresolved),
    "outdated_unresolved_review_thread_count": len(outdated_unresolved),
    "top_level_comment_count": len(payload.get("comments", []) or []),
    "review_count": len(payload.get("reviews", []) or []),
}
files_path.write_text("\n".join(sorted(files)) + ("\n" if files else ""), encoding="utf-8")
comments_path.write_text(json.dumps(payload.get("comments", []), indent=2) + "\n", encoding="utf-8")
reviews_path.write_text(json.dumps(payload.get("reviews", []), indent=2) + "\n", encoding="utf-8")
threads_path.write_text(json.dumps(threads, indent=2) + "\n", encoding="utf-8")
unresolved_path.write_text(json.dumps(unresolved, indent=2) + "\n", encoding="utf-8")
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
PY

git apply --stat <"$OUT_DIR/diff.patch" >"$OUT_DIR/diffstat.txt" 2>/dev/null || true
git apply --numstat <"$OUT_DIR/diff.patch" >"$OUT_DIR/numstat.txt" 2>/dev/null || true
: >"$OUT_DIR/untracked.txt"
