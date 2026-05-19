#!/usr/bin/env python
"""smoke_test_index.py — validate a codemap index file and report mtime staleness.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/smoke_test_index.py" --index-path <path> [--max-age-hours N]

Behaviour:
    1. Smoke test — open the index path and json.load it; reject if missing,
       unreadable, not a JSON object, or empty.
    2. Staleness — compare filesystem mtime against current wall-clock; flag stale
       when age exceeds ``--max-age-hours`` (default: 24).

Output:
    Single JSON object on stdout, e.g.::

        {"ok": true,  "stale": false, "age_hours": 2.31, "path": "<path>"}
        {"ok": false, "stale": false, "age_hours": null,  "path": "<path>",
         "error": "index file not found"}

Exit codes:
    0  index ok and not stale.
    1  index missing/invalid OR stale.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_HOURS = 24


@dataclass(frozen=True)
class SmokeResult:
    """Outcome of an index smoke test.

    Attributes:
        ok: True iff the index file exists, is readable, and parses as a non-empty JSON object.
        stale: True iff the file mtime is older than ``max_age_hours`` (only meaningful when ``ok``).
        age_hours: Filesystem age of the index file in hours, rounded to 2 dp. ``None`` if file missing.
        path: Absolute path of the index that was inspected.
        error: Short human-readable diagnostic when ``ok`` is False; ``None`` otherwise.
    """

    ok: bool
    stale: bool
    age_hours: float | None
    path: str
    error: str | None = None

    def to_json(self) -> str:
        """Serialize to a single-line JSON string.

        Returns:
            JSON object string with stable field order.

        Examples:
            >>> SmokeResult(True, False, 1.5, "/x.json").to_json()
            '{"ok": true, "stale": false, "age_hours": 1.5, "path": "/x.json"}'
            >>> SmokeResult(False, False, None, "/x.json", "missing").to_json()
            '{"ok": false, "stale": false, "age_hours": null, "path": "/x.json", "error": "missing"}'
        """
        payload: dict[str, Any] = {
            "ok": self.ok,
            "stale": self.stale,
            "age_hours": self.age_hours,
            "path": self.path,
        }
        if self.error is not None:
            payload["error"] = self.error
        return json.dumps(payload)


def compute_age_hours(mtime: float, now: float) -> float:
    """Return file age in hours, rounded to 2 decimal places, clamped at 0.

    Args:
        mtime: filesystem mtime (POSIX seconds since epoch).
        now: current wall-clock time (POSIX seconds since epoch).

    Returns:
        Non-negative age in hours.

    Examples:
        >>> compute_age_hours(0.0, 3600.0)
        1.0
        >>> compute_age_hours(0.0, 8190.0)
        2.27
        >>> compute_age_hours(100.0, 50.0)
        0.0
    """
    return round(max(0.0, (now - mtime) / 3600.0), 2)


def smoke_test_index(index_path: Path, max_age_hours: int, now: float | None = None) -> SmokeResult:
    """Run smoke test on a codemap index file.

    Smoke test sequence (any failure short-circuits with ``ok=False``):

    1. File exists and is a regular file.
    2. File contents parse as JSON.
    3. Parsed value is a dict and non-empty.

    Staleness is computed only when the smoke test passes.

    Args:
        index_path: path to the codemap index JSON.
        max_age_hours: age threshold (hours) above which the index is reported stale.
        now: POSIX timestamp used as "current time" — overridable for tests.

    Returns:
        :class:`SmokeResult` describing validity and staleness.
    """
    abs_path = str(index_path.resolve()) if index_path.exists() else str(index_path)

    if not index_path.exists() or not index_path.is_file():
        return SmokeResult(ok=False, stale=False, age_hours=None, path=abs_path, error="index file not found")

    try:
        with index_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return SmokeResult(ok=False, stale=False, age_hours=None, path=abs_path, error=f"unreadable index: {exc}")

    if not isinstance(data, dict) or not data:
        return SmokeResult(
            ok=False, stale=False, age_hours=None, path=abs_path, error="index payload empty or not a JSON object"
        )

    current = time.time() if now is None else now
    age_hours = compute_age_hours(index_path.stat().st_mtime, current)
    stale = age_hours > max_age_hours
    return SmokeResult(ok=True, stale=stale, age_hours=age_hours, path=abs_path)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: optional argv override for testing. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (0 = ok & fresh, 1 = invalid OR stale).
    """
    parser = argparse.ArgumentParser(
        description="Smoke-test a codemap index file and report mtime staleness.",
    )
    parser.add_argument("--index-path", required=True, help="Path to the codemap index JSON file.")
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"Hours above which the index is considered stale (default: {DEFAULT_MAX_AGE_HOURS}).",
    )
    args = parser.parse_args(argv)

    result = smoke_test_index(Path(args.index_path), max_age_hours=args.max_age_hours)
    print(result.to_json())
    return 0 if (result.ok and not result.stale) else 1


if __name__ == "__main__":
    sys.exit(main())
