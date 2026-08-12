#!/usr/bin/env bash
# Provider-neutral benchmark batch entrypoint.
#
# Usage:
#   bash benchmarks/run-all.sh smoke   # fail-fast Claude + Codex smoke only
#   bash benchmarks/run-all.sh claude  # fail-fast Claude smoke, then full Claude batches
#   bash benchmarks/run-all.sh claude --struct --dry-run  # Claude structural plans only, no model
#   bash benchmarks/run-all.sh claude --struct  # Claude structural batches only
#   bash benchmarks/run-all.sh claude --agentic --dry-run  # shared 144-cell Claude agentic plan, no model
#   bash benchmarks/run-all.sh claude --agentic --tasks=BA-02,BA-04,BA-12,BA-16 --dry-run  # selected nonpoolable Claude plan
#   bash benchmarks/run-all.sh claude --agentic --repetitions=2 --dry-run  # scope-bound Claude repeat override
#   bash benchmarks/run-all.sh codex --struct --dry-run  # unified 73-task/219-cell Codex plan, no model
#   bash benchmarks/run-all.sh codex --struct  # paid unified Codex task study
#   bash benchmarks/run-all.sh codex --dry-run  # unified task + agentic Codex plans, no model
#   bash benchmarks/run-all.sh codex   # paid unified task study, then paid agentic study
#   bash benchmarks/run-all.sh codex --struct --tasks=RC,FS,FM,PT [--dry-run]  # selected stage-native task families
#   bash benchmarks/run-all.sh codex --agentic --dry-run  # shared 48-cell agentic plan, no model
#   bash benchmarks/run-all.sh codex --agentic --tasks=BA-02,BA-04,BA-12,BA-16 --dry-run  # selected nonpoolable Codex plan
#   bash benchmarks/run-all.sh codex --agentic --repetitions=2 --dry-run  # scope-bound repeat override
#   bash benchmarks/run-all.sh codex --agentic  # paid shared agentic study
#
# Paid Codex modes require the active scope approval and a private auth source.
# The launcher creates a fresh evidence directory when CODEX_RUN_DIR is omitted.
# No mode runs when the argument is missing or unknown. This entrypoint
# reconstructs a missing index and accepts it only when normalization reproduces
# the reviewed byte hash exactly.
set -euo pipefail

ROOT="${CODEX_LAUNCHER_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
CODEX_RESULTS_ROOT="${CODEX_RESULTS_ROOT:-$ROOT/benchmarks/results}"
PL_TAG="2.6.5"
PL_URL="${PL_URL:-https://github.com/Lightning-AI/pytorch-lightning.git}"
BENCHMARK_TEMP_ROOT="$(python3 -c 'import os; from pathlib import Path; print((Path(os.sep) / "tmp").resolve())')"
MANAGED_REPO="$BENCHMARK_TEMP_ROOT/codemap-provider-parity-pl-2.6.5"
REPO="${REPO:-$MANAGED_REPO}"
INDEX_PATH="$REPO/.cache/codemap/$(basename "$REPO").json"
MODE="${1:-}"
DRY_RUN=false
AGENTIC=false
STRUCTURAL=false
AGENTIC_REPETITIONS=1
AGENTIC_REPETITIONS_SET=false
AGENTIC_SCOPE_SHA=""
AGENTIC_TOTAL_CELLS=""
AGENTIC_RUNNER=""
AGENTIC_DISPATCH_ARGS=()
CODEX_TASKS=""
AGENTIC_TASK_IDS=()
SHARED_STRUCTURAL_TASK_IDS=()
CODEX_SELECTION_SCOPE_SHA=""
CODEX_SELECTION_TOTAL_CELLS=""
CODEX_EXECUTION_SCOPE_SHA=""
CODEX_SELECTION_TASK_IDS=()
MANIFEST_PATH="$ROOT/benchmarks/manifests/codex-integration.json"
AGENTIC_MANIFEST_PATH="$ROOT/benchmarks/manifests/codex-agentic.json"
METHODOLOGY_PATH="$ROOT/benchmarks/manifests/provider-parity-methodology.json"
MANIFEST_CHECKER="$ROOT/benchmarks/build-codex-integration-manifest.py"
AGENTIC_MANIFEST_CHECKER="$ROOT/benchmarks/build-codex-agentic-manifest.py"
METHODOLOGY_CHECKER="$ROOT/benchmarks/build-provider-parity-methodology-manifest.py"
CODEMAP_BIN="${CODEMAP_BIN:-$ROOT/plugins/codemap-py/bin/codemap-py}"
INDEX_PREPARER="$ROOT/benchmarks/prepare-codex-index.py"
SCHEMA_PATH="$ROOT/plugins/codemap-py/src/codemap_py/schema.py"
LOCKED_INDEX_SHA=""
LOCKED_INDEX_SCAN_VERSION=""

usage() {
  echo "usage: bash benchmarks/run-all.sh {smoke | claude [--struct|--agentic] [--dry-run] [--tasks=TASK[,TASK...]] [--repetitions=N] | codex [--struct|--agentic] [--dry-run] [--tasks=TASK[,TASK...]] [--repetitions=N]}" >&2
}

if [ "$#" -lt 1 ]; then
  usage
  exit 2
fi
case "$MODE" in
  smoke)
    if [ "$#" -ne 1 ]; then
      usage
      exit 2
    fi
    ;;
  claude | codex)
    for option in "${@:2}"; do
      case "$option" in
        --dry-run)
          if [ "$DRY_RUN" = true ]; then
            usage
            exit 2
          fi
          DRY_RUN=true
          ;;
        --agentic)
          if [ "$AGENTIC" = true ]; then
            usage
            exit 2
          fi
          AGENTIC=true
          ;;
        --struct)
          if [ "$STRUCTURAL" = true ]; then
            usage
            exit 2
          fi
          STRUCTURAL=true
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
        --repetitions=*)
          if [ "$AGENTIC_REPETITIONS_SET" = true ]; then
            usage
            exit 2
          fi
          AGENTIC_REPETITIONS_SET=true
          AGENTIC_REPETITIONS="${option#--repetitions=}"
          if ! [[ "$AGENTIC_REPETITIONS" =~ ^[1-9][0-9]*$ ]]; then
            echo "ERROR: --repetitions must be a positive integer." >&2
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
    if [ "$AGENTIC" = true ] && [ "$STRUCTURAL" = true ]; then
      echo "ERROR: --struct and --agentic are mutually exclusive." >&2
      usage
      exit 2
    fi
    if [ "$AGENTIC" != true ] && [ "$MODE" != "codex" ] && [ -n "$CODEX_TASKS" ]; then
      echo "ERROR: --tasks is available for Codex structural or either provider's agentic mode." >&2
      usage
      exit 2
    fi
    if [ "$AGENTIC" != true ] && [ "$AGENTIC_REPETITIONS_SET" = true ]; then
      echo "ERROR: --repetitions is available only with --agentic." >&2
      usage
      exit 2
    fi
    if [ "$MODE" = "codex" ] && [ -n "$CODEX_TASKS" ] && [ "$AGENTIC" != true ] && [ "$STRUCTURAL" != true ]; then
      echo "ERROR: Codex --tasks requires an explicit --struct or --agentic selector." >&2
      usage
      exit 2
    fi
    ;;
  *)
    usage
    exit 2
    ;;
