"""Tests for ``bin/setup_release_dir.sh``.

The script creates the release directory, symlinks the canonical
CHANGELOG file into it, and backs up any pre-existing release artifacts
(HIGHLIGHTS.md, DRAFT.md, SUMMARY.md, MIGRATION.md, demo.py) with ``.bak``
suffix before overwrite.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "setup_release_dir.sh"


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


def test_missing_release_dir(tmp_path: Path):
    """No args → ``${1:?release_dir required}`` non-zero exit."""
    result = sh()
    assert result.returncode != 0
    assert "release_dir required" in result.stderr


def test_missing_changelog(tmp_path: Path):
    """One arg only → ``${2:?changelog_file required}`` non-zero exit."""
    result = sh(str(tmp_path / "rel"))
    assert result.returncode != 0
    assert "changelog_file required" in result.stderr


def test_creates_dir_and_symlink(tmp_path: Path):
    """Happy path: creates release dir + CHANGELOG.md symlink to canonical file."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n")
    release_dir = tmp_path / "release"
    result = sh(str(release_dir), str(changelog))
    assert result.returncode == 0
    assert release_dir.is_dir()
    linked = release_dir / "CHANGELOG.md"
    assert linked.is_symlink()
    assert linked.resolve() == changelog.resolve()


def test_backups_existing_files(tmp_path: Path):
    """Pre-existing ``HIGHLIGHTS.md`` is copied to ``.bak`` before overwrite."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n")
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    highlights = release_dir / "HIGHLIGHTS.md"
    highlights.write_text("# old highlights\n")
    result = sh(str(release_dir), str(changelog))
    assert result.returncode == 0
    backup = release_dir / "HIGHLIGHTS.md.bak"
    assert backup.exists()
    assert backup.read_text() == "# old highlights\n"


def test_backups_all_artifact_files(tmp_path: Path):
    """All five recognized artifacts get backed up when present."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n")
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    artifacts = ("HIGHLIGHTS.md", "DRAFT.md", "SUMMARY.md", "MIGRATION.md", "demo.py")
    for name in artifacts:
        (release_dir / name).write_text(f"# {name}\n")
    result = sh(str(release_dir), str(changelog))
    assert result.returncode == 0
    for name in artifacts:
        assert (release_dir / f"{name}.bak").exists(), f"missing backup for {name}"
