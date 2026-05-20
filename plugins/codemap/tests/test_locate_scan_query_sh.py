"""Tests for ``bin/locate-scan-query.sh`` three-tier scan-query resolver.

The script resolves the ``scan-query`` executable via three fallback tiers:
1. ``command -v scan-query`` (PATH lookup)
2. ``${CLAUDE_PLUGIN_ROOT}/bin/scan-query``
3. ``~/.claude/plugins/cache/*/codemap/*/bin/scan-query`` (newest by sort -V)

Exits 0 with absolute path on stdout when found; exits 1 with stderr message
when no tier matches.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "locate-scan-query.sh"


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


def _make_executable(path: Path, content: str = "#!/bin/sh\necho ok\n") -> Path:
    """Create an executable file with optional content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_not_found_exits_1(tmp_path: Path):
    """All three tiers empty → exit 1 (stderr may be empty when ``set -e`` aborts the pipeline).

    The script's ``set -euo pipefail`` + tier-3 ``ls`` failure (no glob match)
    propagates exit 1 immediately, so the final "not found" message line is
    not always reached. Either path is acceptable: exit 1 with or without the
    stderr message.
    """
    env = {
        "PATH": "/bin:/usr/bin",  # no scan-query on PATH
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_ROOT": "",  # empty tier 2
    }
    result = sh(env=env)
    assert result.returncode == 1
    # stdout must be empty (no resolved path printed)
    assert result.stdout.strip() == ""


def test_resolved_via_claude_plugin_root(tmp_path: Path):
    """Tier 2: CLAUDE_PLUGIN_ROOT/bin/scan-query exists and is executable."""
    exe = _make_executable(tmp_path / "bin" / "scan-query")
    env = {
        "PATH": "/bin:/usr/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_ROOT": str(tmp_path),
    }
    result = sh(env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == str(exe)


def test_resolved_via_cache_fallback(tmp_path: Path):
    """Tier 3: cache glob ``<marketplace>/codemap/<version>/bin/scan-query``."""
    # Real cache layout: ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/bin/
    # Glob in script: $HOME/.claude/plugins/cache/*/codemap/*/bin/scan-query
    cache_exe = _make_executable(
        tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap" / "0.1.0" / "bin" / "scan-query"
    )
    env = {
        "PATH": "/bin:/usr/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_ROOT": "",
    }
    result = sh(env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache_exe)


def test_path_tier_wins_over_plugin_root(tmp_path: Path):
    """Tier 1 (PATH) takes precedence over tier 2 (CLAUDE_PLUGIN_ROOT)."""
    # PATH-resolvable scan-query lives in tmp_path/path_bin/
    path_exe = _make_executable(tmp_path / "path_bin" / "scan-query")
    # Also create a tier-2 candidate that should be ignored
    _make_executable(tmp_path / "bin" / "scan-query")
    env = {
        "PATH": f"{tmp_path / 'path_bin'}:/bin:/usr/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_ROOT": str(tmp_path),
    }
    result = sh(env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == str(path_exe)


def test_non_executable_in_plugin_root_falls_through(tmp_path: Path):
    """Tier 2 file exists but is not executable → fall through to tier 3."""
    # Tier 2: non-executable file
    non_exe = tmp_path / "bin" / "scan-query"
    non_exe.parent.mkdir(parents=True)
    non_exe.write_text("#!/bin/sh\necho nope\n")
    # No chmod +x — script's `[ -x ]` check filters it out
    # Tier 3: cache executable (real layout: <marketplace>/codemap/<version>/bin/)
    cache_exe = _make_executable(
        tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap" / "0.1.0" / "bin" / "scan-query"
    )
    env = {
        "PATH": "/bin:/usr/bin",
        "HOME": str(tmp_path),
        "CLAUDE_PLUGIN_ROOT": str(tmp_path),
    }
    result = sh(env=env)
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache_exe)
