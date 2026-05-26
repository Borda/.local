#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
OUT_DIR="$ROOT/.reports/codex/calibration/$TS"
mkdir -p "$OUT_DIR"

PROJECT_CFG="$ROOT/.codex/config.toml"
HOME_CFG="$HOME/.codex/config.toml"
TASKS="$ROOT/.codex/calibration/tasks.json"
BENCHMARKS="$ROOT/.codex/calibration/benchmarks.json"
SKILLS=(review develop resolve audit calibrate release investigate sync manage analyse optimize research)
AGENTS=(sw-engineer qa-specialist squeezer doc-scribe security-auditor data-steward cicd-steward linting-expert oss-shepherd solution-architect web-explorer curator challenger scientist)

LEAKS=0
FAILS=0
CHECKS_FAILED=()

mark_check_failed() {
  local check_id="$1"
  local existing
  set +u
  for existing in "${CHECKS_FAILED[@]}"; do
    if [[ "$existing" == "$check_id" ]]; then
      set -u
      return 0
    fi
  done
  set -u
  CHECKS_FAILED+=("$check_id")
}

check_model_value() {
  local file="$1"
  local expected="$2"
  awk -v expected="$expected" '
    BEGIN {
      result = 1
    }
    /^[[:space:]]*#/ {
      next
    }
    /^[[:space:]]*developer_instructions[[:space:]]*=/ {
      exit result
    }
    /^[[:space:]]*\[/ {
      exit result
    }
    /^[[:space:]]*model[[:space:]]*=/ {
      line = $0
      sub(/^[[:space:]]*model[[:space:]]*=[[:space:]]*/, "", line)
      sub(/[[:space:]]*#.*$/, "", line)
      if (line == "\"" expected "\"") {
        result = 0
      }
      exit result
    }
    END {
      exit result
    }
  ' "$file"
}

check_contains() {
  local file="$1"
  local pattern="$2"
  local check_id="$3"
  if ! grep -qi "$pattern" "$file"; then
    echo "missing:$pattern:$file" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "$check_id"
    LEAKS=$((LEAKS + 1))
    return 0
  fi
  return 0
}

check_model() {
  local file="$1"
  local label="$2"
  local check_id="$3"
  if check_model_value "$file" "gpt-5.4-mini"; then
    echo "$label:model=ok" >> "$OUT_DIR/checks.txt"
  else
    echo "$label:model=fail" >> "$OUT_DIR/checks.txt"
    echo "model-not-gpt-5.4-mini:$file" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "$check_id"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
  return 0
}

expected_agent_model() {
  case "$1" in
    sw-engineer | qa-specialist | squeezer | data-steward | linting-expert | cicd-steward | security-auditor)
      echo "gpt-5.3-codex"
      ;;
    solution-architect | challenger | scientist)
      echo "gpt-5.5"
      ;;
    doc-scribe | web-explorer | oss-shepherd | curator)
      echo "gpt-5.4-mini"
      ;;
    *)
      echo "unknown"
      ;;
  esac
}

check_agent_model() {
  local agent="$1"
  local file="$2"
  local expected
  expected="$(expected_agent_model "$agent")"
  if [[ "$expected" == "unknown" ]]; then
    echo "agent-model-policy-missing:$agent" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "agent-model-policy"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
    return 0
  fi
  if check_model_value "$file" "$expected"; then
    echo "agent-model:$agent=$expected" >> "$OUT_DIR/checks.txt"
  else
    echo "agent-model-mismatch:$agent:expected=$expected:$file" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "agent-model-policy"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
  return 0
}

echo "calibration-start:$TS" > "$OUT_DIR/checks.txt"
check_model "$PROJECT_CFG" "project-config" "project-model-default"
check_model "$HOME_CFG" "home-config" "home-model-default"

for skill in "${SKILLS[@]}"; do
  SKILL_FILE="$ROOT/.codex/skills/$skill/SKILL.md"
  if [[ ! -f "$SKILL_FILE" ]]; then
    echo "missing-skill:$skill" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "skill-schema-all"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
    continue
  fi
  check_contains "$SKILL_FILE" "^# " "skill-schema-all"
  check_contains "$SKILL_FILE" "Workflow" "skill-schema-all"
  check_contains "$SKILL_FILE" "Output Contract" "skill-schema-all"
  check_contains "$SKILL_FILE" "quality-gates" "skill-schema-all"
  check_contains "$SKILL_FILE" ".reports/codex/$skill/" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"status\"" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"checks_run\"" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"checks_failed\"" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"findings\"" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"confidence\"" "skill-schema-all"
  check_contains "$SKILL_FILE" "\"artifact_path\"" "skill-schema-all"
  check_contains "$PROJECT_CFG" "path[[:space:]]*=[[:space:]]*\"skills/$skill\"" "skill-registration-project"
  if ! grep -qiE "path[[:space:]]*=[[:space:]]*\"(.*\\/)?skills/$skill\"" "$HOME_CFG"; then
    echo "missing:skills/$skill:$HOME_CFG" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "skill-registration-home"
    LEAKS=$((LEAKS + 1))
  fi
done

if [[ ! -f "$TASKS" ]]; then
  echo "missing-tasks:$TASKS" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "fixed-task-set"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

if [[ ! -f "$BENCHMARKS" ]]; then
  echo "missing-benchmarks:$BENCHMARKS" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "benchmark-pattern-checks"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

