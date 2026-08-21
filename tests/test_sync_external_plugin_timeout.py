"""Acceptance checks for bounded external-plugin commands in root sync."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = ROOT / "sync.sh"
TIMEOUT_RUNNER = ROOT / "scripts" / "run_with_timeout.py"


def _run_timeout(*command: str, timeout: str = "2") -> subprocess.CompletedProcess[str]:
    """Run the timeout helper with captured output for one isolated command."""
    return subprocess.run(
        [
            sys.executable,
            str(TIMEOUT_RUNNER),
            "--timeout-seconds",
            timeout,
            "--label",
            "external-plugin fixture",
            "--",
            *command,
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )


def test_sync_routes_every_external_plugin_command_through_timeout_runner() -> None:
    """Prevent one newly added external lifecycle command from restoring an indefinite wait."""
    text = SYNC_SCRIPT.read_text(encoding="utf-8")
    external_block = text.split('echo "Refreshing external plugin marketplaces..."', maxsplit=1)[1].split(
        'echo "Registering marketplace (GitHub source → versioned cache install)..."', maxsplit=1
    )[0]
    claude_commands = [line.strip() for line in external_block.splitlines() if "claude plugin" in line]

    assert len(claude_commands) == 4
    assert all("run_external_plugin_command" in command for command in claude_commands)
    assert any("marketplace add" in command for command in claude_commands)
    assert any("marketplace update" in command for command in claude_commands)
    assert any("plugin uninstall" in command for command in claude_commands)
    assert any("plugin install" in command for command in claude_commands)
    assert 'EXTERNAL_PLUGIN_TIMEOUT_SECONDS="${EXTERNAL_PLUGIN_TIMEOUT_SECONDS:-120}"' in text
    assert "--external-plugin-timeout-seconds" in text


def test_timeout_runner_preserves_success_output() -> None:
    """Keep the wrapper transparent when an external command finishes normally."""
    completed = _run_timeout(sys.executable, "-c", "print('completed')")

    assert completed.returncode == 0
    assert completed.stdout == "completed\n"
    assert completed.stderr == ""


def test_timeout_runner_forwards_nonzero_exit_status() -> None:
    """Preserve ordinary CLI failure so existing sync branches retain their meaning."""
    completed = _run_timeout(sys.executable, "-c", "raise SystemExit(7)")

    assert completed.returncode == 7
    assert "timed out" not in completed.stderr


def test_timeout_runner_stops_command_and_descendants(tmp_path: Path) -> None:
    """Prevent a timed-out marketplace child from surviving to mutate plugin state later."""
    sentinel = tmp_path / "late-write.txt"
    child_code = (
        "import time; from pathlib import Path; "
        f"time.sleep(0.8); Path({str(sentinel)!r}).write_text('leaked', encoding='utf-8')"
    )
    parent_code = (
        f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(5)"
    )
    started = time.monotonic()

    completed = _run_timeout(sys.executable, "-c", parent_code, timeout="0.1")
    elapsed = time.monotonic() - started
    time.sleep(1)

    assert completed.returncode == 124
    assert elapsed < 3
    assert "external-plugin fixture timed out after 0.1 seconds" in completed.stderr
    assert not sentinel.exists()


def test_timeout_runner_rejects_nonpositive_deadline() -> None:
    """Reject a disabled deadline before launching any external command."""
    completed = _run_timeout(sys.executable, "-c", "print('must not run')", timeout="0")

    assert completed.returncode == 2
    assert "must be a finite positive number" in completed.stderr
    assert "must not run" not in completed.stdout
