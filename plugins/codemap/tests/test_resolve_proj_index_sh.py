"""Tests for ``bin/resolve-proj-index.sh`` project-index path resolver.

The script computes the project name (from git root basename, falling back
to PWD basename) and the codemap index path (``<git-root>/.cache/scan/<proj>.json``).
With ``--check``, it additionally verifies the index file exists and exits
non-zero when missing.

Marked as integration because the script uses ``git rev-parse`` — the test
runs from inside the actual project repo. ``RUN_INTEGRATION=1`` to enable.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")

SCRIPT = Path(__file__).parent.parent / "bin" / "resolve-proj-index.sh"
REPO_ROOT = Path(__file__).parents[3]


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


def test_no_check_emits_two_lines():
    """Default mode: two lines — PROJ name + INDEX path."""
    result = sh(cwd=str(REPO_ROOT))
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    proj, index = lines
    assert proj  # non-empty project name
    assert index.endswith(f"/.cache/scan/{proj}.json")


def test_check_missing_index_exits_1():
    """``--check`` with non-existent index → exit 1, third line ``✗ index``."""
    # First get the expected paths from no-check run
    base = sh(cwd=str(REPO_ROOT))
    assert base.returncode == 0
    _, index = base.stdout.strip().splitlines()
    # If the index already exists locally, move it aside for the test
    index_path = Path(index)
    moved = None
    try:
        if index_path.exists():
            moved = index_path.with_suffix(".json.test-bak")
            index_path.rename(moved)
        result = sh("--check", cwd=str(REPO_ROOT))
        assert result.returncode == 1
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 3
        assert "✗ index" in lines[2]
    finally:
        if moved is not None and moved.exists():
            moved.rename(index_path)


def test_check_existing_index_exits_0():
    """``--check`` with existing index → exit 0, third line ``✓ index: exists``."""
    base = sh(cwd=str(REPO_ROOT))
    _, index = base.stdout.strip().splitlines()
    index_path = Path(index)
    created_by_test = False
    moved = None
    try:
        if not index_path.exists():
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text("{}\n")
            created_by_test = True
        else:
            # Preserve original to avoid corrupting real index — write a stub.
            moved = index_path.with_suffix(".json.test-bak")
            index_path.rename(moved)
            index_path.write_text("{}\n")
            created_by_test = True
        result = sh("--check", cwd=str(REPO_ROOT))
        assert result.returncode == 0
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 3
        assert lines[2] == "✓ index: exists"
    finally:
        if created_by_test:
            index_path.unlink(missing_ok=True)
        if moved is not None and moved.exists():
            moved.rename(index_path)
