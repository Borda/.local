"""Tests for ``bin/diagnosis-parse.sh``.

The script parses ``--diagnosis <path>`` (or ``--diagnosis=<path>``) from
the ARGUMENTS string. Resolved path is printed to stdout (empty when flag
absent). Exits 0 always except when the file referenced by ``--diagnosis``
does not exist — then exits 1 with a ``! BREAKING`` stderr message.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "diagnosis-parse.sh"


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


def test_no_flag_empty_output():
    """Empty ARGUMENTS → empty stdout, exit 0."""
    result = sh("")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_unrelated_flags_empty_output():
    """ARGUMENTS without ``--diagnosis`` → empty stdout, exit 0."""
    result = sh("--mode fix --team")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_equals_form_resolves_path(tmp_path: Path):
    """``--diagnosis=<path>`` form: file exists → emit path, exit 0."""
    diag = tmp_path / "diag.md"
    diag.write_text("# diagnosis\n")
    result = sh(f"--diagnosis={diag}")
    assert result.returncode == 0
    assert result.stdout.strip() == str(diag)


def test_space_form_resolves_path(tmp_path: Path):
    """``--diagnosis <path>`` form: file exists → emit path, exit 0."""
    diag = tmp_path / "diag.md"
    diag.write_text("# diagnosis\n")
    result = sh(f"--diagnosis {diag}")
    assert result.returncode == 0
    assert result.stdout.strip() == str(diag)


def test_diagnosis_followed_by_other_flag():
    """``--diagnosis --team`` — next token is ``--*`` → no value captured."""
    result = sh("--diagnosis --team")
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_diagnosis_file_missing_exits_1():
    """Path referenced does not exist → exit 1 with ``! BREAKING`` stderr."""
    result = sh("--diagnosis /nonexistent/diag/path.md")
    assert result.returncode == 1
    assert "! BREAKING" in result.stderr


def test_combined_with_other_flags(tmp_path: Path):
    """``--mode fix --diagnosis=<path> --team`` correctly extracts path."""
    diag = tmp_path / "d.md"
    diag.write_text("x")
    result = sh(f"--mode fix --diagnosis={diag} --team")
    assert result.returncode == 0
    assert result.stdout.strip() == str(diag)
