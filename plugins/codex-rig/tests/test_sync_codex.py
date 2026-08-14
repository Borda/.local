"""Acceptance checks for the native cross-platform Codex restore entrypoint."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SYNC_SCRIPT = PLUGIN_ROOT / "scripts" / "sync_codex.py"


def load_sync() -> ModuleType:
    """Load the packaged sync entrypoint without package imports."""
    specification = importlib.util.spec_from_file_location("codex_rig_sync_codex", SYNC_SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def marketplace_fixture(tmp_path: Path) -> Path:
    """Create the installed marketplace files consumed by global setup."""
    root = tmp_path / "marketplace"
    plugin = root / "plugins" / "codex-rig"
    (plugin / "assets").mkdir(parents=True)
    (plugin / "scripts").mkdir()
    (plugin / "assets" / "AGENTS.md").write_text("# fixture\n", encoding="utf-8")
    (plugin / "scripts" / "install_global_agents.py").write_text("# fixture\n", encoding="utf-8")
    return root


def fake_runner(
    marketplace_root: Path,
    calls: list[tuple[str, ...]],
    *,
    configured_ref: str = "",
    source_type: str = "git",
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Return deterministic Codex/Git command results for one restore."""
    metadata = marketplace_root / ".codex-marketplace-install.json"
    metadata.write_text(json.dumps({"ref_name": configured_ref}), encoding="utf-8")

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        rendered = tuple(str(item) for item in command)
        calls.append(rendered)
        if rendered[1:5] == ("plugin", "marketplace", "list", "--json"):
            payload = {
                "marketplaces": [
                    {
                        "name": "borda-ai-rig",
                        "root": str(marketplace_root),
                        "marketplaceSource": {"sourceType": source_type},
                    }
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[1:5] == ("plugin", "list", "--marketplace", "borda-ai-rig"):
            payload = {
                "installed": [
                    {
                        "pluginId": "codex-rig@borda-ai-rig",
                        "enabled": True,
                        "version": "0.3.0",
                    },
                    {
                        "pluginId": "codemap-py@borda-ai-rig",
                        "enabled": True,
                        "version": "0.28.8",
                    },
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[:3] == ("git", "-C", str(marketplace_root)):
            return subprocess.CompletedProcess(command, 0, "0123456789abcdef\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_native_sync_refreshes_latest_and_installs_global_instructions(tmp_path: Path) -> None:
    """Restore the latest plugin without Bash, jq, or shell interpolation."""
    module = load_sync()
    root = marketplace_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []
    output = io.StringIO()

    result = module.sync_codex(
        module.parse_args([]),
        run=fake_runner(root, calls),
        environ={"CODEX_HOME": str(tmp_path / "home")},
        stdout=output,
    )

    assert result == 0
    assert ("codex", "plugin", "marketplace", "upgrade", "borda-ai-rig") in calls
    assert ("codex", "plugin", "add", "codex-rig@borda-ai-rig") in calls
    assert ("codex", "plugin", "add", "codemap-py@borda-ai-rig") in calls
    installer = root / "plugins" / "codex-rig" / "scripts" / "install_global_agents.py"
    template = root / "plugins" / "codex-rig" / "assets" / "AGENTS.md"
    assert any(
        call[1:] == (str(installer), "--source", str(template), "--codex-home", str(tmp_path / "home"))
        for call in calls
    )
    assert "Codex Rig 0.3.0 installed" in output.getvalue()
    assert "Codemap 0.28.8 installed" in output.getvalue()


def test_native_sync_preserves_local_marketplace_without_upgrade(tmp_path: Path) -> None:
    """Install managed plugins from a configured local marketplace snapshot."""
    module = load_sync()
    root = marketplace_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []
    output = io.StringIO()

    result = module.sync_codex(
        module.parse_args(["--no-codex-global-agents"]),
        run=fake_runner(root, calls, source_type="local"),
        environ={},
        stdout=output,
    )

    assert result == 0
    assert ("codex", "plugin", "marketplace", "upgrade", "borda-ai-rig") not in calls
    assert ("codex", "plugin", "add", "codex-rig@borda-ai-rig") in calls
    assert ("codex", "plugin", "add", "codemap-py@borda-ai-rig") in calls
    assert "marketplace refresh: configured local source" in output.getvalue()


def test_native_sync_adds_pinned_marketplace_when_absent(tmp_path: Path) -> None:
    """Forward one explicit ref without relying on shell quoting."""
    module = load_sync()
    root = marketplace_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []
    listings = 0

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal listings
        rendered = tuple(str(item) for item in command)
        calls.append(rendered)
        if rendered[1:5] == ("plugin", "marketplace", "list", "--json"):
            listings += 1
            payload = {"marketplaces": [] if listings == 1 else [{"name": "borda-ai-rig", "root": str(root)}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[1:5] == ("plugin", "list", "--marketplace", "borda-ai-rig"):
            payload = {
                "installed": [
                    {"pluginId": "codex-rig@borda-ai-rig", "enabled": True, "version": "0.3.0"},
                    {"pluginId": "codemap-py@borda-ai-rig", "enabled": True, "version": "0.28.8"},
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[:3] == ("git", "-C", str(root)):
            return subprocess.CompletedProcess(command, 0, "0123456789abcdef\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    result = module.sync_codex(
        module.parse_args(["--codex-ref", "codex-rig-v0.3.0", "--no-codex-global-agents"]),
        run=run,
        environ={},
        stdout=io.StringIO(),
    )

    assert result == 0
    assert (
        "codex",
        "plugin",
        "marketplace",
        "add",
        "Borda/AI-Rig",
        "--ref",
        "codex-rig-v0.3.0",
    ) in calls
    assert not any("install_global_agents.py" in item for call in calls for item in call)


def test_native_sync_rejects_existing_ref_mismatch_without_changes(tmp_path: Path) -> None:
    """Fail before refresh when the configured marketplace tracks another ref."""
    module = load_sync()
    root = marketplace_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []

    with pytest.raises(module.SyncError, match="marketplace tracks"):
        module.sync_codex(
            module.parse_args(["--codex-ref", "codex-rig-v0.3.0"]),
            run=fake_runner(root, calls, configured_ref="codex-rig-v0.2.4"),
            environ={},
            stdout=io.StringIO(),
        )

    assert not any(
        call[1:4] == ("plugin", "marketplace", "upgrade") or call[1:3] == ("plugin", "add") for call in calls
    )


def test_native_sync_requires_both_managed_plugins_after_install(tmp_path: Path) -> None:
    """Reject a partial restore that enables Codex Rig without Codemap."""
    module = load_sync()
    root = marketplace_fixture(tmp_path)
    calls: list[tuple[str, ...]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        rendered = tuple(str(item) for item in command)
        calls.append(rendered)
        if rendered[1:5] == ("plugin", "marketplace", "list", "--json"):
            payload = {"marketplaces": [{"name": "borda-ai-rig", "root": str(root)}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[1:5] == ("plugin", "list", "--marketplace", "borda-ai-rig"):
            payload = {"installed": [{"pluginId": "codex-rig@borda-ai-rig", "enabled": True, "version": "0.3.0"}]}
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if rendered[:3] == ("git", "-C", str(root)):
            return subprocess.CompletedProcess(command, 0, "0123456789abcdef\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    with pytest.raises(module.SyncError, match="Codemap is not uniquely enabled"):
        module.sync_codex(
            module.parse_args(["--no-codex-global-agents"]),
            run=run,
            environ={},
            stdout=io.StringIO(),
        )


def test_native_sync_clear_removes_plugin_and_managed_block(tmp_path: Path) -> None:
    """Route teardown through the same portable Python entrypoint."""
    module = load_sync()
    calls: list[tuple[str, ...]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(str(item) for item in command))
        return subprocess.CompletedProcess(command, 0, "", "")

    result = module.sync_codex(
        module.parse_args(["clear"]),
        run=run,
        environ={"CODEX_HOME": str(tmp_path / "home")},
        stdout=io.StringIO(),
    )

    assert result == 0
    assert ("codex", "plugin", "remove", "codex-rig@borda-ai-rig") in calls
    assert ("codex", "plugin", "remove", "codemap-py@borda-ai-rig") in calls
    assert any(
        call[1:]
        == (
            str(PLUGIN_ROOT / "scripts" / "install_global_agents.py"),
            "--remove",
            "--codex-home",
            str(tmp_path / "home"),
        )
        for call in calls
    )


def test_native_sync_clear_removes_managed_block_when_codex_is_missing(tmp_path: Path) -> None:
    """Keep local teardown usable after the Codex executable was removed."""
    module = load_sync()
    calls: list[tuple[str, ...]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(str(item) for item in command))
        if command[0] == "codex":
            raise FileNotFoundError("codex")
        return subprocess.CompletedProcess(command, 0, "managed block removed\n", "")

    output = io.StringIO()
    result = module.sync_codex(
        module.parse_args(["clear"]),
        run=run,
        environ={"CODEX_HOME": str(tmp_path / "home")},
        stdout=output,
    )

    assert result == 0
    assert "not installed" in output.getvalue()
    assert "managed block removed" in output.getvalue()
    assert ("codex", "plugin", "remove", "codex-rig@borda-ai-rig") in calls
    assert ("codex", "plugin", "remove", "codemap-py@borda-ai-rig") in calls
    assert any(
        call[1:]
        == (
            str(PLUGIN_ROOT / "scripts" / "install_global_agents.py"),
            "--remove",
            "--codex-home",
            str(tmp_path / "home"),
        )
        for call in calls
    )


def test_system_runner_resolves_windows_batch_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    """Launch a resolved Codex batch shim through the Windows command processor."""
    module = load_sync()

    def which(command: str) -> str | None:
        return {"codex": r"C:\Program Files\Codex\codex.cmd"}.get(command)

    monkeypatch.setattr(module.shutil, "which", which)

    resolved, shell = module._resolve_system_command(["codex", "plugin", "list"], windows=True)

    assert resolved == r'"C:\Program Files\Codex\codex.cmd" plugin list'
    assert shell is True


@pytest.mark.parametrize(
    "argument",
    (
        "main&whoami",
        "main|whoami",
        "main<in",
        "main>out",
        "main^x",
        "main(x)",
        "main%x%",
        "main!x!",
        'main"x',
        "main x",
    ),
)
def test_system_runner_rejects_windows_batch_shell_syntax(monkeypatch: pytest.MonkeyPatch, argument: str) -> None:
    """Reject user-controlled values that cmd.exe could reinterpret."""
    module = load_sync()
    monkeypatch.setattr(module.shutil, "which", lambda _command: r"C:\fixture\codex.cmd")

    with pytest.raises(OSError, match="unsafe Windows batch command"):
        module._resolve_system_command(["codex", "plugin", "add", argument], windows=True)
