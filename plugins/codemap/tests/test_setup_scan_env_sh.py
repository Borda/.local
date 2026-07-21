"""Tests for ``bin/setup_scan_env.sh`` — scan-codebase setup state file generation.

Covered scenarios:
- Bad CLI args → exit 3, no state file.
- Missing ``scan-index`` binary (bogus ``CLAUDE_PLUGIN_ROOT``) → exit 1, message on stderr.
- Happy path — state file written, sourceable, KEY=VAL contents match expected fields,
  per-PROJ_SLUG tmpfiles populated.
- ``--root`` extraction overrides ``PROJ_NAME`` (basename of ``--root`` value, not repo).
- ``--incremental`` sentinel created when no prior index exists for ``PROJ_NAME``.
- ``--incremental`` sentinel absent when prior index exists.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "setup_scan_env.sh"
PLUGIN_ROOT = Path(__file__).parent.parent  # contains real bin/scan-index


def sh(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``setup_scan_env.sh`` under bash with explicit env override.

    Args:
        *args: Positional arguments forwarded to the script.
        env: Environment overlay (``None`` ⇒ inherit only).
        cwd: Working directory for the invocation.

    Returns:
        Captured ``CompletedProcess`` with text-mode stdout/stderr.
    """
    e = {**os.environ, **(env or {})}
    # Force the script's CSID="${CSID:-shared}" fallback regardless of the host shell —
    # a real Claude Code session (like the one running this suite) never sets CSID itself,
    # only CLAUDE_CODE_SESSION_ID (which the script does not read directly).
    e.pop("CSID", None)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=e,
        cwd=cwd,
    )


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """Return a throwaway directory acting as a fake repo root.

    setup_scan_env.sh uses ``git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD"``
    so it falls back to $PWD when git is unavailable — no real git repo needed.

    Returns:
        Directory path used as the working directory for script invocations.
    """
    return tmp_path


