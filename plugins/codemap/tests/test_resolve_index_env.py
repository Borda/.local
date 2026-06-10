"""Tests for ``bin/resolve_index_env.py`` — eval-safe PROJ + INDEX emitter.

The script calls ``resolve_proj_index.py`` via subprocess, reads PROJ (line 1)
and INDEX (line 2), and emits ``PROJ=<quoted> INDEX=<quoted>`` to stdout using
:func:`shlex.quote` so the output round-trips safely through ``eval``.

Tests cover:
* Happy path — resolver returns valid PROJ + INDEX → eval-safe stdout, exit 0
* ``--check-exists`` with present INDEX file → exit 0
* ``--check-exists`` with missing INDEX file → exit 1, PROJ/INDEX still on stdout
* Resolver failure (empty output) → exit 1, PROJ/INDEX still on stdout
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
    """Unit tests for ``format_eval_line()`` — eval-safety guard."""

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
    """``main()`` — successful resolver runs."""

    def test_happy_path_emits_eval_safe_line(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No flags: prints ``PROJ=<q> INDEX=<q>`` and exits 0."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("demo-proj", "/tmp/demo.json"))
        rc = main([])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "PROJ=demo-proj INDEX=/tmp/demo.json"
        assert captured.err == ""

    def test_happy_path_output_is_eval_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Round-trip: main() output line parses back to original PROJ + INDEX via shlex."""
        tricky_proj = "proj with space"
        tricky_index = str(tmp_path / "tricky idx.json")
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock(tricky_proj, tricky_index))
        rc = main([])
        assert rc == 0
        line = capsys.readouterr().out.strip()
        parts = dict(tok.split("=", 1) for tok in shlex.split(line) if "=" in tok)
        assert parts["PROJ"] == tricky_proj
        assert parts["INDEX"] == tricky_index


class TestCheckExists:
    """``--check-exists`` — gate exit code on INDEX file presence."""

    def test_present_index_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check-exists`` with a real INDEX file → exit 0, no stderr."""
        index = tmp_path / "with-index.json"
        index.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("with-index", str(index)))
        rc = main(["--check-exists"])
        captured = capsys.readouterr()
        assert rc == 0
        assert "PROJ=with-index" in captured.out
        assert str(index) in captured.out
        assert captured.err == ""

    def test_missing_index_exits_1_but_emits_proj_index(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check-exists`` with absent INDEX → exit 1, PROJ/INDEX still on stdout, error on stderr."""
        missing = tmp_path / "absent.json"  # never created
        monkeypatch.setattr(_mod.subprocess, "run", _make_resolver_mock("no-idx", str(missing)))
        rc = main(["--check-exists"])
        captured = capsys.readouterr()
        assert rc == 1
        # PROJ/INDEX still emitted on stdout — contract for callers needing variables.
        assert "PROJ=no-idx" in captured.out
        assert shlex.quote(str(missing)) in captured.out
        assert "INDEX file not found" in captured.err
        assert str(missing) in captured.err


class TestResolverFailure:
    """Resolver returns no output → exit 1, but variables still emitted."""

    def test_empty_resolver_exits_1(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """Empty resolver stdout → exit 1, empty PROJ + INDEX still emitted, error on stderr."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_empty_resolver_mock())
        rc = main([])
        captured = capsys.readouterr()
        assert rc == 1
        # Empty strings shlex-quote to '', so output line is PROJ='' INDEX=''.
        assert captured.out.strip() == "PROJ='' INDEX=''"
        assert "produced no output" in captured.err

    def test_check_exists_with_empty_resolver_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check-exists`` does not change behaviour when resolver itself fails first."""
        monkeypatch.setattr(_mod.subprocess, "run", _make_empty_resolver_mock())
        rc = main(["--check-exists"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "produced no output" in captured.err


class TestUnknownFlag:
    """Unknown CLI flag → exit 2 with stderr message naming the flag."""

    def test_unknown_flag_exits_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        """``--no-such-flag`` → exit 2 + stderr mentioning the flag."""
        rc = main(["--no-such-flag"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "unknown flag" in captured.err
        assert "--no-such-flag" in captured.err
