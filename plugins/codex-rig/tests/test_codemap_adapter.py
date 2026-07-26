"""Acceptance and unit checks for the optional codemap-py structural-context adapter."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = PLUGIN_ROOT / "shared" / "codemap_adapter.py"


def load_adapter() -> ModuleType:
    """Load the adapter module directly, mirroring this suite's other shared-script tests."""
    specification = importlib.util.spec_from_file_location("codemap_adapter", ADAPTER_PATH)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _write_fake_codemap_py(bin_dir: Path, script_body: str) -> None:
    """Install a fake `codemap-py` executable on a directory meant to be prepended to PATH.

    Uses an absolute-path shebang (POSIX) rather than `/usr/bin/env bash`/python, so the fake
    binary still runs when a test intentionally narrows `PATH` to prove absence/isolation.
    """
    if os.name == "nt":
        fake = bin_dir / "codemap-py.bat"
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{bin_dir / "codemap_py_fake.py"}" %*\r\n')
    else:
        fake = bin_dir / "codemap-py"
        fake.write_text(f"#!{sys.executable}\n{script_body}")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (bin_dir / "codemap_py_fake.py").write_text(script_body)


_HEALTHY_DOCTOR = {
    "python": sys.executable,
    "version": "3.12.4",
    "implementation": "cpython",
    "supported": True,
    "plugin_root": "/fake/codemap-py",
    "index_path": "/fake/codemap-py/.cache/codemap/proj.json",
}

_CLEAN_QUERY = {"index": {"query_complete": True, "not_covered": [], "degraded": 0, "stale": False}}
_DEGRADED_QUERY = {
    "index": {"query_complete": False, "not_covered": ["dynamic-dispatch"], "degraded": 0, "stale": False}
}
_STALE_QUERY = {"index": {"query_complete": True, "not_covered": [], "degraded": 0, "stale": True}}


def _fake_script(doctor_payload: dict, doctor_exit: int, query_payload: dict, query_exit: int) -> str:
    """Build a fake `codemap-py` dispatcher that answers `doctor --json` and `query <sub>`."""
    return f"""
import json, sys
if sys.argv[1:2] == ["doctor"]:
    print(json.dumps({doctor_payload!r} if False else {doctor_payload}))
    sys.exit({doctor_exit})
if sys.argv[1:2] == ["query"]:
    print(json.dumps({query_payload}))
    sys.exit({query_exit})
sys.exit(2)
"""


