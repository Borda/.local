"""Tests for ``bin/parse_scan_args.py`` — flag extraction from $ARGUMENTS strings."""

from __future__ import annotations

import sys

import pytest


import parse_scan_args  # noqa: E402
from parse_scan_args import main, parse_scan_args as parse  # noqa: E402


# ---------------------------------------------------------------------------
# parse_scan_args() — pure function
# ---------------------------------------------------------------------------


class TestRootValueExtraction:
    """The three quoting styles must all be recognised.

    ``shlex.quote`` emits the minimal shell-safe form: plain alphanumeric paths
    pass through unquoted; paths containing whitespace or shell metacharacters
    are wrapped in single quotes.
    """

    def test_unquoted_path(self) -> None:
        assert parse("--root /abs/path") == "--root /abs/path"

    def test_single_quoted_path(self) -> None:
        # Input quoting style is irrelevant — only the extracted value matters.
        assert parse("--root '/abs/path'") == "--root /abs/path"

    def test_double_quoted_path(self) -> None:
        assert parse('--root "/abs/path"') == "--root /abs/path"

    def test_single_quoted_path_with_spaces(self) -> None:
        # Values with spaces must come out single-quoted so `eval` rebuilds one token.
        assert parse("--root '/abs path/with spaces'") == "--root '/abs path/with spaces'"

    def test_double_quoted_path_with_spaces(self) -> None:
        assert parse('--root "/abs path/with spaces"') == "--root '/abs path/with spaces'"

    def test_unquoted_path_with_special_chars_is_shell_quoted(self) -> None:
        # `$` is a shell metacharacter — shlex.quote must wrap the value.
        assert parse("--root '/path/with$dollar'") == "--root '/path/with$dollar'"


class TestIncrementalFlag:
    def test_incremental_alone(self) -> None:
        assert parse("--incremental") == "--incremental"

    def test_incremental_absent(self) -> None:
        assert parse("--root /tmp/x") == "--root /tmp/x"


class TestBothFlags:
    def test_root_then_incremental(self) -> None:
        assert parse("--root /abs/path --incremental") == "--root /abs/path --incremental"

    def test_incremental_then_root(self) -> None:
        # Order in output is fixed: --root first, then --incremental.
        assert parse("--incremental --root /tmp/x") == "--root /tmp/x --incremental"

    def test_both_with_quoted_root_containing_space(self) -> None:
        assert parse("--root '/p with space' --incremental") == "--root '/p with space' --incremental"


class TestEmptyAndNeither:
    def test_empty_string(self) -> None:
        assert parse("") == ""

    def test_no_recognised_flags(self) -> None:
        assert parse("--unknown foo --other bar") == ""

    def test_only_whitespace(self) -> None:
        assert parse("   ") == ""


class TestRootPosition:
    """`--root` must be detected wherever it appears in the string."""

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            ("--root /abs/path --incremental", "--root /abs/path --incremental"),
            ("--incremental --root /abs/path", "--root /abs/path --incremental"),
            ("prefix-noise --root /abs/path", "--root /abs/path"),
            ("--root /abs/path trailing-noise", "--root /abs/path"),
        ],
    )
    def test_position_variants(self, arguments: str, expected: str) -> None:
        assert parse(arguments) == expected


# ---------------------------------------------------------------------------
# main() — CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_with_arg(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["--root /tmp/x --incremental"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == "--root /tmp/x --incremental"

    def test_main_with_empty_arg(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main([""])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == ""

    def test_main_with_no_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Calling with no argv at all — must not crash; should print empty line.
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == ""

    def test_main_uses_sys_argv_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["parse_scan_args.py", "--root /from/argv"])
        rc = main()
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == "--root /from/argv"


# ---------------------------------------------------------------------------
# Doctest hookup — keeps doctest examples covered by `pytest`
# ---------------------------------------------------------------------------


def test_doctests_pass() -> None:
    import doctest

    results = doctest.testmod(parse_scan_args, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
