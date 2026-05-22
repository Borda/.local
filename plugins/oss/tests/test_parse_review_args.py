"""Tests for ``bin/parse-review-args.py`` — oss:review argument parser.

Covers:
* ``parse_review_args`` — individual flags and defaults:
  - ``--reply`` → REPLY_MODE='true'
  - ``--no-challenge`` → CHALLENGE_ENABLED='false'
  - ``--codemap`` → CODEMAP_ENABLED='true'
  - ``--semble`` → SEMBLE_ENABLED='true'
* Flag combinations and defaults when flags absent
* CLEAN_ARGS normalization: leading whitespace trimmed, single '#' stripped
* Doctest hookup for embedded examples
* ``_emit`` output ordering and shell-quoting
* ``main()`` end-to-end via subprocess including hostile input
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from parse_review_args import _emit, parse_review_args  # loaded by conftest.py

_BIN = Path(__file__).resolve().parents[1] / "bin" / "parse-review-args.py"


# ---------------------------------------------------------------------------
# parse_review_args — individual flags
# ---------------------------------------------------------------------------


class TestIndividualFlags:
    """parse_review_args: each flag flips exactly its own variable."""

    def test_no_flags_all_defaults(self) -> None:
        """No flags present → all defaults: REPLY_MODE=false, CHALLENGE_ENABLED=true, etc."""
        result = parse_review_args("123")
        assert result["REPLY_MODE"] == "false"
        assert result["CHALLENGE_ENABLED"] == "true"
        assert result["CODEMAP_ENABLED"] == "false"
        assert result["SEMBLE_ENABLED"] == "false"
        assert result["CLEAN_ARGS"] == "123"

    def test_reply_flag(self) -> None:
        """--reply sets REPLY_MODE='true'; other flags stay at defaults."""
        result = parse_review_args("--reply 42")
        assert result["REPLY_MODE"] == "true"
        assert result["CHALLENGE_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "42"

    def test_no_challenge_flag(self) -> None:
        """--no-challenge sets CHALLENGE_ENABLED='false'."""
        result = parse_review_args("--no-challenge 42")
        assert result["CHALLENGE_ENABLED"] == "false"
        assert result["CLEAN_ARGS"] == "42"

    def test_codemap_flag(self) -> None:
        """--codemap sets CODEMAP_ENABLED='true'."""
        result = parse_review_args("--codemap 7")
        assert result["CODEMAP_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "7"

    def test_semble_flag(self) -> None:
        """--semble sets SEMBLE_ENABLED='true'."""
        result = parse_review_args("--semble 7")
        assert result["SEMBLE_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "7"


class TestFlagCombinations:
    """parse_review_args: multiple flags set simultaneously."""

    def test_all_four_flags(self) -> None:
        """All four flags present: every variable reflects its present_val."""
        result = parse_review_args("--reply --no-challenge --codemap --semble 99")
        assert result["REPLY_MODE"] == "true"
        assert result["CHALLENGE_ENABLED"] == "false"
        assert result["CODEMAP_ENABLED"] == "true"
        assert result["SEMBLE_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "99"

    def test_reply_and_codemap(self) -> None:
        """--reply + --codemap without --no-challenge or --semble."""
        result = parse_review_args("--reply --codemap 5")
        assert result["REPLY_MODE"] == "true"
        assert result["CODEMAP_ENABLED"] == "true"
        assert result["CHALLENGE_ENABLED"] == "true"
        assert result["SEMBLE_ENABLED"] == "false"


# ---------------------------------------------------------------------------
# CLEAN_ARGS normalization
# ---------------------------------------------------------------------------


class TestCleanArgsNormalization:
    """parse_review_args: CLEAN_ARGS whitespace and hash handling."""

    def test_hash_stripped(self) -> None:
        """Single leading '#' is removed from CLEAN_ARGS."""
        result = parse_review_args("#123")
        assert result["CLEAN_ARGS"] == "123"

    def test_hash_stripped_after_flag(self) -> None:
        """Leading '#' stripped even when a flag precedes the argument."""
        result = parse_review_args("--reply #456")
        assert result["REPLY_MODE"] == "true"
        assert result["CLEAN_ARGS"] == "456"

    def test_double_hash_strips_only_one(self) -> None:
        """Only one leading '#' is stripped, not two."""
        result = parse_review_args("##99")
        assert result["CLEAN_ARGS"] == "#99"

    def test_empty_input(self) -> None:
        """Empty string → CLEAN_ARGS='' and all flags at defaults."""
        result = parse_review_args("")
        assert result["CLEAN_ARGS"] == ""
        assert result["REPLY_MODE"] == "false"
        assert result["CHALLENGE_ENABLED"] == "true"

    def test_flags_only_no_trailing_arg(self) -> None:
        """Flag-only invocation leaves CLEAN_ARGS empty after trimming."""
        result = parse_review_args("--reply")
        assert result["REPLY_MODE"] == "true"
        assert result["CLEAN_ARGS"] == ""

    def test_leading_whitespace_trimmed(self) -> None:
        """Leading whitespace in remaining text is stripped before hash check."""
        result = parse_review_args("  42")
        assert result["CLEAN_ARGS"] == "42"


# ---------------------------------------------------------------------------
# _emit — output ordering and shell-quoting
# ---------------------------------------------------------------------------


def test_emit_output_order() -> None:
    """_emit emits keys in the canonical order defined by the script."""
    parsed = {
        "REPLY_MODE": "false",
        "CHALLENGE_ENABLED": "true",
        "CODEMAP_ENABLED": "false",
        "SEMBLE_ENABLED": "false",
        "CLEAN_ARGS": "42",
    }
    lines = _emit(parsed).strip().splitlines()
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == ["REPLY_MODE", "CHALLENGE_ENABLED", "CODEMAP_ENABLED", "SEMBLE_ENABLED", "CLEAN_ARGS"]


def test_emit_hostile_value_is_shell_quoted() -> None:
    """Hostile CLEAN_ARGS value is shlex-quoted; semicolons must not appear unquoted."""
    hostile = "'; touch /tmp/pwned; echo 'x"
    parsed = {
        "REPLY_MODE": "false",
        "CHALLENGE_ENABLED": "true",
        "CODEMAP_ENABLED": "false",
        "SEMBLE_ENABLED": "false",
        "CLEAN_ARGS": hostile,
    }
    output = _emit(parsed)
    assignments = dict(line.split("=", 1) for line in output.strip().splitlines())
    value = assignments["CLEAN_ARGS"]
    assert value.startswith("'"), f"CLEAN_ARGS should be single-quoted, got: {value!r}"


# ---------------------------------------------------------------------------
# Doctest hookup
# ---------------------------------------------------------------------------


def test_module_doctests_pass() -> None:
    """Doctest examples embedded in parse-review-args.py must not regress."""
    import doctest
    import parse_review_args as _mod

    results = doctest.testmod(_mod, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"


# ---------------------------------------------------------------------------
# main() — subprocess end-to-end
# ---------------------------------------------------------------------------


def test_main_via_subprocess_default_flags() -> None:
    """Subprocess invocation with bare PR number returns correct defaults."""
    result = subprocess.run(
        [sys.executable, str(_BIN), "42"],
        capture_output=True,
        text=True,
        check=True,
    )
    assignments = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert assignments["REPLY_MODE"] == "false"
    assert assignments["CHALLENGE_ENABLED"] == "true"
    assert assignments["CODEMAP_ENABLED"] == "false"
    assert assignments["SEMBLE_ENABLED"] == "false"
    assert assignments["CLEAN_ARGS"] == "42"


def test_main_via_subprocess_with_flags() -> None:
    """Subprocess invocation with --reply and --codemap reflects both flags."""
    result = subprocess.run(
        [sys.executable, str(_BIN), "--reply", "--codemap", "42"],
        capture_output=True,
        text=True,
        check=True,
    )
    assignments = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    assert assignments["REPLY_MODE"] == "true"
    assert assignments["CODEMAP_ENABLED"] == "true"
    assert assignments["CLEAN_ARGS"] == "42"


def test_main_via_subprocess_hostile_input_is_eval_safe() -> None:
    """Hostile input is shell-quoted — no unquoted metacharacters in output."""
    hostile = "'; touch /tmp/pwned; echo 'x"
    result = subprocess.run(
        [sys.executable, str(_BIN), hostile],
        capture_output=True,
        text=True,
        check=True,
    )
    for line in result.stdout.strip().splitlines():
        key, _, value = line.partition("=")
        is_empty_quoted = value == "''"
        is_single_quoted = value.startswith("'") and value.endswith("'")
        is_bare_safe = all(c.isalnum() or c in "_-+/.:" for c in value)
        assert is_empty_quoted or is_single_quoted or is_bare_safe, f"unsafe shell value for {key}: {value!r}"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["--reply", "1"], {"REPLY_MODE": "true", "CHALLENGE_ENABLED": "true"}),
        (["--no-challenge", "1"], {"CHALLENGE_ENABLED": "false", "REPLY_MODE": "false"}),
        (["--codemap", "1"], {"CODEMAP_ENABLED": "true", "SEMBLE_ENABLED": "false"}),
        (["--semble", "1"], {"SEMBLE_ENABLED": "true", "CODEMAP_ENABLED": "false"}),
        (["#1"], {"CLEAN_ARGS": "1"}),
    ],
)
def test_main_flag_routing_via_subprocess(argv: list[str], expected: dict[str, str]) -> None:
    """Each documented flag combination routes correctly through subprocess."""
    result = subprocess.run(
        [sys.executable, str(_BIN), *argv],
        capture_output=True,
        text=True,
        check=True,
    )
    assignments = dict(line.split("=", 1) for line in result.stdout.strip().splitlines())
    for key, val in expected.items():
        assert assignments[key] == val, f"argv={argv!r}: {key}={assignments[key]!r} != {val!r}"
