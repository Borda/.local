#!/usr/bin/env bash
set -euo pipefail

OUT_DIR=""
LINT_CMD="${LINT_CMD:-}"
FORMAT_CMD="${FORMAT_CMD:-}"
TYPES_CMD="${TYPES_CMD:-}"
TESTS_CMD="${TESTS_CMD:-}"
REVIEW_CMD="${REVIEW_CMD:-}"
TIMEOUT_SECONDS="${GATE_TIMEOUT_SECONDS:-900}"
LINT_SKIP_REASON=""
FORMAT_SKIP_REASON=""
TYPES_SKIP_REASON=""
TESTS_SKIP_REASON=""
REVIEW_SKIP_REASON=""

usage() {
  cat <<'EOF'
Usage: run-gates.sh --out DIR [gate options] [--timeout-seconds N]

Run the canonical lint, format, types, tests, and review gates and write
gates.json, gates.txt, failed.txt, gates.checks.jsonl, and per-gate logs.

Gate commands:
  --lint CMD            Lint command
  --format CMD          Format-check command
  --types CMD           Type-check command
  --tests CMD           Test command
  --review CMD          Review command

Explicit not-applicable gates:
  --skip-lint REASON
  --skip-format REASON
  --skip-types REASON
  --skip-tests REASON
  --skip-review REASON

Other options:
  --out DIR             Required artifact directory
  --timeout-seconds N   Per-gate timeout; default 900 or GATE_TIMEOUT_SECONDS
  -h, --help            Show this help

Each gate requires either a command or an explicit skip reason. Exit 0 means
all applicable gates passed, 1 means a gate failed, 124 means timeout, and 2
means invalid CLI input.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
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
    --skip-lint)
      LINT_SKIP_REASON="$2"
      shift 2
      ;;
    --skip-format)
      FORMAT_SKIP_REASON="$2"
      shift 2
      ;;
    --skip-types)
      TYPES_SKIP_REASON="$2"
      shift 2
      ;;
    --skip-tests)
      TESTS_SKIP_REASON="$2"
      shift 2
      ;;
    --skip-review)
      REVIEW_SKIP_REASON="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
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
if [[ ! "$TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
  echo "invalid-timeout-seconds:$TIMEOUT_SECONDS" >&2
  exit 2
fi
for reason in "$LINT_SKIP_REASON" "$FORMAT_SKIP_REASON" "$TYPES_SKIP_REASON" "$TESTS_SKIP_REASON" "$REVIEW_SKIP_REASON"; do
  if [[ "$reason" == *$'\n'* ]]; then
    echo "invalid-skip-reason:newline" >&2
    exit 2
  fi
done

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
  LINT_CMD='if command -v ruff >/dev/null 2>&1; then ruff check .; elif command -v uv >/dev/null 2>&1; then uv run --no-sync ruff check .; else echo "missing-command:ruff" >&2; exit 127; fi'
fi
if [[ -z "$FORMAT_CMD" ]]; then
  FORMAT_CMD='if command -v ruff >/dev/null 2>&1; then ruff format --check .; elif command -v uv >/dev/null 2>&1; then uv run --no-sync ruff format --check .; else echo "missing-command:ruff" >&2; exit 127; fi'
fi
if [[ -z "$TYPES_CMD" ]]; then
  if [[ ! -d src ]]; then
    TYPES_CMD=":"
    TYPES_SKIP_REASON="no src directory or typed package target"
  else
    TYPES_CMD='if command -v mypy >/dev/null 2>&1; then mypy src/; elif command -v uv >/dev/null 2>&1; then uv run --no-sync mypy src/; else echo "missing-command:mypy" >&2; exit 127; fi'
  fi
fi
if [[ -z "$TESTS_CMD" ]]; then
  TESTS_CMD='if command -v pytest >/dev/null 2>&1; then pytest -q; elif command -v uv >/dev/null 2>&1; then uv run --no-sync pytest -q; else echo "missing-command:pytest" >&2; exit 127; fi'
fi
if [[ -z "$REVIEW_CMD" ]]; then
  REVIEW_CMD='git diff --check'
fi

run_check() {
  local id="$1"
  local cmd="$2"
  local skip_reason="$3"
  local stdout_file="$CHECKS_DIR/$id.stdout.txt"
  local stderr_file="$CHECKS_DIR/$id.stderr.txt"
  local command_file="$CHECKS_DIR/$id.command.txt"
  local status="pass"
  local exit_code=0
  local reason=""
  local start
  local end
  local duration

  if [[ -n "$skip_reason" ]]; then
    echo "$id:not-applicable" >> "$GATES_TXT"
    : > "$stdout_file"
    printf '%s\n' "not-applicable:$skip_reason" > "$stderr_file"
    printf '%s\n' "not-applicable: $skip_reason" > "$command_file"
    python3 - "$CHECKS_JSONL" "$id" "$command_file" "$stdout_file" "$stderr_file" "$skip_reason" <<'PY'
import json
import sys

path, check_id, command_path, stdout_path, stderr_path, reason = sys.argv[1:]
payload = {
    "id": check_id,
    "status": "not-applicable",
    "exit_code": 0,
    "duration_seconds": 0.0,
    "command_path": command_path,
    "stdout": stdout_path,
    "stderr": stderr_path,
    "reason": reason,
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
PY
    return 0
  fi

  if [[ -z "$cmd" ]]; then
    echo "$id:missing-command" >> "$GATES_TXT"
    echo "$id" >> "$FAILED_TXT"
    : > "$stdout_file"
    echo "missing command" > "$stderr_file"
    : > "$command_file"
    python3 - "$CHECKS_JSONL" "$id" "missing-command" "127" "0" "$command_file" "$stdout_file" "$stderr_file" <<'PY'
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
    "reason": "no command configured for required gate",
}
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
PY
    return 1
  fi

  printf '%s\n' "$cmd" > "$command_file"
  start="$(date +%s)"
  set +e
  python3 - "$cmd" "$TIMEOUT_SECONDS" "$stdout_file" "$stderr_file" <<'PY'
import os
import signal
import subprocess
import sys
from pathlib import Path

command, timeout, stdout_path, stderr_path = sys.argv[1:]
with Path(stdout_path).open("w", encoding="utf-8") as stdout, Path(stderr_path).open("w", encoding="utf-8") as stderr:
    try:
        process = subprocess.Popen(
            ["bash", "-lc", command],
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        result = process.wait(timeout=int(timeout))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        stderr.write(f"timeout: exceeded {timeout} seconds\n")
        raise SystemExit(124) from None
raise SystemExit(result)
PY
  exit_code=$?
  set -e
  end="$(date +%s)"
  duration=$((end - start))

  case "$exit_code" in
    0)
      status="pass"
      ;;
    124)
      status="timeout"
      reason="timeout after ${TIMEOUT_SECONDS} seconds"
      echo "$id" >> "$FAILED_TXT"
      ;;
    127)
      status="missing-command"
      reason="$(sed -n '1p' "$stderr_file")"
      echo "$id" >> "$FAILED_TXT"
      ;;
    *)
      status="fail"
      echo "$id" >> "$FAILED_TXT"
      ;;
  esac

  echo "$id:$status" >> "$GATES_TXT"
  python3 - "$CHECKS_JSONL" "$id" "$status" "$exit_code" "$duration" "$command_file" "$stdout_file" "$stderr_file" "$reason" <<'PY'
