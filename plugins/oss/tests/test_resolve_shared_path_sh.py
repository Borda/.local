"""Tests for ``bin/resolve-shared-path.sh`` plugin path resolver.

The script resolves a plugin's ``<subdir>`` (e.g. ``skills/_shared``)
from the installed cache and falls back to ``plugins/<plugin>/<subdir>``
when the cache lookup is empty. Prints resolved path; always exits 0
on the success path. Missing required args trigger bash ``${1:?...}``
non-zero exit. No input sanitization beyond bash's standard quoting.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "resolve-shared-path.sh"


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


def test_missing_both_args_fails(tmp_path: Path):
    """No args → ``${1:?...}`` non-zero exit with usage message."""
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_missing_second_arg_fails(tmp_path: Path):
    """One arg → ``${2:?...}`` non-zero exit with usage message."""
    result = sh("oss", env={"HOME": str(tmp_path)})
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_source_tree_fallback(tmp_path: Path):
    """No cache match → emits ``plugins/<plugin>/<subdir>`` fallback."""
    result = sh("oss", "skills/_shared", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == "plugins/oss/skills/_shared"


def test_cache_hit_returns_cached_path(tmp_path: Path):
    """Cache contains the subdir → emit the cache path."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "oss" / "0.1.0" / "skills" / "_shared"
    cache.mkdir(parents=True)
    result = sh("oss", "skills/_shared", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache)


def test_cache_hit_picks_highest_version(tmp_path: Path):
    """Multiple cache versions → ``sort -V | tail -1`` selects newest."""
    base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "oss"
    older = base / "0.1.0" / "skills" / "_shared"
    newer = base / "0.20.0" / "skills" / "_shared"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    result = sh("oss", "skills/_shared", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == str(newer)


def test_custom_subdir_resolves_independently(tmp_path: Path):
    """Subdir arg is interpolated literally; non-_shared dirs also resolve."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "oss" / "0.1.0" / "agents"
    cache.mkdir(parents=True)
    result = sh("oss", "agents", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache)
