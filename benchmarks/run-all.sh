#!/usr/bin/env bash
# Provider-neutral benchmark batch entrypoint.
#
# Usage:
#   bash benchmarks/run-all.sh smoke   # fail-fast Claude + Codex smoke only
#   bash benchmarks/run-all.sh claude  # fail-fast Claude smoke, then full Claude batches
#   bash benchmarks/run-all.sh codex --dry-run  # smoke + exact 165-cell Codex plan, no model
#   bash benchmarks/run-all.sh codex   # fail-fast Codex smoke, then full 55-task A/B/C study
#   bash benchmarks/run-all.sh codex --tasks=DI,GR [--dry-run]  # selected, nonpoolable task study
#
# The Codex mode fails before setup unless the caller supplies the exact active
# plain/CLI/skill manifest SHA-256, a private auth source, a new run directory, and
# the manifest-locked complete-run wall-clock limit.
# No mode runs when the argument is missing or unknown. This entrypoint
# reconstructs a missing index and accepts it only when normalization reproduces
# the reviewed byte hash exactly.
set -euo pipefail

ROOT="${CODEX_LAUNCHER_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PL_TAG="2.6.5"
PL_URL="${PL_URL:-https://github.com/Lightning-AI/pytorch-lightning.git}"
MANAGED_REPO="/private/tmp/codemap-provider-parity-pl-2.6.5"
REPO="${REPO:-$MANAGED_REPO}"
INDEX_PATH="$REPO/.cache/codemap/$(basename "$REPO").json"
MODE="${1:-}"
CODEX_DRY_RUN=false
CODEX_TASKS=""
CODEX_SELECTION_SCOPE_SHA=""
CODEX_SELECTION_REPETITIONS=""
CODEX_SELECTION_WALL_CLOCK=""
CODEX_SELECTION_TASK_IDS=()
MANIFEST_PATH="$ROOT/benchmarks/manifests/codex-integration.json"
METHODOLOGY_PATH="$ROOT/benchmarks/manifests/provider-parity-methodology.json"
MANIFEST_CHECKER="$ROOT/benchmarks/build-codex-integration-manifest.py"
METHODOLOGY_CHECKER="$ROOT/benchmarks/build-provider-parity-methodology-manifest.py"
CODEMAP_BIN="${CODEMAP_BIN:-$ROOT/plugins/codemap-py/bin/codemap-py}"
INDEX_PREPARER="$ROOT/benchmarks/prepare-codex-index.py"
SCHEMA_PATH="$ROOT/plugins/codemap-py/src/codemap_py/schema.py"
LOCKED_INDEX_SHA=""
LOCKED_INDEX_SCAN_VERSION=""

usage() {
  echo "usage: bash benchmarks/run-all.sh {smoke | claude | codex [--dry-run] [--tasks=TASK[,TASK...]]}" >&2
}

if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
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
    for option in "${@:2}"; do
      case "$option" in
        --dry-run)
          if [ "$CODEX_DRY_RUN" = true ]; then
            usage
            exit 2
          fi
          CODEX_DRY_RUN=true
          ;;
        --tasks=*)
          if [ -n "$CODEX_TASKS" ]; then
            usage
            exit 2
          fi
          CODEX_TASKS="${option#--tasks=}"
          if [ -z "$CODEX_TASKS" ]; then
            usage
            exit 2
          fi
          ;;
        *)
          usage
          exit 2
          ;;
      esac
    done
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
  python3 "$METHODOLOGY_CHECKER" --check
  python3 "$MANIFEST_CHECKER" --check
}

load_index_contract() {
  local contract_json
  if ! contract_json="$(python3 "$INDEX_PREPARER" \
    --manifest-path "$MANIFEST_PATH" \
    --methodology-path "$METHODOLOGY_PATH" \
    --schema-path "$SCHEMA_PATH" \
    --print-contract 2>&1)"; then
    echo "ERROR: active index contract validation failed:" >&2
    echo "$contract_json" >&2
    exit 1
  fi
  LOCKED_INDEX_SHA="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["raw_sha256"])' <<<"$contract_json")"
  LOCKED_INDEX_SCAN_VERSION="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["scan_version"])' <<<"$contract_json")"
  echo "→ index contract: scan_version=$LOCKED_INDEX_SCAN_VERSION sha256=$LOCKED_INDEX_SHA"
}

