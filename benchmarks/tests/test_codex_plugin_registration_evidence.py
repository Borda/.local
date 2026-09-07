"""Failure-evidence tests for the Codex plugin registration gates."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCHMARKS_DIR))

SCRIPT_PATH = BENCHMARKS_DIR / "run-codex-structural.py"

FROZEN_REGISTRATION = (
    '[plugins."codemap-py@borda-ai-rig-frozen"]\nenabled = true\n\n'
    '[plugins."codex-rig@borda-ai-rig-frozen"]\nenabled = true\n'
)


@pytest.fixture(name="script_run_codex", scope="module")
def _script_run_codex() -> Any:
    """Load the Codex adapter without executing its command-line entry point.

    Example:
        >>> getfixture("script_run_codex").__name__
        'run_codemap_codex_registration_evidence'
    """
    spec = importlib.util.spec_from_file_location("run_codemap_codex_registration_evidence", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Codex adapter at {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(name="registered_home")
def _registered_home(script_run_codex: Any, tmp_path: Path) -> Any:
    """Return a C arm home whose configuration still registers both treatment plugins."""
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    (home_path / "config.toml").write_text(FROZEN_REGISTRATION, encoding="utf-8")
    return script_run_codex.ArmHome("C_strict", home_path, {}, True, True)


def test_installed_pair_failure_reports_status_roster_and_surviving_registration(
    script_run_codex: Any,
    registered_home: Any,
) -> None:
    """A rejected C roster names the exit status, the parsed roster, and the surviving registration.

    The paid launcher deletes the disposable home while failing, so a message carrying only the child's standard error
    cannot separate a lost registration from a Codex listing that returned nothing while ``config.toml`` still held both
    plugin tables. A negative status is the shape a signal-killed Codex process produces.
    """

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return an empty roster the way a signal-killed Codex process would."""
        return SimpleNamespace(returncode=-9, stdout='{"installed": [], "available": []}', stderr="")

    with pytest.raises(RuntimeError) as failure:
        script_run_codex._verify_installed_plugin_pair(registered_home, command_runner=_command_runner)

    message = str(failure.value)
    assert "rc=-9" in message
    assert "enabled=[]" in message
    assert "codemap-py@borda-ai-rig-frozen" in message
    assert "codex-rig@borda-ai-rig-frozen" in message


def test_installed_pair_admits_codex_first_party_plugins_this_home_never_registered(
    script_run_codex: Any,
    registered_home: Any,
) -> None:
    """First-party Codex plugins outside this home's registration are admitted and recorded.

    Codex 0.153 lists its own connector plugins for an authenticated home, and a disposable home can neither register
    nor remove them. They are present in every arm, so admission turns on what the home installed for itself while the
    remaining names are kept as host-tooling evidence.
    """
    roster = {
        "installed": [
            {"name": "codemap-py", "enabled": True},
            {"name": "codex-rig", "enabled": True},
            {"name": "gmail", "enabled": True},
            {"name": "slack", "enabled": True},
        ],
        "available": [],
    }

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return the treatment pair alongside the host's own first-party plugins."""
        return SimpleNamespace(returncode=0, stdout=json.dumps(roster), stderr="")

    script_run_codex._verify_installed_plugin_pair(registered_home, command_runner=_command_runner)

    assert registered_home.host_plugin_names == ("gmail", "slack")


