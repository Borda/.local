"""Tests for ``bin/check-agent.sh`` plugin-agent installation probe.

The script checks whether a plugin agent is installed, either in the
installed cache (``~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/agents/<agent>.md``)
or in the project-local ``.claude/agents/<agent>.md`` path. Prints
``true`` or ``false``; always exits 0 on the success path. Missing
required args trigger bash ``${1:?...}`` non-zero exit.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "bin" / "check-agent.sh"


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
    """No args → ``${1:?Usage...}`` errors out non-zero."""
    result = sh(env={"HOME": str(tmp_path)}, cwd=str(tmp_path))
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_missing_second_arg_fails(tmp_path: Path):
    """One arg → ``${2:?Usage...}`` errors out non-zero."""
    result = sh("foundry", env={"HOME": str(tmp_path)}, cwd=str(tmp_path))
    assert result.returncode != 0
    assert "Usage" in result.stderr


def test_agent_not_found(tmp_path: Path):
    """No cache match and no local .claude/agents → ``false``."""
    result = sh("oss", "shepherd", env={"HOME": str(tmp_path)}, cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == "false"


def test_agent_found_in_cache(tmp_path: Path):
    """Cache contains ``<plugin>/<version>/agents/<agent>.md`` → ``true``."""
    cache_dir = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "oss" / "0.1.0" / "agents"
    cache_dir.mkdir(parents=True)
    (cache_dir / "shepherd.md").write_text("---\nname: shepherd\n---\n")
    result = sh("oss", "shepherd", env={"HOME": str(tmp_path)}, cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_agent_found_in_local_claude(tmp_path: Path):
    """Local ``.claude/agents/<agent>.md`` (no cache match) → ``true``."""
    local = tmp_path / ".claude" / "agents"
    local.mkdir(parents=True)
    (local / "shepherd.md").write_text("---\nname: shepherd\n---\n")
    # HOME points elsewhere (no cache); CWD has the local file.
    other_home = tmp_path / "alt-home"
    other_home.mkdir()
    result = sh("oss", "shepherd", env={"HOME": str(other_home)}, cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


def test_cache_with_different_agent_returns_false(tmp_path: Path):
    """Cache has only agent X; query for agent Y → ``false``."""
    cache_dir = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "oss" / "0.1.0" / "agents"
    cache_dir.mkdir(parents=True)
    (cache_dir / "shepherd.md").write_text("---\nname: shepherd\n---\n")
    result = sh("oss", "cicd-steward", env={"HOME": str(tmp_path)}, cwd=str(tmp_path))
    assert result.returncode == 0
    assert result.stdout.strip() == "false"
