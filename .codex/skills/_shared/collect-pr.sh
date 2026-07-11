#!/usr/bin/env bash
set -euo pipefail

TARGET=""
OUT_DIR=""
CHECKOUT=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage: collect-pr.sh --out DIR [--target PR] [--checkout]

Collect authoritative GitHub PR metadata, diff, comments, reviews, review
threads, routing identity, and local status. With --checkout, fetch and update
the local PR checkout after repository/OID validation.

Options:
  --out DIR       Required artifact directory
  --target PR     PR number, URL, or gh-compatible selector; default current branch
  --checkout      Fetch and update the validated local PR checkout
  -h, --help      Show this help

Requires gh authentication and a matching local repository remote. Exit 0
means collection succeeded; exit 2 means invalid input or unavailable PR data.
Remote mutation is never performed.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --out)
      OUT_DIR="$2"
      shift 2
      ;;
    --checkout)
      CHECKOUT=true
      shift
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
  --json number,title,url,author,baseRefName,baseRefOid,headRefName,headRefOid,headRepository,headRepositoryOwner,isCrossRepository,state,isDraft,reviewDecision,mergeable,comments,reviews,files \
  >"$OUT_DIR/pr.json"; then
  echo "gh-pr-view-failed:${TARGET:-current-branch}" >"$OUT_DIR/pr-error.txt"
  exit 2
fi

PR_URL="$(python3 - "$OUT_DIR/pr.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
url = payload.get("url")
if not isinstance(url, str) or not url:
    raise SystemExit("missing-pr-url")
print(url)
PY
)"
if ! BASE_IDENTITY_JSON="$(python3 "$SCRIPT_DIR/select-git-remote.py" --expected-url "$PR_URL" --identity-only)"; then
  echo "invalid-pr-base-url:$PR_URL" >"$OUT_DIR/pr-error.txt"
  exit 2
fi
REPO_NAME_WITH_OWNER="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["repository"])' "$BASE_IDENTITY_JSON")"
BASE_HOST="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["host"])' "$BASE_IDENTITY_JSON")"
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

python3 - "$OUT_DIR/pr.json" "$OUT_DIR/review-threads.raw.json" "$OUT_DIR/files.txt" "$OUT_DIR/comments.json" "$OUT_DIR/reviews.json" "$OUT_DIR/review-threads.json" "$OUT_DIR/unresolved-review-threads.json" "$OUT_DIR/online-review-summary.json" "$OUT_DIR/pr-routing.json" "$OUT_DIR/pr-error.txt" "$REPO_NAME_WITH_OWNER" "$BASE_HOST" <<'PY'
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
routing_path = Path(sys.argv[9])
error_path = Path(sys.argv[10])
base_repo = sys.argv[11]
base_host = sys.argv[12]
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

def repo_name_with_owner(value: object, owner_value: object | None = None) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("nameWithOwner", "name_with_owner"):
        raw = value.get(key)
        if isinstance(raw, str) and "/" in raw:
            return raw
    name = value.get("name")
    owner = value.get("owner", owner_value)
    owner_login = ""
    if isinstance(owner, dict):
        owner_login = str(owner.get("login") or owner.get("name") or "")
    elif isinstance(owner, str):
        owner_login = owner
    if isinstance(name, str) and owner_login:
        return f"{owner_login}/{name}"
    return ""

head_repo = repo_name_with_owner(
    payload.get("headRepository"),
    payload.get("headRepositoryOwner"),
)
same_repo = bool(head_repo and base_repo and head_repo.lower() == base_repo.lower())
routing = {
    "base_repo": base_repo,
    "base_host": base_host,
    "base_identity_source": "pr_url",
    "pr_number": payload.get("number"),
    "pr_url": payload.get("url"),
    "base_ref": payload.get("baseRefName"),
    "base_oid": payload.get("baseRefOid"),
    "head_ref": payload.get("headRefName"),
    "head_oid": payload.get("headRefOid"),
    "head_repo": head_repo,
    "is_cross_repository": bool(payload.get("isCrossRepository")),
    "same_repo": same_repo,
    "local_checkout_required": True,
    "local_checkout_command": f"gh pr checkout {payload.get('url')}",
    "force_policy": "never pass --force to git or gh automatically; stop and ask the user with a rationale if a forced checkout appears necessary",
    "source_policy": "inspect local checkout; use gh only for PR metadata, diff, and review-thread evidence",
}
files_path.write_text("\n".join(sorted(files)) + ("\n" if files else ""), encoding="utf-8")
comments_path.write_text(json.dumps(payload.get("comments", []), indent=2) + "\n", encoding="utf-8")
reviews_path.write_text(json.dumps(payload.get("reviews", []), indent=2) + "\n", encoding="utf-8")
threads_path.write_text(json.dumps(threads, indent=2) + "\n", encoding="utf-8")
unresolved_path.write_text(json.dumps(unresolved, indent=2) + "\n", encoding="utf-8")
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
routing_path.write_text(json.dumps(routing, indent=2) + "\n", encoding="utf-8")
PY

