#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: codex-harness.sh [--help]

Run packaged Codex Rig calibration in an isolated temporary HOME with
network-capable and LLM commands blocked. Writes a compact summary and copies failure artifacts to
.github/codex-harness-results or CODEX_HARNESS_RESULTS_DIR.

Exit 0 means isolated calibration passed; nonzero means setup, calibration, or
artifact validation failed.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  "")
    ;;
  *)
    echo "unknown-arg:$1" >&2
    exit 2
    ;;
esac

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP_PARENT="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
TMP_HOME="$(mktemp -d "$TMP_PARENT/codex-offline-home.XXXXXX")"
TMP_BIN="$TMP_HOME/bin"
RESULTS_DIR="${CODEX_HARNESS_RESULTS_DIR:-$ROOT/.github/codex-harness-results}"
REAL_GIT="$(command -v git || true)"

if [[ -z "$REAL_GIT" ]]; then
  echo "missing-command:git" >&2
  exit 2
fi

cleanup() {
  rm -rf "$TMP_HOME"
}
trap cleanup EXIT

mkdir -p "$TMP_BIN"
mkdir -p "$RESULTS_DIR"
mkdir -p "$TMP_HOME/.codex"

write_blocker() {
  local name="$1"
  cat >"$TMP_BIN/$name" <<'EOF'
#!/usr/bin/env bash
echo "blocked by offline Codex harness: $0 $*" >&2
exit 125
EOF
  chmod +x "$TMP_BIN/$name"
}

for command in codex openai gh curl wget; do
  write_blocker "$command"
done

cat >"$TMP_BIN/git" <<EOF
#!/usr/bin/env bash
set -euo pipefail
case "\${1:-}" in
  status|diff|ls-files|show|init|config|add|commit)
    exec "$REAL_GIT" "\$@"
    ;;
  remote)
    case "\${2:-}" in
      ""|get-url)
        exec "$REAL_GIT" "\$@"
        ;;
      *)
        echo "blocked by offline Codex harness: git \$*" >&2
        exit 125
        ;;
    esac
    ;;
  -C)
    case "\${3:-}" in
      remote)
        case "\${4:-}" in
          add|get-url|"")
            exec "$REAL_GIT" "\$@"
            ;;
          *)
            echo "blocked by offline Codex harness: git \$*" >&2
            exit 125
            ;;
        esac
        ;;
      *)
        echo "blocked by offline Codex harness: git \$*" >&2
        exit 125
        ;;
    esac
    ;;
  *)
    echo "blocked by offline Codex harness: git \$*" >&2
    exit 125
    ;;
esac
EOF
chmod +x "$TMP_BIN/git"

set +e
CALIBRATION_OUTPUT="$(env -i \
  HOME="$TMP_HOME" \
  CODEX_HOME="$TMP_HOME/.codex" \
  TMPDIR="$TMP_PARENT" \
  PATH="$TMP_BIN:$PATH" \
  CI="true" \
  CODEX_OFFLINE_HARNESS="1" \
  "$ROOT/plugins/codex-rig/runtime/calibration/run.py" --layout plugin --root "$ROOT" 2>&1)"
CALIBRATION_EXIT=$?
set -e

if [[ -n "$CALIBRATION_OUTPUT" ]]; then
  printf '%s\n' "$CALIBRATION_OUTPUT"
fi

RESULT_PATH="$(printf '%s\n' "$CALIBRATION_OUTPUT" | awk '/\/result\.json$/ { path = $0 } END { print path }')"
if [[ -z "$RESULT_PATH" || ! -f "$RESULT_PATH" ]]; then
  echo "missing-result-artifact: expected calibration run to print a result.json path" >&2
  exit 1
fi

CALIBRATION_DIR="$(dirname "$RESULT_PATH")"
for artifact in result.json behavioral.json recommendations.md checks.txt leaks.txt; do
  if [[ -f "$CALIBRATION_DIR/$artifact" ]]; then
    cp -p "$CALIBRATION_DIR/$artifact" "$RESULTS_DIR/$artifact"
  fi
done

STATUS="$(
  python3 - "$RESULT_PATH" "$RESULTS_DIR/summary.md" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
payload = json.loads(result_path.read_text(encoding="utf-8"))

status = payload.get("status", "unknown")
checks_failed = payload.get("checks_failed") or []
leaks_found = payload.get("leaks_found", "unknown")
behavioral = payload.get("behavioral") or {}
overall = behavioral.get("overall") or {}
freshness = behavioral.get("observation_freshness") or {}

lines = [
    "# Codex Offline Harness",
    "",
    f"- Status: `{status}`",
    f"- Checks failed: `{', '.join(checks_failed) if checks_failed else 'none'}`",
    f"- Leaks found: `{leaks_found}`",
    f"- Result artifact: `{payload.get('artifact_path', result_path)}`",
]

if overall:
    lines.extend(
        [
            f"- Recall: `{overall.get('recall')}`",
            f"- Precision: `{overall.get('precision')}`",
            f"- F1: `{overall.get('f1')}`",
            f"- Confidence accuracy: `{overall.get('confidence_accuracy')}`",
            f"- Fixture observations: `{freshness.get('fixture_observations', 0)}`",
            f"- Live observations: `{freshness.get('live_observations', 0)}`",
        ]
    )

summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(status)
PY
)"

echo "Codex offline harness summary:"
cat "$RESULTS_DIR/summary.md"

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat "$RESULTS_DIR/summary.md" >> "$GITHUB_STEP_SUMMARY"
fi

if [[ "$CALIBRATION_EXIT" -ne 0 ]]; then
  exit "$CALIBRATION_EXIT"
fi

if [[ "$STATUS" != "pass" ]]; then
  exit 1
fi
