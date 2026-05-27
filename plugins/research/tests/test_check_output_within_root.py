"""Tests for check_output_within_root.py"""

import subprocess
import sys
import tempfile
import os

BIN = os.path.join(os.path.dirname(__file__), "..", "bin", "check_output_within_root.py")


def test_within_root():
    with tempfile.TemporaryDirectory() as td:
        sub = os.path.join(td, "sub", "dir")
        result = subprocess.run([sys.executable, BIN, sub, td])
        assert result.returncode == 0


def test_equal_to_root():
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run([sys.executable, BIN, td, td])
        assert result.returncode == 0


def test_outside_root():
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run([sys.executable, BIN, "/tmp/evil", td])
        assert result.returncode == 1


def test_path_traversal_blocked():
    with tempfile.TemporaryDirectory() as td:
        traversal = os.path.join(td, "..", "..", "etc")
        result = subprocess.run([sys.executable, BIN, traversal, td])
        assert result.returncode == 1
