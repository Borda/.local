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
BEHAVIORAL_CASES="$ROOT/.codex/calibration/behavioral-cases.json"
BEHAVIORAL_OBSERVATIONS="$ROOT/.codex/calibration/behavioral-observations.jsonl"
BEHAVIORAL_SCORER="$ROOT/.codex/calibration/score_behavioral.py"
BEHAVIORAL_RESULT="$OUT_DIR/behavioral.json"
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
  if check_model_value "$file" "gpt-5.5"; then
    echo "$label:model=ok" >> "$OUT_DIR/checks.txt"
  else
    echo "$label:model=fail" >> "$OUT_DIR/checks.txt"
    echo "model-not-gpt-5.5:$file" >> "$OUT_DIR/leaks.txt"
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
  check_contains "$SKILL_FILE" "Input Schema" "native-skill-contract"
  check_contains "$SKILL_FILE" "Workflow" "skill-schema-all"
  check_contains "$SKILL_FILE" "Fail-[Ff]ast Rules" "native-skill-contract"
  check_contains "$SKILL_FILE" "Quality Gates" "native-skill-contract"
  check_contains "$SKILL_FILE" "Calibration Hooks" "native-skill-contract"
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

if [[ ! -f "$BEHAVIORAL_CASES" ]]; then
  echo "missing-behavioral-cases:$BEHAVIORAL_CASES" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "behavioral-metrics"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

if [[ ! -f "$BEHAVIORAL_OBSERVATIONS" ]]; then
  echo "missing-behavioral-observations:$BEHAVIORAL_OBSERVATIONS" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "behavioral-metrics"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

if [[ ! -f "$BEHAVIORAL_SCORER" ]]; then
  echo "missing-behavioral-scorer:$BEHAVIORAL_SCORER" >> "$OUT_DIR/leaks.txt"
  mark_check_failed "behavioral-metrics"
  FAILS=$((FAILS + 1))
  LEAKS=$((LEAKS + 1))
fi

for agent in "${AGENTS[@]}"; do
  check_contains "$PROJECT_CFG" "\\[agents\\.$agent\\]" "agent-registration-project"
  check_contains "$HOME_CFG" "\\[agents\\.$agent\\]" "agent-registration-home"
  if [[ -f "$ROOT/.codex/agents/$agent.toml" ]]; then
    check_contains "$ROOT/.codex/agents/$agent.toml" "^name[[:space:]]*=" "agent-schema-all"
    check_contains "$ROOT/.codex/agents/$agent.toml" "developer_instructions" "agent-schema-all"
    check_contains "$ROOT/.codex/agents/$agent.toml" "Boundaries" "native-agent-contract"
    check_contains "$ROOT/.codex/agents/$agent.toml" "Evidence Standard" "native-agent-contract"
    check_contains "$ROOT/.codex/agents/$agent.toml" "TRIGGER when" "native-agent-contract"
    check_contains "$ROOT/.codex/agents/$agent.toml" "SKIP when" "native-agent-contract"
    check_contains "$ROOT/.codex/agents/$agent.toml" "NOT for" "native-agent-contract"
    check_contains "$ROOT/.codex/agents/$agent.toml" "Output Contract" "native-agent-contract"
    check_agent_model "$agent" "$ROOT/.codex/agents/$agent.toml"
  else
    echo "missing-agent-file:$agent" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "agent-schema-all"
    mark_check_failed "agent-model-policy"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
  fi
done

python3 - "$ROOT" "$OUT_DIR/leaks.txt" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
leaks = Path(sys.argv[2])
targets = list((root / ".codex" / "skills").glob("*/SKILL.md"))
targets.extend((root / ".codex" / "agents").glob("*.toml"))

def token(*parts: str) -> str:
    return "".join(parts)