git apply --stat <"$OUT_DIR/diff.patch" >"$OUT_DIR/diffstat.txt" 2>/dev/null || true
git apply --numstat <"$OUT_DIR/diff.patch" >"$OUT_DIR/numstat.txt" 2>/dev/null || true
: >"$OUT_DIR/untracked.txt"

if [[ "$CHECKOUT" == true ]]; then
  BASE_REF="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("base_ref") or "")
PY
)"
  BASE_OID="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("base_oid") or "")
PY
)"
  HEAD_REF="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("head_ref") or "")
PY
)"
  HEAD_OID="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("head_oid") or "")
PY
)"
  SAME_REPO="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print("true" if payload.get("same_repo") is True else "false")
PY
)"
  if ! python3 "$SCRIPT_DIR/select-git-remote.py" --expected-url "$PR_URL" >"$OUT_DIR/remote-selection.json" 2>"$OUT_DIR/remote-selection-error.txt"; then
    echo "missing-matching-git-remote-for-pr-base" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi
  REMOTE_NAME="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote"])' "$OUT_DIR/remote-selection.json")"
  REMOTE_URL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["remote_url"])' "$OUT_DIR/remote-selection.json")"
  printf '%s\n' "$REMOTE_NAME $REMOTE_URL" >"$OUT_DIR/remote.txt"
  if [[ -z "$BASE_REF" ]]; then
    echo "missing-pr-base-ref-for-target-refresh" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi
  if [[ -z "$BASE_OID" ]]; then
    echo "missing-pr-base-oid-for-target-refresh" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi
  if [[ -z "$HEAD_OID" ]]; then
    echo "missing-pr-head-oid-for-checkout" >"$OUT_DIR/pr-head-fetch-error.txt"
    exit 2
  fi

  BASE_REMOTE_REF="refs/remotes/${REMOTE_NAME}/${BASE_REF}"
  if ! git fetch --no-tags "$REMOTE_NAME" "$BASE_REF:$BASE_REMOTE_REF" >"$OUT_DIR/target-branch-fetch.stdout.txt" 2>"$OUT_DIR/target-branch-fetch.stderr.txt"; then
    echo "target-branch-fetch-failed:${REMOTE_NAME}/${BASE_REF}" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi
  BASE_LOCAL_HEAD="$(git rev-parse "$BASE_REMOTE_REF" 2>/dev/null || git rev-parse FETCH_HEAD 2>/dev/null || true)"
  if [[ -z "$BASE_LOCAL_HEAD" ]]; then
    echo "target-branch-fetch-head-missing:${REMOTE_NAME}/${BASE_REF}" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi
  python3 - "$OUT_DIR/target-branch.json" "$REMOTE_NAME" "$REMOTE_URL" "$BASE_REF" "$BASE_REMOTE_REF" "$BASE_LOCAL_HEAD" "$BASE_OID" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
remote = sys.argv[2]
remote_url = sys.argv[3]
base_ref = sys.argv[4]
remote_ref = sys.argv[5]
local_head = sys.argv[6]
expected_oid = sys.argv[7]
payload = {
    "status": "fetched",
    "remote": remote,
    "remote_url": remote_url,
    "base_ref": base_ref,
    "remote_ref": remote_ref,
    "local_head": local_head,
    "expected_base_oid": expected_oid,
    "base_matches_pr_metadata": bool(expected_oid and local_head == expected_oid),
    "command": f"git fetch --no-tags {remote} {base_ref}:{remote_ref}",
    "source_policy": "target branch is refreshed before PR conflict or review-item resolution",
}
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  if [[ "$BASE_LOCAL_HEAD" != "$BASE_OID" ]]; then
    echo "target-branch-oid-mismatch:${BASE_LOCAL_HEAD}:${BASE_OID}" >"$OUT_DIR/target-branch-fetch-error.txt"
    exit 2
  fi

  if [[ "$SAME_REPO" == true && -n "$HEAD_REF" ]]; then
    HEAD_REMOTE_REF="refs/remotes/${REMOTE_NAME}/${HEAD_REF}"
    if ! git fetch --no-tags "$REMOTE_NAME" "$HEAD_REF:$HEAD_REMOTE_REF" >"$OUT_DIR/pr-head-fetch.stdout.txt" 2>"$OUT_DIR/pr-head-fetch.stderr.txt"; then
      echo "pr-head-fetch-failed:${REMOTE_NAME}/${HEAD_REF}" >"$OUT_DIR/pr-head-fetch-error.txt"
      exit 2
    fi
    HEAD_FETCH_HEAD="$(git rev-parse "$HEAD_REMOTE_REF" 2>/dev/null || git rev-parse FETCH_HEAD 2>/dev/null || true)"
    python3 - "$OUT_DIR/pr-head-fetch.json" "$REMOTE_NAME" "$HEAD_REF" "$HEAD_REMOTE_REF" "$HEAD_FETCH_HEAD" "$HEAD_OID" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
