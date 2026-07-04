#!/usr/bin/env bash
set -euo pipefail

OUT_DIR=""
LINT_CMD="${LINT_CMD:-}"
FORMAT_CMD="${FORMAT_CMD:-}"
TYPES_CMD="${TYPES_CMD:-}"
TESTS_CMD="${TESTS_CMD:-}"
REVIEW_CMD="${REVIEW_CMD:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)
      OUT_DIR="$2"
      shift 2
      ;;
    --lint)
      LINT_CMD="$2"
      shift 2
      ;;
    --format)
      FORMAT_CMD="$2"
      shift 2
      ;;
    --types)
      TYPES_CMD="$2"
      shift 2
      ;;
    --tests)
      TESTS_CMD="$2"
      shift 2
      ;;
    --review)
      REVIEW_CMD="$2"
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
GATES_TXT="$OUT_DIR/gates.txt"
FAILED_TXT="$OUT_DIR/failed.txt"
RESULT_JSON="$OUT_DIR/gates.json"
CHECKS_DIR="$OUT_DIR/checks"
CHECKS_JSONL="$OUT_DIR/gates.checks.jsonl"
: > "$GATES_TXT"
: > "$FAILED_TXT"
: > "$CHECKS_JSONL"
mkdir -p "$CHECKS_DIR"

if [[ -z "$LINT_CMD" ]]; then
  LINT_CMD='if command -v ruff >/dev/null 2>&1; then ruff check .; elif command -v uv >/dev/null 2>&1; then uv run --no-sync ruff check .; else true; fi'
fi
if [[ -z "$FORMAT_CMD" ]]; then
  FORMAT_CMD='if command -v ruff >/dev/null 2>&1; then ruff format --check .; elif command -v uv >/dev/null 2>&1; then uv run --no-sync ruff format --check .; else true; fi'
fi
if [[ -z "$TYPES_CMD" ]]; then
  TYPES_CMD='if [[ -d src ]]; then if command -v mypy >/dev/null 2>&1; then mypy src/; elif command -v uv >/dev/null 2>&1; then uv run --no-sync mypy src/; else true; fi; else true; fi'
fi
if [[ -z "$TESTS_CMD" ]]; then
  TESTS_CMD='if [[ -d tests ]]; then if command -v pytest >/dev/null 2>&1; then pytest -q; elif command -v uv >/dev/null 2>&1; then uv run --no-sync pytest -q; else true; fi; else true; fi'
fi
if [[ -z "$REVIEW_CMD" ]]; then
  REVIEW_CMD='git diff --check'
fi

run_check() {
  local id="$1"
  local cmd="$2"
  local stdout_file="$CHECKS_DIR/$id.stdout.txt"
  local stderr_file="$CHECKS_DIR/$id.stderr.txt"
  local command_file="$CHECKS_DIR/$id.command.txt"
  local status="pass"
  local exit_code=0
  local start
  local end
  local duration

  if [[ -z "$cmd" ]]; then
    echo "$id:missing-command" >> "$GATES_TXT"
    echo "$id" >> "$FAILED_TXT"
    : > "$stdout_file"
    echo "missing command" > "$stderr_file"
    : > "$command_file"
    python3 - "$CHECKS_JSONL" "$id" "missing-command" "" "0" "$command_file" "$stdout_file" "$stderr_file" <<'PY'
import json
import sys

path, check_id, status, exit_code, duration, command_path, stdout_path, stderr_path = sys.argv[1:]
payload = {
    "id": check_id,
    "status": status,
    "exit_code": None if not exit_code else int(exit_code),
    "duration_seconds": float(duration),
    "command_path": command_path,
    "stdout": stdout_path,
    "stderr": stderr_path,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
PY
    return 1
  fi

  printf '%s\n' "$cmd" > "$command_file"
  start="$(date +%s)"
  set +e
  bash -lc "$cmd" >"$stdout_file" 2>"$stderr_file"
  exit_code=$?
  set -e
  end="$(date +%s)"
  duration=$((end - start))

  if [[ "$exit_code" -ne 0 ]]; then
    status="fail"
    echo "$id" >> "$FAILED_TXT"
  fi

  echo "$id:$status" >> "$GATES_TXT"
  python3 - "$CHECKS_JSONL" "$id" "$status" "$exit_code" "$duration" "$command_file" "$stdout_file" "$stderr_file" <<'PY'
import json
import sys

path, check_id, status, exit_code, duration, command_path, stdout_path, stderr_path = sys.argv[1:]
payload = {
    "id": check_id,
    "status": status,
    "exit_code": int(exit_code),
    "duration_seconds": float(duration),
    "command_path": command_path,
    "stdout": stdout_path,
    "stderr": stderr_path,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
PY
  return "$exit_code"
}

run_check "lint" "$LINT_CMD" || true
run_check "format" "$FORMAT_CMD" || true
run_check "types" "$TYPES_CMD" || true
run_check "tests" "$TESTS_CMD" || true
run_check "review" "$REVIEW_CMD" || true

FAILED_COUNT="$(wc -l < "$FAILED_TXT" | tr -d ' ')"
STATUS="pass"
if [[ "$FAILED_COUNT" -gt 0 ]]; then
  STATUS="fail"
fi

python3 - "$STATUS" "$FAILED_COUNT" "$FAILED_TXT" "$RESULT_JSON" "$CHECKS_JSONL" <<'PY'
import json
import sys
from pathlib import Path

status = sys.argv[1]
failed_count = int(sys.argv[2])
failed_path = Path(sys.argv[3])
result_path = Path(sys.argv[4])
checks_jsonl = Path(sys.argv[5])
failed = [line.strip() for line in failed_path.read_text().splitlines() if line.strip()]
checks = []
if checks_jsonl.exists():
    checks = [json.loads(line) for line in checks_jsonl.read_text().splitlines() if line.strip()]
payload = {
    "status": status,
    "checks_run": [check["id"] for check in checks],
    "checks_failed": failed,
    "failed_count": failed_count,
    "checks": checks,
}
result_path.write_text(json.dumps(payload, indent=2) + "\n")
PY

echo "$RESULT_JSON"
