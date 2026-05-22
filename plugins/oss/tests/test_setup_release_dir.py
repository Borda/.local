"""Tests for ``bin/setup_release_dir.py``.

Pure filesystem tests — no subprocess mocking required. The script
performs only pathlib/shutil operations; ``tmp_path`` provides isolation.
Tests mirror the shell-script test coverage plus re-run (symlink overwrite)
and non-existent-file-not-backed-up edge cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import setup_release_dir as srd


def test_missing_release_dir_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """No args → exit 1 with 'release_dir required' on stderr."""
    rc = srd.main([])
    assert rc == 1
    assert "release_dir required" in capsys.readouterr().err


def test_missing_changelog_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """One arg only → exit 1 with 'changelog_file required' on stderr."""
    rc = srd.main([str(tmp_path / "rel")])
    assert rc == 1
    assert "changelog_file required" in capsys.readouterr().err


def test_creates_release_dir_and_symlink(tmp_path: Path) -> None:
    """Happy path: creates release dir and CHANGELOG.md symlink to canonical file."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n")
    release_dir = tmp_path / "v1.0.0"

    rc = srd.main([str(release_dir), str(changelog)])

    assert rc == 0
    assert release_dir.is_dir()
    link = release_dir / "CHANGELOG.md"
    assert link.is_symlink()
    assert link.resolve() == changelog.resolve()


def test_creates_nested_dirs(tmp_path: Path) -> None:
    """RELEASE_DIR with non-existent parents → directories created recursively."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("")
    release_dir = tmp_path / "releases" / "v1.0.0"

    rc = srd.main([str(release_dir), str(changelog)])

    assert rc == 0
    assert release_dir.is_dir()


def test_backs_up_existing_highlights(tmp_path: Path) -> None:
    """Pre-existing HIGHLIGHTS.md → backed up to HIGHLIGHTS.md.bak."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("")
    release_dir = tmp_path / "rel"
    release_dir.mkdir()
    highlights = release_dir / "HIGHLIGHTS.md"
    highlights.write_text("# old highlights\n")

    rc = srd.main([str(release_dir), str(changelog)])

    assert rc == 0
    bak = release_dir / "HIGHLIGHTS.md.bak"
    assert bak.exists()
    assert bak.read_text() == "# old highlights\n"


def test_backs_up_all_five_artifacts(tmp_path: Path) -> None:
    """All five recognised artifacts get backed up when present."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("")
    release_dir = tmp_path / "rel"
    release_dir.mkdir()
    for name in srd._ARTIFACTS:
        (release_dir / name).write_text(f"# {name}\n")

    rc = srd.main([str(release_dir), str(changelog)])

    assert rc == 0
    for name in srd._ARTIFACTS:
        assert (release_dir / f"{name}.bak").exists(), f"missing backup for {name}"


def test_nonexistent_artifact_not_backed_up(tmp_path: Path) -> None:
    """Artifacts absent from release dir → no .bak files created."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("")
    release_dir = tmp_path / "rel"

    srd.main([str(release_dir), str(changelog)])

    for name in srd._ARTIFACTS:
        assert not (release_dir / f"{name}.bak").exists()


def test_rerun_overwrites_symlink(tmp_path: Path) -> None:
    """Re-running replaces existing CHANGELOG.md symlink safely."""
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("v1\n")
    release_dir = tmp_path / "rel"

    srd.main([str(release_dir), str(changelog)])

    changelog2 = tmp_path / "CHANGELOG2.md"
    changelog2.write_text("v2\n")
    rc = srd.main([str(release_dir), str(changelog2)])

    assert rc == 0
    link = release_dir / "CHANGELOG.md"
    assert link.resolve() == changelog2.resolve()