verify_current_index() {
  local verification
  if verification="$(python3 "$INDEX_PREPARER" \
    --index-path "$INDEX_PATH" \
    --manifest-path "$MANIFEST_PATH" \
    --methodology-path "$METHODOLOGY_PATH" \
    --schema-path "$SCHEMA_PATH" \
    --require-hash \
    --verify 2>&1)"; then
    echo "$verification"
    return 0
  fi
  echo "⚠ existing index failed the active contract; rebuilding: $verification" >&2
  return 1
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
  load_index_contract
  ensure_repo
  echo "== PREPARE frozen parity index =="
  if [ ! -f "$INDEX_PATH" ] || ! verify_current_index; then
    if [ -f "$INDEX_PATH" ]; then
      echo "→ existing index is stale or schema-incompatible; rebuild from the locked target"
    else
      echo "→ build missing index from the locked target"
    fi
    CODEMAP_PYTHON="/opt/homebrew/bin/python3.11" "$CODEMAP_BIN" index --root "$REPO"
  fi
  index_sha="$(sha256_file "$INDEX_PATH")"
  if [ "$index_sha" != "$LOCKED_INDEX_SHA" ]; then
    python3 "$INDEX_PREPARER" \
      --index-path "$INDEX_PATH" \
      --source-root "$REPO" \
      --manifest-path "$MANIFEST_PATH" \
      --methodology-path "$METHODOLOGY_PATH" \
      --schema-path "$SCHEMA_PATH"
  fi
  if ! verify_current_index; then
    echo "ERROR: rebuilt index failed the active schema contract (scan_version=$LOCKED_INDEX_SCAN_VERSION)" >&2
    exit 1
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
  local legend_arg="${1:-}"
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
    --dry-run \
    $legend_arg
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
  if [ -n "$CODEX_TASKS" ]; then
    ensure_codex_scope_resolved
    approved_approval="$CODEX_SELECTION_SCOPE_SHA"
    approved_wall_clock="$CODEX_SELECTION_WALL_CLOCK"
  else
    approved_approval="$active_manifest_sha"
    approved_wall_clock="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["execution_controls"]["confirmatory_max_wall_clock_seconds"])' "$MANIFEST_PATH")"
  fi
  if [ "${CODEX_PAID_APPROVAL:-}" != "$approved_approval" ]; then
    echo "ERROR: paid Codex mode requires CODEX_PAID_APPROVAL=$approved_approval" >&2
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
  if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" = "1" ]; then
    expected_launcher="$CODEX_RUN_DIR/.launcher/run-all.sh"
    if [ "$0" != "$expected_launcher" ] || [ "${CODEX_INVOCATION_LAUNCHER:-}" != "$expected_launcher" ]; then
      echo "ERROR: paid Codex mode is not executing its private launcher snapshot." >&2
      exit 2
    fi
    if [ "$(sha256_file "$expected_launcher")" != "${CODEX_LAUNCHER_SHA256:-}" ]; then
      echo "ERROR: paid Codex launcher snapshot changed before execution." >&2
      exit 2
    fi
  elif [ -e "$CODEX_RUN_DIR" ]; then
    echo "ERROR: CODEX_RUN_DIR already exists: $CODEX_RUN_DIR" >&2
    print_codex_paid_guidance
    exit 2
  fi
}

exec_codex_launcher_snapshot() {
  launcher_dir="$CODEX_RUN_DIR/.launcher"
  launcher_snapshot="$launcher_dir/run-all.sh"
  mkdir -p "$launcher_dir"
  cp "$ROOT/benchmarks/run-all.sh" "$launcher_snapshot"
  chmod 500 "$launcher_snapshot"
  export CODEX_LAUNCHER_ROOT="$ROOT"
  export CODEX_INVOCATION_LAUNCHER="$launcher_snapshot"
  export CODEX_LAUNCHER_SHA256="$(sha256_file "$launcher_snapshot")"
  export CODEX_LAUNCHER_SNAPSHOT_ACTIVE=1
  exec /bin/bash "$launcher_snapshot" "$@"
}

