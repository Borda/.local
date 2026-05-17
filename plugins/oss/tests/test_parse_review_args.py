"""Tests for ``plugins/oss/bin/parse-review-args.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


from parse_review_args import parse_review_args  # loaded by conftest.py

_BIN = Path(__file__).resolve().parents[1] / "bin" / "parse-review-args.py"


class TestFlagParsing:
    """parse_review_args: individual flags and combinations — CHALLENGE, CODEMAP, SEMBLE, REPLY."""

    def test_no_challenge_flag(self) -> None:
        result = parse_review_args("--no-challenge 42")
        assert result["CHALLENGE_ENABLED"] == "false"
        assert result["CLEAN_ARGS"] == "42"

    def test_codemap_flag(self) -> None:
        result = parse_review_args("--codemap 7")
        assert result["CODEMAP_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "7"

    def test_semble_flag(self) -> None:
        result = parse_review_args("--semble 7")
        assert result["SEMBLE_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "7"

    def test_multiple_flags(self) -> None:
        result = parse_review_args("--reply --no-challenge --codemap --semble 99")
        assert result["REPLY_MODE"] == "true"
        assert result["CHALLENGE_ENABLED"] == "false"
        assert result["CODEMAP_ENABLED"] == "true"
        assert result["SEMBLE_ENABLED"] == "true"
        assert result["CLEAN_ARGS"] == "99"


class TestInputNormalization:
    """parse_review_args: hash stripping, empty input, flags-only — CLEAN_ARGS normalization."""

    def test_hash_stripping(self) -> None:
        result = parse_review_args("#123")
        assert result["CLEAN_ARGS"] == "123"

    def test_hash_stripping_with_flag(self) -> None:
        result = parse_review_args("--reply #456")
        assert result["REPLY_MODE"] == "true"
        assert result["CLEAN_ARGS"] == "456"

    def test_empty_input(self) -> None:
        result = parse_review_args("")
        assert result["CLEAN_ARGS"] == ""
        assert result["REPLY_MODE"] == "false"
        assert result["CHALLENGE_ENABLED"] == "true"

    def test_flags_only_no_arg(self) -> None:
        """Flag-only invocation leaves CLEAN_ARGS empty (after whitespace trim)."""
        result = parse_review_args("--reply")
        assert result["REPLY_MODE"] == "true"
        assert result["CLEAN_ARGS"] == ""


def test_output_is_eval_safe() -> None:
    """Output assignments must round-trip safely through `eval` — no injection."""
    hostile = "'; touch /tmp/pwned; echo 'x"
    result = subprocess.run(
        [sys.executable, str(_BIN), hostile],
        capture_output=True,
        text=True,
        check=True,
    )
    out = result.stdout
    assert "REPLY_MODE=" in out
    assert "CHALLENGE_ENABLED=" in out
    assert "CODEMAP_ENABLED=" in out
    assert "SEMBLE_ENABLED=" in out
    assert "CLEAN_ARGS=" in out
    for line in out.strip().splitlines():
        key, _, value = line.partition("=")
        assert value, f"empty raw value for {key}"
        is_empty_quoted = value == "''"
        is_single_quoted = value.startswith("'") and value.endswith("'")
        is_bare_safe = all(c.isalnum() or c in "_-+/.:" for c in value)
        assert is_empty_quoted or is_single_quoted or is_bare_safe, f"unsafe value for {key}: {value!r}"


def test_main_invocation_via_subprocess() -> None:
    """End-to-end: subprocess invocation produces parseable shell output."""
    result = subprocess.run(
        [sys.executable, str(_BIN), "--reply", "--codemap", "42"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    assignments = dict(line.split("=", 1) for line in lines)
    assert assignments["REPLY_MODE"] == "true"
    assert assignments["CODEMAP_ENABLED"] == "true"
    assert assignments["CLEAN_ARGS"] == "42"