for agent in "${AGENTS[@]}"; do
  check_contains "$PROJECT_CFG" "\\[agents\\.$agent\\]" "agent-registration-project"
  check_contains "$HOME_CFG" "\\[agents\\.$agent\\]" "agent-registration-home"
  if [[ -f "$ROOT/.codex/agents/$agent.toml" ]]; then
    check_contains "$ROOT/.codex/agents/$agent.toml" "developer_instructions" "agent-schema-all"
    check_agent_model "$agent" "$ROOT/.codex/agents/$agent.toml"
  else
    echo "missing-agent-file:$agent" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "agent-schema-all"
    mark_check_failed "agent-model-policy"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
done

RUN_GATES="$ROOT/.codex/skills/_shared/run-gates.sh"
WRITE_RESULT="$ROOT/.codex/skills/_shared/write-result.sh"

if [[ ! -x "$RUN_GATES" ]]; then
  echo "shared-script-not-executable:$RUN_GATES" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "shared-script-selftests"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

if [[ ! -x "$WRITE_RESULT" ]]; then
  echo "shared-script-not-executable:$WRITE_RESULT" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "shared-script-selftests"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

SELFTEST_DIR="$OUT_DIR/selftest"
mkdir -p "$SELFTEST_DIR"

if [[ -x "$RUN_GATES" ]]; then
  "$RUN_GATES" \
    --out "$SELFTEST_DIR/gates" \
    --lint "true" \
    --format "true" \
    --types "true" \
    --tests "true" \
    --review "true" >/dev/null
  if [[ ! -f "$SELFTEST_DIR/gates/gates.json" ]]; then
    echo "selftest-missing:gates.json" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "shared-script-selftests"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
fi

if [[ -x "$WRITE_RESULT" ]]; then
  "$WRITE_RESULT" \
    --out "$SELFTEST_DIR/result.json" \
    --status "pass" \
    --checks-run "lint,format,types,tests,review" \
    --checks-failed "" \
    --critical "0" \
    --high "0" \
    --medium "0" \
    --low "0" \
    --confidence "0.95" \
    --artifact-path "$SELFTEST_DIR/result.json" >/dev/null
  if [[ ! -f "$SELFTEST_DIR/result.json" ]]; then
    echo "selftest-missing:result.json" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "shared-script-selftests"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
fi

if [[ -f "$BENCHMARKS" ]]; then
  python3 - "$ROOT" "$BENCHMARKS" "$OUT_DIR/leaks.txt" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
bench = Path(sys.argv[2])
leaks = Path(sys.argv[3])
data = json.loads(bench.read_text())

def record(msg: str) -> None:
    with leaks.open("a", encoding="utf-8") as fh:
        fh.write(msg + "\n")

for skill, patterns in data.get("skills", {}).items():
    path = root / ".codex" / "skills" / skill / "SKILL.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for pat in patterns:
        if not re.search(pat, text, flags=re.IGNORECASE):
            record(f"benchmark-skill-miss:{skill}:{pat}")

for agent, patterns in data.get("agents", {}).items():
    path = root / ".codex" / "agents" / f"{agent}.toml"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for pat in patterns:
        if not re.search(pat, text, flags=re.IGNORECASE):
            record(f"benchmark-agent-miss:{agent}:{pat}")
PY
fi

if [[ -f "$OUT_DIR/leaks.txt" ]]; then
  NEW_FAILS="$(grep -c '^benchmark-.*-miss:' "$OUT_DIR/leaks.txt" || true)"
  if [[ "$NEW_FAILS" -gt 0 ]]; then
    mark_check_failed "benchmark-pattern-checks"
    FAILS=$((FAILS + NEW_FAILS))
    LEAKS=$((LEAKS + NEW_FAILS))
  fi
fi

STATUS="pass"
if [[ "$FAILS" -gt 0 || "$LEAKS" -gt 0 ]]; then
  STATUS="fail"
fi

CHECKS_FAILED_CSV=""
if [[ "${#CHECKS_FAILED[@]}" -gt 0 ]]; then
  CHECKS_FAILED_CSV="$(IFS=,; echo "${CHECKS_FAILED[*]}")"
fi

python3 - "$OUT_DIR/result.json" "$STATUS" "$TS" "$FAILS" "$LEAKS" "$CHECKS_FAILED_CSV" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
status = sys.argv[2]
timestamp = sys.argv[3]
fail_count = int(sys.argv[4])
leak_count = int(sys.argv[5])
checks_failed = [check for check in sys.argv[6].split(",") if check]

payload = {
    "status": status,
    "timestamp": timestamp,
    "checks_run": [
        "project-model-default",
        "home-model-default",
        "skill-schema-all",
        "skill-registration-project",
        "skill-registration-home",
        "agent-registration-project",
        "agent-registration-home",
        "agent-schema-all",
        "agent-model-policy",
        "fixed-task-set",
        "benchmark-pattern-checks",
        "shared-script-selftests",
    ],
    "checks_failed": checks_failed,
    "findings": {
        "critical": 0,
        "high": leak_count,
        "medium": 0,
        "low": 0,
    },
    "confidence": 0.95,
    "artifact_path": f".reports/codex/calibration/{timestamp}/result.json",
    "leaks_found": leak_count,
    "artifacts": {
        "checks": f".reports/codex/calibration/{timestamp}/checks.txt",
        "leaks": f".reports/codex/calibration/{timestamp}/leaks.txt",
        "result": f".reports/codex/calibration/{timestamp}/result.json",
    },
}
result_path.write_text(json.dumps(payload, indent=2) + "\n")
PY

if [[ ! -f "$OUT_DIR/leaks.txt" ]]; then
  touch "$OUT_DIR/leaks.txt"
fi

echo "$OUT_DIR/result.json"
