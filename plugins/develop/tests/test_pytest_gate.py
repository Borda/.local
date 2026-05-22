"""Tests for ``bin/pytest_gate.py``.

The script validates ``PYTEST_CMD`` against an allowlist
(``pytest``, ``uv run pytest``, ``python -m pytest``), then execs pytest with
``--tb=short -v``. ``subprocess.run`` is monkeypatched so no real test runs;
``shutil.which`` is patched so ``_resolve`` succeeds without the binary present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pytest_gate  # type: ignore[import-not-found]


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


@pytest.fixture
def captured_argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Patch ``subprocess.run`` and ``shutil.which`` inside the script."""
    recorded: list[list[str]] = []

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        recorded.append(list(cmd))
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(pytest_gate.subprocess, "run", _fake_run)
    monkeypatch.setattr(pytest_gate, "which", lambda name: f"/fake/bin/{name}")
    return recorded


def test_default_cmd_and_target(captured_argv: list[list[str]]) -> None:
    """No args → ``pytest --tb=short . -v`` invoked with resolved binary."""
    rc = pytest_gate.main([])
    assert rc == 0
    assert len(captured_argv) == 1
    assert captured_argv[0] == ["/fake/bin/pytest", "--tb=short", ".", "-v"]


def test_allowlisted_uv_run(captured_argv: list[list[str]]) -> None:
    """``"uv run pytest"`` split to 3 tokens; first resolved; full argv passed."""
    rc = pytest_gate.main(["uv run pytest", "tests/"])
    assert rc == 0
    assert captured_argv[0] == ["/fake/bin/uv", "run", "pytest", "--tb=short", "tests/", "-v"]


def test_allowlisted_python_m_pytest(captured_argv: list[list[str]]) -> None:
    """``"python -m pytest"`` split to 3 tokens; first resolved."""
    rc = pytest_gate.main(["python -m pytest", "tests/foo.py"])
    assert rc == 0
    assert captured_argv[0] == ["/fake/bin/python", "-m", "pytest", "--tb=short", "tests/foo.py", "-v"]


def test_rejects_unsafe_cmd(
    captured_argv: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Non-allowlisted cmd → exit 2; subprocess never invoked; stderr contains "rejected"."""
    rc = pytest_gate.main(["rm -rf /", "."])
    assert rc == 2
    assert captured_argv == []
    assert "rejected" in capsys.readouterr().err


def test_rejects_injection_payload(
    captured_argv: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Shell-injection-style payload not in allowlist → exit 2."""
    rc = pytest_gate.main(["python3 -c 'os.system(\"x\")'", "."])
    assert rc == 2
    assert captured_argv == []
    assert "rejected" in capsys.readouterr().err


def test_passes_through_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest exits 1 → ``main`` returns 1 unchanged."""

    def _fake_run(_cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(returncode=1)

    monkeypatch.setattr(pytest_gate.subprocess, "run", _fake_run)
    monkeypatch.setattr(pytest_gate, "which", lambda name: f"/fake/{name}")
    assert pytest_gate.main(["pytest", "tests/"]) == 1


def test_passes_through_collection_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pytest exits 5 (no tests collected) → ``main`` returns 5."""

    def _fake_run(_cmd: list[str], **_kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(returncode=5)

    monkeypatch.setattr(pytest_gate.subprocess, "run", _fake_run)
    monkeypatch.setattr(pytest_gate, "which", lambda name: f"/fake/{name}")
    assert pytest_gate.main(["pytest"]) == 5


def test_rejects_target_outside_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    captured_argv: list[list[str]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Resolved target path outside ``Path.cwd()`` → exit 1; pytest never invoked."""
    cwd_dir = tmp_path / "project"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)
    outside = tmp_path / "outside"
    outside.mkdir()
    rogue = outside / "leak"
    rogue.mkdir()
    with pytest.raises(SystemExit) as exc:
        pytest_gate.main(["pytest", str(rogue)])
    assert exc.value.code == 1
    assert captured_argv == []
    assert "outside project directory" in capsys.readouterr().err


def test_subprocess_called_without_capture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inherits stdout/stderr — no capture flags passed (full output streams through)."""
    recorded_kwargs: dict[str, Any] = {}

    def _fake_run(_cmd: list[str], **kwargs: Any) -> _FakeCompleted:
        recorded_kwargs.update(kwargs)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(pytest_gate.subprocess, "run", _fake_run)
    monkeypatch.setattr(pytest_gate, "which", lambda name: f"/fake/{name}")
    pytest_gate.main(["pytest"])
    assert recorded_kwargs.get("capture_output") in (None, False)
    assert "stdout" not in recorded_kwargs or recorded_kwargs["stdout"] is None
    assert "stderr" not in recorded_kwargs or recorded_kwargs["stderr"] is None
