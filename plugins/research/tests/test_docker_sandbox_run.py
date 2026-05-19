"""Tests for ``docker_sandbox_run.py``.

Covers:
    - ``build_explore_command`` / ``build_verify_command`` argv shape (pure functions).
    - ``main()``: mode dispatch, ``SANDBOX_NETWORK`` override, bad-arg exit 2, return-code forwarding,
      missing-docker handling.
"""

from __future__ import annotations

from typing import Any

import pytest

import docker_sandbox_run as ds


# ---------- Pure builders ----------


def test_build_explore_command_strips_leading_dotslash() -> None:
    cmd = ds.build_explore_command("./scripts/x.py", "none", "/proj")
    assert cmd[-1] == "/workspace/scripts/x.py"
    assert cmd[-2] == "python"
    assert cmd[0:3] == ["docker", "run", "--rm"]
    assert "--network" in cmd
    assert "none" in cmd
    assert "/proj:/workspace:ro" in cmd
    assert "--tmpfs" in cmd


def test_build_explore_command_preserves_path_without_dotslash() -> None:
    cmd = ds.build_explore_command("scripts/x.py", "none", "/proj")
    assert cmd[-1] == "/workspace/scripts/x.py"


def test_build_verify_command_mounts_experiments_rw() -> None:
    cmd = ds.build_verify_command("pytest -q", "bridge", "/proj")
    # Must contain both read-only project mount and read-write .experiments mount.
    assert "/proj:/workspace:ro" in cmd
    assert "/proj/.experiments:/workspace/.experiments:rw" in cmd
    # Command suffix: sh -c <metric-cmd>
    assert cmd[-3:] == ["sh", "-c", "pytest -q"]


def test_build_verify_command_network_override() -> None:
    cmd = ds.build_verify_command("echo hi", "host", "/proj")
    idx = cmd.index("--network")
    assert cmd[idx + 1] == "host"


# ---------- main() ----------


class _FakeCompleted:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


@pytest.fixture
def captured_run(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture ``subprocess.run`` invocations; return a list filled on each call."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kw: Any) -> _FakeCompleted:
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(ds.subprocess, "run", fake_run)
    return calls


def test_main_missing_mode_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ds.main(["script.py"])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_main_missing_arg_returns_2(capsys: pytest.CaptureFixture[str]) -> None:
    rc = ds.main(["--mode", "explore"])
    assert rc == 2
    assert "usage:" in capsys.readouterr().err


def test_main_explore_mode_dispatches_correctly(captured_run: list[list[str]]) -> None:
    rc = ds.main(["--mode", "explore", "./scripts/x.py"], env={}, cwd="/proj")
    assert rc == 0
    assert len(captured_run) == 1
    cmd = captured_run[0]
    assert cmd[0:3] == ["docker", "run", "--rm"]
    assert cmd[-2:] == ["python", "/workspace/scripts/x.py"]
    # Default network = "none"
    assert "none" in cmd


def test_main_explore_mode_equals_form(captured_run: list[list[str]]) -> None:
    rc = ds.main(["--mode=explore", "./scripts/x.py"], env={}, cwd="/proj")
    assert rc == 0
    assert captured_run[0][-1] == "/workspace/scripts/x.py"


def test_main_verify_mode_dispatches_correctly(captured_run: list[list[str]]) -> None:
    rc = ds.main(["--mode", "verify", "pytest -q"], env={}, cwd="/proj")
    assert rc == 0
    cmd = captured_run[0]
    assert cmd[-3:] == ["sh", "-c", "pytest -q"]
    assert "/proj/.experiments:/workspace/.experiments:rw" in cmd


def test_main_sandbox_network_env_override(captured_run: list[list[str]]) -> None:
    rc = ds.main(["--mode", "explore", "x.py"], env={"SANDBOX_NETWORK": "host"}, cwd="/proj")
    assert rc == 0
    cmd = captured_run[0]
    idx = cmd.index("--network")
    assert cmd[idx + 1] == "host"


def test_main_sandbox_network_empty_falls_back_to_none(captured_run: list[list[str]]) -> None:
    rc = ds.main(["--mode", "explore", "x.py"], env={"SANDBOX_NETWORK": ""}, cwd="/proj")
    assert rc == 0
    cmd = captured_run[0]
    idx = cmd.index("--network")
    assert cmd[idx + 1] == "none"


def test_main_forwards_docker_return_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds.subprocess, "run", lambda cmd, **_kw: _FakeCompleted(returncode=42))
    rc = ds.main(["--mode", "explore", "x.py"], env={}, cwd="/proj")
    assert rc == 42


def test_main_docker_not_in_path(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def raise_fnf(*_a: Any, **_kw: Any) -> Any:
        raise FileNotFoundError("docker")

    monkeypatch.setattr(ds.subprocess, "run", raise_fnf)
    rc = ds.main(["--mode", "explore", "x.py"], env={}, cwd="/proj")
    assert rc == 127
    assert "'docker' binary not found" in capsys.readouterr().err
