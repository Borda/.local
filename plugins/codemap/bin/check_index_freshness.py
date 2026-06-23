#!/usr/bin/env python
"""check_index_freshness.py — report calendar age of a scanned_at timestamp from a codemap index.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_index_freshness.py" <index_path>

Output: one line of '✓ freshness:' or '⚠ freshness:' status. Always exits 0; reports problems via the output line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STALE_THRESHOLD_DAYS = 7
MAX_INDEX_SIZE = 50_000_000  # 50 MB — refuse to load oversized index files (SEC-M9: DoS guard)
MAX_SCANNED_AT_LEN = 80  # cap untrusted scanned_at length before embedding in output (SEC-L2)


def _is_user_owned(p: Path) -> bool:
    """Return True when ``p`` is owned by the current effective user.

    Used to gate world-writable temporary directories: a file under ``/tmp``
    is only trusted when its owner matches the running user (SEC-M4), which
    blocks an attacker pre-creating an index file another user will scan.

    Args:
        p: Path to inspect (file or directory).

    Returns:
        ``True`` when ``p.stat().st_uid`` equals the current UID, else ``False``
        (including when the path cannot be stat-ed).
    """
    try:
        if not hasattr(os, "getuid"):
            return True  # Windows: ownership check via UID unsupported
        return p.stat().st_uid == os.getuid()
    except OSError:
        return False


def _is_test_mode() -> bool:
    """Return True when the environment opts into permissive temp-dir validation.

    Production runs reject world-writable temp directories outright; tests
    (pytest ``tmp_path``, sandboxed CI) set ``CODEMAP_TEST_MODE=1`` to allow
    indices under ``tempfile.gettempdir()`` regardless of ownership.

    Returns:
        ``True`` when ``CODEMAP_TEST_MODE`` is ``"1"``, else ``False``.
    """
    return os.environ.get("CODEMAP_TEST_MODE") == "1"


def _validate_index_path(raw: str, is_test_mode: bool | None = None) -> Path | None:
    """Resolve and validate that ``raw`` stays within a safe base directory.

    Permitted base directories (any one is sufficient):
      * The current working directory (treated as the repository root)
      * ``~/.claude`` (where codemap indices typically live)
      * The OS temporary directory (``tempfile.gettempdir()``) — only honored in
        test mode, or in production when the candidate is owned by the current
        user. ``/tmp`` is world-writable, so an unowned index there is rejected
        (SEC-M4).

    Args:
        raw: User-supplied path from argv.
        is_test_mode: Override for test-mode detection; defaults to
            :func:`_is_test_mode` (reads ``CODEMAP_TEST_MODE``).

    Returns:
        Resolved ``Path`` if validation succeeds; ``None`` if the path is empty,
        does not point at a file, resolves outside every allowed base, or sits in
        a world-writable temp dir it does not own (outside test mode).
    """
    if not raw:
        return None
    test_mode = _is_test_mode() if is_test_mode is None else is_test_mode
    candidate = Path(raw).expanduser().resolve()
    if not candidate.is_file():
        return None
    temp_root = Path(tempfile.gettempdir()).resolve()
    allowed_roots = [
        Path.cwd().resolve(),
        (Path(os.path.expanduser("~")) / ".claude").resolve(),
        temp_root,
    ]
    for root in allowed_roots:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if root == temp_root and not test_mode and not _is_user_owned(candidate):
            return None
        return candidate
    return None


def parse_scanned_at(scanned_at: str) -> datetime | None:
    """Parse the first 19 characters of a scanned_at ISO-8601-ish string into a UTC datetime.

    Args:
        scanned_at: timestamp string, expected to begin with ``YYYY-MM-DDTHH:MM:SS``.

    Returns:
        Timezone-aware UTC ``datetime`` if parsing succeeds, otherwise ``None``.

    Examples:
        >>> parse_scanned_at("2026-01-15T12:30:45Z") is not None
        True
        >>> parse_scanned_at("not-a-timestamp") is None
        True
        >>> parse_scanned_at("") is None
        True
    """
    if not scanned_at:
        return None
    cleaned = scanned_at[:19]
    try:
        naive = datetime.strptime(cleaned, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return naive.replace(tzinfo=timezone.utc)


def age_days(scan_time: datetime, now: datetime) -> int:
    """Return the integer number of full days between ``scan_time`` and ``now``.

    Args:
        scan_time: when the index was produced.
        now: current time (typically ``datetime.now(timezone.utc)``).

    Returns:
        Non-negative integer day count (floored).

    Examples:
        >>> from datetime import datetime, timezone, timedelta
        >>> ref = datetime(2026, 1, 10, tzinfo=timezone.utc)
        >>> age_days(ref - timedelta(days=3, hours=5), ref)
        3
        >>> age_days(ref, ref)
        0
    """
    delta_seconds = (now - scan_time).total_seconds()
    return max(0, int(delta_seconds // 86400))


def format_status(scanned_at: str | None, scan_time: datetime | None, now: datetime) -> str:
    """Build the single freshness status line (newline-terminated, possibly multi-line).

    Args:
        scanned_at: raw scanned_at value (may be ``None`` if missing).
        scan_time: parsed UTC ``datetime`` (may be ``None`` if unparsable).
        now: current UTC ``datetime`` used to compute age.

    Returns:
        Formatted status string ending with a trailing newline.

    Examples:
        >>> from datetime import datetime, timezone, timedelta
        >>> ref = datetime(2026, 1, 10, tzinfo=timezone.utc)
        >>> format_status(None, None, ref).startswith("⚠ freshness: scanned_at missing")
        True
        >>> format_status("bogus", None, ref).startswith("⚠ freshness: could not parse")
        True
        >>> scan = ref - timedelta(days=2)
        >>> format_status("2026-01-08T00:00:00Z", scan, ref).startswith("✓ freshness:")
        True
        >>> stale = ref - timedelta(days=10)
        >>> format_status("2025-12-31T00:00:00Z", stale, ref).startswith("⚠ freshness:")
        True
    """
    scanned_at_safe = str(scanned_at)[:MAX_SCANNED_AT_LEN] if scanned_at else scanned_at
    if scan_time is None:
        if not scanned_at_safe:
            return "⚠ freshness: scanned_at missing — index may be corrupted\n  → Re-run /codemap:scan-codebase\n"
        return f"⚠ freshness: could not parse scanned_at timestamp ({scanned_at_safe}) — run /codemap:scan-codebase\n"

    days = age_days(scan_time, now)
    scan_date = (scanned_at_safe or "")[:10]
    if days > STALE_THRESHOLD_DAYS:
        return f"⚠ freshness: {days} day(s) ago ({scan_date})\n  → Run /codemap:scan-codebase to refresh\n"
    return f"✓ freshness: {days} day(s) ago ({scan_date})\n"


def read_scanned_at(index_path: Path) -> str | None:
    """Read the ``scanned_at`` field from a codemap index JSON file.

    Args:
        index_path: path to the index JSON file (must exist).

    Returns:
        The ``scanned_at`` value if present, otherwise ``None``.
    """
    # DoS guard (SEC-M9): refuse oversized index files before json.load to avoid memory exhaustion.
    try:
        if index_path.stat().st_size > MAX_INDEX_SIZE:
            return None
    except OSError:
        return None
    try:
        with index_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("scanned_at")
    return value if isinstance(value, str) and value else None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Always returns 0; surfaces problems via stdout."""
    parser = argparse.ArgumentParser(
        description="Report calendar age of a scanned_at timestamp from a codemap index.",
    )
    parser.add_argument("index_path", nargs="?", default="", help="Path to the codemap index JSON file.")
    args = parser.parse_args(argv)

    index_arg = args.index_path
    # Preserve the legacy "index not provided or not found" wording for the
    # absent / missing-file paths so existing CLI consumers still match.
    if not index_arg or not Path(index_arg).is_file():
        sys.stdout.write("⚠ freshness: index not provided or not found\n  → Pass a valid index path\n")
        return 0
    validated = _validate_index_path(index_arg)
    if validated is None:
        sys.stdout.write(
            "⚠ freshness: index path outside allowed roots — pass a path within the project or ~/.claude\n"
        )
        return 0

    scanned_at = read_scanned_at(validated)
    scan_time = parse_scanned_at(scanned_at or "")
    sys.stdout.write(format_status(scanned_at, scan_time, datetime.now(timezone.utc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
