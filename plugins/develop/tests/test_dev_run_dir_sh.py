"""Tests for ``bin/dev-run-dir.sh`` timestamped run-dir creator.

The script computes a UTC ISO timestamp, creates ``.developments/<ts>/``
under the current working directory, and optionally touches a sentinel
file under ``/tmp/<name>-<ts>`` when invoked with ``--sentinel <name>``.
No input sanitization is performed; sentinel name is interpolated verbatim.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "dev-run-dir.sh"

TIMESTAMP_RE = re.compile(r"\.developments/\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


def sh(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run the script under test and capture stdout/stderr."""
    e = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
    )


def test_creates_developments_dir(tmp_path: Path):
    """Happy path: creates ``.developments/<ts>/`` and prints its relative path."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode == 0
    relative = result.stdout.strip()
    assert relative.startswith(".developments/")
    assert (tmp_path / relative).is_dir()


def test_timestamp_format_matches_iso_utc(tmp_path: Path):
    """Output path tail matches the ``YYYY-MM-DDTHH-MM-SSZ`` UTC pattern."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode == 0
    assert TIMESTAMP_RE.search(result.stdout.strip()) is not None


def test_sentinel_flag_creates_tmp_sentinel(tmp_path: Path):
    """``--sentinel <name>`` touches ``/tmp/<name>-<ts>``."""
    sentinel_name = f"dev-run-test-{os.getpid()}"
    try:
        result = sh("--sentinel", sentinel_name, cwd=str(tmp_path))
        assert result.returncode == 0
        ts = result.stdout.strip().split("/")[-1]
        sentinel_path = Path("/tmp") / f"{sentinel_name}-{ts}"
        assert sentinel_path.exists()
    finally:
        # Cleanup: remove all sentinel files created with our PID-scoped prefix
        for stale in Path("/tmp").glob(f"{sentinel_name}-*"):
            stale.unlink(missing_ok=True)


def test_sentinel_without_name_skipped(tmp_path: Path):
    """``--sentinel`` alone (no name) does not create any /tmp sentinel."""
    before = set(Path("/tmp").glob("*"))
    result = sh("--sentinel", cwd=str(tmp_path))
    assert result.returncode == 0
    after = set(Path("/tmp").glob("*"))
    # No new files matching a sentinel pattern under /tmp
    new_files = after - before
    assert not any(re.search(r"\d{4}-\d{2}-\d{2}T", f.name) for f in new_files)
