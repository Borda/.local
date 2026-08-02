#!/usr/bin/env bash
# Provider-neutral benchmark batch entrypoint.
#
# Usage:
#   bash benchmarks/run-all.sh smoke   # fail-fast Claude + Codex smoke only
#   bash benchmarks/run-all.sh claude  # fail-fast Claude smoke, then full Claude batches
#   bash benchmarks/run-all.sh codex --dry-run  # smoke + exact 165-cell Codex plan, no model
#   bash benchmarks/run-all.sh codex   # fail-fast Codex smoke, then full 55-task A/B/C study
#
# The Codex mode fails before setup unless the caller supplies the exact active
# plain/CLI/skill manifest SHA-256, a private auth source, a new run directory, and
# the manifest-locked complete-run wall-clock limit.
# No mode runs when the argument is missing or unknown. This entrypoint
# reconstructs a missing index and accepts it only when normalization reproduces
# the reviewed byte hash exactly.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PL_TAG="2.6.5"
PL_URL="${PL_URL:-https://github.com/Lightning-AI/pytorch-lightning.git}"
MANAGED_REPO="/private/tmp/codemap-provider-parity-pl-2.6.5"
REPO="${REPO:-$MANAGED_REPO}"
INDEX_PATH="$REPO/.cache/codemap/$(basename "$REPO").json"
MODE="${1:-}"
CODEX_DRY_RUN=false
MANIFEST_PATH="$ROOT/benchmarks/manifests/codex-integration.json"
MANIFEST_CHECKER="$ROOT/benchmarks/build-codex-integration-manifest.py"
CODEMAP_BIN="${CODEMAP_BIN:-$ROOT/plugins/codemap-py/bin/codemap-py}"
INDEX_PREPARER="$ROOT/benchmarks/prepare-codex-index.py"
LOCKED_INDEX_SHA="b0e4a5c9ae7da6503cf1e831d39c73abac6eb696be849fc0080f61bce6c1f045"

usage() {
  echo "usage: bash benchmarks/run-all.sh {smoke | claude | codex [--dry-run]}" >&2
}

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  usage
  exit 2
fi
case "$MODE" in
  smoke | claude)
    if [ "$#" -ne 1 ]; then
      usage
      exit 2
    fi
    ;;
  codex)
    if [ "$#" -eq 2 ]; then
      if [ "$2" != "--dry-run" ]; then
        usage
        exit 2
      fi
      CODEX_DRY_RUN=true
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac

cd "$ROOT"

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    echo "ERROR: shasum or sha256sum is required to validate frozen evidence." >&2
    return 1
  fi
}

validate_generated_manifest() {
  echo "== CHECK generated Codex integration manifest (no model) =="
  python3 "$MANIFEST_CHECKER" --check
}

ensure_repo() {
  # Only the canonical benchmark target is reset. An overridden REPO is never mutated.
  if [ "$REPO" = "$MANAGED_REPO" ]; then
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
  validate_generated_manifest
  ensure_repo
  echo "== PREPARE frozen parity index =="
  if [ ! -f "$INDEX_PATH" ]; then
    echo "→ build missing index from the locked target"
    CODEMAP_PYTHON="/opt/homebrew/bin/python3.11" "$CODEMAP_BIN" index --root "$REPO"
    index_sha="$(sha256_file "$INDEX_PATH")"
    if [ "$index_sha" != "$LOCKED_INDEX_SHA" ]; then
      python3 "$INDEX_PREPARER" \
        --index-path "$INDEX_PATH" \
        --source-root "$REPO" \
        --manifest-path "$MANIFEST_PATH"
    fi
  fi
  index_sha="$(sha256_file "$INDEX_PATH")"
  if [ "$index_sha" != "$LOCKED_INDEX_SHA" ]; then
    echo "ERROR: locked parity index SHA-256 mismatch: expected $LOCKED_INDEX_SHA, got $index_sha" >&2
    exit 1
  fi
  echo "→ locked index: $INDEX_PATH ($index_sha)"
}

query_check() {
  echo "== QUERY (no model) =="
  python3 benchmarks/run-codemap-cli.py --repo-path "$REPO"
}

