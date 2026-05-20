"""Tests for ``bin/resolve_preflight.sh``.

The script performs preflight checks for /oss:resolve: gh auth status,
codex plugin availability, git fetch/pull. Outputs KEY=value lines.

Unit test: gh-not-found triggers exit 1 with stderr message.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

_SHADOW_TOOLS = [
    "bash",
    "sh",
    "date",
    "grep",
    "head",
    "xargs",
    "wc",
    "tr",
    "mkdir",
    "git",
    "find",
    "cat",
    "sort",
    "tail",
]


def _make_shadow_bin(tmp_path: Path, exclude: list[str] | None = None) -> Path:
    """Create bin dir with symlinks to system tools, excluding named executables."""
    shadow = tmp_path / "shadow_bin"
    shadow.mkdir(exist_ok=True)
    for tool in _SHADOW_TOOLS:
        if exclude and tool in exclude:
            continue
        found = shutil.which(tool)
        if found:
            link = shadow / tool
            if not link.exists():
                link.symlink_to(found)
    return shadow


SCRIPT = Path(__file__).parent.parent / "bin" / "resolve_preflight.sh"


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


def _make_fake_bin(tmp_path: Path, name: str, script_content: str) -> Path:
    """Create a fake executable in ``tmp_path/bin/``."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    fake = bindir / name
    fake.write_text(script_content)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return fake


def test_gh_not_found(tmp_path: Path):
    """No gh on PATH → exit 1 with stderr "gh not found"."""
    # Shadow bin has real tools but no gh — prevents pre-installed gh on CI from being found.
    shadow = _make_shadow_bin(tmp_path, exclude=["gh"])
    env = {
        "HOME": str(tmp_path),
        "PATH": str(shadow),
    }
    result = sh(env=env, cwd=str(tmp_path))
    assert result.returncode == 1
    assert "gh not found" in result.stderr


def test_gh_present_but_unauthenticated(tmp_path: Path):
    """gh exists but auth fails → exit 1 with "gh found but not authenticated"."""
    # Fake gh that exits non-zero on `auth status`.
    _make_fake_bin(
        tmp_path,
        "gh",
        "#!/bin/sh\nif [ \"$1\" = 'auth' ]; then exit 1; fi\nexit 0\n",
    )
    # Fake claude that says codex not installed (so codex tier doesn't poll).
    _make_fake_bin(tmp_path, "claude", "#!/bin/sh\nexit 0\n")
    env = {
        "HOME": str(tmp_path),
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
    }
    # Use tmp_path as cwd (not a git repo) — the upstream lookup yields empty,
    # so git section is silently skipped.
    result = sh(env=env, cwd=str(tmp_path))
    assert result.returncode == 1
    assert "gh found but not authenticated" in result.stderr


def test_happy_path_mocked(tmp_path: Path):
    """Mocked happy path: authenticated gh → exit 0, GH_OK=true on stdout."""
    _make_fake_bin(
        tmp_path,
        "gh",
        "#!/bin/sh\n"
        'if [ "$1" = "auth" ]; then\n'
        '  echo "Logged in to github.com as testuser (oauth_token)" >&2\n'
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    _make_fake_bin(tmp_path, "claude", "#!/bin/sh\nexit 0\n")
    env = {
        "HOME": str(tmp_path),
        "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
    }
    result = sh(env=env, cwd=str(tmp_path))
    assert result.returncode == 0
    assert "GH_OK=true" in result.stdout
