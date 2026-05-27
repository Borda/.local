"""Tests for ``bin/diagnosis_parse.py``.

The script extracts the ``--diagnosis`` value from a single ``$ARGUMENTS`` string
(accepting both ``--diagnosis=<path>`` and ``--diagnosis <path>`` forms) and prints
the resolved path to stdout. Missing files trigger exit 1 with a ``! BREAKING``
stderr block. No subprocess involvement — pure string parsing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import diagnosis_parse  # type: ignore[import-not-found]


def test_equals_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--diagnosis=<path>`` form: file exists under cwd → prints path, exits 0.

    Cwd is pointed at ``tmp_path`` so the containment check passes (the script
    rejects paths outside ``Path.cwd()`` to close the path-existence oracle).
    """
    monkeypatch.chdir(tmp_path)
    diag = tmp_path / "diag.md"
    diag.write_text("# diagnosis\n")
    rc = diagnosis_parse.main([f"--diagnosis={diag.as_posix()}"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out) == diag


def test_space_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``--diagnosis <path>`` form: file exists under cwd → prints path, exits 0."""
    monkeypatch.chdir(tmp_path)
    diag = tmp_path / "diag.md"
    diag.write_text("# diagnosis\n")
    rc = diagnosis_parse.main([f"--diagnosis {diag.as_posix()}"])
    assert rc == 0
    assert Path(capsys.readouterr().out.strip()) == diag


def test_no_diagnosis(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty arguments → prints empty string, exits 0."""
    rc = diagnosis_parse.main([""])
    assert rc == 0
    # Print of "" still emits a newline; .strip() yields empty.
    assert capsys.readouterr().out.strip() == ""


def test_no_diagnosis_unrelated_flags(capsys: pytest.CaptureFixture[str]) -> None:
    """Arguments without ``--diagnosis`` → prints empty string, exits 0."""
    rc = diagnosis_parse.main(["--mode fix --team"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_no_argv_at_all(capsys: pytest.CaptureFixture[str]) -> None:
    """Script invoked with no argv tokens at all → treated as empty arguments."""
    rc = diagnosis_parse.main([])
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_file_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    """``--diagnosis`` given but file missing → exit 1 with ``! BREAKING`` stderr block."""
    rc = diagnosis_parse.main(["--diagnosis /nonexistent/diag/path.md"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "! BREAKING" in err
    assert "/nonexistent/diag/path.md" in err
    assert "Fix:" in err


def test_next_flag_not_treated_as_value(capsys: pytest.CaptureFixture[str]) -> None:
    """``--diagnosis --other-flag`` → next token starts with ``--`` → no value consumed."""
    rc = diagnosis_parse.main(["--diagnosis --other-flag"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == ""


def test_combined_with_other_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--mode fix --diagnosis=<path> --team`` → correct path extracted (containment-safe)."""
    monkeypatch.chdir(tmp_path)
    diag = tmp_path / "d.md"
    diag.write_text("x")
    rc = diagnosis_parse.main([f"--mode fix --diagnosis={diag.as_posix()} --team"])
    assert rc == 0
    assert Path(capsys.readouterr().out.strip()) == diag


def test_rejects_path_outside_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Existing file outside cwd → exit 1 with ``! BREAKING`` (closes path-existence oracle).

    Without containment, ``--diagnosis /etc/passwd`` would exit 0 and echo the absolute path,
    leaking which system files exist. The containment check rejects any resolved path that
    does not live under ``Path.cwd()``.
    """
    # Build an isolated cwd; the diag file lives in a sibling dir, deliberately outside cwd.
    cwd_dir = tmp_path / "project"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    diag = outside / "leak.md"
    diag.write_text("# outside\n")
    rc = diagnosis_parse.main([f"--diagnosis={diag.as_posix()}"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "outside project root" in err


def test_equals_form_missing_file_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """``--diagnosis=<nonexistent>`` also triggers exit 1, not only space form."""
    rc = diagnosis_parse.main(["--diagnosis=/no/such/file.md"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "! BREAKING" in err
    assert "/no/such/file.md" in err