validate_codex_cli() {
  expected_codex_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["codex_cli"]["version"])' "$MANIFEST_PATH")"
  actual_codex_version="$(command codex --version)"
  if [ "$actual_codex_version" != "$expected_codex_version" ]; then
    echo "ERROR: Codex CLI identity mismatch: expected $expected_codex_version, got $actual_codex_version" >&2
    exit 1
  fi
  echo "→ Codex CLI: $actual_codex_version"
}

claude_preflight() {
  echo "== CLAUDE PREFLIGHT (no model) =="
  python3 benchmarks/run-claude-structural.py \
    --repo-path "$REPO" \
    --tasks "['FN-02']" \
    --arm all \
    --model haiku \
    --dry-run
  python3 benchmarks/run-claude-agentic.py \
    --repo-path "$REPO" \
    --tasks "['BA-01']" \
    --arm A_plain \
    --model haiku \
    --dry-run
}

codex_smoke_preflight() {
  echo "== CODEX PREFLIGHT (no model) =="
  validate_codex_cli
  python3 benchmarks/run-codex-structural.py \
    --repo-path "$REPO" \
    --tasks-path benchmarks/suites/tasks-bench.json \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model gpt-5.6-luna \
    --reasoning-effort high \
    --task-id FN-02 \
    --arm all \
    --dry-run
}

smoke() {
  query_check
  claude_preflight
  codex_smoke_preflight
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
    _step_full python3 benchmarks/run-claude-structural.py \
      --repo-path "$REPO" \
      --run-all \
      --model "$model"
  done

  echo "== CLAUDE AGENTIC (paid model runs) =="
  _step_full python3 benchmarks/run-claude-agentic.py "$REPO" --run-all --report
}

require_codex_paid_inputs() {
  if [ ! -f "$MANIFEST_PATH" ]; then
    echo "ERROR: active provider-parity manifest is missing: $MANIFEST_PATH" >&2
    exit 2
  fi
  active_manifest_sha="$(sha256_file "$MANIFEST_PATH")"
  approved_wall_clock="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["execution_controls"]["confirmatory_max_wall_clock_seconds"])' "$MANIFEST_PATH")"
  if [ "${CODEX_PAID_APPROVAL:-}" != "$active_manifest_sha" ]; then
    echo "ERROR: paid Codex mode requires CODEX_PAID_APPROVAL=$active_manifest_sha" >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_AUTH_SOURCE:-}" ] || [ ! -f "$CODEX_AUTH_SOURCE" ]; then
    echo "ERROR: paid Codex mode requires CODEX_AUTH_SOURCE pointing to a private auth.json." >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_RUN_DIR:-}" ]; then
    echo "ERROR: paid Codex mode requires a new CODEX_RUN_DIR." >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_MAX_WALL_CLOCK_SECONDS:-}" ]; then
    echo "ERROR: paid Codex mode requires CODEX_MAX_WALL_CLOCK_SECONDS." >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ "$CODEX_MAX_WALL_CLOCK_SECONDS" != "$approved_wall_clock" ]; then
    echo "ERROR: CODEX_MAX_WALL_CLOCK_SECONDS must equal the manifest lock: $approved_wall_clock" >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ -e "$CODEX_RUN_DIR" ]; then
    echo "ERROR: CODEX_RUN_DIR already exists: $CODEX_RUN_DIR" >&2
    print_codex_paid_guidance
    exit 2
  fi
}

print_codex_paid_guidance() {
  run_dir_hint="benchmarks/results/codex-integration-$(date -u +%Y%m%dT%H%M%SZ)"
  cat >&2 <<EOF

Review the exact no-model plan first:
  bash benchmarks/run-all.sh codex --dry-run

Then launch the paid study with one manifest-bound command:
  CODEX_PAID_APPROVAL=$active_manifest_sha \\
  CODEX_AUTH_SOURCE="\$HOME/.codex/auth.json" \\
  CODEX_RUN_DIR="$run_dir_hint" \\
  CODEX_MAX_WALL_CLOCK_SECONDS=$approved_wall_clock \\
    bash benchmarks/run-all.sh codex

The command itself records paid authorization for this exact manifest; no separate chat approval is needed when you run it. CODEX_RUN_DIR must not already exist. Review benchmarks/manifests/codex-integration.md for the locked scope.
EOF
}

