"""Shared platform fixtures for Codex Rig tests."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def posix_bash() -> str:
    """Return a POSIX Bash executable without selecting Windows' WSL launcher."""
    if os.name != "nt":
        executable = shutil.which("bash")
        if executable is None:
            pytest.skip("POSIX Bash is unavailable")
        return executable

    candidates: list[Path] = []
    configured = os.environ.get("GIT_BASH")
    if configured:
        candidates.append(Path(configured))

    # Anchor Windows discovery to Git because bare `bash` may be the WSL launcher.
    git_executable = shutil.which("git")
    if git_executable:
        git_directory = Path(git_executable).resolve().parent
        candidates.extend((git_directory / "bash.exe", git_directory.parent / "bin" / "bash.exe"))

    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            relative = Path("Programs/Git/bin/bash.exe") if variable == "LOCALAPPDATA" else Path("Git/bin/bash.exe")
            candidates.append(Path(root) / relative)

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    pytest.fail("Git for Windows Bash is required for sync integration tests")
