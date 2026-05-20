"""Tests for ``bin/search_downstream_consumers.sh``.

The script queries the GitHub code-search API for repos importing changed
symbols. Required: ``--package <name>`` and at least one symbol (argv or
stdin). Missing inputs exit 1; all queries failing exits 2; success prints
deduplicated repo full_names.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "search_downstream_consumers.sh"


def sh(
    *args: str,
    env: dict | None = None,
    cwd: str | None = None,
    stdin_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the script under test and capture stdout/stderr."""
    e = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
    )


def test_missing_package():
    """No ``--package`` → exit 1 "--package required"."""
    result = sh()
    assert result.returncode == 1
    assert "--package required" in result.stderr


def test_no_symbols_argv_only(tmp_path: Path):
    """``--package`` but no symbols + no stdin → exit 1 "no symbols provided".

    Pass empty stdin to ensure ``[ ! -t 0 ]`` resolves the stdin branch but
    yields zero symbols.
    """
    result = sh("--package", "mylib", stdin_text="")
    assert result.returncode == 1
    assert "no symbols provided" in result.stderr


def test_argv_symbols_accepted_without_stdin(tmp_path: Path):
    """Symbols on argv with closed stdin → script proceeds past validation."""
    # We pass stdin_text=None so subprocess inherits parent stdin; but since
    # parent's stdin in tests is closed/terminal-like, [ ! -t 0 ] depends on
    # context. To be deterministic, pass an empty string for stdin: this means
    # stdin is a pipe (not a terminal), but argv already has symbols so the
    # stdin branch is skipped.
    result = sh("--package", "mylib", "MySymbol", stdin_text="")
    # Script will call `gh api search/code` which will fail without auth →
    # all-failed → exit 2. Either way, exit != 1 (validation passes).
    assert result.returncode != 1


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real gh auth + network")
def test_integration_emits_repos():
    """End-to-end: real gh code search returns repo names (or empty)."""
    result = sh("--package", "requests", "get")
    # Either gh succeeds (rc=0) or fails-all (rc=2).
    assert result.returncode in (0, 2)
