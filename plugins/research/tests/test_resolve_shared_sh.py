"""Tests for ``bin/resolve-shared.sh`` plugin shared-dir resolver.

The script resolves the research plugin's ``_shared/`` directory via the
installed cache and falls back to the source-tree path
``plugins/research/skills/_shared`` when no cache match exists. Emits a
stderr warning on fallback. Always exits 0.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "resolve-shared.sh"


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


def test_no_cache_returns_source_fallback(tmp_path: Path):
    """No cache match → emits ``plugins/research/skills/_shared`` source-tree fallback."""
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == "plugins/research/skills/_shared"


def test_cache_hit_returns_cached_path(tmp_path: Path):
    """Cache contains a ``_shared`` dir → emit the cache path."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "research" / "0.1.0" / "skills" / "_shared"
    cache.mkdir(parents=True)
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache)


def test_cache_hit_picks_newest_by_mtime(tmp_path: Path):
    """``ls -td`` orders by mtime descending → newest dir wins."""
    base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "research"
    old_dir = base / "0.1.0" / "skills" / "_shared"
    new_dir = base / "0.2.0" / "skills" / "_shared"
    old_dir.mkdir(parents=True)
    # Set the older one to an earlier mtime
    os.utime(old_dir, (1_700_000_000, 1_700_000_000))
    new_dir.mkdir(parents=True)
    # new_dir keeps current mtime, which is newer than 1.7e9 epoch.
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    # The script's `ls -td .../research/*/skills/_shared` orders version dirs by
    # the version-dir mtime (since the glob is on the *parent* path component).
    # We set old_dir's leaf mtime; but ls -td evaluates on the matched leaves
    # themselves. Verify the newest leaf is picked.
    assert result.stdout.strip() == str(new_dir)


def test_takes_no_args(tmp_path: Path):
    """Script accepts no arguments; extras are ignored without error."""
    result = sh("ignored-arg", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
