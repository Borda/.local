#!/usr/bin/env bash
# Full codemap benchmark run — query + real-codebase + agentic, all model tiers.
#
# Usage:
#   bash benchmarks/run-all.sh              # refresh index, smoke check, then the full suite
#   bash benchmarks/run-all.sh smoke        # refresh index + smoke check only (cheap, no big spend)
#   bash benchmarks/run-all.sh full         # refresh index, skip smoke, go straight to the full suite
#   bash benchmarks/run-all.sh refresh      # rebuild the target codemap index only
#   REPO=/path/to/clone bash benchmarks/run-all.sh   # override the target repo
#
# Target repo is PINNED to a git tag ($PL_TAG) and lives in-project at .sandbox/pytorch-lightning
# — a real clone that owns its .git (bench needs git provenance + patch archive/restore). It is
# HARD-RESET to the tag before every run so drift and leftover patch-task edits never leak across
# runs. Override with REPO=/path/to/clone (must own .git; only the managed .sandbox clone is auto-
# reset — an overridden REPO is used as-is, never force-reset, to protect your working tree).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PL_TAG="${PL_TAG:-2.6.5}"
PL_URL="${PL_URL:-https://github.com/Lightning-AI/pytorch-lightning.git}"
REPO="${REPO:-$ROOT/.sandbox/pytorch-lightning}"
MODE="${1:-all}"

ensure_repo() {
  # Clone the pinned tag if the managed sandbox clone is missing, then hard-reset it to the tag so
  # every run starts from a pristine tree. Only the default .sandbox clone is managed; a
  # user-overridden REPO is checked for .git but never reset (protects uncommitted work).
  if [ "$REPO" = "$ROOT/.sandbox/pytorch-lightning" ]; then
    if [ ! -d "$REPO/.git" ]; then
      echo "== clone pytorch-lightning @ $PL_TAG into .sandbox =="
      rm -rf "$REPO"
      git clone --depth 1 --branch "$PL_TAG" "$PL_URL" "$REPO"
    fi
    echo "== reset .sandbox clone to $PL_TAG (pristine baseline) =="
    git -C "$REPO" reset --hard "$PL_TAG"
    git -C "$REPO" clean -fd
  elif [ ! -d "$REPO/.git" ]; then
    echo "ERROR: \$REPO ($REPO) has no .git — bench needs a real clone at tag $PL_TAG." >&2
    exit 1
  fi
  echo "→ target repo: $REPO ($(git -C "$REPO" rev-parse --short HEAD))"
}

refresh() {
  ensure_repo
  echo "== 0. REFRESH codemap index (full rebuild) =="
  local cm
  cm="$(ls -td "$HOME"/.claude/plugins/cache/borda-ai-rig/codemap-py/*/bin/codemap-py 2>/dev/null | head -1)"
  if [ -z "$cm" ]; then
    echo "ERROR: codemap-py bin not found under ~/.claude/plugins/cache/" >&2
    exit 1
  fi
  "$cm" index --root "$REPO"
}

# Hard-error markers a healthy codemap run never prints. The runners exit 0 even when a
# codemap run errors (e.g. the /codemap:query skill returns <tool_use_error>), so `set -e`
# alone will NOT catch it — we scan the captured smoke output for these instead.
_SMOKE_ERROR_RE='codemap_skill_errored|skill_blocked|_errored|SandboxError|sandbox_error|Traceback \(most recent call last\)|^ERROR:'

smoke() {
  echo "== SMOKE (cheap harness check) =="
  local log
  log="$(mktemp "${TMPDIR:-/tmp}/codemap-smoke-XXXXXX")"  # tmpdir-exempt: mktemp template already unique
  local crashed=0

  # Run each check; tee so the user still sees live output, capture for post-scan.
  # `if ! …` suppresses errexit so a crash is recorded, not aborted mid-scan.
  _step() { echo "→ $*"; if ! "$@" 2>&1 | tee -a "$log"; then crashed=1; fi; }
  _step python benchmarks/run-codemap-cli.py --repo-path "$REPO"
  _step python benchmarks/run-codemap-bench.py --repo-path "$REPO" --tasks "['SE-01']" --arm codemap --model haiku
  _step python benchmarks/run-codemap-agentic.py "$REPO" --tasks "['BA-01']" --model haiku

  # Gate: hold the full suite if any codemap run crashed or printed a hard-error marker.
  if [ "$crashed" -ne 0 ] || grep -Eq "$_SMOKE_ERROR_RE" "$log"; then
    echo "" >&2
    echo "! BLOCKED — smoke found errored/crashed codemap runs; NOT proceeding to the full suite." >&2
    echo "  Matched markers:" >&2
    grep -En "$_SMOKE_ERROR_RE" "$log" | sed 's/^/    /' >&2 || true
    echo "  Full smoke log: $log" >&2
    exit 1
  fi
  rm -f "$log"
  echo "→ smoke OK — codemap path healthy"
}

# In the full suite one runner crashing (or exiting non-zero on failed runs) must NOT abort the
# whole batch — later tiers/steps are independent and worth finishing. Each step is wrapped so its
# failure logs a warning and continues. Only smoke() hard-gates (it decides whether full runs at all).
_step_full() {  # $@ = command; run it, warn-and-continue on non-zero instead of aborting under set -e
  "$@" || echo "⚠ step exited $? — continuing the full suite: $*" >&2
}

full() {
  echo "== 1. QUERY (no LLM) — gates the index =="
  _step_full python benchmarks/run-codemap-cli.py --repo-path "$REPO" --report

  echo "== 2. REAL-CODEBASE (LLM) — 54 tasks x 2 arms, per tier =="
  for m in haiku sonnet opus; do
    printf '\n\n'
    echo "################################################################"
    echo "##  REAL-CODEBASE  ·  model tier: $m"
    echo "################################################################"
    _step_full python benchmarks/run-codemap-bench.py --repo-path "$REPO" --run-all --model "$m"
  done

  echo "== 3. AGENTIC (LLM) — 16 tasks x 4 arms x 3 tiers =="
  _step_full python benchmarks/run-codemap-agentic.py "$REPO" --run-all --report
}

case "$MODE" in
  refresh) refresh ;;
  smoke)   refresh; smoke ;;
  full)    refresh; full ;;
  all)     refresh; smoke; full ;;
  *) echo "unknown mode '$MODE' (use: refresh | smoke | full | all)" >&2; exit 2 ;;
esac

echo "→ done. Results in benchmarks/results/"
