#!/usr/bin/env bash
# Provider-neutral benchmark batch entrypoint.
#
# Usage:
#   bash benchmarks/run-all.sh smoke   # validate lock + query + no-model Claude/Codex preflights
#   bash benchmarks/run-all.sh claude  # validate lock + preflight + full Claude batches
#   bash benchmarks/run-all.sh codex   # validate lock + preregistered paid Codex FN-02 A/B/C smoke
#
# The Codex mode fails before setup unless the caller supplies the exact r6
# approval token, a private auth source, and a new output path. No mode runs
# when the argument is missing or unknown. This entrypoint never rebuilds the
# frozen parity index because scanner timestamps would invalidate its byte hash.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PL_TAG="2.6.5"
PL_URL="${PL_URL:-https://github.com/Lightning-AI/pytorch-lightning.git}"
REPO="${REPO:-$ROOT/.sandbox/pytorch-lightning}"
INDEX_PATH="$REPO/.cache/codemap/$(basename "$REPO").json"
MODE="${1:-}"
R6_REVISION="codemap-provider-parity-v1-b0-r6"
LOCKED_INDEX_SHA="b0e4a5c9ae7da6503cf1e831d39c73abac6eb696be849fc0080f61bce6c1f045"

usage() {
  echo "usage: bash benchmarks/run-all.sh {smoke | claude | codex}" >&2
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi
case "$MODE" in
  smoke | claude | codex) ;;
  *)
    usage
    exit 2
    ;;
esac

cd "$ROOT"

ensure_repo() {
  # Only the managed sandbox is reset. An overridden REPO is never mutated.
  if [ "$REPO" = "$ROOT/.sandbox/pytorch-lightning" ]; then
    if [ ! -d "$REPO/.git" ]; then
      echo "== clone pytorch-lightning @ $PL_TAG into .sandbox =="
      rm -rf "$REPO"
      git clone --depth 1 --branch "$PL_TAG" "$PL_URL" "$REPO"
    fi
    echo "== reset .sandbox clone to $PL_TAG (pristine baseline) =="
    git -C "$REPO" reset --hard "$PL_TAG"
    git -C "$REPO" clean -fd
  elif ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: \$REPO ($REPO) is not a Git worktree at tag $PL_TAG." >&2
    exit 1
  fi
  echo "→ target repo: $REPO ($(git -C "$REPO" rev-parse --short HEAD))"
}

prepare_locked_inputs() {
  ensure_repo
  echo "== VALIDATE frozen parity index =="
  if [ ! -f "$INDEX_PATH" ]; then
    echo "ERROR: locked parity index is missing: $INDEX_PATH" >&2
    exit 1
  fi
  if command -v shasum >/dev/null 2>&1; then
    index_sha="$(shasum -a 256 "$INDEX_PATH" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    index_sha="$(sha256sum "$INDEX_PATH" | awk '{print $1}')"
  else
    echo "ERROR: shasum or sha256sum is required to validate the locked parity index." >&2
    exit 1
  fi
  if [ "$index_sha" != "$LOCKED_INDEX_SHA" ]; then
    echo "ERROR: locked parity index SHA-256 mismatch: expected $LOCKED_INDEX_SHA, got $index_sha" >&2
    exit 1
  fi
  echo "→ locked index: $INDEX_PATH ($index_sha)"
}

query_check() {
  echo "== QUERY (no model) =="
  python benchmarks/run-cli.py --repo-path "$REPO"
}

claude_preflight() {
  echo "== CLAUDE PREFLIGHT (no model) =="
  python benchmarks/run-claude-structural.py \
    --repo-path "$REPO" \
    --tasks "['FN-02']" \
    --arm all \
    --model haiku \
    --dry-run
  python benchmarks/run-claude-agentic.py \
    --repo-path "$REPO" \
    --tasks "['BA-01']" \
    --arm A_plain \
    --model haiku \
    --dry-run
}

codex_preflight() {
  echo "== CODEX PREFLIGHT (no model) =="
  python benchmarks/run-codex-structural.py \
    --repo-path "$REPO" \
    --tasks-path benchmarks/suites/tasks-bench.json \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --model gpt-5.6-luna \
    --task-id FN-02 \
    --arm all \
    --dry-run
}

smoke() {
  query_check
  claude_preflight
  codex_preflight
  echo "→ smoke OK: query command completed; Claude/Codex no-model preflights passed"
}

_step_full() {
  # Paid Claude cells are independent; preserve later evidence after one failure.
  "$@" || echo "⚠ step exited $?; continuing the Claude batch: $*" >&2
}

claude() {
  query_check
  claude_preflight
  echo "== CLAUDE STRUCTURAL (paid model runs) =="
  for model in haiku sonnet opus; do
    _step_full python benchmarks/run-claude-structural.py \
      --repo-path "$REPO" \
      --run-all \
      --model "$model"
  done

  echo "== CLAUDE AGENTIC (paid model runs) =="
  _step_full python benchmarks/run-claude-agentic.py "$REPO" --run-all --report
}

require_codex_paid_inputs() {
  if [ "${CODEX_PAID_APPROVAL:-}" != "$R6_REVISION" ]; then
    echo "ERROR: paid Codex mode requires CODEX_PAID_APPROVAL=$R6_REVISION" >&2
    exit 2
  fi
  if [ -z "${CODEX_AUTH_SOURCE:-}" ] || [ ! -f "$CODEX_AUTH_SOURCE" ]; then
    echo "ERROR: paid Codex mode requires CODEX_AUTH_SOURCE pointing to a private auth.json." >&2
    exit 2
  fi
  if [ -z "${CODEX_OUTPUT_PATH:-}" ]; then
    echo "ERROR: paid Codex mode requires a new CODEX_OUTPUT_PATH." >&2
    exit 2
  fi
  if [ -e "$CODEX_OUTPUT_PATH" ]; then
    echo "ERROR: CODEX_OUTPUT_PATH already exists: $CODEX_OUTPUT_PATH" >&2
    exit 2
  fi
}

codex() {
  query_check
  codex_preflight
  echo "== CODEX FN-02 r6 A/B/C SMOKE (paid model runs) =="
  python benchmarks/run-codex-structural.py \
    --repo-path "$REPO" \
    --tasks-path benchmarks/suites/tasks-bench.json \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --auth-source "$CODEX_AUTH_SOURCE" \
    --model gpt-5.6-luna \
    --task-id FN-02 \
    --arm all \
    --output-path "$CODEX_OUTPUT_PATH"
}

case "$MODE" in
  smoke)
    prepare_locked_inputs
    smoke
    ;;
  claude)
    prepare_locked_inputs
    claude
    ;;
  codex)
    require_codex_paid_inputs
    prepare_locked_inputs
    codex
    ;;
esac

echo "→ done. Results in benchmarks/results/"
