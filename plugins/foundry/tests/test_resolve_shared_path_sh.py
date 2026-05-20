"""Tests for ``bin/resolve-shared-path.sh`` plugin shared-dir resolver.

The script resolves a plugin's ``<subdir>`` via a three-tier cascade:
0. ``installed_plugins.json`` registry lookup (skipped without helper)
1. Cache semver scan under ``~/.claude/plugins/cache/borda-ai-rig/<plugin>/...``,
   skipping orphaned version dirs (marked by ``.orphaned_at``)
2. Source-tree fallback ``plugins/<plugin>/<subdir>`` (with stderr warning)

Required args: plugin-name + subdir. Validation: plugin must match
``^[a-zA-Z0-9_-]+$``; subdir must match ``^[a-zA-Z0-9_/-]+$`` and not
contain ``..``. Violations exit 2.
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
    """One arg only → ``${2:?...}`` non-zero exit."""
    result = sh("foundry", env={"HOME": str(tmp_path)})
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_invalid_plugin_traversal_exits_2(tmp_path: Path):
    """Plugin containing ``/`` fails ``^[a-zA-Z0-9_-]+$`` → exit 2."""
    result = sh("../evil", "skills/_shared", env={"HOME": str(tmp_path)})
    assert result.returncode == 2
    assert "invalid PLUGIN" in result.stderr


def test_invalid_plugin_special_chars_exits_2(tmp_path: Path):
    """Plugin with special chars fails regex → exit 2."""
    result = sh("plug!in", "skills/_shared", env={"HOME": str(tmp_path)})
    assert result.returncode == 2
    assert "invalid PLUGIN" in result.stderr


def test_invalid_subdir_traversal_exits_2(tmp_path: Path):
    """Subdir containing ``..`` is rejected → exit 2."""
    result = sh("foundry", "skills/../etc/passwd", env={"HOME": str(tmp_path)})
    assert result.returncode == 2
    assert "invalid SUBDIR" in result.stderr


def test_source_tree_fallback(tmp_path: Path):
    """No cache match → emit ``plugins/<plugin>/<subdir>`` with stderr warning."""
    # CLAUDE_PLUGIN_ROOT empty to prevent helper resolution
    result = sh("foundry", "skills/_shared", env={"HOME": str(tmp_path), "CLAUDE_PLUGIN_ROOT": ""})
    assert result.returncode == 0
    assert result.stdout.strip() == "plugins/foundry/skills/_shared"


def test_valid_cache_hit(tmp_path: Path):
    """Cache contains the subdir → emit cache path (Tier 1)."""
    cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry" / "0.19.0" / "skills" / "_shared"
    cache.mkdir(parents=True)
    result = sh("foundry", "skills/_shared", env={"HOME": str(tmp_path), "CLAUDE_PLUGIN_ROOT": ""})
    assert result.returncode == 0
    assert result.stdout.strip() == str(cache)


def test_orphaned_version_skipped(tmp_path: Path):
    """Version dir with ``.orphaned_at`` is skipped → next-best version selected."""
    base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
    # Newer version marked orphaned
    orphaned_ver = base / "0.20.0"
    orphaned_shared = orphaned_ver / "skills" / "_shared"
    orphaned_shared.mkdir(parents=True)
    (orphaned_ver / ".orphaned_at").write_text("2026-01-01T00:00:00Z\n")
    # Older version usable
    older_ver = base / "0.1.0"
    older_shared = older_ver / "skills" / "_shared"
    older_shared.mkdir(parents=True)
    result = sh("foundry", "skills/_shared", env={"HOME": str(tmp_path), "CLAUDE_PLUGIN_ROOT": ""})
    assert result.returncode == 0
    assert result.stdout.strip() == str(older_shared)
