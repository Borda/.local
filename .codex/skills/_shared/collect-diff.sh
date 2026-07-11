#!/usr/bin/env bash
set -euo pipefail

SCOPE="working-tree"
TARGET=""
OUT_DIR=""

usage() {
  cat <<'EOF'
Usage: collect-diff.sh --out DIR [--scope working-tree|path|commit] [--target VALUE]

Collect a Git diff context pack. working-tree is the default scope. path and
commit require --target. Outputs include status.txt, diff.patch, files.txt,
diffstat.txt, numstat.txt, and untracked.txt.

Options:
  --out DIR       Required artifact directory
  --scope SCOPE   working-tree, path, or commit
  --target VALUE  Path for path scope or revision for commit scope
  -h, --help      Show this help

Exit 0 means collection succeeded; exit 2 means invalid input.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --scope)
      SCOPE="$2"
      shift 2
      ;;
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
git status --short >"$OUT_DIR/status.txt"

case "$SCOPE" in
  working-tree)
    git diff HEAD >"$OUT_DIR/diff.patch"
    git diff --name-only HEAD >"$OUT_DIR/files.txt"
    git diff --stat HEAD >"$OUT_DIR/diffstat.txt"
    git diff --numstat HEAD >"$OUT_DIR/numstat.txt"
    git ls-files --others --exclude-standard >"$OUT_DIR/untracked.txt"
    ;;
  path)
    if [[ -z "$TARGET" ]]; then
      echo "missing-required:--target" >"$OUT_DIR/scope-error.txt"
      exit 2
    fi
    git diff HEAD -- "$TARGET" >"$OUT_DIR/diff.patch"
    git diff --name-only HEAD -- "$TARGET" >"$OUT_DIR/files.txt"
    git diff --stat HEAD -- "$TARGET" >"$OUT_DIR/diffstat.txt"
    git diff --numstat HEAD -- "$TARGET" >"$OUT_DIR/numstat.txt"
    git ls-files --others --exclude-standard -- "$TARGET" >"$OUT_DIR/untracked.txt"
    ;;
  commit)
    if [[ -z "$TARGET" ]]; then
      echo "missing-required:--target" >"$OUT_DIR/scope-error.txt"
      exit 2
    fi
    git diff "$TARGET" >"$OUT_DIR/diff.patch"
    git diff --name-only "$TARGET" >"$OUT_DIR/files.txt"
    git diff --stat "$TARGET" >"$OUT_DIR/diffstat.txt"
    git diff --numstat "$TARGET" >"$OUT_DIR/numstat.txt"
    : >"$OUT_DIR/untracked.txt"
    ;;
  *)
    echo "invalid-scope:$SCOPE" >"$OUT_DIR/scope-error.txt"
    exit 2
    ;;
esac
