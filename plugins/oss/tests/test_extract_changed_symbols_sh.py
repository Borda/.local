"""Tests for ``bin/extract_changed_symbols.sh``.

The script extracts added/removed public Python symbols (class/def names)
from ``__init__.py`` diffs in a given git range. Invalid ranges produce
empty stdout + exit 0 (the script guards via ``git rev-parse``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "extract_changed_symbols.sh"


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


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with one initial commit."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_invalid_range_exits_0(git_repo: Path):
    """Invalid range (non-existent ref) → exit 0, empty stdout (guard fires)."""
    result = sh("nonexistent_ref..HEAD", cwd=str(git_repo))
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_invalid_single_ref_exits_0(git_repo: Path):
    """Non-existent single ref → exit 0, empty stdout."""
    result = sh("nonexistent_ref", cwd=str(git_repo))
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_no_init_py_files_exits_0(git_repo: Path):
    """No ``__init__.py`` files in tree → exit 0, empty stdout."""
    # Add a non-init file and commit so HEAD~1 doesn't exist; pass HEAD..HEAD
    # which resolves but is empty.
    (git_repo / "file.py").write_text("def foo(): pass\n")
    subprocess.run(["git", "-C", str(git_repo), "add", "file.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "add"], check=True, capture_output=True)
    result = sh("HEAD..HEAD", cwd=str(git_repo))
    assert result.returncode == 0
    assert result.stdout.strip() == ""


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git diff")
def test_extracts_changed_symbols(git_repo: Path):
    """Integration: real ``__init__.py`` diff yields the new symbol names."""
    init = git_repo / "pkg" / "__init__.py"
    init.parent.mkdir()
    init.write_text("# initial\n")
    subprocess.run(["git", "-C", str(git_repo), "add", "pkg/__init__.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "init pkg"], check=True, capture_output=True)
    init.write_text("class Foo: pass\ndef bar(): pass\n")
    subprocess.run(["git", "-C", str(git_repo), "add", "pkg/__init__.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(git_repo), "commit", "-m", "add symbols"], check=True, capture_output=True)
    result = sh("HEAD~1..HEAD", cwd=str(git_repo))
    assert result.returncode == 0
    symbols = set(result.stdout.strip().splitlines())
    assert "Foo" in symbols
    assert "bar" in symbols