@pytest.fixture()
def isolated_tmpdir(tmp_path: Path) -> Path:
    """Provide a fresh ``TMPDIR`` so per-PROJ_SLUG tmpfiles don't leak across tests.

    Returns:
        Directory path passed as ``TMPDIR`` to the script.
    """
    d = tmp_path / "tmp"
    d.mkdir()
    return d


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    """Bad CLI shapes must fail fast with exit 3 and never touch tmpfiles."""

    def test_unknown_flag(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """An unknown long flag exits 3 with a stderr message."""
        r = sh(
            "--bogus",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 3
        assert "unknown argument" in r.stderr

    def test_arguments_without_value(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """``--arguments`` without a following token exits 3."""
        r = sh(
            "--arguments",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 3
        assert "needs a value" in r.stderr


# ---------------------------------------------------------------------------
# Missing scan-index binary
# ---------------------------------------------------------------------------


class TestMissingScanIndex:
    """Bogus ``CLAUDE_PLUGIN_ROOT`` ⇒ scan-index validation fails (exit 1)."""

    def test_bogus_plugin_root(self, fake_repo: Path, isolated_tmpdir: Path, tmp_path: Path) -> None:
        """Pointing ``CLAUDE_PLUGIN_ROOT`` at an empty dir surfaces the missing-binary error."""
        empty = tmp_path / "no-plugin"
        empty.mkdir()
        r = sh(
            "--arguments",
            "",
            env={"CLAUDE_PLUGIN_ROOT": str(empty), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 1
        assert "scan-index binary not found" in r.stderr
        # No state file should have been printed.
        assert r.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Happy path — state file + per-PROJ_SLUG tmpfiles
# ---------------------------------------------------------------------------


def _read_state(state_file: Path) -> dict[str, str]:
    """Parse the script's KEY='value' state file into a dict.

    Bash sourcing semantics are emulated via a small subshell that ``source``s
    the file and prints each variable — preserves the script's contract that
    the file is sourceable.

    Args:
        state_file: Path written by ``setup_scan_env.sh``.

    Returns:
        Mapping ``{PROJ_SLUG, SCAN_BIN, SCAN_ARGS_RAW, PROJ_NAME}``.
    """
    script = (
        f'source "{state_file}" && '
        'printf "PROJ_SLUG\\t%s\\n" "$PROJ_SLUG" && '
        'printf "SCAN_BIN\\t%s\\n" "$SCAN_BIN" && '
        'printf "SCAN_ARGS_RAW\\t%s\\n" "$SCAN_ARGS_RAW" && '
        'printf "PROJ_NAME\\t%s\\n" "$PROJ_NAME"'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True)
    out: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("\t")
        out[key] = value
    return out


class TestHappyPath:
    """Normal invocation produces a sourceable state file and per-slug tmpfiles."""

    def _run_minimal(self, fake_repo: Path, isolated_tmpdir: Path) -> dict[str, str]:
        """Run the minimal setup invocation and return the sourced state."""
        r = sh(
            "--arguments",
            "",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 0, r.stderr
        state_path = Path(r.stdout.strip())
        assert state_path.is_file(), f"state file not created at {state_path}"
        return _read_state(state_path)

    def test_minimal_invocation_writes_sourceable_state(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """No flags writes a sourceable state file with project identity and scan command fields."""
        state = self._run_minimal(fake_repo, isolated_tmpdir)
        assert state["PROJ_NAME"] == fake_repo.name
        # PROJ_SLUG ends in the sanitised repo basename — the script's `tr -cd '[:alnum:]-'`
        # strips underscores and other punctuation, so compare on the sanitised form.
        sanitised_repo = "".join(c for c in fake_repo.name if c.isalnum() or c == "-")
        assert state["PROJ_SLUG"].endswith(sanitised_repo)
        assert state["SCAN_BIN"].endswith("/bin/scan-index")
        assert state["SCAN_ARGS_RAW"] == ""

    def test_minimal_invocation_writes_per_slug_tmpfiles(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """Per-PROJ_SLUG tmpfiles exist with content matching the sourceable state.

        ``CSID`` env var is unset in the test invocation (only inherited by real
        ``export CSID=...`` callers), so the script's ``CSID="${CSID:-shared}"``
        fallback applies — every written filename carries a terminal ``-shared``.
        """
        state = self._run_minimal(fake_repo, isolated_tmpdir)
        slug = state["PROJ_SLUG"]
        assert (isolated_tmpdir / "codemap-proj-slug-shared").read_text() == slug
        assert (isolated_tmpdir / f"codemap-proj-name-{slug}-shared").read_text() == fake_repo.name
        assert (isolated_tmpdir / f"codemap-scan-bin-{slug}-shared").read_text() == state["SCAN_BIN"]
        assert (isolated_tmpdir / f"codemap-scan-args-{slug}-shared").read_text() == ""

    def test_minimal_invocation_does_not_create_incremental_sentinel(
        self, fake_repo: Path, isolated_tmpdir: Path
    ) -> None:
        """No --incremental request leaves the fallback sentinel absent."""
        state = self._run_minimal(fake_repo, isolated_tmpdir)
        slug = state["PROJ_SLUG"]
        assert not (isolated_tmpdir / f"codemap-incremental-noop-{slug}-shared").exists()

    def test_root_flag_overrides_proj_name(self, fake_repo: Path, isolated_tmpdir: Path, tmp_path: Path) -> None:
        """``--root /some/other`` ⇒ PROJ_NAME = basename(other), not repo basename."""
        other = tmp_path / "alt-project"
        other.mkdir()
        r = sh(
            "--arguments",
            f"--root {other}",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 0, r.stderr
        state = _read_state(Path(r.stdout.strip()))
        assert state["PROJ_NAME"] == "alt-project"
        assert state["SCAN_ARGS_RAW"] == f"--root {other}"

    def test_root_flag_with_spaces_overrides_proj_name(
        self, fake_repo: Path, isolated_tmpdir: Path, tmp_path: Path
    ) -> None:
        """A quoted ``--root`` path containing spaces still drives project identity."""
        other = tmp_path / "alt project with spaces"
        other.mkdir()
        raw_args = f"--root {shlex.quote(str(other))}"
        r = sh(
            "--arguments",
            raw_args,
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 0, r.stderr
        state = _read_state(Path(r.stdout.strip()))
        assert state["PROJ_NAME"] == other.name
        assert str(other) in state["SCAN_ARGS_RAW"]


# ---------------------------------------------------------------------------
# --incremental sentinel behaviour
# ---------------------------------------------------------------------------


class TestIncrementalSentinel:
    """``--incremental`` flag interacts with the prior-index check."""

    def test_sentinel_created_when_no_prior_index(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """``--incremental`` with no ``.cache/codemap/<proj>.json`` writes the sentinel."""
        r = sh(
            "--arguments",
            "--incremental",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 0, r.stderr
        # Informational message routed to stderr — keeps stdout reserved for state path.
        assert "No prior index" in r.stderr

        state = _read_state(Path(r.stdout.strip()))
        slug = state["PROJ_SLUG"]
        sentinel = isolated_tmpdir / f"codemap-incremental-noop-{slug}-shared"
        assert sentinel.is_file(), "incremental-noop sentinel should have been created"

    def test_sentinel_absent_when_prior_index_exists(self, fake_repo: Path, isolated_tmpdir: Path) -> None:
        """``--incremental`` with an existing prior index ⇒ no sentinel, no stderr notice."""
        cache_dir = fake_repo / ".cache" / "codemap"
        cache_dir.mkdir(parents=True)
        (cache_dir / f"{fake_repo.name}.json").write_text("{}")

        r = sh(
            "--arguments",
            "--incremental",
            env={"CLAUDE_PLUGIN_ROOT": str(PLUGIN_ROOT), "TMPDIR": str(isolated_tmpdir)},
            cwd=str(fake_repo),
        )
        assert r.returncode == 0, r.stderr
        assert "No prior index" not in r.stderr

        state = _read_state(Path(r.stdout.strip()))
        slug = state["PROJ_SLUG"]
        assert not (isolated_tmpdir / f"codemap-incremental-noop-{slug}-shared").exists()


# ---------------------------------------------------------------------------
# Module-level skip — script depends on real `git` + `python` on PATH.
# ---------------------------------------------------------------------------


pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("python3") is None,
    reason="setup_scan_env.sh uses POSIX-only tools (hostname -s, tr) — not supported on Windows",
)
