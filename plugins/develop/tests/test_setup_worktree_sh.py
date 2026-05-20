"""Tests for ``bin/setup-worktree.sh``.

The script creates ``.temp/develop/<UTC-ISO-TS>/`` and prints two lines:
the timestamp on line 1 and the run-dir path on line 2. With ``--sentinel
<name>``, it also touches ``/tmp/<sanitized-name>-<ts>``. Sentinel names
are sanitized to ``[a-zA-Z0-9_-]+`` to prevent /tmp path traversal.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "setup-worktree.sh"

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


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


def test_creates_run_dir(tmp_path: Path):
    """Happy path: creates ``.temp/develop/<ts>/`` and prints ts + path."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    ts, run_dir = lines
    assert (tmp_path / run_dir).is_dir()


def test_output_format(tmp_path: Path):
    """Line 1 = ISO timestamp; line 2 = ``.temp/develop/<ts>``."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode == 0
    ts, run_dir = result.stdout.strip().splitlines()
    assert TIMESTAMP_RE.match(ts)
    assert run_dir == f".temp/develop/{ts}"


def test_sentinel_flag_creates_tmp_sentinel(tmp_path: Path):
    """``--sentinel <name>`` touches ``/tmp/<name>-<ts>``."""
    sentinel_name = f"swt-test-{os.getpid()}"
    try:
        result = sh("--sentinel", sentinel_name, cwd=str(tmp_path))
        assert result.returncode == 0
        ts, _ = result.stdout.strip().splitlines()
        sentinel_path = Path("/tmp") / f"{sentinel_name}-{ts}"
        assert sentinel_path.exists()
    finally:
        for stale in Path("/tmp").glob(f"{sentinel_name}-*"):
            stale.unlink(missing_ok=True)


def test_sentinel_sanitizes_traversal(tmp_path: Path):
    """``--sentinel ../evil`` is stripped to ``evil`` — no traversal."""
    sentinel_name = f"../evil-{os.getpid()}"
    # The script strips `[^a-zA-Z0-9_-]` so `../evil-<pid>` becomes `evil-<pid>`.
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "", sentinel_name)
    try:
        result = sh("--sentinel", sentinel_name, cwd=str(tmp_path))
        assert result.returncode == 0
        ts, _ = result.stdout.strip().splitlines()
        # Sanitized sentinel is at /tmp/<sanitized>-<ts>; verify no path traversal.
        sanitized_path = Path("/tmp") / f"{sanitized}-{ts}"
        assert sanitized_path.exists()
        # And the un-sanitized path with slashes is NOT created.
        traversal_path = Path("/tmp") / f"{sentinel_name}-{ts}"
        assert not traversal_path.exists()
    finally:
        for stale in Path("/tmp").glob(f"{sanitized}-*"):
            stale.unlink(missing_ok=True)
