"""Pytest fixtures and shared helpers for research plugin bin/ tests.

Adds ``plugins/cc_research/bin/`` to ``sys.path`` so test modules can import scripts directly,
and resolves a usable POSIX shell for the tests that execute the shipped bash blocks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))


def _bash_candidates() -> list[str]:
    """Absolute or PATH-resolvable bash commands worth probing, best first."""
    if sys.platform != "win32":
        return ["bash"]
    # System32\bash.exe is the WSL launcher, not a shell: with no distribution installed it
    # prints an error and exits 1 before reading -c at all, and it shadows Git's bash because
    # System32 precedes Git on the runner PATH. Git's own bash is therefore tried first.
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432"), os.environ.get("ProgramFiles(x86)")]
    found = [str(Path(root) / "Git" / sub / "bash.exe") for root in roots if root for sub in ("bin", "usr/bin")]
    which = shutil.which("bash")
    return [*found, which] if which else found


@pytest.fixture(scope="session")
def posix_bash() -> str:
    """Return a bash that actually runs a script, skipping the test when the host has none.

    A capability probe rather than a platform check: the question is whether a working POSIX
    shell exists, and the answer differs between a Git-for-Windows host and a bare one. Every
    candidate is executed, so a launcher stub that exits before interpreting ``-c`` is rejected
    on behaviour instead of on its filename.
    """
    for candidate in _bash_candidates():
        try:
            probe = subprocess.run([candidate, "-c", "printf ok"], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "ok":
            return candidate
    pytest.skip("no working POSIX bash on this host")