import json
import sys

path, check_id, status, exit_code, duration, command_path, stdout_path, stderr_path, reason = sys.argv[1:]
payload = {
    "id": check_id,
    "status": status,
    "exit_code": int(exit_code),
    "duration_seconds": float(duration),
    "command_path": command_path,
    "stdout": stdout_path,
    "stderr": stderr_path,
}
if reason:
    payload["reason"] = reason
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
PY
  [[ "$status" == "pass" ]]
}

run_check "lint" "$LINT_CMD" "$LINT_SKIP_REASON" || true
run_check "format" "$FORMAT_CMD" "$FORMAT_SKIP_REASON" || true
run_check "types" "$TYPES_CMD" "$TYPES_SKIP_REASON" || true
run_check "tests" "$TESTS_CMD" "$TESTS_SKIP_REASON" || true
run_check "review" "$REVIEW_CMD" "$REVIEW_SKIP_REASON" || true

FAILED_COUNT="$(wc -l < "$FAILED_TXT" | tr -d ' ')"
STATUS="pass"
if grep -q '"status": "timeout"' "$CHECKS_JSONL"; then
  STATUS="timeout"
elif [[ "$FAILED_COUNT" -gt 0 ]]; then
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
not_applicable = [check["id"] for check in checks if check["status"] == "not-applicable"]
payload = {
    "status": status,
    "checks_run": [check["id"] for check in checks],
    "checks_failed": failed,
    "failed_count": failed_count,
    "checks_not_applicable": not_applicable,
    "checks": checks,
}
result_path.write_text(json.dumps(payload, indent=2) + "\n")
PY

echo "$RESULT_JSON"
if [[ "$STATUS" == "timeout" ]]; then
  exit 124
fi
if [[ "$STATUS" == "fail" ]]; then
  exit 1
fi
