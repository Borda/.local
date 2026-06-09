"""Tests for ``bin/run_pytest_short.py``.

The script validates ``PYTEST_CMD`` against the same allowlist as ``pytest_gate``,
captures combined stdout+stderr from pytest via incremental ``Popen`` reads
(byte-capped at ``_MAX_OUTPUT_BYTES``), then prints only the last ``tail_n``
lines (default 20). Bad ``tail_n`` falls back to 20. ``subprocess.Popen`` is
monkeypatched so no real pytest runs.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import pytest

import run_pytest_short  # type: ignore[import-not-found]


class _FakePopen:
    """Stand-in for ``subprocess.Popen`` exposing a readable ``stdout`` stream."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = io.StringIO(stdout)

    def wait(self, timeout: float | None = None) -> int:
        """Return stored returncode; accepts optional timeout kwarg to match real Popen."""
        return self.returncode


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returncode: int = 0,
    stdout: str = "",
) -> list[dict[str, Any]]:
    """Patch ``subprocess.Popen`` to return a fake process; record call kwargs."""
    recorded: list[dict[str, Any]] = []

    def _fake_popen(cmd: list[str], **kwargs: Any) -> _FakePopen:
        recorded.append({"cmd": list(cmd), **kwargs})
        return _FakePopen(returncode=returncode, stdout=stdout)

    monkeypatch.setattr(run_pytest_short.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(run_pytest_short, "which", lambda name: f"/fake/{name}")
    return recorded


def _make_lines(n: int) -> str:
    """Build a string with ``n`` numbered lines (``line-1`` … ``line-n``)."""
    return "\n".join(f"line-{i + 1}" for i in range(n))


def test_default_tail_20(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """30 lines of output, default tail (20) → only lines 11..30 printed."""
    _patch_subprocess(monkeypatch, returncode=0, stdout=_make_lines(30))
    rc = run_pytest_short.main(["pytest", "."])
    assert rc == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines == [f"line-{i}" for i in range(11, 31)]
    assert len(out_lines) == 20


def test_custom_tail_n(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """``tail_n=5`` → only the last 5 lines printed."""
    _patch_subprocess(monkeypatch, returncode=0, stdout=_make_lines(30))
    rc = run_pytest_short.main(["pytest", ".", "5"])
    assert rc == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines == [f"line-{i}" for i in range(26, 31)]
    assert len(out_lines) == 5


def test_bad_tail_n_falls_back_to_20(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``tail_n="abc"`` → silently uses default 20."""
    _patch_subprocess(monkeypatch, returncode=0, stdout=_make_lines(25))
    rc = run_pytest_short.main(["pytest", ".", "abc"])
    assert rc == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert len(out_lines) == 20
    assert out_lines == [f"line-{i}" for i in range(6, 26)]


def test_tail_n_larger_than_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``tail_n`` greater than line count → entire output printed."""
    _patch_subprocess(monkeypatch, returncode=0, stdout=_make_lines(3))
    rc = run_pytest_short.main(["pytest", ".", "100"])
    assert rc == 0
    out_lines = capsys.readouterr().out.splitlines()
    assert out_lines == ["line-1", "line-2", "line-3"]


def test_passes_through_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest exits 4 → ``main`` returns 4 unchanged."""
    _patch_subprocess(monkeypatch, returncode=4, stdout=_make_lines(5))
    assert run_pytest_short.main(["pytest"]) == 4


def test_rejects_unsafe_cmd(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-allowlisted cmd → exit 2; subprocess never invoked; stderr contains "rejected"."""
    recorded = _patch_subprocess(monkeypatch, returncode=0, stdout="")
    rc = run_pytest_short.main(["rm -rf /", "."])
    assert rc == 2
    assert recorded == []
    assert "rejected" in capsys.readouterr().err


def test_combined_stdout_stderr_captured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Subprocess invoked with ``stdout=PIPE`` and ``stderr=STDOUT`` for merged tailing."""
    recorded = _patch_subprocess(monkeypatch, returncode=0, stdout=_make_lines(5))
    run_pytest_short.main(["pytest"])
    assert len(recorded) == 1
    call = recorded[0]
    assert call["stdout"] == subprocess.PIPE
    assert call["stderr"] == subprocess.STDOUT
    assert call.get("text") is True


def test_rejects_target_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Resolved target path outside ``Path.cwd()`` → exit 1; Popen never invoked."""
    recorded = _patch_subprocess(monkeypatch, returncode=0, stdout="")
    cwd_dir = tmp_path / "project"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    rogue = outside / "leak"
    rogue.mkdir()
    with pytest.raises(SystemExit) as exc:
        run_pytest_short.main(["pytest", str(rogue)])
    assert exc.value.code == 1
    assert recorded == []
    assert "outside project directory" in capsys.readouterr().err


def test_resolves_first_token_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """``"uv run pytest"`` → only ``uv`` is path-resolved; other tokens kept literal."""
    recorded = _patch_subprocess(monkeypatch, returncode=0, stdout="")
    run_pytest_short.main(["uv run pytest", "tests/"])
    cmd = recorded[0]["cmd"]
    assert cmd[0] == "/fake/uv"
    assert cmd[1] == "run"
    assert cmd[2] == "pytest"
