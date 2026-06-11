"""Tests for ``bin/parse_deprecate_args.py`` — --deprecate flag extraction from $ARGUMENTS strings."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import parse_deprecate_args
from parse_deprecate_args import (
    format_shell_assignments,
    main,
    parse_deprecate_args as parse,
)


# ---------------------------------------------------------------------------
# parse_deprecate_args() — pure function
# ---------------------------------------------------------------------------


class TestBareDeprecateFlag:
    """Bare ``--deprecate`` enables deprecation with empty decorator value."""

    def test_bare_flag_alone(self) -> None:
        assert parse("--deprecate") == (True, "")

    def test_bare_flag_with_surrounding_args(self) -> None:
        assert parse("--dry-run --deprecate --since 1.0") == (True, "")

    def test_bare_flag_at_end(self) -> None:
        assert parse("--since 1.0 --deprecate") == (True, "")

    def test_bare_flag_at_start(self) -> None:
        assert parse("--deprecate --since 1.0") == (True, "")


class TestDeprecateValueExtraction:
    """The three quoting styles must all be recognised for --deprecate=<value>."""

    @pytest.mark.parametrize(
        ("arguments", "expected_decorator"),
        [
            pytest.param("--deprecate=@deprecated", "@deprecated", id="unquoted-simple"),
            pytest.param(
                "--deprecate='@deprecated(target=bar)'",
                "@deprecated(target=bar)",
                id="single-quoted-with-parens",
            ),
            pytest.param(
                '--deprecate="@deprecated_class(target=Bar)"',
                "@deprecated_class(target=Bar)",
                id="double-quoted-class-form",
            ),
            pytest.param(
                "--deprecate=@deprecated(target=fn,deprecated_in='1.0')",
                "@deprecated(target=fn,deprecated_in='1.0')",
                id="unquoted-with-embedded-single-quote",
            ),
        ],
    )
    def test_value_extraction(self, arguments: str, expected_decorator: str) -> None:
        deprecate, decorator = parse(arguments)
        assert deprecate is True
        assert decorator == expected_decorator

    def test_value_form_with_surrounding_args(self) -> None:
        assert parse("--dry-run --deprecate=@mydecorator --since 1.0") == (
            True,
            "@mydecorator",
        )


class TestNoDeprecateFlag:
    """``--no-deprecate`` is explicit negation — always wins."""

    def test_no_deprecate_alone(self) -> None:
        assert parse("--no-deprecate") == (False, "")

    def test_no_deprecate_overrides_bare_deprecate(self) -> None:
        # Negation wins even when both flags present.
        assert parse("--deprecate --no-deprecate") == (False, "")

    def test_no_deprecate_overrides_deprecate_value(self) -> None:
        assert parse("--deprecate=@mydecorator --no-deprecate") == (False, "")

    def test_no_deprecate_at_start(self) -> None:
        assert parse("--no-deprecate --since 1.0") == (False, "")


class TestAbsent:
    """No ``--deprecate`` flag at all → DEPRECATE=false, empty decorator."""

    def test_empty_string(self) -> None:
        assert parse("") == (False, "")

    def test_only_whitespace(self) -> None:
        assert parse("   ") == (False, "")

    def test_unrelated_flags(self) -> None:
        assert parse("--dry-run --since 1.0 --removed-in 2.0") == (False, "")

    def test_subcommand_only(self) -> None:
        assert parse("symbol mypkg::old_fn mypkg::new_fn") == (False, "")


class TestSimilarButDistinctFlags:
    """Flags that share a prefix with --deprecate must not trigger detection.

    ``--deprecated`` and ``--deprecate-foo`` are not the same flag — guard against
    accidental matches.
    """

    def test_deprecated_suffix_does_not_match(self) -> None:
        # `--deprecated` is a distinct token; should not be treated as `--deprecate`.
        assert parse("--deprecated") == (False, "")

    def test_deprecate_dash_suffix_does_not_match(self) -> None:
        assert parse("--deprecate-foo") == (False, "")


# ---------------------------------------------------------------------------
# format_shell_assignments() — output formatting (pure helper, not called by main)
# ---------------------------------------------------------------------------


class TestFormatShellAssignments:
    def test_true_with_empty_decorator(self) -> None:
        assert format_shell_assignments(True, "") == "DEPRECATE=true\nDEPRECATE_DECORATOR=''"

    def test_false_with_empty_decorator(self) -> None:
        assert format_shell_assignments(False, "") == "DEPRECATE=false\nDEPRECATE_DECORATOR=''"

    def test_true_with_simple_decorator(self) -> None:
        out = format_shell_assignments(True, "@deprecated")
        assert out == "DEPRECATE=true\nDEPRECATE_DECORATOR=@deprecated"

    def test_true_with_decorator_containing_parens_and_quotes(self) -> None:
        # Single quotes must come back shell-quoted so `eval` rebuilds one token.
        out = format_shell_assignments(True, "@deprecated(target=bar)")
        assert out == "DEPRECATE=true\nDEPRECATE_DECORATOR='@deprecated(target=bar)'"

    def test_true_with_decorator_containing_spaces(self) -> None:
        out = format_shell_assignments(True, "@deprecated(target=bar, in='1.0')")
        # shlex.quote wraps in single quotes and escapes embedded single quotes
        # via '"'"' — the exact form may vary by Python version but eval must round-trip.
        assert out.startswith("DEPRECATE=true\nDEPRECATE_DECORATOR=")


# ---------------------------------------------------------------------------
# main() — CLI entry point: writes to temp files (not stdout)
# ---------------------------------------------------------------------------


class TestMain:
    """``main()`` writes raw values to ``${TMPDIR}/codemap-deprecate-{flag,decorator}``.

    The ``--arguments=`` form (equals sign, no space) is required so that values
    starting with ``--`` survive argparse's flag-detection.
    """

    def test_main_with_bare_deprecate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bare --deprecate → flag=true, decorator=empty."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments=--deprecate"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "true"
        assert (tmp_path / "codemap-deprecate-decorator").read_text() == ""

    def test_main_with_deprecate_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--deprecate=<value> → flag=true, decorator=raw value (no shell quoting)."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments=--deprecate=@mydecorator"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "true"
        assert (tmp_path / "codemap-deprecate-decorator").read_text() == "@mydecorator"

    def test_main_with_no_deprecate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--no-deprecate → flag=false, decorator=empty."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments=--no-deprecate"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "false"
        assert (tmp_path / "codemap-deprecate-decorator").read_text() == ""

    def test_main_with_absent_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No --deprecate flag → flag=false, decorator=empty."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments=--dry-run --since 1.0"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "false"
        assert (tmp_path / "codemap-deprecate-decorator").read_text() == ""

    def test_main_with_empty_arguments(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty arguments → flag=false, decorator=empty."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments="])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "false"

    def test_main_with_no_argv(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Default empty string when --arguments omitted → flag=false."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main([])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "false"

    def test_main_decorator_written_raw_not_shell_quoted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decorator with parens/spaces is written raw — no shlex.quote wrapping."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments=--deprecate='@deprecated(target=bar, in=\"1.0\")'"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "true"
        # Raw value — no surrounding quotes, no shlex escaping
        decorator = (tmp_path / "codemap-deprecate-decorator").read_text()
        assert "@deprecated(target=bar" in decorator

    def test_main_with_space_separated_arguments_value(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Space-separated form works for payloads not starting with ``--``."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        rc = main(["--arguments", "symbol mypkg::old mypkg::new"])
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "false"

    def test_main_uses_sys_argv_when_none(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """main() reads sys.argv when argv=None."""
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        monkeypatch.setattr(
            sys,
            "argv",
            ["parse_deprecate_args.py", "--arguments=--deprecate=@fromargv"],
        )
        rc = main()
        assert rc == 0
        assert (tmp_path / "codemap-deprecate-flag").read_text() == "true"
        assert (tmp_path / "codemap-deprecate-decorator").read_text() == "@fromargv"


# ---------------------------------------------------------------------------
# Doctest hookup — keeps doctest examples covered by `pytest`
# ---------------------------------------------------------------------------


def test_doctests_pass() -> None:
    import doctest

    results = doctest.testmod(parse_deprecate_args, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
