"""Tests for ``bin/codemap-flags.sh`` argument-string parser.

The script resolves CODEMAP_ENABLED value from ``$ARGUMENTS`` to one of
``off``, ``strict``, or ``auto``. It always exits 0; no validation is
performed (substring match only).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "codemap-flags.sh"


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


def test_no_codemap_flag_returns_off():
    """``--no-codemap`` substring resolves to ``off``."""
    result = sh("--no-codemap")
    assert result.returncode == 0
    assert result.stdout.strip() == "off"


def test_codemap_flag_returns_strict():
    """``--codemap`` substring (without leading ``--no-``) resolves to ``strict``."""
    result = sh("--codemap")
    assert result.returncode == 0
    assert result.stdout.strip() == "strict"


def test_no_flag_returns_auto():
    """Empty argument string resolves to default ``auto``."""
    result = sh("")
    assert result.returncode == 0
    assert result.stdout.strip() == "auto"


def test_unrelated_flag_returns_auto():
    """Unrelated flags resolve to default ``auto``."""
    result = sh("--team --mode fix")
    assert result.returncode == 0
    assert result.stdout.strip() == "auto"


def test_no_codemap_overrides_codemap():
    """``--no-codemap`` precedes ``--codemap`` in branch order → ``off`` wins."""
    result = sh("--no-codemap --codemap")
    assert result.returncode == 0
    assert result.stdout.strip() == "off"


def test_missing_argument_treated_as_empty():
    """No positional arg falls through to default ``auto`` via ``${1:-}``."""
    result = sh()
    assert result.returncode == 0
    assert result.stdout.strip() == "auto"