print_codex_paid_guidance() {
  if [ -n "$CODEX_TASKS" ]; then
    ensure_codex_scope_resolved
    run_dir_hint="benchmarks/results/codex-integration-selected-$(date -u +%Y%m%dT%H%M%SZ)"
    mode_args=" --tasks=$CODEX_TASKS"
    approval_hint="$CODEX_SELECTION_SCOPE_SHA"
    scope_guidance="Selected task study: $CODEX_TASKS; $CODEX_SELECTION_REPETITIONS repetitions × A/B/C = $(( ${#CODEX_SELECTION_TASK_IDS[@]} * CODEX_SELECTION_REPETITIONS * 3 )) cells; 600 seconds per coordinate; $CODEX_SELECTION_WALL_CLOCK seconds complete run. It is nonpoolable."
  else
    run_dir_hint="benchmarks/results/codex-integration-$(date -u +%Y%m%dT%H%M%SZ)"
    mode_args=""
    approval_hint="$active_manifest_sha"
    scope_guidance=""
  fi
  cat >&2 <<EOF

Review the exact no-model plan first:
  bash benchmarks/run-all.sh codex${mode_args} --dry-run

Then launch the paid study with one manifest-bound command:
  CODEX_PAID_APPROVAL=$approval_hint \\
  CODEX_AUTH_SOURCE="\$HOME/.codex/auth.json" \\
  CODEX_RUN_DIR="$run_dir_hint" \\
  CODEX_MAX_WALL_CLOCK_SECONDS=$approved_wall_clock \\
    bash benchmarks/run-all.sh codex${mode_args}

The command itself records paid authorization for this exact manifest; no separate chat approval is needed when you run it. CODEX_RUN_DIR must not already exist. Review benchmarks/manifests/codex-integration.md for the locked scope.
Credential warning: use an immutable, user-owned 0600 auth source. Do not run a concurrent Codex session with it; use an independently authenticated benchmark credential instead. The runner keeps private run state and atomically propagates valid refreshes between cells. A private sequential refresh can invalidate an unchanged source, so reauthenticate after the run if needed. Known refresh-token authentication failures stop immediately; three matching unknown zero-token pre-response failures preserve partial artifacts and stop scheduling.
${scope_guidance:+$'\n'"$scope_guidance"$'\n'}
EOF
}

resolve_codex_tasks() {
  local selection_json
  if ! selection_json="$(python3 benchmarks/run-codex-structural.py \
    --manifest-path "$MANIFEST_PATH" \
    --resolve-tasks "$CODEX_TASKS" 2>&1)"; then
    echo "ERROR: invalid Codex task selection '$CODEX_TASKS':" >&2
    echo "$selection_json" >&2
    return 2
  fi
  if ! CODEX_SELECTION_SCOPE_SHA="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["scope_sha256"])' <<<"$selection_json" 2>/dev/null)" \
    || ! CODEX_SELECTION_REPETITIONS="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["repetitions"])' <<<"$selection_json" 2>/dev/null)" \
    || ! CODEX_SELECTION_WALL_CLOCK="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["complete_run_max_wall_clock_seconds"])' <<<"$selection_json" 2>/dev/null)"; then
    echo "ERROR: Codex task resolver returned malformed selection metadata:" >&2
    echo "$selection_json" >&2
    return 2
  fi
  CODEX_SELECTION_TASK_IDS=()
  while IFS= read -r task_id; do
    [ -n "$task_id" ] && CODEX_SELECTION_TASK_IDS+=("$task_id")
  done < <(python3 -c 'import json,sys; print(*json.loads(sys.stdin.read())["task_ids"], sep="\n")' <<<"$selection_json")
  if [ "${#CODEX_SELECTION_TASK_IDS[@]}" -eq 0 ]; then
    echo "ERROR: Codex task resolver returned no task IDs." >&2
    return 2
  fi
}