esac

cd "$ROOT"

refresh_generated_manifests() {
  if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" = "1" ] || {
    [ "$ROOT" = "${CODEX_LAUNCHER_ROOT:-}" ] && [ -n "${CODEX_SOURCE_MANIFEST_SHA256:-}" ]
  }; then
    echo "== CHECK frozen generated benchmark manifests (no model) =="
    CODEX_LAUNCHER_SNAPSHOT_ACTIVE=1 python3 "$METHODOLOGY_CHECKER" --check
    CODEX_LAUNCHER_SNAPSHOT_ACTIVE=1 python3 "$MANIFEST_CHECKER" --check
    CODEX_LAUNCHER_SNAPSHOT_ACTIVE=1 python3 "$AGENTIC_MANIFEST_CHECKER" --check
    return
  fi
  echo "== BUILD generated benchmark manifests (no model) =="
  python3 "$METHODOLOGY_CHECKER"
  python3 "$MANIFEST_CHECKER"
  python3 "$AGENTIC_MANIFEST_CHECKER"
}

refresh_generated_manifests

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

archive_paid_source() {
  local source_root="$1"
  mkdir -p "$source_root"
  (
    cd "$ROOT"
    COPYFILE_DISABLE=1 tar \
      --exclude='benchmarks/results' \
      --exclude='benchmarks/results/*' \
      --exclude='*/.git' \
      --exclude='*/.git/*' \
      --exclude='*/.cache' \
      --exclude='*/.cache/*' \
      --exclude='*/__pycache__' \
      --exclude='*/__pycache__/*' \
      --exclude='*/.pytest_cache' \
      --exclude='*/.pytest_cache/*' \
      --exclude='*/.ruff_cache' \
      --exclude='*/.ruff_cache/*' \
      --exclude='*/.mypy_cache' \
      --exclude='*/.mypy_cache/*' \
      --exclude='*.pyc' \
      --exclude='*.pyo' \
      -cf - \
      benchmarks \
      plugins/codemap-py \
      plugins/codex-rig \
      .agents/plugins/marketplace.json
  ) | (
    cd "$source_root"
    COPYFILE_DISABLE=1 tar -xf -
  )
}

capture_codemap_mode_map() {
  local output_path="$1"
  python3 -c \
    'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from _probe_runtime import write_real_mode_map; write_real_mode_map(Path(sys.argv[2]), Path(sys.argv[3]))' \
    "$ROOT/plugins/codemap-py/scripts" \
    "$ROOT" \
    "$output_path"
}

build_source_checksum_manifest() {
  local source_root="$1"
  local output_path="$2"
  local source_file relative_path source_symlink
  source_symlink="$(find "$source_root" -type l -print -quit)"
  if [ -n "$source_symlink" ]; then
    echo "ERROR: paid Codex source snapshot contains a symlink: $source_symlink" >&2
    return 2
  fi
  : > "$output_path"
  while IFS= read -r source_file; do
    relative_path="${source_file#"$source_root"/}"
    printf '%s  %s\n' "$(sha256_file "$source_file")" "$relative_path" >> "$output_path"
  done < <(find "$source_root" -type f -print | LC_ALL=C sort)
}

validate_paid_source_snapshot() {
  local expected_source="$CODEX_RUN_DIR/.launcher/source"
  local source_manifest="$CODEX_RUN_DIR/.launcher/source.sha256"
  local actual_manifest
  if [ "$ROOT" != "$expected_source" ] || [ "${CODEX_LAUNCHER_ROOT:-}" != "$expected_source" ]; then
    echo "ERROR: paid Codex mode is not using its run-scoped source snapshot." >&2
    exit 2
  fi
  if [ ! -d "$expected_source" ] || [ ! -f "$source_manifest" ]; then
    echo "ERROR: paid Codex source snapshot is incomplete." >&2
    exit 2
  fi
  if [ ! -f "$expected_source/benchmarks/manifests/codemap-package-mode-map.json" ]; then
    echo "ERROR: paid Codex source snapshot lacks the Codemap package mode map." >&2
    exit 2
  fi
  if [ "$(sha256_file "$source_manifest")" != "${CODEX_SOURCE_MANIFEST_SHA256:-}" ]; then
    echo "ERROR: paid Codex source checksum manifest changed before execution." >&2
    exit 2
  fi
  if ! actual_manifest="$(mktemp "$BENCHMARK_TEMP_ROOT/codex-source-checksums.XXXXXX")"; then
    echo "ERROR: failed to create the paid Codex source validation manifest." >&2
    exit 2
  fi
  build_source_checksum_manifest "$expected_source" "$actual_manifest"
  if ! cmp -s "$source_manifest" "$actual_manifest"; then
    rm -f "$actual_manifest"
    echo "ERROR: paid Codex source snapshot changed before execution." >&2
    exit 2
  fi
  rm -f "$actual_manifest"
}

append_launcher_checksum_attestation() {
  local checksum_path="$1"
  local launcher_artifact
  for launcher_artifact in "$CODEX_RUN_DIR/.launcher/run-all.sh" "$CODEX_RUN_DIR/.launcher/source.sha256"; do
    if [ -f "$launcher_artifact" ]; then
      shasum -a 256 "$launcher_artifact" >> "$checksum_path"
    fi
  done
}

write_codex_result_checksums() {
  local checksum_path="$1"
  local artifact input_artifact benchmark_artifact
  : > "$checksum_path"
  for artifact in run.log telemetry.jsonl telemetry-canonical.jsonl run-metadata.json runtime-isolation.jsonl; do
    if [ -f "$CODEX_RUN_DIR/$artifact" ]; then
      shasum -a 256 "$CODEX_RUN_DIR/$artifact" >> "$checksum_path"
    fi
  done
  if [ -d "$CODEX_RUN_DIR/inputs" ]; then
    while IFS= read -r input_artifact; do
      shasum -a 256 "$input_artifact" >> "$checksum_path"
    done < <(find "$CODEX_RUN_DIR/inputs" -type f -print | LC_ALL=C sort)
  fi
  if [ -d "$CODEX_RUN_DIR/benchmark" ]; then
    while IFS= read -r benchmark_artifact; do
      shasum -a 256 "$benchmark_artifact" >> "$checksum_path"
    done < <(find "$CODEX_RUN_DIR/benchmark" -type f -print | LC_ALL=C sort)
  fi
  append_launcher_checksum_attestation "$checksum_path"
}

