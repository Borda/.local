"""Tests for ``bin/dev-shared-resolve.sh`` plugin shared-dir resolver.

The script prints the resolved ``_shared/`` directory for the ``develop``
plugin. With ``--foundry``, a second line is emitted with the resolved
foundry ``_shared/`` directory. Resolution tier: cache first
(``~/.claude/plugins/cache/borda-ai-rig/<plugin>/...``), then source-tree
fallback (``plugins/<plugin>/skills/_shared``).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "dev-shared-resolve.sh"

DEV_SOURCE_FALLBACK = "plugins/develop/skills/_shared"
FOUNDRY_SOURCE_FALLBACK = "plugins/foundry/skills/_shared"


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


def test_no_cache_uses_dev_source_fallback(tmp_path: Path):
    """Empty HOME (no cache hit) emits the source-tree develop fallback path."""
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == DEV_SOURCE_FALLBACK


def test_no_cache_foundry_flag_emits_two_fallbacks(tmp_path: Path):
    """``--foundry`` with no cache yields develop fallback + foundry fallback (two lines)."""
    result = sh("--foundry", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines == [DEV_SOURCE_FALLBACK, FOUNDRY_SOURCE_FALLBACK]


def test_cache_hit_uses_cached_dev_path(tmp_path: Path):
    """When develop cache contains a ``_shared`` dir, that path is emitted."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop" / "1.0.0" / "skills" / "_shared"
    cache.mkdir(parents=True)
    result = sh(env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache)


def test_cache_hit_both_with_foundry_flag(tmp_path: Path):
    """``--foundry`` with both caches populated yields both cache paths."""
    dev_cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop" / "1.0.0" / "skills" / "_shared"
    foundry_cache = (
        tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry" / "2.0.0" / "skills" / "_shared"
    )
    dev_cache.mkdir(parents=True)
    foundry_cache.mkdir(parents=True)
    result = sh("--foundry", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert lines == [str(dev_cache), str(foundry_cache)]


def test_unknown_flag_does_not_emit_foundry_line(tmp_path: Path):
    """Any flag other than ``--foundry`` produces only the develop path."""
    result = sh("--unknown", env={"HOME": str(tmp_path)})
    assert result.returncode == 0
    assert result.stdout.strip() == DEV_SOURCE_FALLBACK
