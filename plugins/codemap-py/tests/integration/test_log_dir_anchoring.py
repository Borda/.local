"""Telemetry log directory is anchored to the project root, not to the process CWD (E-N3).

The hook layer, the skill layer and the CLI layer each append shards keyed on one
session id, and ``debrief-coding`` joins them by reading a single directory. Each layer
used to spell its own ``Path(os.environ.get("CODEMAP_LOG_DIR", ".cache/codemap/logs"))``
default, which resolves against the *process* CWD — so a session whose hooks fired at the
repo root while a query ran from a subdirectory wrote the two halves into two directories
and the join silently returned nothing. ``query.py`` was the worst of the four because its
``_LOG_DIR`` was a module constant frozen at IMPORT time.

Every case here therefore runs from a **subdirectory** of a real git repo and asserts the
shard landed at the repo root. A test run from the repo root itself cannot fail.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import _runtime_log as rl
from codemap_py import telemetry

_HOOKS_DIR = Path(__file__).resolve().parents[2] / "hooks"
_TOOL_HOOK = _HOOKS_DIR / "log-tool-use.py"
_SKILL_HOOK = _HOOKS_DIR / "log-skill-start.py"

_LOGS_REL = Path(".cache") / "codemap" / "logs"


def _load_hookutil():
    """Load ``hooks/_hookutil.py`` by path (it is not an importable package member)."""
    spec = importlib.util.spec_from_file_location("codemap_hookutil_anchoring", _HOOKS_DIR / "_hookutil.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo_with_subdir(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(repo_root, nested_subdir)`` for a real, initialised git repository.

    A real repo (not a bare ``.git`` directory) so the package layer's
    ``git rev-parse --show-toplevel`` and the hook layer's ``.git`` walk both resolve —
    the two anchoring mechanisms must agree, and only a real repo proves it.
    """
    root = tmp_path / "proj"
    (root / "src" / "pkg").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True, capture_output=True)
    # tmp_path is a symlink farm on macOS (/var -> /private/var); the resolvers collapse
    # it, so the expected path must be collapsed too or every comparison fails on the prefix.
    return root.resolve(), (root / "src" / "pkg").resolve()


def _run_hook(hook: Path, payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    """Feed one event through *hook* as a subprocess rooted at *cwd*."""
    env = {**os.environ}
    env.pop("CODEMAP_LOG_DIR", None)  # inherited override would mask the anchoring
    env["CODEMAP_LOGGING"] = "true"  # conftest's autouse gate disables it suite-wide
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(cwd),
        env=env,
        check=False,
    )


class TestHookLayerAnchoring:
    """Hooks launched inside a subdirectory still write to the repo-root log directory."""

    def test_tool_hook_writes_at_the_repo_root(self, repo_with_subdir: tuple[Path, Path]) -> None:
        """``log-tool-use.py`` run from ``src/pkg`` lands in ``<repo>/.cache/codemap/logs``."""
        root, subdir = repo_with_subdir

        result = _run_hook(_TOOL_HOOK, {"tool_name": "Grep", "tool_input": {"pattern": "x"}}, subdir)

        assert result.returncode == 0, result.stderr
        assert sorted(p.name for p in (root / _LOGS_REL).glob("tools*.jsonl")) != []
        assert not (subdir / _LOGS_REL).exists()

    def test_skill_hook_writes_at_the_repo_root(self, repo_with_subdir: tuple[Path, Path]) -> None:
        """``log-skill-start.py`` run from ``src/pkg`` lands in ``<repo>/.cache/codemap/logs``."""
        root, subdir = repo_with_subdir
        payload = {"tool_name": "Skill", "tool_input": {"skill": "codemap-py:query-code"}}

        result = _run_hook(_SKILL_HOOK, payload, subdir)

        assert result.returncode == 0, result.stderr
        assert sorted(p.name for p in (root / _LOGS_REL).glob("skills*.jsonl")) != []
        assert not (subdir / _LOGS_REL).exists()


