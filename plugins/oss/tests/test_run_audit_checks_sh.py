"""Tests for ``bin/run_audit_checks.sh``.

The script gathers pre-release readiness data via git + gh. Tags
starting with ``-`` are rejected (option-injection guard) with exit 2.
Heavy git/gh usage → most tests integration. Unit tests cover argument
parsing and the tag-injection guard.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "run_audit_checks.sh"


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


def _make_fake_gh(tmp_path: Path, auth_ok: bool = True) -> Path:
    """Create a fake gh executable in ``tmp_path/bin/``."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / "gh"
    exit_code = 0 if auth_ok else 1
    fake.write_text(f"#!/bin/sh\nif [ \"$1\" = 'auth' ]; then exit {exit_code}; fi\necho '[]'\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def test_unknown_arg(tmp_path: Path):
    """Unrecognized flag → exit 1 "unknown arg"."""
    result = sh("--unknown")
    assert result.returncode == 1
    assert "unknown arg" in result.stderr


def test_invalid_tag_injection(tmp_path: Path):
    """LAST_TAG starting with ``-`` (option injection) → exit 2 "invalid tag"."""
    _make_fake_gh(tmp_path, auth_ok=True)
    env = {
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
        "LAST_TAG": "-injected",  # leading dash triggers rejection
        "HOME": str(tmp_path),
    }
    # No --range provided → script uses LAST_TAG env var path.
    # cwd needs to be a git repo so git rev-parse calls don't fail before
    # the LAST_TAG check. Use the actual project repo root.
    repo_root = Path(__file__).parents[3]
    result = sh("--repo", "owner/repo", env=env, cwd=str(repo_root))
    assert result.returncode == 2
    assert "invalid tag" in result.stderr


@pytest.mark.skipif(not os.getenv("RUN_INTEGRATION"), reason="requires real git + gh")
def test_integration_emits_check_banners():
    """End-to-end: script emits ``--- check: ... ---`` section banners."""
    repo_root = Path(__file__).parents[3]
    result = sh("--repo", "borda-ai/rig", cwd=str(repo_root))
    # Exit 0 or 2 depending on gh auth — never 1 (which is bad-args).
    assert result.returncode != 1
    if result.returncode == 0:
        assert "--- check: gh-auth ---" in result.stdout
