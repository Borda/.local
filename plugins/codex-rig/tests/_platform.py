"""Platform capability probes shared by Codex Rig tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def _symlinks_available() -> bool:
    """Return whether the current host permits creating a file symlink.

    Windows can, given Developer Mode or an elevated session, and the hosted CI runner does —
    so the question is a per-host capability, not a platform. Asking it by attempting the
    operation keeps the answer honest on both sides instead of writing Windows off wholesale.
    """
    with tempfile.TemporaryDirectory() as scratch:
        root = Path(scratch)
        source = root / "source"
        target = root / "target"
        source.write_text("fixture\n", encoding="utf-8")
        try:
            target.symlink_to(source)
        except (OSError, NotImplementedError):
            return False
        return target.is_symlink()


SYMLINKS_AVAILABLE = _symlinks_available()


def _bash_candidates() -> list[str]:
    """Return Bash candidates, preferring Git for Windows over WSL."""
    if os.name != "nt":
        located = shutil.which("bash")
        return [located] if located else []

    candidates: list[str] = []
    configured = os.environ.get("GIT_BASH")
    if configured:
        candidates.append(configured)
    git_executable = shutil.which("git")
    if git_executable:
        git_directory = Path(git_executable).resolve().parent
        candidates.extend((str(git_directory / "bash.exe"), str(git_directory.parent / "bin" / "bash.exe")))
    for variable in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            suffix = "Programs/Git/bin/bash.exe" if variable == "LOCALAPPDATA" else "Git/bin/bash.exe"
            candidates.append(str(Path(root) / suffix))
    return candidates


def _find_posix_bash() -> str | None:
    """Return a Bash executable that actually evaluates a POSIX command."""
    for candidate in _bash_candidates():
        try:
            result = subprocess.run(
                [candidate, "-c", "printf ok"], capture_output=True, text=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode == 0 and result.stdout.strip() == "ok":
            return candidate
    return None


POSIX_BASH = _find_posix_bash()
