"""Tests for ``bin/resolve_preflight.py``.

``subprocess.run`` and ``which`` monkeypatched — no real tools invoked.
``monkeypatch.chdir`` places the ``.claude/state/preflight/`` TTL cache
under ``tmp_path`` (the script uses a relative path).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import resolve_preflight as rp


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _dispatch(responses: dict[str, tuple[int, str]]) -> Any:
    """Build a subprocess.run fake dispatching on the binary name + first subcommand."""

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        binary = Path(cmd[0]).name
        subcmd = cmd[1] if len(cmd) > 1 else ""
        key = f"{binary} {subcmd}".strip()
        for pattern, (rc, out) in responses.items():
            if pattern in key:
                return _FakeCompleted(returncode=rc, stdout=out)
        return _FakeCompleted(returncode=0, stdout="")

    return _fake_run


def test_gh_not_found_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No gh on PATH → exit 1 with 'gh not found' on stderr."""
    monkeypatch.setattr(rp, "which", lambda cmd: None if cmd == "gh" else "/fake/" + cmd)
    monkeypatch.setattr(rp.subprocess, "run", _dispatch({}))
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 1
    assert "gh not found" in capsys.readouterr().err


def test_gh_unauthenticated_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """gh found but auth fails → exit 1 with 'gh found but not authenticated'."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)
    monkeypatch.setattr(
        rp.subprocess,
        "run",
        _dispatch(
            {
                "gh auth": (1, ""),
                "claude plugin": (0, ""),
                "git remote": (0, ""),
                "git rev-parse": (1, ""),
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 1
    assert "gh found but not authenticated" in capsys.readouterr().err


def test_gh_ok_codex_absent_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Authenticated gh, codex absent → exit 0, CODEX_AVAILABLE=false, GH_OK=true."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)
    monkeypatch.setattr(
        rp.subprocess,
        "run",
        _dispatch(
            {
                "gh auth": (0, ""),
                "claude plugin": (0, "some-other-plugin\n"),
                "git remote": (0, ""),
                "git rev-parse": (1, ""),
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "CODEX_AVAILABLE='false'" in out or "CODEX_AVAILABLE=false" in out
    assert "GH_OK=true" in out


def test_gh_ok_codex_present_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Authenticated gh, codex present in plugin list → CODEX_AVAILABLE=true."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)
    monkeypatch.setattr(
        rp.subprocess,
        "run",
        _dispatch(
            {
                "gh auth": (0, ""),
                "claude plugin": (0, "codex@openai-codex\n"),
                "git remote": (0, ""),
                "git rev-parse": (1, ""),
            }
        ),
    )
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "CODEX_AVAILABLE='true'" in out or "CODEX_AVAILABLE=true" in out


def test_gh_cache_hit_skips_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Valid gh cache entry → auth subprocess not called."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)
    calls: list[str] = []

    def _tracking_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        calls.append(Path(cmd[0]).name + " " + (cmd[1] if len(cmd) > 1 else ""))
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(rp.subprocess, "run", _tracking_run)
    monkeypatch.chdir(tmp_path)
    rp._preflight_pass("gh")
    rp.main()
    assert not any("gh auth" in c for c in calls)


def test_remote_ahead_pulls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Remote ahead by 2 commits → git pull invoked, exit 0."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)

    call_n = [0]

    def _seq_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        call_n[0] += 1
        binary = Path(cmd[0]).name
        subcmd = cmd[1] if len(cmd) > 1 else ""
        if binary == "claude":
            return _FakeCompleted(returncode=0, stdout="")
        if binary == "gh" and subcmd == "auth":
            return _FakeCompleted(returncode=0, stdout="")
        if binary == "git" and subcmd == "remote":
            return _FakeCompleted(returncode=0, stdout="origin\t... (fetch)\n")
        if binary == "git" and subcmd == "rev-parse":
            return _FakeCompleted(returncode=0, stdout="origin/main")
        if binary == "git" and subcmd == "fetch":
            return _FakeCompleted(returncode=0)
        if binary == "git" and subcmd == "log":
            return _FakeCompleted(returncode=0, stdout="abc123 commit1\ndef456 commit2\n")
        if binary == "git" and subcmd == "pull":
            return _FakeCompleted(returncode=0)
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(rp.subprocess, "run", _seq_run)
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 0
    assert "git pull: merged" in capsys.readouterr().err


def test_pull_conflict_exits_1(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """git pull returns non-zero → exit 1 with conflict message."""
    monkeypatch.setattr(rp, "which", lambda cmd: "/fake/" + cmd)

    def _conflict_run(cmd: list[str], **_: Any) -> _FakeCompleted:
        binary = Path(cmd[0]).name
        subcmd = cmd[1] if len(cmd) > 1 else ""
        if binary == "claude":
            return _FakeCompleted(returncode=0, stdout="")
        if binary == "gh" and subcmd == "auth":
            return _FakeCompleted(returncode=0, stdout="")
        if binary == "git" and subcmd == "remote":
            return _FakeCompleted(returncode=0, stdout="")
        if binary == "git" and subcmd == "rev-parse":
            return _FakeCompleted(returncode=0, stdout="origin/main")
        if binary == "git" and subcmd == "fetch":
            return _FakeCompleted(returncode=0)
        if binary == "git" and subcmd == "log":
            return _FakeCompleted(returncode=0, stdout="abc123 commit\n")
        if binary == "git" and subcmd == "pull":
            return _FakeCompleted(returncode=1)
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr(rp.subprocess, "run", _conflict_run)
    monkeypatch.chdir(tmp_path)
    rc = rp.main()
    assert rc == 1
    assert "git pull had conflicts" in capsys.readouterr().err


def test_preflight_ok_expired_returns_false(tmp_path: Path) -> None:
    """Cache file with timestamp >4h old → ``_preflight_ok`` returns False."""
    state_dir = tmp_path / "preflight"
    state_dir.mkdir()
    old_ts = 0
    (state_dir / "gh.ok").write_text(str(old_ts))
    assert rp._preflight_ok("gh", state_dir) is False


def test_preflight_ok_fresh_returns_true(tmp_path: Path) -> None:
    """Cache file written by ``_preflight_pass`` → ``_preflight_ok`` returns True."""
    state_dir = tmp_path / "preflight"
    rp._preflight_pass("gh", state_dir)
    assert rp._preflight_ok("gh", state_dir) is True