configure_codex_plan() {
  active_manifest_sha="$(sha256_file "$MANIFEST_PATH")"
  confirmatory_wall_clock="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["execution_controls"]["confirmatory_max_wall_clock_seconds"])' "$MANIFEST_PATH")"
  confirmatory_repetitions="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["preregistered_cells"]["confirmatory_repetitions"])' "$MANIFEST_PATH")"
  confirmatory_task_args=()
  while IFS= read -r task_id; do
    confirmatory_task_args+=(--task-id "$task_id")
  done < <(python3 -c 'import json,sys; print(*json.load(open(sys.argv[1]))["preregistered_cells"]["structural_execution_task_ids"], sep="\n")' "$MANIFEST_PATH")
  task_count=$((${#confirmatory_task_args[@]} / 2))
  planned_cells=$((task_count * confirmatory_repetitions * 3))
  echo "== CODEX STRUCTURAL STUDY =="
  echo "→ design: $planned_cells cells ($task_count tasks × $confirmatory_repetitions run × 3 arms)"
  echo "→ analysis: 45 independently scored headline tasks; 10 diagnostic tasks reported separately"
  echo "→ model: gpt-5.6-luna; reasoning effort: high"
  echo "→ limits: 600 seconds per coordinate; $confirmatory_wall_clock seconds complete run"
  echo "→ manifest: $MANIFEST_PATH ($active_manifest_sha)"
  common_args=(
    --repo-path "$REPO" \
    --tasks-path benchmarks/suites/tasks-bench.json \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model gpt-5.6-luna \
    --reasoning-effort high \
    "${confirmatory_task_args[@]}" \
    --repetitions "$confirmatory_repetitions" \
    --arm all \
    --max-wall-clock-seconds "$confirmatory_wall_clock"
  )
}

run_codex_plan() {
  # Paid execution wraps this function in a tee pipeline. Explicit propagation
  # prevents the full plan or paid cells from starting after a failed smoke.
  query_check || return "$?"
  codex_smoke_preflight || return "$?"
  configure_codex_plan || return "$?"
  echo "== CODEX CONFIRMATORY A/B/C PREFLIGHT (no model) =="
  python3 benchmarks/run-codex-structural.py "${common_args[@]}" --dry-run || return "$?"
}

run_codex_study() {
  run_codex_plan || return "$?"
  echo "== CODEX CONFIRMATORY A/B/C STUDY (paid model runs) =="
  python3 benchmarks/run-codex-structural.py \
    "${common_args[@]}" \
    --auth-source "$CODEX_AUTH_SOURCE" \
    --output-path "$CODEX_RUN_DIR/telemetry.jsonl" \
    --metadata-path "$CODEX_RUN_DIR/run-metadata.json"
}

run_codex_with_artifacts() {
  # Keep the artifact log lossless; the structural runner renders only the console stream.
  if run_codex_study 2>&1 | tee "$CODEX_RUN_DIR/run.log" | python3 "$ROOT/benchmarks/run-codex-structural.py" --render-results --hide-plan; then
    run_status=0
  else
    run_status=$?
  fi
  checksum_path="$CODEX_RUN_DIR/checksums.sha256"
  : > "$checksum_path"
  for artifact in run.log telemetry.jsonl telemetry-canonical.jsonl run-metadata.json; do
    if [ -f "$CODEX_RUN_DIR/$artifact" ]; then
      shasum -a 256 "$CODEX_RUN_DIR/$artifact" >> "$checksum_path"
    fi
  done
  echo "→ artifact checksums: $checksum_path"
  return "$run_status"
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
    if [ "$CODEX_DRY_RUN" = true ]; then
      prepare_locked_inputs
      run_codex_plan
    else
      require_codex_paid_inputs
      prepare_locked_inputs
      mkdir -p "$CODEX_RUN_DIR"
      run_codex_with_artifacts
    fi
    ;;
esac

echo "→ done. Results in benchmarks/results/"
