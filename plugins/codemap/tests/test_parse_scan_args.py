"""Tests for ``bin/parse_scan_args.py`` — flag extraction from $ARGUMENTS strings."""

from __future__ import annotations


import pytest


from parse_scan_args import main, parse_scan_args as parse  # noqa: E402


# ---------------------------------------------------------------------------
# parse_scan_args() — pure function; returns list[str] of unquoted tokens
# ---------------------------------------------------------------------------


class TestRootValueExtraction:
    """All three quoting styles must be stripped; returned value is the raw path."""

    def test_unquoted_path(self) -> None:
        assert parse("--root /abs/path") == ["--root", "/abs/path"]

    def test_single_quoted_path(self) -> None:
        assert parse("--root '/abs/path'") == ["--root", "/abs/path"]

    def test_double_quoted_path(self) -> None:
        assert parse('--root "/abs/path"') == ["--root", "/abs/path"]

    def test_single_quoted_path_with_spaces(self) -> None:
        assert parse("--root '/abs path/with spaces'") == ["--root", "/abs path/with spaces"]

    def test_double_quoted_path_with_spaces(self) -> None:
        assert parse('--root "/abs path/with spaces"') == ["--root", "/abs path/with spaces"]

    def test_path_with_special_chars_returned_raw(self) -> None:
        assert parse("--root '/path/with$dollar'") == ["--root", "/path/with$dollar"]


class TestIncrementalFlag:
    def test_incremental_alone(self) -> None:
        assert parse("--incremental") == ["--incremental"]

    def test_incremental_absent(self) -> None:
        assert parse("--root /tmp/x") == ["--root", "/tmp/x"]


class TestBothFlags:
    def test_root_then_incremental(self) -> None:
        assert parse("--root /abs/path --incremental") == ["--root", "/abs/path", "--incremental"]

    def test_incremental_then_root(self) -> None:
        # Output order is fixed: --root first, then --incremental.
        assert parse("--incremental --root /tmp/x") == ["--root", "/tmp/x", "--incremental"]

    def test_both_with_quoted_root_containing_space(self) -> None:
        assert parse("--root '/p with space' --incremental") == ["--root", "/p with space", "--incremental"]


class TestEmptyAndNeither:
    def test_empty_string(self) -> None:
        assert parse("") == []

    def test_no_recognised_flags(self) -> None:
        assert parse("--unknown foo --other bar") == []

    def test_only_whitespace(self) -> None:
        assert parse("   ") == []


class TestRootPosition:
    """`--root` must be detected wherever it appears in the string."""

    @pytest.mark.parametrize(
        ("arguments", "expected"),
        [
            ("--root /abs/path --incremental", ["--root", "/abs/path", "--incremental"]),
            ("--incremental --root /abs/path", ["--root", "/abs/path", "--incremental"]),
            ("prefix-noise --root /abs/path", ["--root", "/abs/path"]),
            ("--root /abs/path trailing-noise", ["--root", "/abs/path"]),
        ],
    )
    def test_position_variants(self, arguments: str, expected: list[str]) -> None:
        assert parse(arguments) == expected


# ---------------------------------------------------------------------------
# main() — CLI entry point; default stdout is shell-quoted for legacy eval use
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
