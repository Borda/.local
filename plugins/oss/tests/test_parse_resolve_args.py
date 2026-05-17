"""Tests for ``plugins/oss/bin/parse-resolve-args.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


from parse_resolve_args import parse_resolve_args  # loaded by conftest.py

_BIN = Path(__file__).resolve().parents[1] / "bin" / "parse-resolve-args.py"


class TestModeRouting:
    """parse_resolve_args: input-to-mode routing — PR number, URL, report, comment-dispatch."""

    def test_pr_number_hash(self) -> None:
        result = parse_resolve_args("#42")
        assert result["PR_NUMBER"] == "42"
        assert result["MODE"] == "pr"
        # ARGUMENTS preserved with leading '#' — not comment-dispatch
        assert result["ARGUMENTS"] == "#42"

    def test_pr_number_bare_with_report(self) -> None:
        result = parse_resolve_args("42 report")
        assert result["PR_NUMBER"] == "42"
        assert result["MODE"] == "pr+report"

    def test_github_url_with_report(self) -> None:
        url = "https://github.com/owner/repo/pull/7"
        result = parse_resolve_args(f"{url} report")
        assert result["PR_URL"] == url
        assert result["MODE"] == "pr+report"

    def test_bare_report(self) -> None:
        result = parse_resolve_args("report")
        assert result["MODE"] == "report"
        assert result["PR_NUMBER"] == ""
        assert result["PR_URL"] == ""

    def test_bare_report_with_whitespace(self) -> None:
        result = parse_resolve_args("  report  ")
        assert result["MODE"] == "report"

    def test_comment_dispatch_no_hash(self) -> None:
        result = parse_resolve_args("please review the logic")
        assert result["MODE"] == "comment-dispatch"
        assert result["ARGUMENTS"] == "please review the logic"

    def test_empty_input_routes_to_comment_dispatch(self) -> None:
        result = parse_resolve_args("")
        assert result["MODE"] == "comment-dispatch"
        assert result["ARGUMENTS"] == ""


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
    assert "PR_NUMBER=" in out
    assert "PR_URL=" in out
    assert "MODE=" in out
    assert "ARGUMENTS=" in out
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
        [sys.executable, str(_BIN), "42"],
        capture_output=True,
        text=True,
        check=True,
    )
    lines = result.stdout.strip().splitlines()
    assignments = dict(line.split("=", 1) for line in lines)
    assert assignments["PR_NUMBER"] == "42"
    assert assignments["MODE"] == "pr"