resolve_agentic_scope() {
  local scope_json
  local -a resolver
  AGENTIC_TASK_IDS=()
  if [ "$MODE" = "claude" ]; then
    resolver=(
      python3 "$ROOT/benchmarks/run-claude-agentic.py"
      --manifest-path "$METHODOLOGY_PATH"
      --repeat "$AGENTIC_REPETITIONS"
      --resolve-scope
    )
    if [ -n "$CODEX_TASKS" ]; then
      resolver+=(--tasks "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1].split(",")))' "$CODEX_TASKS")")
    fi
  else
    resolver=(
      python3 "$ROOT/benchmarks/run-codex-agentic.py"
      --manifest-path "$AGENTIC_MANIFEST_PATH"
      --repetitions "$AGENTIC_REPETITIONS"
      --resolve-scope
    )
    if [ -n "$CODEX_TASKS" ]; then
      resolver+=(--task-id "$CODEX_TASKS")
    fi
  fi
  if ! scope_json="$("${resolver[@]}" 2>&1)"; then
    echo "ERROR: invalid $MODE agentic scope:" >&2
    echo "$scope_json" >&2
    return 2
  fi
  AGENTIC_SCOPE_SHA="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["scope_sha256"])' <<<"$scope_json")"
  AGENTIC_TOTAL_CELLS="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["total_cells"])' <<<"$scope_json")"
  AGENTIC_COORDINATE_TIMEOUT="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["coordinate_timeout_seconds"])' <<<"$scope_json")"
  while IFS= read -r task_id; do
    [ -n "$task_id" ] && AGENTIC_TASK_IDS+=("$task_id")
  done < <(python3 -c 'import json,sys; print(*json.loads(sys.stdin.read())["task_ids"], sep="\n")' <<<"$scope_json")
  if [ "${#AGENTIC_TASK_IDS[@]}" -eq 0 ]; then
    echo "ERROR: $MODE agentic scope resolver returned no task IDs." >&2
    return 2
  fi
}

configure_agentic_dispatch() {
  # Default suites are manifest-defined; only selected or repeated runs need a
  # resolver-derived identity forwarded to prevent a scope mismatch.
  if [ "$MODE" = "claude" ]; then
    AGENTIC_RUNNER="$ROOT/benchmarks/run-claude-agentic.py"
    AGENTIC_DISPATCH_ARGS=(
      --repo-path "$REPO"
      --manifest-path "$METHODOLOGY_PATH"
    )
    if [ -n "$CODEX_TASKS" ]; then
      AGENTIC_DISPATCH_ARGS+=(--tasks "$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1].split(",")))' "$CODEX_TASKS")")
    else
      AGENTIC_DISPATCH_ARGS+=(--run-all)
    fi
    AGENTIC_DISPATCH_ARGS+=(--repeat "$AGENTIC_REPETITIONS")
  else
    AGENTIC_RUNNER="$ROOT/benchmarks/run-codex-agentic.py"
    AGENTIC_DISPATCH_ARGS=(
      --repo-path "$REPO"
      --index-path "$INDEX_PATH"
      --marketplace-root "$ROOT"
      --codemap-bin "$CODEMAP_BIN"
      --manifest-path "$AGENTIC_MANIFEST_PATH"
    )
    if [ -n "$CODEX_TASKS" ]; then
      AGENTIC_DISPATCH_ARGS+=(--task-id "$CODEX_TASKS")
    fi
    AGENTIC_DISPATCH_ARGS+=(--repetitions "$AGENTIC_REPETITIONS")
  fi
  if [ -n "$CODEX_TASKS" ] || [ "$AGENTIC_REPETITIONS" != "1" ]; then
    AGENTIC_DISPATCH_ARGS+=(--scope-sha256 "$AGENTIC_SCOPE_SHA")
  fi
}

load_index_contract() {
  local manifest_path="$1"
  local methodology_path="${2:-}"
  local contract_json
  local -a methodology_args=()
  if [ -n "$methodology_path" ]; then
    methodology_args=(--methodology-path "$methodology_path")
  fi
  # The guarded expansion keeps an empty optional array safe under macOS Bash 3.2 with `set -u`.
  if ! contract_json="$(python3 "$INDEX_PREPARER" \
    --manifest-path "$manifest_path" \
    ${methodology_args[@]+"${methodology_args[@]}"} \
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
  local manifest_path="$1"
  local methodology_path="${2:-}"
  local verification
  local -a methodology_args=()
  if [ -n "$methodology_path" ]; then
    methodology_args=(--methodology-path "$methodology_path")
  fi
  if verification="$(python3 "$INDEX_PREPARER" \
    --index-path "$INDEX_PATH" \
    --manifest-path "$manifest_path" \
    ${methodology_args[@]+"${methodology_args[@]}"} \
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
    if ! git -C "$REPO" reset --hard "$PL_TAG"; then
      echo "ERROR: managed benchmark clone cannot reset to $PL_TAG; recreate $REPO before retrying." >&2
      return 1
    fi
    if ! git -C "$REPO" clean -fd; then
      echo "ERROR: managed benchmark clone cannot remove untracked files." >&2
      return 1
    fi
  elif ! git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "ERROR: \$REPO ($REPO) is not a Git worktree at tag $PL_TAG." >&2
    exit 1
  fi
  echo "→ target repo: $REPO ($(git -C "$REPO" rev-parse --short HEAD))"
}

resolve_codemap_python() {
  local candidate resolved
  local -a candidates=()
  if [ -n "${CODEMAP_PYTHON:-}" ]; then
    candidates+=("$CODEMAP_PYTHON")
  fi
  for candidate in python3.11 python3 python; do
    if resolved="$(command -v "$candidate" 2>/dev/null)"; then
      candidates+=("$resolved")
    fi
  done
  for candidate in "${candidates[@]}"; do
    if [ -x "$candidate" ] && "$candidate" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 11))' >/dev/null 2>&1; then
      "$candidate" -c 'import os,sys; print(os.path.realpath(sys.executable))'
      return 0
    fi
  done
  echo "ERROR: Codemap benchmark preparation requires an executable Python 3.11; set CODEMAP_PYTHON or add python3.11 to PATH." >&2
  return 2
}

