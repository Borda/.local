"""Tests for ``bin/make-run-dir.sh`` timestamped run-dir creator.

The script creates ``<base-dir>/<UTC-ISO-TS>/`` and prints the path.
Required arg: base-dir. No input sanitization is performed beyond bash
quoting; the value is interpolated verbatim.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "make-run-dir.sh"

TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z")


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


def test_missing_arg_fails(tmp_path: Path):
    """No arg → ``${1:?base-dir required}`` non-zero exit."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode != 0
    assert "base-dir required" in result.stderr


def test_creates_dir(tmp_path: Path):
    """Happy path: creates ``<base>/<ts>/`` and prints the path."""
    base = tmp_path / "runs"
    result = sh(str(base))
    assert result.returncode == 0
    created = Path(result.stdout.strip())
    assert created.is_dir()
    assert created.parent == base


def test_timestamp_in_path(tmp_path: Path):
    """Output path contains an ISO-formatted UTC timestamp."""
    result = sh(str(tmp_path / "runs"))
    assert result.returncode == 0
    assert TIMESTAMP_RE.search(result.stdout.strip()) is not None


def test_creates_parents_when_missing(tmp_path: Path):
    """``mkdir -p`` creates intermediate directories transparently."""
    base = tmp_path / "level1" / "level2" / "runs"
    # Don't pre-create base
    result = sh(str(base))
    assert result.returncode == 0
    created = Path(result.stdout.strip())
    assert created.is_dir()