patterns = {
    "external-path-variable": re.compile(token("CLAUDE", "_", "PLUGIN", "_", "ROOT")),
    "interactive-widget": re.compile(token("Ask", "User", "Question")),
    "task-widget-create": re.compile(token("Task", "Create")),
    "task-widget-update": re.compile(token("Task", "Update")),
    "background-runner": re.compile(token("run", "_", "in", "_", "background")),
    "web-fetch-tool": re.compile(token("Web", "Fetch")),
    "web-search-tool": re.compile(token("Web", "Search")),
    "frontmatter-tools": re.compile(r"^tools\s*:", re.MULTILINE),
    "frontmatter-max-turns": re.compile(r"^maxTurns\s*:", re.MULTILINE),
    "frontmatter-isolation": re.compile(r"^isolation\s*:", re.MULTILINE),
    "frontmatter-memory": re.compile(r"^memory\s*:", re.MULTILINE),
    "frontmatter-tool-allowlist": re.compile(token("allowed", "-", "tools")),
    "frontmatter-disable-model": re.compile(token("disable", "-", "model", "-", "invocation")),
}

with leaks.open("a", encoding="utf-8") as handle:
    for path in sorted(targets):
        text = path.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            if pattern.search(text):
                rel = path.relative_to(root)
                handle.write(f"native-runtime-leak:{label}:{rel}\n")
PY

NATIVE_RUNTIME_LEAKS=0
if [[ -f "$OUT_DIR/leaks.txt" ]]; then
  NATIVE_RUNTIME_LEAKS="$(grep -c '^native-runtime-leak:' "$OUT_DIR/leaks.txt" || true)"
fi
if [[ "$NATIVE_RUNTIME_LEAKS" -gt 0 ]]; then
  mark_check_failed "native-runtime-leakage"
  FAILS=$((FAILS + NATIVE_RUNTIME_LEAKS))
  LEAKS=$((LEAKS + NATIVE_RUNTIME_LEAKS))
fi

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

if [[ -f "$BEHAVIORAL_CASES" && -f "$BEHAVIORAL_OBSERVATIONS" && -f "$BEHAVIORAL_SCORER" ]]; then
  if python3 "$BEHAVIORAL_SCORER" \
    --cases "$BEHAVIORAL_CASES" \
    --observations "$BEHAVIORAL_OBSERVATIONS" \
    --out "$BEHAVIORAL_RESULT" >/dev/null; then
    BEHAVIORAL_STATUS="$(python3 - "$BEHAVIORAL_RESULT" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
overall = payload["overall"]
freshness = payload.get("observation_freshness", {})
print(
    "status={status}:recall={recall}:precision={precision}:confidence_accuracy={confidence_accuracy}:live_observations={live_observations}".format(
        status=payload["status"],
        recall=overall["recall"],
        precision=overall["precision"],
        confidence_accuracy=overall["confidence_accuracy"],
        live_observations=freshness.get("live_observations", 0),
    )
)
PY
)"
    echo "behavioral:$BEHAVIORAL_STATUS" >> "$OUT_DIR/checks.txt"
    if [[ "$BEHAVIORAL_STATUS" == status=fail:* ]]; then
      BEHAVIORAL_FAIL_COUNT="$(python3 - "$BEHAVIORAL_RESULT" "$OUT_DIR/leaks.txt" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
leaks_path = Path(sys.argv[2])
checks_failed = payload.get("checks_failed", [])
if not checks_failed:
    checks_failed = ["behavioral-status"]
with leaks_path.open("a", encoding="utf-8") as handle:
    for check in checks_failed:
        handle.write(f"behavioral-fail:{check}\n")
print(len(checks_failed))
PY
)"
      mark_check_failed "behavioral-metrics"
      FAILS=$((FAILS + BEHAVIORAL_FAIL_COUNT))
      LEAKS=$((LEAKS + BEHAVIORAL_FAIL_COUNT))
    fi
  else
    echo "behavioral-scorer-error:$BEHAVIORAL_SCORER" >> "$OUT_DIR/leaks.txt"
    mark_check_failed "behavioral-metrics"
    FAILS=$((FAILS + 1))
    LEAKS=$((LEAKS + 1))
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