ensure_codex_scope_resolved() {
  if [ -n "$CODEX_TASKS" ] && [ -z "$CODEX_SELECTION_SCOPE_SHA" ]; then
    resolve_codex_tasks
  fi
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

configure_codex_selected_plan() {
  ensure_codex_scope_resolved
  active_manifest_sha="$(sha256_file "$MANIFEST_PATH")"
  selected_task_count="${#CODEX_SELECTION_TASK_IDS[@]}"
  selected_cells=$((selected_task_count * CODEX_SELECTION_REPETITIONS * 3))
  echo "== CODEX SELECTED A/B/C STUDY =="
  echo "→ design: $selected_cells cells ($selected_task_count tasks × $CODEX_SELECTION_REPETITIONS runs × 3 arms; nonpoolable)"
  echo "→ tasks: ${CODEX_TASKS}"
  echo "→ model: gpt-5.6-luna; reasoning effort: high"
  echo "→ limits: 600 seconds per coordinate; $CODEX_SELECTION_WALL_CLOCK seconds complete run"
  echo "→ selection scope: $CODEX_SELECTION_SCOPE_SHA"
  common_args=(
    --repo-path "$REPO" \
    --tasks-path benchmarks/suites/tasks-bench.json \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model gpt-5.6-luna \
    --reasoning-effort high \
    --tasks "$CODEX_TASKS" \
    --repetitions "$CODEX_SELECTION_REPETITIONS" \
    --arm all \
    --scope-sha256 "$CODEX_SELECTION_SCOPE_SHA" \
    --max-wall-clock-seconds "$CODEX_SELECTION_WALL_CLOCK"
  )
}

run_codex_plan() {
  # Paid execution wraps this function in a tee pipeline. Explicit propagation
  # prevents the full plan or paid cells from starting after a failed smoke.
  query_check || return "$?"
  codex_smoke_preflight --no-legend || return "$?"
  if [ -n "$CODEX_TASKS" ]; then
    configure_codex_selected_plan || return "$?"
  else
    configure_codex_plan || return "$?"
  fi
  if [ -n "$CODEX_TASKS" ]; then
    echo "== CODEX SELECTED A/B/C PREFLIGHT (no model) =="
  else
    echo "== CODEX CONFIRMATORY A/B/C PREFLIGHT (no model) =="
  fi
  python3 benchmarks/run-codex-structural.py "${common_args[@]}" --dry-run || return "$?"
}

run_codex_study() {
  run_codex_plan || return "$?"
  if [ -n "$CODEX_TASKS" ]; then
    echo "== CODEX SELECTED A/B/C STUDY (paid model runs) =="
  else
    echo "== CODEX CONFIRMATORY A/B/C STUDY (paid model runs) =="
  fi
  python3 benchmarks/run-codex-structural.py \
    "${common_args[@]}" \
    --auth-source "$CODEX_AUTH_SOURCE" \
    --invocation-launcher-path "$CODEX_INVOCATION_LAUNCHER" \
    --no-legend \
    --output-path "$CODEX_RUN_DIR/telemetry.jsonl" \
    --metadata-path "$CODEX_RUN_DIR/run-metadata.json"
}

run_codex_with_artifacts() {
  # Keep the artifact log lossless; the structural runner renders only the console stream.
  local study_runner="$1"
  if "$study_runner" 2>&1 | tee "$CODEX_RUN_DIR/run.log" | python3 "$ROOT/benchmarks/run-codex-structural.py" --render-results --hide-plan; then
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
  if [ -d "$CODEX_RUN_DIR/inputs" ]; then
    while IFS= read -r input_artifact; do
      shasum -a 256 "$input_artifact" >> "$checksum_path"
    done < <(find "$CODEX_RUN_DIR/inputs" -type f -print | LC_ALL=C sort)
  fi
  if [ -f "$CODEX_RUN_DIR/.launcher/run-all.sh" ]; then
    shasum -a 256 "$CODEX_RUN_DIR/.launcher/run-all.sh" >> "$checksum_path"
  fi
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
    if [ -n "$CODEX_TASKS" ]; then
      ensure_codex_scope_resolved
    fi
    if [ "$CODEX_DRY_RUN" = true ]; then
      prepare_locked_inputs
      run_codex_plan
    else
      require_codex_paid_inputs
      if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" != "1" ]; then
        exec_codex_launcher_snapshot "$@"
      fi
      prepare_locked_inputs
      run_codex_with_artifacts run_codex_study
    fi
    ;;
esac

echo "→ done. Results in benchmarks/results/"
