"""Tests for ``bin/health-monitor-start.sh``.

The script creates a per-agent health-monitoring sentinel under ``/tmp``
and prints two ``KEY=VALUE`` lines (``LAUNCH_AT`` epoch seconds and
``SENTINEL`` absolute path). Required arg: skill ID. The sentinel name
is interpolated verbatim; no input sanitization is performed.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "health-monitor-start.sh"


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


def _parse_kv(output: str) -> dict[str, str]:
    """Parse KEY=VALUE lines from stdout into a dict."""
    pairs = {}
    for line in output.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            pairs[key] = value
    return pairs


def test_missing_skill_id_fails():
    """No arg → ``${1:?skill-id required}`` non-zero exit."""
    result = sh()
    assert result.returncode != 0
    assert "skill-id required" in result.stderr


def test_emits_launch_at_and_sentinel():
    """Output contains both ``LAUNCH_AT=`` and ``SENTINEL=`` lines."""
    skill_id = f"healthmon-test-{os.getpid()}"
    try:
        result = sh(skill_id)
        assert result.returncode == 0
        kv = _parse_kv(result.stdout)
        assert "LAUNCH_AT" in kv
        assert "SENTINEL" in kv
        # LAUNCH_AT is epoch seconds (positive integer).
        assert kv["LAUNCH_AT"].isdigit()
    finally:
        for stale in Path("/tmp").glob(f"research-{skill_id}-check-*"):
            stale.unlink(missing_ok=True)


def test_sentinel_file_created():
    """The sentinel path printed in stdout exists on disk afterwards."""
    skill_id = f"healthmon-sentinel-{os.getpid()}"
    try:
        result = sh(skill_id)
        assert result.returncode == 0
        kv = _parse_kv(result.stdout)
        sentinel_path = Path(kv["SENTINEL"])
        assert sentinel_path.exists()
        # Path format: /tmp/research-<skill_id>-check-<ts>
        assert sentinel_path.parent == Path("/tmp")
        assert sentinel_path.name.startswith(f"research-{skill_id}-check-")
    finally:
        for stale in Path("/tmp").glob(f"research-{skill_id}-check-*"):
            stale.unlink(missing_ok=True)


def test_launch_at_matches_sentinel_timestamp():
    """``LAUNCH_AT`` value is embedded as the trailing ``<ts>`` in the sentinel path."""
    skill_id = f"healthmon-tsmatch-{os.getpid()}"
    try:
        result = sh(skill_id)
        assert result.returncode == 0
        kv = _parse_kv(result.stdout)
        # Sentinel format: /tmp/research-<skill_id>-check-<ts>
        m = re.search(r"-check-(\d+)$", kv["SENTINEL"])
        assert m is not None
        assert m.group(1) == kv["LAUNCH_AT"]
    finally:
        for stale in Path("/tmp").glob(f"research-{skill_id}-check-*"):
            stale.unlink(missing_ok=True)
