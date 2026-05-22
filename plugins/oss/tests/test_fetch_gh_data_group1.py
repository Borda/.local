"""Tests for ``bin/fetch_gh_data_group1.py``.

Arg-parsing tests run without any subprocess calls. The happy-path and
individual-failure tests monkeypatch ``subprocess.run`` and ``which``
so no real ``gh`` invocation occurs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import fetch_gh_data_group1 as fgd


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def test_missing_repo_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """No ``--repo`` → exit 1 with '--repo required' on stderr."""
    rc = fgd.main(["--output-dir", str(tmp_path)])
    assert rc == 1
    assert "--repo required" in capsys.readouterr().err


def test_missing_output_dir_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """``--repo`` but no ``--output-dir`` → exit 1 with '--output-dir required' on stderr."""
    rc = fgd.main(["--repo", "owner/repo"])
    assert rc == 1
    assert "--output-dir required" in capsys.readouterr().err


def test_unknown_arg_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """Unrecognized flag → exit 1 with 'unknown arg' on stderr."""
    rc = fgd.main(["--unknown"])
    assert rc == 1
    assert "unknown arg" in capsys.readouterr().err


def test_no_args_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """No args → exit 1 (--repo required)."""
    rc = fgd.main([])
    assert rc == 1
    assert "--repo required" in capsys.readouterr().err


def test_build_datasets_returns_21_entries() -> None:
    """``_build_datasets`` returns exactly 21 (name, args) tuples."""
    datasets = fgd._build_datasets("o/r", "2023-01-01", "2023-01-01T00:00:00Z", "2022-07-01T00:00:00Z")
    assert len(datasets) == 21
    names = [name for name, _ in datasets]
    assert "open_issues" in names
    assert "commits_50" in names


def test_successful_fetch_writes_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """All gh calls succeed → one JSON file per dataset written, exit 0."""
    monkeypatch.setattr(
        fgd.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="[]"),
    )
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    rc = fgd.main(["--repo", "owner/repo", "--output-dir", str(tmp_path)])
    assert rc == 0
    json_files = list(tmp_path.glob("*.json"))
    assert len(json_files) == 21


def test_individual_failure_nonfatal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """All gh calls fail → empty files written, warnings on stderr, exit 0."""
    monkeypatch.setattr(
        fgd.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stdout=""),
    )
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    rc = fgd.main(["--repo", "owner/repo", "--output-dir", str(tmp_path)])
    assert rc == 0
    err = capsys.readouterr().err
    assert "failed (non-fatal)" in err
    empty_files = [f for f in tmp_path.glob("*.json") if f.read_text() == ""]
    assert len(empty_files) == 21


def test_successful_fetch_file_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Successful gh call → file content equals gh stdout."""
    monkeypatch.setattr(
        fgd.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout='[{"sha":"abc"}]'),
    )
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    fgd.main(["--repo", "owner/repo", "--output-dir", str(tmp_path)])
    assert (tmp_path / "open_issues.json").read_text() == '[{"sha":"abc"}]'


def test_custom_cutoffs_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit cutoff flags accepted without error."""
    monkeypatch.setattr(
        fgd.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=0, stdout="[]"),
    )
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    rc = fgd.main(
        [
            "--repo",
            "owner/repo",
            "--output-dir",
            str(tmp_path),
            "--cutoff-3y",
            "2023-01-01",
            "--cutoff-90d",
            "2024-06-01T00:00:00Z",
            "--cutoff-180d",
            "2024-03-01T00:00:00Z",
        ]
    )
    assert rc == 0


def test_gh_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``which`` returns None → FileNotFoundError propagates."""
    monkeypatch.setattr(fgd, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="gh"):
        fgd.main(["--repo", "owner/repo", "--output-dir", str(tmp_path)])
