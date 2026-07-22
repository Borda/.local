"""diff-impact: git diff → changed modules + symbols → blast radius in one JSON.

The subcommand joins per-module ``rdeps``/``coupled``, per-symbol ``fn-rdeps``,
and a union ``test-impact`` for every module the working-tree diff touches,
tiered by reverse-dependency count. Tests drive it over a real git fixture repo
because the diff source is ``git diff --name-only``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _scan(scan_index: Path, root: Path) -> None:
    """Run scan-index over *root*, asserting success."""
    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(root)],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr


def _query(scan_query: Path, root: Path, index_path: Path, *args: str) -> dict:
    """Run scan-query against *index_path* and return the parsed JSON."""
    result = subprocess.run(
        [sys.executable, str(scan_query), "--index", str(index_path), *args],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return json.loads(result.stdout)


def _git(root: Path, *args: str) -> None:
    """Run a git command inside *root*, asserting success."""
    result = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def git_project(tmp_path: Path, scan_index: Path) -> tuple[Path, Path]:
    """A committed git repo: ``lib`` imported by ``app``, one test file, index scanned."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lib.py").write_text("def helper(x):\n    return x + 1\n\n\ndef untouched(y):\n    return y\n")
    (root / "app.py").write_text("import lib\n\n\ndef run(x):\n    return lib.helper(x)\n")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_lib.py").write_text("import lib\n\n\ndef test_helper():\n    assert lib.helper(1) == 2\n")
    _git(root, "init", "-q")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    _scan(scan_index, root)
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    assert index_path.exists()
    return root, index_path


class TestDiffImpact:
    """Working-tree changes map to modules, symbols, risk tiers, and test impact."""

    def test_clean_tree_reports_nothing(self, git_project, scan_query):
        """No diff → zero changed files, empty module list, LOW overall risk."""
        root, index_path = git_project
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        assert data["changed_files"] == 0
        assert data["changed_modules"] == []
        assert data["highest_risk"] == "LOW"

    def test_changed_symbol_and_risk_tier(self, git_project, scan_query):
        """Editing one function surfaces exactly that symbol, its importers, and a tier."""
        root, index_path = git_project
        (root / "lib.py").write_text("def helper(x):\n    return x + 2\n\n\ndef untouched(y):\n    return y\n")
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        assert data["changed_files"] == 1
        (entry,) = data["changed_modules"]
        assert entry["module"] == "lib"
        assert entry["changed_symbols"] == ["lib::helper"]
        # lib is imported by app and test_lib → 1–4 importers = MODERATE blast radius
        assert entry["risk"] == "MODERATE"
        assert data["highest_risk"] == "MODERATE"

    def test_test_impact_union_names_test_file(self, git_project, scan_query):
        """The union test-impact block points at the test exercising the changed module."""
        root, index_path = git_project
        (root / "lib.py").write_text("def helper(x):\n    return x + 3\n\n\ndef untouched(y):\n    return y\n")
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        assert any("test_lib.py" in f for f in data["test_impact"]["test_files"])
        assert "pytest" in data["test_impact"]["pytest_cmd"]

    def test_base_ref_scopes_the_diff(self, git_project, scan_query):
        """--base <ref> diffs against that ref: a committed change is visible via HEAD~1."""
        root, index_path = git_project
        (root / "lib.py").write_text("def helper(x):\n    return x + 4\n\n\ndef untouched(y):\n    return y\n")
        _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-am", "tweak")
        clean = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        ranged = _query(scan_query, root, index_path, "--no-heal", "diff-impact", "--base", "HEAD~1")
        assert clean["changed_files"] == 0
        assert [m["module"] for m in ranged["changed_modules"]] == ["lib"]

    def test_unindexed_changed_file_reported_unmapped(self, git_project, scan_query):
        """A tracked change to a file the index does not know is surfaced, never hidden."""
        root, index_path = git_project
        (root / "extra.py").write_text("def brand_new():\n    return 0\n")
        _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "extra.py")
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        assert "extra.py" in data["unmapped_files"]

    def test_output_is_deterministic(self, git_project, scan_query):
        """Two identical runs produce identical impact payloads (coverage block aside)."""
        root, index_path = git_project
        (root / "lib.py").write_text("def helper(x):\n    return x + 5\n\n\ndef untouched(y):\n    return y\n")
        first = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        second = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        first.pop("index", None)
        second.pop("index", None)
        assert first == second

    def test_single_coverage_block(self, git_project, scan_query):
        """diff-impact emits exactly one coverage block for the whole join."""
        root, index_path = git_project
        (root / "lib.py").write_text("def helper(x):\n    return x + 6\n\n\ndef untouched(y):\n    return y\n")
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact")
        assert "index" in data
        assert all("index" not in m for m in data["changed_modules"])


class TestDiffFileMode:
    """--diff-file feeds the change set from a fetched unified diff (PR-review mode)."""

    _DIFF = (
        "diff --git a/lib.py b/lib.py\n"
        "--- a/lib.py\n"
        "+++ b/lib.py\n"
        "@@ -1,2 +1,2 @@ def helper(x):\n"
        "-    return x + 1\n"
        "+    return x + 9\n"
    )

    def test_diff_file_maps_symbols_without_local_git_change(self, git_project, scan_query):
        """A clean working tree still reports the diff-file's change set, symbol-mapped."""
        root, index_path = git_project
        diff_path = root / "pr.diff"
        diff_path.write_text(self._DIFF)
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact", "--diff-file", str(diff_path))
        assert data["base"] == f"diff-file:{diff_path}"
        (entry,) = data["changed_modules"]
        assert entry["module"] == "lib"
        assert entry["changed_symbols"] == ["lib::helper"]

    def test_diff_file_ignores_non_python_and_deleted_files(self, git_project, scan_query):
        """Doc files and /dev/null (deletions) contribute nothing to the change set."""
        root, index_path = git_project
        diff_path = root / "pr.diff"
        diff_path.write_text("+++ b/README.md\n@@ -1 +1 @@\n+++ /dev/null\n@@ -1,5 +0,0 @@\n")
        data = _query(scan_query, root, index_path, "--no-heal", "diff-impact", "--diff-file", str(diff_path))
        assert data["changed_files"] == 0
        assert data["changed_modules"] == []
