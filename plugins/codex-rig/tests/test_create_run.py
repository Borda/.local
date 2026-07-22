"""Acceptance checks for portable workflow run-directory creation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CREATE_RUN = PLUGIN_ROOT / "shared" / "create_run.py"


def test_create_run_emits_one_new_native_path(tmp_path: Path) -> None:
    """Create a bounded skill artifact directory without shell variables."""
    completed = subprocess.run(
        [sys.executable, str(CREATE_RUN), "--skill", "code-review", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    created = Path(output)
    assert created.is_dir()
    assert created.parent == tmp_path / "code-review"
    assert created.name.endswith("Z")
    assert completed.stderr == ""


def test_create_run_rejects_path_like_skill_id(tmp_path: Path) -> None:
    """Prevent a skill argument from escaping the artifact root."""
    completed = subprocess.run(
        [sys.executable, str(CREATE_RUN), "--skill", "../escape", "--root", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "invalid skill id" in completed.stderr
    assert not (tmp_path.parent / "escape").exists()