class TestCliLayerAnchoring:
    """The CLI telemetry layer resolves the same repo-root directory from a subdirectory."""

    def test_log_cli_writes_at_the_repo_root(
        self, repo_with_subdir: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``telemetry.log_cli`` invoked from ``src/pkg`` writes under the repo root."""
        root, subdir = repo_with_subdir
        monkeypatch.setenv("CODEMAP_LOGGING", "true")
        monkeypatch.delenv("CODEMAP_LOG_DIR", raising=False)
        monkeypatch.chdir(subdir)

        telemetry.log_cli("rdeps", ["rdeps", "m"], {"ok": True}, 0.0)

        assert sorted(p.name for p in (root / _LOGS_REL).glob("cli*.jsonl")) != []
        assert not (subdir / _LOGS_REL).exists()

    def test_query_engine_has_no_import_time_log_dir(self) -> None:
        """``query`` must not re-freeze a CWD-relative log dir at import time.

        The regression this pins is specifically the module *constant*: any value bound
        at import cannot follow a later ``chdir`` or a ``CODEMAP_LOG_DIR`` exported after
        the process started, which is exactly how the engine's shards ended up split from
        the hooks'.
        """
        from codemap_py import query

        assert not hasattr(query, "_LOG_DIR")


class TestLayersAgree:
    """The hook layer and the CLI layer resolve one identical directory (the join contract)."""

    def test_hook_and_cli_shards_share_one_directory(
        self, repo_with_subdir: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both layers, both launched from the subdirectory, write into the same dir."""
        root, subdir = repo_with_subdir
        assert _run_hook(_TOOL_HOOK, {"tool_name": "Glob", "tool_input": {"pattern": "*"}}, subdir).returncode == 0
        monkeypatch.setenv("CODEMAP_LOGGING", "true")
        monkeypatch.delenv("CODEMAP_LOG_DIR", raising=False)
        monkeypatch.chdir(subdir)

        telemetry.log_cli("central", ["central"], {"ok": True}, 0.0)

        shards = {p.parent for p in (root / _LOGS_REL).glob("*.jsonl")}
        assert shards == {root / _LOGS_REL}
        assert len(list((root / _LOGS_REL).glob("*.jsonl"))) == 2

    def test_hookutil_and_runtime_log_agree_from_a_subdir(
        self, repo_with_subdir: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The hook resolver and the package resolver return byte-identical paths."""
        root, subdir = repo_with_subdir
        monkeypatch.delenv("CODEMAP_LOG_DIR", raising=False)
        monkeypatch.chdir(subdir)

        assert _load_hookutil().log_dir() == rl.log_root() == root / _LOGS_REL


class TestOverrideAnchoring:
    """``CODEMAP_LOG_DIR`` keeps its absolute meaning and gains an anchored relative one."""

    def test_absolute_override_is_honoured_verbatim(
        self, repo_with_subdir: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An absolute override is already unambiguous, so it is used as given."""
        _root, subdir = repo_with_subdir
        elsewhere = (tmp_path / "shared_logs").resolve()
        monkeypatch.setenv("CODEMAP_LOG_DIR", str(elsewhere))
        monkeypatch.chdir(subdir)

        assert rl.log_root() == elsewhere
        assert _load_hookutil().log_dir() == elsewhere

    def test_relative_override_anchors_to_the_repo_root(
        self, repo_with_subdir: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative override splits per-CWD exactly like the old default did."""
        root, subdir = repo_with_subdir
        monkeypatch.setenv("CODEMAP_LOG_DIR", "build/logs")
        monkeypatch.chdir(subdir)

        assert rl.log_root() == root / "build" / "logs"
        assert _load_hookutil().log_dir() == root / "build" / "logs"

    def test_runtime_component_survives_the_anchoring(self, repo_with_subdir: tuple[Path, Path]) -> None:
        """``log_dir_for`` still appends ``<runtime>/`` on top of the anchored root."""
        root, _subdir = repo_with_subdir

        assert rl.log_dir_for("codex", root=root, override="") == root / _LOGS_REL / "codex"
