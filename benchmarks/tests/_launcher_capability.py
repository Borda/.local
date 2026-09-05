"""Capability checks for benchmark launcher artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _raw_codemap_launchers_are_runnable(repo_root: Path) -> bool:
    """Probe both raw launchers, returning false for launch errors, timeouts, or nonzero exits.

    The missing-checkout example cannot start a subprocess because neither executable exists.

    >>> from tempfile import TemporaryDirectory
    >>> with TemporaryDirectory() as directory:
    ...     _raw_codemap_launchers_are_runnable(Path(directory))
    False
    """
    for name in ("scan-index", "scan-query"):
        launcher = repo_root / "plugins" / "codemap-py" / "bin" / name
        try:
            result = subprocess.run([str(launcher), "--help"], capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        if result.returncode != 0:
            return False
    return True
