"""Capability checks for benchmark launcher artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path


def raw_codemap_launchers_are_runnable(repo_root: Path) -> bool:
    """Return whether both shipped raw Codemap launchers can run on this host."""
    for name in ("scan-index", "scan-query"):
        launcher = repo_root / "plugins" / "codemap-py" / "bin" / name
        try:
            result = subprocess.run([str(launcher), "--help"], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
    return True