python3 - "$OUT_DIR/result.json" "$STATUS" "$TS" "$FAILS" "$LEAKS" "$CHECKS_FAILED_CSV" "$BEHAVIORAL_RESULT" "$OUT_DIR/recommendations.md" "$OUT_DIR/leaks.txt" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
status = sys.argv[2]
timestamp = sys.argv[3]
fail_count = int(sys.argv[4])
leak_count = int(sys.argv[5])
checks_failed = [check for check in sys.argv[6].split(",") if check]
behavioral_path = Path(sys.argv[7])
recommendations_path = Path(sys.argv[8])
leaks_path = Path(sys.argv[9])
behavioral = json.loads(behavioral_path.read_text()) if behavioral_path.exists() else None

def metric(behavioral_payload, name, default=0.0):
    if not behavioral_payload:
        return default
    return behavioral_payload.get("gate_metrics_raw", behavioral_payload.get("overall", {})).get(name, default)

def rounded(value):
    return round(float(value), 3)

def top_case_gaps(behavioral_payload, key, limit=5):
    if not behavioral_payload:
        return []
    cases = [case for case in behavioral_payload.get("case_results", []) if int(case.get(key, 0)) > 0]
    return sorted(
        cases,
        key=lambda case: (int(case.get(key, 0)), float(case.get("confidence_error", 0.0))),
        reverse=True,
    )[:limit]

def confidence_outliers(behavioral_payload, limit=5):
    if not behavioral_payload:
        return []
    cases = behavioral_payload.get("case_results", [])
    return sorted(cases, key=lambda case: float(case.get("confidence_error", 0.0)), reverse=True)[:limit]

def build_recommendations(behavioral_payload, failed_checks, leak_total):
    recommendations = []
    follow_up = []

    if failed_checks:
        recommendations.append(
            "Fix failed calibration checks first: " + ", ".join(failed_checks) + "."
        )
    if leak_total:
        recommendations.append(
            f"Inspect leaks.txt and fix {leak_total} missing or mismatched config references before widening changes."
        )

    if not behavioral_payload:
        recommendations.append("Restore behavioral scoring output; behavioral.json was not produced.")
        return recommendations, follow_up

    thresholds = behavioral_payload.get("thresholds", {})
    raw = behavioral_payload.get("gate_metrics_raw", behavioral_payload.get("overall", {}))
    recall = float(raw.get("recall", 0.0))
    precision = float(raw.get("precision", 0.0))
    confidence_mae = float(raw.get("confidence_mae", 0.0))
    confidence_accuracy = max(0.0, 1.0 - confidence_mae)
    mean_overconfidence = float(raw.get("mean_overconfidence", 0.0))
    observations = int(raw.get("observations", 0))
    min_observations = float(thresholds.get("min_observations", 1.0))
    min_recall = float(thresholds.get("min_recall", 0.75))
    min_precision = float(thresholds.get("min_precision", 0.75))
    max_confidence_mae = float(thresholds.get("max_confidence_mae", 0.2))
    max_mean_overconfidence = float(thresholds.get("max_mean_overconfidence", 0.15))

    if observations < min_observations:
        recommendations.append(
            f"Add behavioral observations: {observations} present, threshold is {rounded(min_observations)}."
        )
    if recall < min_recall or int(raw.get("fn", 0)) > 0:
        gaps = top_case_gaps(behavioral_payload, "fn")
        if gaps:
            detail = "; ".join(
                f"{case['case_id']} missed {case['fn']} expected finding(s)"
                for case in gaps
            )
            recommendations.append(
                f"Improve recall by addressing missing expected findings: {detail}."
            )
        else:
            recommendations.append(
                f"Improve behavioral recall from {rounded(recall)} toward threshold {rounded(min_recall)}."
            )
    if precision < min_precision or int(raw.get("fp", 0)) > 0:
        gaps = top_case_gaps(behavioral_payload, "fp")
        if gaps:
            detail = "; ".join(
                f"{case['case_id']} reported {case['fp']} unsupported finding(s)"
                for case in gaps
            )
            recommendations.append(
                f"Improve precision by removing unsupported observations or updating expected ground truth with evidence: {detail}."
            )
        else:
            recommendations.append(
                f"Improve behavioral precision from {rounded(precision)} toward threshold {rounded(min_precision)}."
            )
    if confidence_mae > max_confidence_mae:
        recommendations.append(
            f"Reduce confidence calibration error: MAE {rounded(confidence_mae)} exceeds threshold {rounded(max_confidence_mae)}."
        )
    elif confidence_accuracy < 0.9:
        outliers = confidence_outliers(behavioral_payload, limit=3)
        detail = "; ".join(
            f"{case['case_id']} confidence {case['confidence']} vs F1 {case['f1']}"
            for case in outliers
        )
        recommendations.append(
            f"Review stale confidence labels; confidence accuracy is {rounded(confidence_accuracy)}. Largest gaps: {detail}."
        )
    if mean_overconfidence > max_mean_overconfidence:
        recommendations.append(
            f"Reduce overconfidence: mean overconfidence {rounded(mean_overconfidence)} exceeds threshold {rounded(max_mean_overconfidence)}."
        )

    freshness = behavioral_payload.get("observation_freshness", {})
    if int(freshness.get("live_observations", 0) or 0) == 0:
        follow_up.append(
            "Add source=live-* observations from real Codex calibration prompts before treating fixture metrics as live model quality."
        )
    if int(freshness.get("missing_observed_at", 0) or 0) > 0:
        follow_up.append("Backfill missing observed_at timestamps in behavioral observations.")

    if not recommendations:
        recommendations.append(
            "No blocking calibration fixes found; maintain the current gates and collect live observations next."
        )

    return recommendations, follow_up

