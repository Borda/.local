"""Protect concise provider-explicit benchmark entrypoint names."""

from __future__ import annotations

import ast
from pathlib import Path


BENCHMARKS_DIR = Path(__file__).parent.parent


def test_runner_names_encode_provider_or_neutral_role_without_redundant_project_name() -> None:
    """Prevent ambiguous provider ownership or a repeated Codemap namespace."""
    expected = {
        "run-claude-agentic.py",
        "run-claude-structural.py",
        "run-codemap-cli.py",
        "run-codex-structural.py",
    }
    actual = {path.name for path in BENCHMARKS_DIR.glob("run-*.py")}

    assert expected <= actual
    assert {name for name in actual if "codemap" in name} == {"run-codemap-cli.py"}


def test_codex_structural_header_explains_scope_and_usage() -> None:
    """Keep the Codex runner as discoverable as the Claude runner headers."""
    script = BENCHMARKS_DIR / "run-codex-structural.py"
    module = ast.parse(script.read_text(encoding="utf-8"))
    docstring = ast.get_docstring(module)

    assert docstring is not None
    assert "former `bench`/real-codebase category" in docstring
    assert "not a third benchmark type" in docstring
    for section in (
        "## What this measures",
        "## Arms",
        "## Metrics",
        "## Quick start",
        "## Requirements",
        "## Failure conditions",
        "## Output",
    ):
        assert section in docstring
    for option in (
        "--repo-path",
        "--tasks-path",
        "--index-path",
        "--model",
        "--dry-run",
        "--output-path",
    ):
        assert option in docstring