remote = sys.argv[2]
head_ref = sys.argv[3]
remote_ref = sys.argv[4]
local_head = sys.argv[5]
expected_oid = sys.argv[6]
payload = {
    "status": "fetched",
    "remote": remote,
    "head_ref": head_ref,
    "remote_ref": remote_ref,
    "local_head": local_head,
    "expected_head_oid": expected_oid,
    "head_matches_pr_metadata": bool(expected_oid and local_head == expected_oid),
    "command": f"git fetch --no-tags {remote} {head_ref}:{remote_ref}",
    "source_policy": "PR branch is refreshed before local checkout and conflict analysis",
}
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
    if [[ -z "$HEAD_FETCH_HEAD" || "$HEAD_FETCH_HEAD" != "$HEAD_OID" ]]; then
      echo "pr-head-oid-mismatch:${HEAD_FETCH_HEAD:-missing}:${HEAD_OID}" >"$OUT_DIR/pr-head-fetch-error.txt"
      exit 2
    fi
  else
    python3 - "$OUT_DIR/pr-head-fetch.json" "$SAME_REPO" "$HEAD_REF" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
payload = {
    "status": "skipped",
    "same_repo": sys.argv[2] == "true",
    "head_ref": sys.argv[3],
    "reason": "cross-repository PR head is refreshed by gh pr checkout",
}
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
  fi

  DIRTY_TRACKED="$(git status --short --untracked-files=no 2>/dev/null || true)"
  if [[ -n "$DIRTY_TRACKED" ]]; then
    printf '%s\n' "$DIRTY_TRACKED" >"$OUT_DIR/local-checkout-error.txt"
    echo "dirty-tracked-worktree-before-pr-checkout" >>"$OUT_DIR/local-checkout-error.txt"
    exit 2
  fi

  if ! gh pr checkout "$PR_URL" >"$OUT_DIR/local-checkout.stdout.txt" 2>"$OUT_DIR/local-checkout.stderr.txt"; then
    echo "gh-pr-checkout-failed:${TARGET:-$PR_NUMBER}" >"$OUT_DIR/local-checkout-error.txt"
    echo "forced-checkout-not-attempted" >>"$OUT_DIR/local-checkout-error.txt"
    echo "if --force appears necessary, stop and ask the user with a concrete explanation before retrying" >>"$OUT_DIR/local-checkout-error.txt"
    exit 2
  fi

  LOCAL_BRANCH="$(git branch --show-current 2>/dev/null || true)"
  LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null || true)"
  EXPECTED_HEAD="$(python3 - "$OUT_DIR/pr-routing.json" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload.get("head_oid") or "")
PY
)"
  CHECKOUT_MATCHES=false
  if [[ -n "$LOCAL_HEAD" && -n "$EXPECTED_HEAD" && "$LOCAL_HEAD" == "$EXPECTED_HEAD" ]]; then
    CHECKOUT_MATCHES=true
  fi

  python3 - "$OUT_DIR/local-checkout.json" "$PR_NUMBER" "$PR_URL" "$LOCAL_BRANCH" "$LOCAL_HEAD" "$EXPECTED_HEAD" "$CHECKOUT_MATCHES" <<'PY'
import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
payload = {
    "status": "checked-out",
    "pr_number": int(sys.argv[2]),
    "pr_url": sys.argv[3],
    "local_branch": sys.argv[4],
    "local_head": sys.argv[5],
    "expected_head": sys.argv[6],
    "head_matches_pr": sys.argv[7] == "true",
    "command": f"gh pr checkout {sys.argv[3]}",
    "target_branch_artifact": "target-branch.json",
    "pr_head_fetch_artifact": "pr-head-fetch.json",
    "force_policy": "no --force was used; if a forced checkout is required, ask the user before running it",
    "source_policy": "local checkout is authoritative for code inspection and edits",
}
out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

  if [[ -n "$EXPECTED_HEAD" && "$CHECKOUT_MATCHES" != true ]]; then
    echo "local-checkout-head-mismatch" >"$OUT_DIR/local-checkout-error.txt"
    echo "forced-checkout-not-attempted" >>"$OUT_DIR/local-checkout-error.txt"
    echo "ask the user before any git or gh command with --force" >>"$OUT_DIR/local-checkout-error.txt"
    exit 2
  fi
fi