set_default_codex_run_dir() {
  local prefix="codex-combined"
  if [ -n "${CODEX_RUN_DIR:-}" ]; then
    if [[ "$CODEX_RUN_DIR" != /* ]]; then
      CODEX_RUN_DIR="$ROOT/$CODEX_RUN_DIR"
      export CODEX_RUN_DIR
    fi
    return 0
  fi
  if [ "$AGENTIC" = true ]; then
    prefix="codex-agentic"
  elif [ "$STRUCTURAL" = true ]; then
    prefix="codex-integration"
  fi
  if [ -n "$CODEX_TASKS" ]; then
    prefix="$prefix-selected"
  fi
  CODEX_RUN_DIR="$CODEX_RESULTS_ROOT/$prefix-$(date -u +%Y%m%dT%H%M%SZ)"
  if [[ "$CODEX_RUN_DIR" != /* ]]; then
    CODEX_RUN_DIR="$ROOT/$CODEX_RUN_DIR"
  fi
  export CODEX_RUN_DIR
}

prepare_index_inputs() {
  local manifest_path="$1"
  local methodology_path="${2:-}"
  local -a methodology_args=()
  if [ -n "$methodology_path" ]; then
    methodology_args=(--methodology-path "$methodology_path")
  fi
  load_index_contract "$manifest_path" "$methodology_path" || return "$?"
  ensure_repo || return "$?"
  echo "== PREPARE frozen parity index =="
  if [ ! -f "$INDEX_PATH" ] || ! verify_current_index "$manifest_path" "$methodology_path"; then
    if [ -f "$INDEX_PATH" ]; then
      echo "→ existing index is stale or schema-incompatible; rebuild from the locked target"
    else
      echo "→ build missing index from the locked target"
    fi
    codemap_python="$(resolve_codemap_python)"
    CODEMAP_PYTHON="$codemap_python" "$CODEMAP_BIN" index --root "$REPO"
  fi
  index_sha="$(sha256_file "$INDEX_PATH")"
  if [ "$index_sha" != "$LOCKED_INDEX_SHA" ]; then
    python3 "$INDEX_PREPARER" \
      --index-path "$INDEX_PATH" \
      --source-root "$REPO" \
      --manifest-path "$manifest_path" \
      ${methodology_args[@]+"${methodology_args[@]}"} \
      --schema-path "$SCHEMA_PATH"
  fi
  if ! verify_current_index "$manifest_path" "$methodology_path"; then
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

prepare_patch_index_inputs() {
  local patch_locks="$ROOT/benchmarks/suites/patch-index-locks.json"
  local -a patch_commits=(
    8e805f9268043c9aa8f0d70800be537b56a93c19
    aa0ee0d18d49c6b26f18d34a3473f177adefc262
    9df1910f0833100478886bef0a08b450ff2d0c14
    3876cc525d2678463199407ca48230d3eba09461
    b15d394f2a9d36ccefba08328ac8dc2bd13e49b2
  )
  echo "== PREPARE frozen historical patch indexes =="
  for commit in "${patch_commits[@]}"; do
    if ! git -C "$REPO" cat-file -e "$commit^{commit}" 2>/dev/null; then
      echo "→ fetch missing patch baseline $commit"
      git -C "$REPO" fetch origin "$commit" || return "$?"
    fi
  done
  if ! python3 "$INDEX_PREPARER" \
    --prepare-patch-bundle \
    --source-root "$REPO" \
    --patch-locks-path "$patch_locks" \
    --scan-index-bin "$ROOT/plugins/codemap-py/bin/scan-index"; then
    echo "ERROR: historical patch indexes could not be prepared. Ensure the exact PT baseline commits are present, then rerun this no-model command." >&2
    echo "git -C $REPO fetch origin 8e805f9268043c9aa8f0d70800be537b56a93c19 aa0ee0d18d49c6b26f18d34a3473f177adefc262 9df1910f0833100478886bef0a08b450ff2d0c14 3876cc525d2678463199407ca48230d3eba09461 b15d394f2a9d36ccefba08328ac8dc2bd13e49b2" >&2
    echo "python3 benchmarks/prepare-codex-index.py --prepare-patch-bundle --source-root $REPO --patch-locks-path $patch_locks --scan-index-bin $ROOT/plugins/codemap-py/bin/scan-index" >&2
    return 1
  fi
}

patch_bundle_required() {
  # Historical indexes are only consumed by the PT stage. The unqualified
  # Codex task study includes every stage, while selected structural scopes
  # expose their resolved IDs before input preparation.
  if [ "$MODE" != "codex" ] || [ "$AGENTIC" = true ]; then
    return 1
  fi
  if [ -z "$CODEX_TASKS" ]; then
    return 0
  fi
  local task_id
  for task_id in "${CODEX_SELECTION_TASK_IDS[@]}"; do
    case "$task_id" in
      PT-*) return 0 ;;
    esac
  done
  return 1
}

prepare_locked_inputs() {
  load_shared_structural_tasks || return "$?"
  prepare_index_inputs "$MANIFEST_PATH" "$METHODOLOGY_PATH"
  if patch_bundle_required; then
    prepare_patch_index_inputs
  fi
}

prepare_claude_inputs() {
  load_shared_structural_tasks || return "$?"
  prepare_index_inputs "$METHODOLOGY_PATH"
}

load_shared_structural_tasks() {
  SHARED_STRUCTURAL_TASK_IDS=()
  while IFS= read -r task_id; do
    [ -n "$task_id" ] && SHARED_STRUCTURAL_TASK_IDS+=("$task_id")
  done < <(
    python3 -c \
      'import json,sys; print(*json.load(open(sys.argv[1]))["preregistered_cells"]["structural_execution_task_ids"], sep="\n")' \
      "$METHODOLOGY_PATH"
  )
  if [ "${#SHARED_STRUCTURAL_TASK_IDS[@]}" -eq 0 ]; then
    echo "ERROR: provider-neutral methodology defines no structural execution tasks." >&2
    return 2
  fi
}

query_check() {
  echo "== QUERY (no model) =="
  python3 "$ROOT/benchmarks/run-codemap-cli.py" --repo-path "$REPO"
}

validate_codex_cli() {
  local actual_codex_version
  if ! actual_codex_version="$(command codex --version)"; then
    echo "ERROR: Codex CLI is unavailable or cannot report its identity." >&2
    exit 2
  fi
  CODEX_CLI_OBSERVED_VERSION="$actual_codex_version"
  export CODEX_CLI_OBSERVED_VERSION
  echo "→ Codex CLI: $actual_codex_version"
}

claude_structural_preflight() {
  echo "== CLAUDE STRUCTURAL PREFLIGHT (no model) =="
  python3 "$ROOT/benchmarks/run-claude-structural.py" \
    --repo-path "$REPO" \
    --tasks "['FN-02']" \
    --arm all \
    --model haiku \
    --dry-run
}

claude_agentic_preflight() {
  echo "== CLAUDE AGENTIC PREFLIGHT (no model) =="
  python3 "$ROOT/benchmarks/run-claude-agentic.py" \
    --repo-path "$REPO" \
    --tasks "['BA-01']" \
    --arm A_plain \
    --model haiku \
    --dry-run
}

claude_preflight() {
  claude_structural_preflight
  claude_agentic_preflight
}

codex_smoke_preflight() {
  local legend_arg="${1:-}"
  local codex_model codex_reasoning_effort
  codex_model="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["name"])' "$MANIFEST_PATH")"
  codex_reasoning_effort="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["reasoning_effort"])' "$MANIFEST_PATH")"
  echo "== CODEX PREFLIGHT (no model) =="
  validate_codex_cli
  python3 "$ROOT/benchmarks/run-codex-structural.py" \
    --repo-path "$REPO" \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model "$codex_model" \
    --reasoning-effort "$codex_reasoning_effort" \
    --tasks FN-02 \
    --dry-run \
    $legend_arg
}

smoke() {
  query_check
  claude_preflight
  codex_smoke_preflight
  echo "→ smoke OK: query command completed; Claude/Codex no-model preflights passed"
}

run_claude_structural_study() {
  local structural_tasks
  structural_tasks="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${SHARED_STRUCTURAL_TASK_IDS[@]}")"
  query_check
  claude_structural_preflight
  echo "== CLAUDE STRUCTURAL (paid model runs) =="
  for model in haiku sonnet opus; do
    python3 "$ROOT/benchmarks/run-claude-structural.py" \
      --repo-path "$REPO" \
      --tasks "$structural_tasks" \
      --model "$model" \
      --provider-parity
  done
}

claude() {
  run_claude_structural_study
  claude_agentic_preflight

  echo "== CLAUDE AGENTIC (paid model runs) =="
  resolve_agentic_scope
  configure_agentic_dispatch
  python3 "$AGENTIC_RUNNER" "${AGENTIC_DISPATCH_ARGS[@]}" --report
}

run_claude_agentic_plan() {
  resolve_agentic_scope
  configure_agentic_dispatch
  echo "== CLAUDE SHARED AGENTIC A/B/C PREFLIGHT (no model) =="
  echo "→ design: $AGENTIC_TOTAL_CELLS cells (${#AGENTIC_TASK_IDS[@]} tasks × $AGENTIC_REPETITIONS repetitions × 3 arms × 3 models; nonpoolable)"
  echo "→ scope: $AGENTIC_SCOPE_SHA"
  python3 "$AGENTIC_RUNNER" "${AGENTIC_DISPATCH_ARGS[@]}" --dry-run
}

run_claude_agentic_study() {
  resolve_agentic_scope
  configure_agentic_dispatch
  echo "== CLAUDE SHARED AGENTIC A/B/C STUDY (paid model runs) =="
  echo "→ design: $AGENTIC_TOTAL_CELLS cells (${#AGENTIC_TASK_IDS[@]} tasks × $AGENTIC_REPETITIONS repetitions × 3 arms × 3 models; nonpoolable)"
  echo "→ timeout: $AGENTIC_COORDINATE_TIMEOUT seconds per cell, including retries"
  echo "→ manifest: $METHODOLOGY_PATH ($(sha256_file "$METHODOLOGY_PATH"))"
  echo "→ scope: $AGENTIC_SCOPE_SHA"
  python3 "$AGENTIC_RUNNER" "${AGENTIC_DISPATCH_ARGS[@]}" --report
}

run_claude_structural_plan() {
  local structural_tasks
  structural_tasks="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "${SHARED_STRUCTURAL_TASK_IDS[@]}")"
  query_check
  claude_structural_preflight
  echo "== CLAUDE STRUCTURAL (no-model full plans) =="
  for model in haiku sonnet opus; do
    python3 "$ROOT/benchmarks/run-claude-structural.py" \
      --repo-path "$REPO" \
      --tasks "$structural_tasks" \
      --model "$model" \
      --provider-parity \
      --dry-run
  done
}

run_claude_plan() {
  run_claude_structural_plan
  claude_agentic_preflight
  run_claude_agentic_plan
}

require_codex_paid_inputs() {
  if [ ! -f "$MANIFEST_PATH" ]; then
    echo "ERROR: active provider-parity manifest is missing: $MANIFEST_PATH" >&2
    exit 2
  fi
  if [[ ! "${CODEX_PAID_APPROVAL:-}" =~ ^[0-9a-f]{16,64}$ ]]; then
    echo "ERROR: paid Codex mode requires the 16-character approval token (or longer matching prefix) printed by --dry-run." >&2
    print_codex_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_AUTH_SOURCE:-}" ] || [ ! -f "$CODEX_AUTH_SOURCE" ]; then
    echo "ERROR: paid Codex mode requires CODEX_AUTH_SOURCE pointing to a private auth.json." >&2
    print_codex_paid_guidance
    exit 2
  fi
  set_default_codex_run_dir
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
    validate_paid_source_snapshot
  elif [ -e "$CODEX_RUN_DIR" ]; then
    echo "ERROR: CODEX_RUN_DIR already exists: $CODEX_RUN_DIR" >&2
    print_codex_paid_guidance
    exit 2
  fi
}

exec_codex_launcher_snapshot() {
  local launcher_dir="$CODEX_RUN_DIR/.launcher"
  local launcher_snapshot="$launcher_dir/run-all.sh"
  local source_root="$launcher_dir/source"
  local source_manifest="$launcher_dir/source.sha256"
  mkdir -p "$launcher_dir"
  archive_paid_source "$source_root"
  if [ -f "$ROOT/benchmarks/manifests/codemap-package-mode-map.json" ]; then
    cp "$ROOT/benchmarks/manifests/codemap-package-mode-map.json" "$source_root/benchmarks/manifests/codemap-package-mode-map.json"
  else
    capture_codemap_mode_map "$source_root/benchmarks/manifests/codemap-package-mode-map.json"
  fi
  build_source_checksum_manifest "$source_root" "$source_manifest"
  cp "$source_root/benchmarks/run-all.sh" "$launcher_snapshot"
  chmod 500 "$launcher_snapshot"
  if [[ "${CODEMAP_BIN:-}" == "$ROOT/plugins/codemap-py/"* ]]; then
    export CODEMAP_BIN="$source_root/${CODEMAP_BIN#"$ROOT"/}"
  fi
  export CODEX_LAUNCHER_ROOT="$source_root"
  export CODEX_INVOCATION_LAUNCHER="$launcher_snapshot"
  export CODEX_LAUNCHER_SHA256="$(sha256_file "$launcher_snapshot")"
  export CODEX_SOURCE_MANIFEST_SHA256="$(sha256_file "$source_manifest")"
  export CODEX_LAUNCHER_SNAPSHOT_ACTIVE=1
  export PYTHONDONTWRITEBYTECODE=1
  exec /bin/bash "$launcher_snapshot" "$@"
}

print_codex_paid_guidance() {
  local structural_arg=""
  if [ "$STRUCTURAL" = true ]; then
    structural_arg=" --struct"
  fi
  if [ -n "$CODEX_TASKS" ]; then
    ensure_codex_scope_resolved
    mode_args="$structural_arg --tasks=$CODEX_TASKS"
    scope_guidance="Selected tasks: $CODEX_TASKS; $CODEX_SELECTION_TOTAL_CELLS stage-native A/B/C cells."
  else
    mode_args="$structural_arg"
    scope_guidance=""
  fi
  cat >&2 <<EOF

Review the exact no-model plan first:
  bash benchmarks/run-all.sh codex${mode_args} --dry-run

Then launch the paid study with the short approval token printed above:
  CODEX_PAID_APPROVAL=<approval-token-printed-above> \\
  CODEX_AUTH_SOURCE="\$HOME/.codex/auth.json" \\
    bash benchmarks/run-all.sh codex${mode_args}

The command records paid authorization for this exact aggregate scope. The launcher creates a fresh run directory under benchmarks/results; set CODEX_RUN_DIR only to choose another new path. Review benchmarks/manifests/codex-integration.md for the locked scope.
Credential warning: use an immutable, user-owned 0600 auth source. Do not run a concurrent Codex session with it; use an independently authenticated benchmark credential instead. The runner keeps private run state and atomically propagates valid refreshes between cells. A private sequential refresh can invalidate an unchanged source, so reauthenticate after the run if needed. Known refresh-token authentication failures stop immediately; three matching unknown zero-token pre-response failures preserve partial artifacts and stop scheduling.
${scope_guidance:+$'\n'"$scope_guidance"$'\n'}
EOF
}

print_codex_agentic_paid_guidance() {
  local agentic_manifest_sha
  local repetition_arg=""
  local selection_arg=""
  agentic_manifest_sha="$(sha256_file "$AGENTIC_MANIFEST_PATH")"
  if [ -z "$AGENTIC_SCOPE_SHA" ]; then
    resolve_agentic_scope
  fi
  if [ -n "$CODEX_TASKS" ] || [ "$AGENTIC_REPETITIONS" != "1" ]; then
    approval_hint="$AGENTIC_SCOPE_SHA"
  else
    approval_hint="$agentic_manifest_sha"
  fi
  if [ -n "$CODEX_TASKS" ]; then
    selection_arg=" --tasks=$CODEX_TASKS"
  fi
  if [ "$AGENTIC_REPETITIONS" != "1" ]; then
    repetition_arg=" --repetitions=$AGENTIC_REPETITIONS"
  fi
  cat >&2 <<EOF

Review the exact no-model shared agentic plan:
  bash benchmarks/run-all.sh codex --agentic${selection_arg}${repetition_arg} --dry-run

Then launch the paid $AGENTIC_TOTAL_CELLS-cell study with one scope-bound command:
  CODEX_AGENTIC_PAID_APPROVAL=$approval_hint \\
  CODEX_AUTH_SOURCE="\$HOME/.codex/auth.json" \\
    bash benchmarks/run-all.sh codex --agentic${selection_arg}${repetition_arg}

The launcher creates a fresh run directory under benchmarks/results; set CODEX_RUN_DIR only to choose another new path. Review benchmarks/manifests/codex-agentic.md for the locked scope before running the paid study.
Credential warning: use an immutable, user-owned 0600 auth source. Do not run a concurrent Codex session with it; use an independently authenticated benchmark credential instead. The runner keeps private run state and atomically propagates valid refreshes between cells. A private sequential refresh can invalidate an unchanged source, so reauthenticate after the run if needed.
EOF
}

require_codex_agentic_paid_inputs() {
  if [ ! -f "$AGENTIC_MANIFEST_PATH" ]; then
    echo "ERROR: active Codex agentic manifest is missing: $AGENTIC_MANIFEST_PATH" >&2
    exit 2
  fi
  local agentic_manifest_sha
  agentic_manifest_sha="$(sha256_file "$AGENTIC_MANIFEST_PATH")"
  resolve_agentic_scope
  if [ -n "$CODEX_TASKS" ] || [ "$AGENTIC_REPETITIONS" != "1" ]; then
    approval_hint="$AGENTIC_SCOPE_SHA"
  else
    approval_hint="$agentic_manifest_sha"
  fi
  if [ "${CODEX_AGENTIC_PAID_APPROVAL:-}" != "$approval_hint" ]; then
    echo "ERROR: paid Codex agentic mode requires CODEX_AGENTIC_PAID_APPROVAL=$approval_hint" >&2
    print_codex_agentic_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_AUTH_SOURCE:-}" ] || [ ! -f "$CODEX_AUTH_SOURCE" ]; then
    echo "ERROR: paid Codex agentic mode requires CODEX_AUTH_SOURCE pointing to a private auth.json." >&2
    print_codex_agentic_paid_guidance
    exit 2
  fi
  set_default_codex_run_dir
  if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" = "1" ]; then
    expected_launcher="$CODEX_RUN_DIR/.launcher/run-all.sh"
    if [ "$0" != "$expected_launcher" ] || [ "${CODEX_INVOCATION_LAUNCHER:-}" != "$expected_launcher" ]; then
      echo "ERROR: paid Codex agentic mode is not executing its private launcher snapshot." >&2
      exit 2
    fi
    if [ "$(sha256_file "$expected_launcher")" != "${CODEX_LAUNCHER_SHA256:-}" ]; then
      echo "ERROR: paid Codex agentic launcher snapshot changed before execution." >&2
      exit 2
    fi
    validate_paid_source_snapshot
  elif [ -e "$CODEX_RUN_DIR" ]; then
    echo "ERROR: CODEX_RUN_DIR already exists: $CODEX_RUN_DIR" >&2
    print_codex_agentic_paid_guidance
    exit 2
  fi
}

print_codex_combined_paid_guidance() {
  local agentic_manifest_sha
  agentic_manifest_sha="$(sha256_file "$AGENTIC_MANIFEST_PATH")"
  cat >&2 <<EOF

Review both exact no-model plans first:
  bash benchmarks/run-all.sh codex --dry-run

Then launch the paid structural and agentic studies from one frozen source:
  CODEX_PAID_APPROVAL=<approval-token-printed-by-the-unified-dry-run> \
  CODEX_AGENTIC_PAID_APPROVAL=$agentic_manifest_sha \
  CODEX_AUTH_SOURCE="\$HOME/.codex/auth.json" \
    bash benchmarks/run-all.sh codex

The launcher creates one combined result root with structural/ and agentic/ child runs; set CODEX_RUN_DIR only to choose another new combined root. Review benchmarks/manifests/codex-integration.md and benchmarks/manifests/codex-agentic.md before running the paid studies.
Credential warning: use an immutable, user-owned 0600 auth source. Do not run a concurrent Codex session with it; use an independently authenticated benchmark credential instead. The two studies run sequentially and stop on the first failure while preserving completed artifacts.
EOF
}

require_codex_combined_paid_inputs() {
  local agentic_manifest_sha expected_launcher
  agentic_manifest_sha="$(sha256_file "$AGENTIC_MANIFEST_PATH")"
  if [[ ! "${CODEX_PAID_APPROVAL:-}" =~ ^[0-9a-f]{16,64}$ ]] || [ "${CODEX_AGENTIC_PAID_APPROVAL:-}" != "$agentic_manifest_sha" ]; then
    echo "ERROR: paid combined Codex mode requires the unified short approval token and exact agentic approval." >&2
    print_codex_combined_paid_guidance
    exit 2
  fi
  if [ -z "${CODEX_AUTH_SOURCE:-}" ] || [ ! -f "$CODEX_AUTH_SOURCE" ]; then
    echo "ERROR: paid combined Codex mode requires CODEX_AUTH_SOURCE pointing to a private auth.json." >&2
    print_codex_combined_paid_guidance
    exit 2
  fi
  set_default_codex_run_dir
  if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" = "1" ]; then
    expected_launcher="$CODEX_RUN_DIR/.launcher/run-all.sh"
    if [ "$0" != "$expected_launcher" ] || [ "${CODEX_INVOCATION_LAUNCHER:-}" != "$expected_launcher" ]; then
      echo "ERROR: paid combined Codex mode is not executing its private launcher snapshot." >&2
      exit 2
    fi
    if [ "$(sha256_file "$expected_launcher")" != "${CODEX_LAUNCHER_SHA256:-}" ]; then
      echo "ERROR: paid combined Codex launcher snapshot changed before execution." >&2
      exit 2
    fi
    validate_paid_source_snapshot
  elif [ -e "$CODEX_RUN_DIR" ]; then
    echo "ERROR: CODEX_RUN_DIR already exists: $CODEX_RUN_DIR" >&2
    print_codex_combined_paid_guidance
    exit 2
  fi
}

resolve_codex_tasks() {
  local selection_json
  if ! selection_json="$(python3 "$ROOT/benchmarks/run-codex-structural.py" \
    --manifest-path "$MANIFEST_PATH" \
    --resolve-tasks "$CODEX_TASKS" 2>&1)"; then
    echo "ERROR: invalid Codex task selection '$CODEX_TASKS':" >&2
    echo "$selection_json" >&2
    return 2
  fi
  if ! CODEX_SELECTION_SCOPE_SHA="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["scope_sha256"])' <<<"$selection_json" 2>/dev/null)" \
    || ! CODEX_SELECTION_TOTAL_CELLS="$(python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["total_cells"])' <<<"$selection_json" 2>/dev/null)"; then
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
  coordinate_timeout="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["execution_controls"]["parity_timeout_seconds"])' "$MANIFEST_PATH")"
  codex_model="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["name"])' "$MANIFEST_PATH")"
  codex_reasoning_effort="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["reasoning_effort"])' "$MANIFEST_PATH")"
  task_count="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["task_selection"]["allowed_task_ids"]))' "$MANIFEST_PATH")"
  planned_cells="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["task_selection"]["default_total_cells"])' "$MANIFEST_PATH")"
  echo "== CODEX UNIFIED TASK STUDY =="
  echo "→ design: $planned_cells cells ($task_count tasks × A/B/C; stage-native scoring)"
  echo "→ stages: 55 structural + 6 ReadCrop + 4 Fix-Single + 3 Fix-Multi + 5 Patch"
  echo "→ model: $codex_model; reasoning effort: $codex_reasoning_effort"
  echo "→ timeout: $coordinate_timeout seconds per cell, including retries"
  echo "→ manifest: $MANIFEST_PATH ($active_manifest_sha)"
  common_args=(
    --repo-path "$REPO" \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model "$codex_model" \
    --reasoning-effort "$codex_reasoning_effort"
  )
}

configure_codex_selected_plan() {
  ensure_codex_scope_resolved
  active_manifest_sha="$(sha256_file "$MANIFEST_PATH")"
  codex_model="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["name"])' "$MANIFEST_PATH")"
  codex_reasoning_effort="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["reasoning_effort"])' "$MANIFEST_PATH")"
  selected_task_count="${#CODEX_SELECTION_TASK_IDS[@]}"
  selected_cells="$CODEX_SELECTION_TOTAL_CELLS"
  echo "== CODEX SELECTED A/B/C STUDY =="
  echo "→ design: $selected_cells cells ($selected_task_count selected tasks; stage-native scoring)"
  echo "→ tasks: ${CODEX_TASKS}"
  echo "→ model: $codex_model; reasoning effort: $codex_reasoning_effort"
  echo "→ selection scope: $CODEX_SELECTION_SCOPE_SHA"
  common_args=(
    --repo-path "$REPO" \
    --manifest-path "$MANIFEST_PATH" \
    --index-path "$INDEX_PATH" \
    --marketplace-root "$ROOT" \
    --codemap-bin "$CODEMAP_BIN" \
    --model "$codex_model" \
    --reasoning-effort "$codex_reasoning_effort" \
    --tasks "$CODEX_TASKS"
  )
}

run_codex_plan() {
  local plan_output
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
  if ! plan_output="$(mktemp "$BENCHMARK_TEMP_ROOT/codex-unified-plan.XXXXXX")"; then
    echo "ERROR: failed to create the private Codex plan capture." >&2
    return 2
  fi
  if ! python3 "$ROOT/benchmarks/run-codex-structural.py" "${common_args[@]}" --dry-run | tee "$plan_output"; then
    rm -f "$plan_output"
    return 1
  fi
  CODEX_EXECUTION_SCOPE_SHA="$(awk '$1 == "SCOPE" {print $2}' "$plan_output" | tail -n 1)"
  rm -f "$plan_output"
  if [[ ! "$CODEX_EXECUTION_SCOPE_SHA" =~ ^[0-9a-f]{64}$ ]]; then
    echo "ERROR: unified Codex preflight did not emit one valid aggregate SCOPE." >&2
    return 2
  fi
}

run_codex_study() {
  run_codex_plan || return "$?"
  if [[ "$CODEX_EXECUTION_SCOPE_SHA" != "$CODEX_PAID_APPROVAL"* ]]; then
    echo "ERROR: paid Codex mode requires CODEX_PAID_APPROVAL=${CODEX_EXECUTION_SCOPE_SHA:0:16}" >&2
    echo "Copy the short approval token printed by the completed no-model preflight." >&2
    return 2
  fi
  if [ -n "$CODEX_TASKS" ]; then
    echo "== CODEX SELECTED A/B/C STUDY (paid model runs) =="
  else
    echo "== CODEX CONFIRMATORY A/B/C STUDY (paid model runs) =="
  fi
  python3 "$ROOT/benchmarks/run-codex-structural.py" \
    "${common_args[@]}" \
    --auth-source "$CODEX_AUTH_SOURCE" \
    --invocation-launcher-path "$CODEX_INVOCATION_LAUNCHER" \
    --no-legend \
    --run-dir "$CODEX_RUN_DIR/benchmark" \
    --paid-approval "${CODEX_EXECUTION_SCOPE_SHA:0:16}"
}

run_codex_agentic_prepared_plan() {
  resolve_agentic_scope || return "$?"
  echo "== CODEX SHARED AGENTIC A/B/C PREFLIGHT (no model) =="
  echo "→ design: $AGENTIC_TOTAL_CELLS cells (${#AGENTIC_TASK_IDS[@]} tasks × $AGENTIC_REPETITIONS repetitions × 3 arms; nonpoolable)"
  echo "→ scope: $AGENTIC_SCOPE_SHA"
  configure_agentic_dispatch
  python3 "$AGENTIC_RUNNER" "${AGENTIC_DISPATCH_ARGS[@]}" --dry-run
  if [ -n "$CODEX_TASKS" ]; then
    print_codex_agentic_paid_guidance
  fi
}

run_codex_agentic_plan() {
  # Agentic execution reuses the structural target/index preparation contract
  # but resolves its own shared task/repeat scope before dispatch.
  prepare_locked_inputs || return "$?"
  validate_codex_cli || return "$?"
  run_codex_agentic_prepared_plan
}

run_codex_agentic_study() {
  local agentic_manifest_sha agentic_model agentic_reasoning_effort
  agentic_manifest_sha="$(sha256_file "$AGENTIC_MANIFEST_PATH")"
  resolve_agentic_scope
  echo "== CODEX SHARED AGENTIC A/B/C STUDY =="
  echo "→ design: $AGENTIC_TOTAL_CELLS cells (${#AGENTIC_TASK_IDS[@]} tasks × $AGENTIC_REPETITIONS repetitions × 3 arms; nonpoolable)"
  agentic_model="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["name"])' "$AGENTIC_MANIFEST_PATH")"
  agentic_reasoning_effort="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["model"]["reasoning_effort"])' "$AGENTIC_MANIFEST_PATH")"
  echo "→ model: $agentic_model; reasoning effort: $agentic_reasoning_effort"
  echo "→ timeout: $AGENTIC_COORDINATE_TIMEOUT seconds per cell, including retries"
  echo "→ manifest: $AGENTIC_MANIFEST_PATH ($agentic_manifest_sha)"
  echo "→ scope: $AGENTIC_SCOPE_SHA"
  echo "ARTIFACTS:"
  echo " - telemetry=$CODEX_RUN_DIR/telemetry.jsonl"
  echo " - metadata=$CODEX_RUN_DIR/run-metadata.json"
  configure_agentic_dispatch
  python3 "$AGENTIC_RUNNER" \
    "${AGENTIC_DISPATCH_ARGS[@]}" \
    --auth-source "$CODEX_AUTH_SOURCE" \
    --invocation-launcher-path "$CODEX_INVOCATION_LAUNCHER" \
    --run-dir "$CODEX_RUN_DIR" \
    --paid-approval "$CODEX_AGENTIC_PAID_APPROVAL"
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
  write_codex_result_checksums "$checksum_path"
  echo "→ artifact checksums: $checksum_path"
  return "$run_status"
}

run_codex_agentic_with_artifacts() {
  # Agentic owns its run metadata/log lifecycle. Capture outside the admitted
  # run directory so Python still sees only the locked launcher at startup.
  local study_runner="$1"
  local stream_path
  local render_status
  local -a pipeline_status
  if ! stream_path="$(mktemp "$BENCHMARK_TEMP_ROOT/codex-agentic-console.XXXXXX")"; then
    echo "ERROR: failed to create the private Codex agentic console stream." >&2
    print_codex_agentic_paid_guidance
    return 2
  fi
  if "$study_runner" 2>&1 | tee "$stream_path" | python3 "$ROOT/benchmarks/run-codex-structural.py" --render-results --hide-plan; then
    pipeline_status=("${PIPESTATUS[@]}")
  else
    pipeline_status=("${PIPESTATUS[@]}")
  fi
  run_status="${pipeline_status[0]:-1}"
  render_status="${pipeline_status[2]:-1}"
  if [ "$run_status" -eq 0 ] && [ "$render_status" -ne 0 ]; then
    run_status="$render_status"
  fi
  cp "$stream_path" "$CODEX_RUN_DIR/run.log"
  rm -f "$stream_path"
  checksum_path="$CODEX_RUN_DIR/checksums.sha256"
  write_codex_result_checksums "$checksum_path"
  echo "→ artifact checksums: $checksum_path"
  if [ "$run_status" -ne 0 ]; then
    echo "ERROR: Codex agentic execution failed. Preserve the reported artifact for diagnosis; any retry requires a fresh CODEX_RUN_DIR." >&2
    print_codex_agentic_paid_guidance
  fi
  return "$run_status"
}

run_codex_combined_child() {
  local child_run_dir="$1"
  local selector="$2"
  validate_paid_source_snapshot
  (
    unset CODEX_INVOCATION_LAUNCHER CODEX_LAUNCHER_SHA256 CODEX_LAUNCHER_SNAPSHOT_ACTIVE
    export CODEX_RUN_DIR="$child_run_dir"
    /bin/bash "$ROOT/benchmarks/run-all.sh" codex "$selector"
  )
}

run_codex_combined_studies() {
  local combined_root="$CODEX_RUN_DIR"
  run_codex_combined_child "$combined_root/structural" --struct
  run_codex_combined_child "$combined_root/agentic" --agentic
}

case "$MODE" in
  smoke)
    prepare_locked_inputs
    smoke
    ;;
  claude)
    prepare_claude_inputs
    if [ "$AGENTIC" = true ]; then
      if [ "$DRY_RUN" = true ]; then
        run_claude_agentic_plan
      else
        run_claude_agentic_study
      fi
    elif [ "$STRUCTURAL" = true ]; then
      if [ "$DRY_RUN" = true ]; then
        run_claude_structural_plan
      else
        run_claude_structural_study
      fi
    elif [ "$DRY_RUN" = true ]; then
      run_claude_plan
    else
      claude
    fi
    ;;
  codex)
    if [ "$AGENTIC" = true ]; then
      if [ "$DRY_RUN" = true ]; then
        run_codex_agentic_plan
      else
        require_codex_agentic_paid_inputs
        if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" != "1" ]; then
          exec_codex_launcher_snapshot "$@"
        fi
        prepare_locked_inputs
        validate_codex_cli
        run_codex_agentic_with_artifacts run_codex_agentic_study
      fi
      echo "→ done. Results in benchmarks/results/"
      exit 0
    fi
    if [ "$STRUCTURAL" = true ]; then
      if [ -n "$CODEX_TASKS" ]; then
        ensure_codex_scope_resolved
      fi
      if [ "$DRY_RUN" = true ]; then
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
    elif [ "$DRY_RUN" = true ]; then
      prepare_locked_inputs
      validate_codex_cli
      run_codex_plan
      run_codex_agentic_prepared_plan
    else
      require_codex_combined_paid_inputs
      if [ "${CODEX_LAUNCHER_SNAPSHOT_ACTIVE:-}" != "1" ]; then
        exec_codex_launcher_snapshot "$@"
      fi
      run_codex_combined_studies
    fi
    ;;
esac

echo "→ done. Results in benchmarks/results/"