def test_installed_pair_rejects_a_third_plugin_registered_by_this_home(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """A home that registered a plugin beyond the reviewed pair is rejected.

    Host tooling is tolerated because no arm controls it; a third registration in the home's own ``config.toml`` is
    exactly the contamination the C admission exists to catch, so it must still fail closed.
    """
    home_path = tmp_path / "codex-home"
    home_path.mkdir()
    (home_path / "config.toml").write_text(
        FROZEN_REGISTRATION + '\n[plugins."extra-tool@borda-ai-rig-frozen"]\nenabled = true\n',
        encoding="utf-8",
    )
    home = script_run_codex.ArmHome("C_strict", home_path, {}, True, True)

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return a roster in which every registered plugin is enabled."""
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "installed": [
                        {"name": "codemap-py", "enabled": True},
                        {"name": "codex-rig", "enabled": True},
                        {"name": "extra-tool", "enabled": True},
                    ]
                }
            ),
            stderr="",
        )

    with pytest.raises(RuntimeError, match="plugin registration is invalid"):
        script_run_codex._verify_installed_plugin_pair(home, command_runner=_command_runner)


def test_plain_absence_probe_admits_first_party_plugins_and_records_them(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """The control arm tolerates host plugins, rejects any treatment plugin, and records what it saw.

    Recording the host roster on the control home is what makes the tolerated names auditable: parity holds only
    while the same first-party tooling is present in every arm.
    """
    home_path = tmp_path / "plain-home"
    home_path.mkdir()
    (home_path / "config.toml").write_text("", encoding="utf-8")
    home = script_run_codex.ArmHome("A_plain", home_path, {"PATH": str(tmp_path / "empty-bin")}, False)

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return only the host's first-party plugins."""
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps({"installed": [{"name": "gmail", "enabled": True}]}),
            stderr="",
        )

    script_run_codex._verify_plain_plugin_absent(home, command_runner=_command_runner)

    assert home.host_plugin_names == ("gmail",)


def test_plain_absence_probe_rejects_a_home_that_registered_a_plugin(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """A control home whose configuration registers any plugin is rejected.

    A registration that lists as disabled would otherwise pass the enabled-name check while leaving the control arm
    carrying an installed treatment plugin.
    """
    home_path = tmp_path / "plain-home"
    home_path.mkdir()
    (home_path / "config.toml").write_text(
        '[plugins."codemap-py@borda-ai-rig"]\nenabled = false\n',
        encoding="utf-8",
    )
    home = script_run_codex.ArmHome("A_plain", home_path, {"PATH": str(tmp_path / "empty-bin")}, False)

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return a roster that hides the disabled registration."""
        return SimpleNamespace(returncode=0, stdout=json.dumps({"installed": []}), stderr="")

    with pytest.raises(RuntimeError, match="carries a treatment plugin"):
        script_run_codex._verify_plain_plugin_absent(home, command_runner=_command_runner)


def test_plain_absence_probe_failure_reports_status_and_roster(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """A failed A absence probe names the exit status and the roster Codex reported.

    The control arm proves the treatment plugin is absent, so a probe that cannot run must say how it failed rather than
    emit an empty diagnosis when Codex writes nothing to standard error.
    """
    home_path = tmp_path / "plain-home"
    home_path.mkdir()
    home = script_run_codex.ArmHome("A_plain", home_path, {"PATH": str(tmp_path / "empty-bin")}, False)

    def _command_runner(_command: list[str], **_kwargs: Any) -> SimpleNamespace:
        """Return a non-zero status without any standard-error detail."""
        return SimpleNamespace(returncode=2, stdout="", stderr="")

    with pytest.raises(RuntimeError, match=r"absence probe failed: rc=2"):
        script_run_codex._verify_plain_plugin_absent(home, command_runner=_command_runner)


def test_registered_plugin_tables_reads_every_registered_identifier(
    script_run_codex: Any,
    registered_home: Any,
) -> None:
    """Every ``[plugins."<id>"]`` table in a Codex home is reported in sorted order.

    The evidence helper reads the same registration the permission composition rewrites, so it must recover both
    marketplace-qualified identifiers rather than the bare plugin names.
    """
    assert script_run_codex._registered_plugin_tables(registered_home.path / "config.toml") == [
        "codemap-py@borda-ai-rig-frozen",
        "codex-rig@borda-ai-rig-frozen",
    ]


def test_registered_plugin_tables_reports_nothing_without_configuration(
    script_run_codex: Any,
    tmp_path: Path,
) -> None:
    """A home without a readable ``config.toml`` registers no plugin tables.

    The helper runs while an arm home is being torn down, so an unreadable configuration must degrade to an empty roster
    instead of replacing the original failure with its own.
    """
    assert script_run_codex._registered_plugin_tables(tmp_path / "config.toml") == []


def test_enabled_plugin_names_returns_an_empty_roster_for_a_non_list_payload(script_run_codex: Any) -> None:
    """A roster payload that is not a list parses to an empty set of enabled names.

    A Codex build that reports plugins as an object would otherwise make the parser return ``False``, which compares
    unequal to every expected roster and reports a registration defect that never happened.
    """
    assert script_run_codex._enabled_plugin_names('{"plugins": {"codemap-py": {"enabled": true}}}') == set()
