#!/usr/bin/env python
"""locate_scan_query.py — resolve the scan-query executable via three-tier fallback.

Tiers (first hit wins):
    1. ``scan-query`` on PATH (``shutil.which``)
    2. ``${CLAUDE_PLUGIN_ROOT}/bin/scan-query``
    3. ``~/.claude/plugins/cache/*/codemap/*/bin/scan-query`` (newest semver)

Usage:
    python locate_scan_query.py

Output:
    Resolved absolute path on stdout (LF-terminated); nothing else.

Exit codes:
    0 — found and executable
    1 — not found (error message on stderr)
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path


def _find_executable(path: Path) -> Path | None:
    """Return *path* if it exists and is executable; ``None`` otherwise.

    On Windows also probes the ``.exe`` variant when the bare name is absent.

    Args:
        path: Candidate path (may or may not exist).

    Returns:
        Executable path if found, ``None`` if not.
    """
    if path.is_file() and os.access(path, os.X_OK):
        return path
    if sys.platform == "win32":
        exe = path.with_suffix(".exe")
        if exe.is_file() and os.access(exe, os.X_OK):
            return exe
    return None


def _version_key(path: Path) -> list[int]:
    """Extract semver digits from the version directory in *path* for sorting.

    Expects a path segment like ``…/codemap/<version>/bin/…`` and returns
    the numeric components of ``<version>`` so ``max()`` picks the newest.

    Args:
        path: Path containing a version segment one level above ``bin/``.

    Returns:
        List of ints representing the version (e.g. ``[0, 3, 2]``).
    """
    parts = path.parts
    try:
        bin_idx = next(i for i, p in enumerate(parts) if p == "bin")
        return [int(t) for t in re.findall(r"\d+", parts[bin_idx - 1])]
    except StopIteration:
        return [0]


def locate_scan_query() -> Path:
    """Resolve the scan-query executable via a three-tier fallback cascade.

    Returns:
        Absolute path to the scan-query executable.

    Raises:
        FileNotFoundError: When no tier locates an executable.
    """
    # Tier 1 — PATH
    found = shutil.which("scan-query")
    if found and os.access(found, os.X_OK):
        return Path(found)

    # Tier 2 — CLAUDE_PLUGIN_ROOT (canonicalized: defence-in-depth against symlink/relative-path tricks, SEC-L6)
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        plugin_root_path = Path(plugin_root).resolve()
        result = _find_executable(plugin_root_path / "bin" / "scan-query")
        if result:
            return result

    # Tier 3 — cache glob, newest semver
    cache_base = Path.home() / ".claude" / "plugins" / "cache"
    candidates = [p for p in cache_base.glob("*/codemap/*/bin/scan-query") if _find_executable(p)]
    if sys.platform == "win32":
        candidates += [p for p in cache_base.glob("*/codemap/*/bin/scan-query.exe") if _find_executable(p)]
    if candidates:
        return max(candidates, key=_version_key)

    raise FileNotFoundError("scan-query binary not found (PATH, CLAUDE_PLUGIN_ROOT, cache glob all empty)")


def main(argv: list[str] | None = None) -> int:
    """Entry point; returns exit code.

    Args:
        argv: Unused (script takes no arguments).

    Returns:
        0 on success, 1 when scan-query is not found.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    try:
        sq = locate_scan_query()
    except FileNotFoundError as exc:
        print(f"locate_scan_query: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(str(sq) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
