#!/usr/bin/env bash
set -euo pipefail

OUT_FILE=""
STATUS=""
CHECKS_RUN=""
CHECKS_FAILED=""
CRITICAL=0
HIGH=0
MEDIUM=0
LOW=0
CONFIDENCE=""
ARTIFACT_PATH=""
RECOMMENDATIONS=""
FOLLOW_UP=""
METADATA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out)
      OUT_FILE="$2"
      shift 2
      ;;
    --status)
      STATUS="$2"
      shift 2
      ;;
    --checks-run)
      CHECKS_RUN="$2"
      shift 2
      ;;
    --checks-failed)
      CHECKS_FAILED="$2"
      shift 2
      ;;
    --critical)
      CRITICAL="$2"
      shift 2
      ;;
    --high)
      HIGH="$2"
      shift 2
      ;;
    --medium)
      MEDIUM="$2"
      shift 2
      ;;
    --low)
      LOW="$2"
      shift 2
      ;;
    --confidence)
      CONFIDENCE="$2"
      shift 2
      ;;
    --artifact-path)
      ARTIFACT_PATH="$2"
      shift 2
      ;;
    --recommendations)
      RECOMMENDATIONS="$2"
      shift 2
      ;;
    --follow-up)
      FOLLOW_UP="$2"
      shift 2
      ;;
    --metadata)
      METADATA="$2"
      shift 2
      ;;
    *)
      echo "unknown-arg:$1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$OUT_FILE" || -z "$STATUS" || -z "$CHECKS_RUN" || -z "$CONFIDENCE" || -z "$ARTIFACT_PATH" ]]; then
  echo "missing-required-args" >&2
  exit 2
fi

if [[ "$STATUS" != "pass" && "$STATUS" != "fail" && "$STATUS" != "timeout" ]]; then
  echo "invalid-status:$STATUS" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUT_FILE")"

python3 - "$OUT_FILE" "$STATUS" "$CHECKS_RUN" "$CHECKS_FAILED" "$CRITICAL" "$HIGH" "$MEDIUM" "$LOW" "$CONFIDENCE" "$ARTIFACT_PATH" "$RECOMMENDATIONS" "$FOLLOW_UP" "$METADATA" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
status = sys.argv[2]
checks_run = [x.strip() for x in sys.argv[3].split(",") if x.strip()]
checks_failed = [x.strip() for x in sys.argv[4].split(",") if x.strip()]
critical = int(sys.argv[5])
high = int(sys.argv[6])
medium = int(sys.argv[7])
low = int(sys.argv[8])
confidence = float(sys.argv[9])
artifact_path = sys.argv[10]
recommendations_raw = sys.argv[11]
follow_up_raw = sys.argv[12]
metadata_raw = sys.argv[13]

def parse_items(raw: str) -> list[str]:
    # Accept JSON array first; fallback to "item1||item2||item3" format.
    raw = raw.strip()
    if not raw:
        return []
    try:
        loaded = json.loads(raw)
        if isinstance(loaded, list):
            return [str(x).strip() for x in loaded if str(x).strip()]
    except Exception:
        pass
    return [x.strip() for x in raw.split("||") if x.strip()]

def parse_metadata(raw: str) -> dict[str, object]:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except Exception as exc:
        raise SystemExit(f"invalid-metadata-json:{exc}") from exc
    if not isinstance(loaded, dict):
        raise SystemExit("invalid-metadata-json:not-object")
    return loaded

payload = {
    "status": status,
    "checks_run": checks_run,
    "checks_failed": checks_failed,
    "findings": {
        "critical": critical,
        "high": high,
        "medium": medium,
        "low": low,
    },
    "confidence": confidence,
    "artifact_path": artifact_path,
    "recommendations": parse_items(recommendations_raw),
    "follow_up": parse_items(follow_up_raw),
}
metadata = parse_metadata(metadata_raw)
if metadata:
    payload["metadata"] = metadata
out.write_text(json.dumps(payload, indent=2) + "\n")
PY

echo "$OUT_FILE"
