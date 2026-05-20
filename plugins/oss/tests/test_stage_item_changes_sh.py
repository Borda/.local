"""Tests for ``bin/stage_item_changes.sh``.

The script pops a pre-item stash (if present) and stages all changed
tracked files plus source-extension untracked files. Required arg:
item_id. Integration-heavy; one unit test covers missing-arg path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "stage_item_changes.sh"


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


def test_missing_item_id(tmp_path: Path):
    """No args → ``${1:?item_id required}`` non-zero exit."""
    result = sh(cwd=str(tmp_path))
    assert result.returncode != 0
    assert "item_id required" in result.stderr


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git env")
def test_stages_changed_tracked_file(tmp_path: Path):
    """Integration: dirty tracked file is staged after script runs."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True, capture_output=True)
    target = tmp_path / "a.py"
    target.write_text("x = 1\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "a.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], check=True, capture_output=True)
    target.write_text("x = 2\n")
    result = sh("42", cwd=str(tmp_path))
    assert result.returncode == 0
    # Verify file is now staged
    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "a.py" in staged.stdout
