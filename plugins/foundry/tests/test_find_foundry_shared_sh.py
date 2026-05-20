"""Tests for ``bin/find-foundry-shared.sh`` plugin shared-dir resolver.

The script resolves the foundry plugin's ``_shared/`` directory via the
installed cache (``~/.claude/plugins/cache/borda-ai-rig/foundry/.../_shared``)
and falls back to the source-tree path (``plugins/foundry/skills/_shared``)
when the cache lookup is empty. Always exits 0.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "find-foundry-shared.sh"

SOURCE_FALLBACK = "plugins/foundry/skills/_shared"


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
    """Empty HOME (no cache hit) emits the source-tree fallback path."""
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == SOURCE_FALLBACK


def test_cache_hit_returns_cached_path(tmp_path: Path):
    """When the foundry cache contains a ``_shared`` dir, that path is emitted."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry" / "0.19.0" / "skills" / "_shared"
    cache.mkdir(parents=True)
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    # The find command searches up to depth 3 from the foundry/ root; the cached
    # `_shared/` lives at depth 3 (foundry/<version>/skills/_shared) — match.
    assert result.stdout.strip() == str(cache)


def test_cache_hit_picks_highest_version(tmp_path: Path):
    """Sort-reverse means newer semver dir wins (lexical fallback for non-numeric)."""
    base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
    older = base / "0.1.0" / "skills" / "_shared"
    newer = base / "0.20.0" / "skills" / "_shared"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    # sort -Vr orders semantically; 0.20.0 sorts above 0.1.0.
    assert result.stdout.strip() == str(newer)


def test_takes_no_args(tmp_path: Path):
    """Script accepts no arguments; extras are ignored without error."""
    result = sh("ignored-arg", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == SOURCE_FALLBACK
