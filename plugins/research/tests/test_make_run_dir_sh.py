"""Tests for ``bin/make-run-dir.sh`` timestamped run-dir creator.

The script creates ``<base-dir>/<skill-slug>-<UTC-ISO-timestamp>/`` and
prints the path. Both args are required (``${1:?...}``, ``${2:?...}``).
No input sanitization is performed; values are interpolated verbatim.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "make-run-dir.sh"

TIMESTAMP_RE = re.compile(r"-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z$")


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


def test_missing_both_args_fails(tmp_path: Path):
    """No args → ``${1:?...}`` non-zero exit."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode != 0
    assert "skill-slug required" in result.stderr


def test_missing_base_dir_fails(tmp_path: Path):
    """Only skill-slug provided → ``${2:?...}`` non-zero exit."""
    result = sh("myskill", cwd=str(tmp_path))
    assert result.returncode != 0
    assert "base-dir required" in result.stderr


def test_creates_dir_with_slug_and_timestamp(tmp_path: Path):
    """Happy path creates ``<base>/<slug>-<ts>/`` and prints the path."""
    base = tmp_path / "runs"
    base.mkdir()
    result = sh("myskill", str(base))
    assert result.returncode == 0
    created = Path(result.stdout.strip())
    assert created.is_dir()
    assert created.parent == base
    assert created.name.startswith("myskill-")


def test_path_includes_iso_timestamp(tmp_path: Path):
    """Output path tail matches ``<slug>-YYYY-MM-DDTHH-MM-SSZ``."""
    base = tmp_path / "runs"
    base.mkdir()
    result = sh("myskill", str(base))
    assert result.returncode == 0
    assert TIMESTAMP_RE.search(result.stdout.strip()) is not None


def test_creates_parents_when_missing(tmp_path: Path):
    """``mkdir -p`` creates intermediate directories when base does not exist."""
    base = tmp_path / "level1" / "level2" / "runs"
    # Don't pre-create base
    result = sh("myskill", str(base))
    assert result.returncode == 0
    created = Path(result.stdout.strip())
    assert created.is_dir()
