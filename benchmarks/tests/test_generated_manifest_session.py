"""Regression checks for generated manifests required during test collection."""

from __future__ import annotations

import subprocess
import sys
import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


BENCHMARKS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BENCHMARKS_DIR.parent
CONFTST = Path(__file__).with_name("conftest.py")


def test_session_makes_manifests_ready_once_with_byte_stable_outputs(
    generated_manifest_artifacts: Any,
) -> None:
    """Session generation must make every manifest available and satisfy read-only checks."""
    artifacts = generated_manifest_artifacts

    assert artifacts.generation_count == 1
    assert all(path.is_file() for path in artifacts.paths)

    for builder in (
        "build-provider-parity-methodology-manifest.py",
        "build-codex-integration-manifest.py",
        "build-codex-agentic-manifest.py",
    ):
        result = subprocess.run(
            [sys.executable, str(BENCHMARKS_DIR / builder), "--check"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_session_hook_recreates_only_absent_outputs_and_cleans_them(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean checkout must build the chain once, then leave no generated outputs behind."""
    conftest = runpy.run_path(str(CONFTST))
    outputs = tuple(
        tmp_path / name
        for name in ("methodology.json", "integration.json", "integration.md", "agentic.json", "agentic.md")
    )
    builders = tuple(tmp_path / name for name in ("methodology.py", "integration.py", "agentic.py"))
    calls: list[tuple[str, ...]] = []

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        """Record the dependency chain and materialize its final generated files."""
        calls.append(tuple(command))
        if len(calls) == len(builders):
            for path in outputs:
                path.write_text(path.name, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    hook_globals = conftest["pytest_sessionstart"].__globals__
    monkeypatch.setitem(hook_globals, "_GENERATED_MANIFEST_PATHS", outputs)
    monkeypatch.setitem(hook_globals, "_MANIFEST_BUILDERS", builders)
    monkeypatch.setattr(subprocess, "run", fake_run)
    session = SimpleNamespace(config=SimpleNamespace())

    conftest["pytest_sessionstart"](session)

    artifacts = session.config._generated_manifest_artifacts
    assert artifacts.initially_missing == outputs
    assert artifacts.generation_count == 1
    assert calls == [(sys.executable, str(builder)) for builder in builders]
    assert all(path.is_file() for path in outputs)

    conftest["pytest_sessionfinish"](session, 0)

    assert not any(path.exists() for path in outputs)
