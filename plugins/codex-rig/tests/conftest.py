"""Shared platform fixtures for Codex Rig tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

from _platform import POSIX_BASH  # noqa: E402


@pytest.fixture(scope="session")
def posix_bash() -> str:
    """Return the decorator-validated POSIX Bash executable."""
    assert POSIX_BASH is not None, "POSIX Bash test lacks requires_posix_bash"
    return POSIX_BASH
