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
# Target repo MUST own its .git (bench uses git provenance + patch archive/restore).
# Do NOT point this at .sandbox/pytorch-lightning-master — it has no .git and git
# calls there resolve to the parent Borda repo.
set -euo pipefail

REPO="${REPO:-$HOME/Workspace/pytorch-lightning-master}"
MODE="${1:-all}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d "$REPO/.git" ]; then
  echo "ERROR: \$REPO ($REPO) has no .git — bench needs a real clone. Set REPO to a git clone." >&2
  exit 1
fi
echo "→ target repo: $REPO ($(git -C "$REPO" rev-parse --short HEAD))"

refresh() {
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

full() {
  echo "== 1. QUERY (no LLM) — gates the index =="
  python benchmarks/run-codemap-cli.py --repo-path "$REPO" --report

  echo "== 2. REAL-CODEBASE (LLM) — 54 tasks x 2 arms, per tier =="
  for m in haiku sonnet opus; do
    echo "   -- model: $m --"
    python benchmarks/run-codemap-bench.py --repo-path "$REPO" --run-all --model "$m"
  done

  echo "== 3. AGENTIC (LLM) — 16 tasks x 4 arms x 3 tiers =="
  python benchmarks/run-codemap-agentic.py "$REPO" --run-all --report
}

case "$MODE" in
  refresh) refresh ;;
  smoke)   refresh; smoke ;;
  full)    refresh; full ;;
  all)     refresh; smoke; full ;;
  *) echo "unknown mode '$MODE' (use: refresh | smoke | full | all)" >&2; exit 2 ;;
esac

echo "→ done. Results in benchmarks/results/"