def test_probe_absent_when_codemap_py_not_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `absent` without running any subprocess when the binary is missing."""
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    result = adapter.probe_codemap()

    assert result.status == adapter.STATUS_ABSENT
    assert result.doctor is None


def test_probe_available_when_doctor_reports_supported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `available` once `doctor --json` returns a supported interpreter."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _CLEAN_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    result = adapter.probe_codemap()

    assert result.status == adapter.STATUS_AVAILABLE
    assert result.doctor is not None
    assert result.doctor.supported is True


def test_probe_incompatible_when_interpreter_unsupported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `incompatible` when `doctor` marks the resolved interpreter unsupported."""
    unsupported = dict(_HEALTHY_DOCTOR, supported=False)
    _write_fake_codemap_py(tmp_path, _fake_script(unsupported, 0, _CLEAN_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    result = adapter.probe_codemap()

    assert result.status == adapter.STATUS_INCOMPATIBLE


def test_probe_incompatible_when_doctor_exits_nonzero(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `incompatible` when `doctor --json` itself fails."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 1, _CLEAN_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    result = adapter.probe_codemap()

    assert result.status == adapter.STATUS_INCOMPATIBLE


def test_gather_context_absent_never_runs_queries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Absence is non-fatal and short-circuits before any query subprocess runs."""
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    context = adapter.gather_structural_context("develop", target="pkg.mod")

    assert context.status == adapter.STATUS_ABSENT
    assert context.queries == ()


def test_gather_context_available_when_all_queries_clean(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `available` when the probe is healthy and every mapped query is exhaustive."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _CLEAN_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    context = adapter.gather_structural_context("develop", target="pkg.mod")

    assert context.status == adapter.STATUS_AVAILABLE
    assert len(context.queries) == 3  # rdeps, coupled, test-impact


def test_gather_context_degraded_when_not_covered_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `degraded` when a query returns non-exhaustive completeness metadata."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _DEGRADED_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    context = adapter.gather_structural_context("review")

    assert context.status == adapter.STATUS_DEGRADED


def test_gather_context_stale_when_query_reports_stale(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Report `stale` when a query's index block flags the index older than source."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _STALE_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    context = adapter.gather_structural_context("audit")

    assert context.status == adapter.STATUS_STALE


def test_gather_context_rejects_unknown_category(tmp_path: Path) -> None:
    """Refuse an undefined category rather than silently mapping it to an empty query set."""
    adapter = load_adapter()

    with pytest.raises(ValueError, match="unknown category"):
        adapter.gather_structural_context("not-a-real-category")


def test_develop_query_without_target_records_bounded_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A target-requiring query with no target degrades that one query instead of guessing one."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _CLEAN_QUERY, 0))
    monkeypatch.setenv("PATH", str(tmp_path))
    adapter = load_adapter()

    context = adapter.gather_structural_context("develop", target=None)

    rdeps = next(outcome for outcome in context.queries if outcome.subcommand == "rdeps")
    assert rdeps.error is not None
    assert context.status == adapter.STATUS_DEGRADED


def test_cli_context_persists_json_to_out_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The `context` CLI mode prints JSON and persists the identical bytes to `--out`."""
    _write_fake_codemap_py(tmp_path, _fake_script(_HEALTHY_DOCTOR, 0, _CLEAN_QUERY, 0))
    env = dict(os.environ, PATH=f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")
    out_path = tmp_path / "run" / "codemap-context.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ADAPTER_PATH),
            "context",
            "--category",
            "review",
            "--out",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    stdout_payload = json.loads(completed.stdout)
    file_payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert stdout_payload == file_payload
    assert stdout_payload["status"] == "available"
    assert stdout_payload["protocol_version"] == "codemap-py.integration.v1"


def test_cli_probe_absent_exits_zero_and_reports_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Absence is data, not a CLI failure — `probe` still exits `0`."""
    env = dict(os.environ, PATH=str(tmp_path))

    completed = subprocess.run(
        [sys.executable, str(ADAPTER_PATH), "probe"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "absent"


_CODEMAP_BIN_DIR = PLUGIN_ROOT.parent / "codemap-py" / "bin"


def _real_cli_ready(path_with_bin: str) -> bool:
    """Return whether the real codemap-py launcher answers `doctor --json` with an eligible interpreter."""
    if not (_CODEMAP_BIN_DIR / "codemap-py").is_file():
        return False
    try:
        completed = subprocess.run(
            ["codemap-py", "doctor", "--json"],
            capture_output=True,
            text=True,
            env=dict(os.environ, PATH=path_with_bin),
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def test_root_scoped_query_runs_against_real_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unmocked regression: a root-scoped query drives the ACTUAL codemap-py grammar (--root must precede the subcommand).

    Every other test in this file fakes the subprocess, so none exercises argparse's real
    grammar — the pre-fix argv order (`query central --root .`) passed those fakes yet errors
    against the real CLI. This runs the genuine launcher on a tiny real fixture and asserts a
    root-scoped query returns exit 0 with parseable metadata.
    """
    path_with_bin = f"{_CODEMAP_BIN_DIR}{os.pathsep}{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", path_with_bin)
    if not _real_cli_ready(path_with_bin):
        pytest.skip("real codemap-py CLI unavailable (installed-plugin isolation or no eligible CPython)")

    fixture = tmp_path / "proj"
    fixture.mkdir()
    (fixture / "leaf.py").write_text("def leaf():\n    return 1\n", encoding="utf-8")
    (fixture / "consumer.py").write_text("import leaf\n\n\ndef use():\n    return leaf.leaf()\n", encoding="utf-8")
    monkeypatch.chdir(fixture)
    scan = subprocess.run(
        ["codemap-py", "index", "--root", str(fixture)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert scan.returncode == 0, scan.stderr

    adapter = load_adapter()
    outcome = adapter._run_one_query(adapter.QuerySpec("central", requires_target=False), None, fixture, 30.0)

    assert outcome.exit_code == 0, outcome.error
    assert outcome.error is None
