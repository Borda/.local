"""Tests for check_output_within_root.py."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

BIN = os.path.join(os.path.dirname(__file__), "..", "bin", "check_output_within_root.py")


def test_within_root(tmp_path: Path):
    sub = tmp_path / "sub" / "dir"
    result = subprocess.run([sys.executable, BIN, str(sub), str(tmp_path)])
    assert result.returncode == 0


def test_equal_to_root(tmp_path: Path):
    result = subprocess.run([sys.executable, BIN, str(tmp_path), str(tmp_path)])
    assert result.returncode == 0


@pytest.mark.parametrize("case", ["absolute_tmp", "sibling_prefix", "relative_parent"])
def test_outside_root(case: str, tmp_path: Path):
    if case == "absolute_tmp":
        candidate = "/tmp/evil"
    elif case == "sibling_prefix":
        candidate = f"{tmp_path}-evil"
    else:
        sibling = tmp_path.parent / "sibling"
        candidate = tmp_path / ".." / sibling.name
    result = subprocess.run([sys.executable, BIN, str(candidate), str(tmp_path)])
    assert result.returncode == 1


def test_path_traversal_blocked(tmp_path: Path):
    traversal = tmp_path / ".." / ".." / "etc"
    result = subprocess.run([sys.executable, BIN, str(traversal), str(tmp_path)])
    assert result.returncode == 1


def test_help_exits_zero():
    """Print usage and exit 0 (argparse contract)."""
    result = subprocess.run([sys.executable, BIN, "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "usage" in result.stdout.lower()


def test_golden_invocation_within_root(tmp_path: Path):
    """Protect the documented behavior against regression: the SKILL call shape ``<candidate> <root>`` (2 positional)
    still exits 0 within root."""
    sub = tmp_path / "sub"
    sub.mkdir()
    result = subprocess.run([sys.executable, BIN, str(sub), str(tmp_path)])
    assert result.returncode == 0
