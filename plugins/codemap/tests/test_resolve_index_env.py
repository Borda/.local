"""Tests for ``bin/resolve_index_env.py`` — PROJ + INDEX temp-file writer.

The script calls ``resolve_proj_index.py`` via subprocess, reads PROJ (line 1)
and INDEX (line 2), and writes each to ``${TMPDIR}/codemap-resolve-{proj,index}``
for the caller to read back with ``cat``.

Tests cover:
* Happy path — resolver returns valid PROJ + INDEX → temp files written, exit 0
* ``--check-exists`` with present INDEX file → exit 0, temp files written
* ``--check-exists`` with missing INDEX file → exit 1, temp files still written
* Resolver failure (empty output) → exit 1, temp files written (empty)
* Unknown flag → exit 2 with stderr message
"""

from __future__ import annotations

import importlib.util
import shlex
import subprocess
from pathlib import Path
from typing import Any

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "resolve_index_env.py"
_spec = importlib.util.spec_from_file_location("codemap_resolve_index_env", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

format_eval_line = _mod.format_eval_line
parse_resolver_output = _mod.parse_resolver_output
main = _mod.main


def _read_resolve_file(tmp_path: Path, key: str, prefix: str = "codemap") -> str:
    """Read a PID-qualified resolve temp file by globbing for the single match.

    Args:
        tmp_path: Directory where temp files are written.
        key: File key — ``"proj"`` or ``"index"``.
        prefix: File name prefix (default ``"codemap"``).

    Returns:
        Contents of the matched temp file.
    """
    matches = list(tmp_path.glob(f"{prefix}-resolve-{key}-*"))
    assert len(matches) == 1, f"Expected exactly one {key} temp file, got: {matches}"
    return matches[0].read_text()


def _make_resolver_mock(
    proj: str,
    index_path: str,
    returncode: int = 0,
) -> Any:
    """Return a callable that mimics ``subprocess.run`` against the resolver.

    Args:
        proj: PROJ value to emit on line 1 of the mocked stdout.
        index_path: INDEX value to emit on line 2 of the mocked stdout.
        returncode: Exit code for the mocked CompletedProcess.

    Returns:
        Callable suitable for ``monkeypatch.setattr`` of ``subprocess.run``.
    """

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        stdout = "" if returncode != 0 else f"{proj}\n{index_path}\n"
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    return _run


def _make_empty_resolver_mock() -> Any:
    """Return a callable that mimics a resolver producing no output."""

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    return _run


class TestParseResolverOutput:
    """Unit tests for ``parse_resolver_output()``."""

    def test_two_line_input(self) -> None:
        """Extracts PROJ from line 1 and INDEX from line 2."""
        assert parse_resolver_output("myproj\n/tmp/idx.json\n") == ("myproj", "/tmp/idx.json")

    def test_missing_second_line(self) -> None:
        """Returns empty INDEX when only PROJ line present."""
        assert parse_resolver_output("only-proj\n") == ("only-proj", "")

    def test_empty_input(self) -> None:
        """Returns both empty when stdout is empty."""
        assert parse_resolver_output("") == ("", "")

    def test_extra_lines_ignored(self) -> None:
        """Lines beyond the second are discarded."""
        assert parse_resolver_output("a\nb\nc\nd\n") == ("a", "b")


class TestFormatEvalLine:
    """Unit tests for ``format_eval_line()`` — retained as pure helper."""

    def test_simple_values_unquoted(self) -> None:
        """Values without metacharacters appear bare (shlex.quote shortcut)."""
        assert format_eval_line("myproj", "/tmp/index.json") == "PROJ=myproj INDEX=/tmp/index.json"

    def test_space_in_proj_is_quoted(self) -> None:
        """Whitespace forces single-quote wrapping."""
        assert format_eval_line("proj with space", "/tmp/x.json") == "PROJ='proj with space' INDEX=/tmp/x.json"

    def test_eval_round_trip_simple(self) -> None:
        """format_eval_line output round-trips through shlex back to original values."""
        line = format_eval_line("round-trip", "/tmp/idx.json")
        parts = dict(tok.split("=", 1) for tok in shlex.split(line) if "=" in tok)
        assert parts["PROJ"] == "round-trip"
        assert parts["INDEX"] == "/tmp/idx.json"

    def test_eval_round_trip_with_quote(self) -> None:
        """Embedded single quotes survive the shlex round-trip via shlex.quote."""
        tricky = "proj'with'quote"
        line = format_eval_line(tricky, "/tmp/idx.json")
        parts = dict(tok.split("=", 1) for tok in shlex.split(line) if "=" in tok)
        assert parts["PROJ"] == tricky


class TestMainHappyPath:
    """``main()`` — successful resolver: writes temp files, exits 0."""

    def test_happy_path_writes_temp_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No flags: writes PROJ and INDEX to temp files and exits 0."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("demo-proj", "/tmp/demo.json"))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main([])
        assert rc == 0
        assert _read_resolve_file(tmp_path, "proj") == "demo-proj"
        assert _read_resolve_file(tmp_path, "index") == "/tmp/demo.json"

    def test_happy_path_tricky_values(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Values with spaces and special chars are written raw (no shell quoting)."""
        tricky_proj = "proj with space"
        tricky_index = str(tmp_path / "tricky idx.json")
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock(tricky_proj, tricky_index))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main([])
        assert rc == 0
        assert _read_resolve_file(tmp_path, "proj") == tricky_proj
        assert _read_resolve_file(tmp_path, "index") == tricky_index


class TestCheckExists:
    """``--check-exists`` — gate exit code on INDEX file presence."""

    def test_present_index_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``--check-exists`` with a real INDEX file → exit 0, temp files written."""
        index = tmp_path / "with-index.json"
        index.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("with-index", str(index)))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--check-exists"])
        assert rc == 0
        assert _read_resolve_file(tmp_path, "proj") == "with-index"
        assert _read_resolve_file(tmp_path, "index") == str(index)

    def test_missing_index_exits_1_but_writes_temp_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check-exists`` with absent INDEX → exit 1, temp files still written, error on stderr."""
        missing = tmp_path / "absent.json"  # never created
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("no-idx", str(missing)))
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--check-exists"])
        captured = capsys.readouterr()
        assert rc == 1
        # Temp files still written — PROJ and INDEX path available for diagnostics.
        assert _read_resolve_file(tmp_path, "proj") == "no-idx"
        assert _read_resolve_file(tmp_path, "index") == str(missing)
        assert "INDEX file not found" in captured.err
        assert str(missing) in captured.err


class TestResolverFailure:
    """Resolver returns no output → exit 1, empty temp files written."""

    def test_empty_resolver_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty resolver stdout → exit 1, empty temp files written, error on stderr."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_empty_resolver_mock())
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main([])
        captured = capsys.readouterr()
        assert rc == 1
        assert _read_resolve_file(tmp_path, "proj") == ""
        assert _read_resolve_file(tmp_path, "index") == ""
        assert "produced no output" in captured.err

    def test_check_exists_with_empty_resolver_exits_1(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """``--check-exists`` does not change behaviour when resolver itself fails first."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_empty_resolver_mock())
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--check-exists"])
        assert rc == 1


class TestUnknownFlag:
    """Unknown CLI flag → exit 2 with stderr message naming the flag."""

    def test_unknown_flag_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``--no-such-flag`` → exit 2 + stderr mentioning the flag."""
        rc = main(["--no-such-flag"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "unknown flag" in captured.err
        assert "--no-such-flag" in captured.err