recommendations, follow_up = build_recommendations(behavioral, checks_failed, leak_count)

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
        "native-skill-contract",
        "native-agent-contract",
        "native-runtime-leakage",
        "fixed-task-set",
        "benchmark-pattern-checks",
        "behavioral-metrics",
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
    "behavioral": behavioral,
    "recommendations": recommendations,
    "follow_up": follow_up,
    "artifacts": {
        "checks": f".reports/codex/calibration/{timestamp}/checks.txt",
        "leaks": f".reports/codex/calibration/{timestamp}/leaks.txt",
        "behavioral": f".reports/codex/calibration/{timestamp}/behavioral.json",
        "recommendations": f".reports/codex/calibration/{timestamp}/recommendations.md",
        "result": f".reports/codex/calibration/{timestamp}/result.json",
    },
}
result_path.write_text(json.dumps(payload, indent=2) + "\n")

lines = [
    "# Calibration Recommendations",
    "",
    f"Status: {status}",
    f"Checks failed: {', '.join(checks_failed) if checks_failed else 'none'}",
    f"Leaks found: {leak_count}",
]
if behavioral:
    overall = behavioral.get("overall", {})
    freshness = behavioral.get("observation_freshness", {})
    lines.extend(
        [
            "",
            "## Behavioral Summary",
            "",
            f"- Recall: {overall.get('recall')}",
            f"- Precision: {overall.get('precision')}",
            f"- F1: {overall.get('f1')}",
            f"- Confidence accuracy: {overall.get('confidence_accuracy')}",
            f"- Mean overconfidence: {overall.get('mean_overconfidence')}",
            f"- Fixture observations: {freshness.get('fixture_observations', 0)}",
            f"- Live observations: {freshness.get('live_observations', 0)}",
        ]
    )
lines.extend(["", "## Recommendations", ""])
lines.extend(f"- {item}" for item in recommendations)
if follow_up:
    lines.extend(["", "## Follow-Up", ""])
    lines.extend(f"- {item}" for item in follow_up)
if leaks_path.exists() and leaks_path.read_text(encoding="utf-8").strip():
    lines.extend(["", "## Leak Details", ""])
    lines.extend(f"- {line}" for line in leaks_path.read_text(encoding="utf-8").splitlines() if line.strip())
recommendations_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

if [[ ! -f "$OUT_DIR/leaks.txt" ]]; then
  touch "$OUT_DIR/leaks.txt"
fi

echo "$OUT_DIR/result.json"
