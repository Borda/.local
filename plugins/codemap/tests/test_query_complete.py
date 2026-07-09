"""Direction-scoped completeness and stale-index self-heal for scan-query (CR-1).

Two behaviours are exercised:

* ``query_complete`` is scoped by command DIRECTION. A degraded (unparsable)
  file must never let a global-in (``rdeps``) or whole-graph (``central``) query
  claim completeness — those directions could hide an inbound / graph-wide edge —
  while a local query (``deps`` / ``symbols``) on a healthy module stays complete.
* A stale index is self-healed inline: committing a new edge and then querying
  ``rdeps`` re-scans the changed file and surfaces the new edge, bounded so a
  large change set falls back to the stale-honest result.

The heal tests need a real git repo because the staleness diff is git-blob based.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


def _scan(scan_index: Path, root: Path, *extra: str) -> None:
    """Run scan-index over *root*, asserting success."""
    result = subprocess.run(
        [sys.executable, str(scan_index), "--root", str(root), *extra],
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
def degraded_project(tmp_path: Path, scan_index: Path) -> tuple[Path, Path]:
    """A non-git project: one healthy importer, one healthy leaf, one unparsable file.

    ``consumer`` imports ``leaf``; ``broken.py`` has a syntax error → degraded.
    """
    root = tmp_path / "degraded"
    root.mkdir()
    (root / "leaf.py").write_text("def leaf_fn(x):\n    return x\n")
    (root / "consumer.py").write_text("import leaf\n\ndef use(x):\n    return leaf.leaf_fn(x)\n")
    (root / "broken.py").write_text("def oops(:\n    return\n")  # SyntaxError → degraded
    _scan(scan_index, root)
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    assert index_path.exists()
    return root, index_path


class TestDirectionScopedCompleteness:
    """query_complete is decided per command direction, gated by the degraded set."""

    def test_degraded_module_is_indexed(self, degraded_project, scan_query):
        """Sanity: the broken file registers as a degraded module in coverage."""
        root, index_path = degraded_project
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["degraded"] == 1
        assert any("broken.py" in p for p in data["index"]["degraded_files"])

    def test_local_deps_on_healthy_module_complete(self, degraded_project, scan_query):
        """Local `deps` on a cleanly-parsed module is complete despite a degraded file elsewhere."""
        root, index_path = degraded_project
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["query_complete"] is True
        assert data["index"]["exhaustive"] is True  # legacy alias tracks query_complete

    def test_local_symbols_on_healthy_module_complete(self, degraded_project, scan_query):
        """Local `symbols` on a healthy module is complete despite a degraded file elsewhere."""
        root, index_path = degraded_project
        data = _query(scan_query, root, index_path, "symbols", "leaf")
        assert data["index"]["query_complete"] is True

    def test_global_in_rdeps_incomplete_with_degraded(self, degraded_project, scan_query):
        """Global-in `rdeps` is never complete while a degraded file could hide an inbound edge."""
        root, index_path = degraded_project
        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert data["index"]["query_complete"] is False
        assert data["index"]["exhaustive"] is False
        assert any("broken.py" in p for p in data["index"]["degraded_files"])

    def test_whole_graph_central_incomplete_with_degraded(self, degraded_project, scan_query):
        """Whole-graph `central` is never complete while any file is degraded."""
        root, index_path = degraded_project
        data = _query(scan_query, root, index_path, "central", "--top", "5")
        assert data["index"]["query_complete"] is False


@pytest.fixture
def clean_project(tmp_path: Path, scan_index: Path) -> tuple[Path, Path]:
    """A fully-healthy non-git project so every direction can reach completeness."""
    root = tmp_path / "clean"
    root.mkdir()
    (root / "leaf.py").write_text("def leaf_fn(x):\n    return x\n")
    (root / "consumer.py").write_text("import leaf\n\ndef use(x):\n    return leaf.leaf_fn(x)\n")
    _scan(scan_index, root)
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    return root, index_path


class TestCleanGraphCompleteness:
    """With zero degraded files, global-in and whole-graph queries reach completeness."""

    def test_rdeps_complete_when_no_degraded(self, clean_project, scan_query):
        """Global-in `rdeps` is complete on a clean, fresh (non-git → not-stale) index."""
        root, index_path = clean_project
        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert data["index"]["degraded"] == 0
        assert data["index"]["query_complete"] is True

    def test_central_complete_when_no_degraded(self, clean_project, scan_query):
        """Whole-graph `central` is complete on a clean index."""
        root, index_path = clean_project
        data = _query(scan_query, root, index_path, "central", "--top", "5")
        assert data["index"]["query_complete"] is True


@pytest.fixture
def git_project(tmp_path: Path, scan_index: Path) -> tuple[Path, Path]:
    """A committed git project so the git-blob staleness diff (and heal) engages."""
    root = tmp_path / "gitrepo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "leaf.py").write_text("def leaf_fn(x):\n    return x\n")
    (root / "consumer.py").write_text("import leaf\n\ndef use(x):\n    return leaf.leaf_fn(x)\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    _scan(scan_index, root)
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    return root, index_path


class TestSelfHeal:
    """A stale index is refreshed inline (bounded) before the query answers."""

    def test_heal_surfaces_new_edge(self, git_project, scan_query):
        """Committing a new importer then querying rdeps auto-heals and reflects the new edge."""
        root, index_path = git_project
        # New module importing leaf, committed AFTER the index was built → index is stale.
        (root / "newcaller.py").write_text("import leaf\n\ndef also(x):\n    return leaf.leaf_fn(x)\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "add newcaller")

        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert "newcaller" in data["imported_by"], "self-heal must surface the newly-committed edge"
        assert data["index"]["stale"] is False, "post-heal index must report fresh"
        assert data["index"]["query_complete"] is True

    def test_no_heal_flag_keeps_stale_result(self, git_project, scan_query):
        """--no-heal answers from the stale index: new edge invisible, stale flagged honestly."""
        root, index_path = git_project
        (root / "newcaller.py").write_text("import leaf\n\ndef also(x):\n    return leaf.leaf_fn(x)\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "add newcaller")

        data = _query(scan_query, root, index_path, "--no-heal", "rdeps", "leaf")
        assert "newcaller" not in data["imported_by"], "stale index must not see the new edge"
        assert data["index"]["stale"] is True
        assert data["index"]["query_complete"] is False


class TestHealBound:
    """The heal is bounded: a large change set falls back to the stale-honest result."""

    def test_large_change_set_skips_heal(self, git_project, scan_query, monkeypatch):
        """More changed files than the heal cap → answer from the stale index, flagged stale."""
        root, index_path = git_project
        # Add more changed files than the cap so the heal is skipped. The cap lives in
        # scan-query as _HEAL_MAX_CHANGED_FILES (50); overshoot it deterministically.
        for i in range(60):
            (root / f"mod{i}.py").write_text(f"import leaf\n\ndef f{i}(x):\n    return leaf.leaf_fn(x)\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "many")

        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert data["index"]["stale"] is True, "over-cap change set must leave the index stale"
        assert "mod0" not in data["imported_by"], "skipped heal must not surface new edges"


class TestUntrackedFileVeto:
    """An untracked new .py file vetoes global-in/whole-graph but never a local query (F2)."""

    def test_untracked_present(self, git_project, scan_query):
        """Sanity: an uncommitted new .py file is reported in the coverage `untracked_py` list."""
        root, index_path = git_project
        (root / "orphan.py").write_text("x = 1\n")  # present but never `git add`-ed
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert any("orphan.py" in p for p in data["index"]["untracked_py"])

    def test_untracked_vetoes_global_in(self, git_project, scan_query):
        """rdeps (global-in) is incomplete while an untracked .py could hide an inbound edge."""
        root, index_path = git_project
        (root / "orphan.py").write_text("x = 1\n")
        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert data["index"]["query_complete"] is False

    def test_untracked_does_not_veto_local(self, git_project, scan_query):
        """F2: `deps` on a healthy module stays complete despite an untracked .py file.

        An untracked file cannot change an already-indexed module's own direct_imports.
        """
        root, index_path = git_project
        (root / "orphan.py").write_text("x = 1\n")
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["query_complete"] is True

    def test_incomplete_note_matches_flag(self, git_project, scan_query):
        """F1: when the untracked veto fires, the note must not claim the result is complete."""
        root, index_path = git_project
        (root / "orphan.py").write_text("x = 1\n")
        data = _query(scan_query, root, index_path, "rdeps", "leaf")
        assert data["index"]["query_complete"] is False
        assert "This result is complete" not in data["index"]["note"]
        assert "incomplete" in data["index"]["note"]


class TestCollisionVeto:
    """A qualname collision vetoes whole-graph always, but local only for the colliding module."""

    def _inject_collision(self, index_path: Path, name: str) -> None:
        """Write a `collisions` entry (as scan-index task 1.3 would) into an existing index file."""
        data = json.loads(index_path.read_text())
        data["collisions"] = [{"name": name, "kept": f"{name}.a", "dropped": f"{name}.b"}]
        index_path.write_text(json.dumps(data))

    def test_collision_count_surfaced(self, clean_project, scan_query):
        """collision_count reflects an injected collisions list (missing key would be 0)."""
        root, index_path = clean_project
        self._inject_collision(index_path, "somewhere")
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["collision_count"] == 1

    def test_collision_vetoes_whole_graph(self, clean_project, scan_query):
        """central (whole-graph) is incomplete whenever any collision dropped a module."""
        root, index_path = clean_project
        self._inject_collision(index_path, "somewhere")
        data = _query(scan_query, root, index_path, "central", "--top", "5")
        assert data["index"]["query_complete"] is False

    def test_collision_does_not_veto_unrelated_local(self, clean_project, scan_query):
        """F2: `deps` on a module whose name is NOT the colliding one stays complete."""
        root, index_path = clean_project
        self._inject_collision(index_path, "unrelated.module")
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["query_complete"] is True

    def test_collision_vetoes_own_local(self, clean_project, scan_query):
        """F2: `deps` on the colliding module itself is incomplete — its own name is ambiguous."""
        root, index_path = clean_project
        self._inject_collision(index_path, "consumer")
        data = _query(scan_query, root, index_path, "deps", "consumer")
        assert data["index"]["query_complete"] is False


@pytest.fixture
def excluded_git_project(tmp_path: Path, scan_index: Path) -> tuple[Path, Path]:
    """A committed git repo holding a .codemapignore-excluded tracked .py and a SKIP_DIR copy.

    ``vendored/vendored.py`` is excluded via ``.codemapignore`` (dropped from file_shas);
    ``.claude/ghost.py`` sits in a built-in SKIP_DIR but is git-tracked (kept in the
    git-blob file_shas, since scan-index's git path filters only user exclusions).
    """
    root = tmp_path / "excluded"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "leaf.py").write_text("def leaf_fn(x):\n    return x\n")
    (root / "consumer.py").write_text("import leaf\n\ndef use(x):\n    return leaf.leaf_fn(x)\n")
    (root / "vendored").mkdir()
    (root / "vendored" / "vendored.py").write_text("def v():\n    return 0\n")
    (root / ".codemapignore").write_text("vendored\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "ghost.py").write_text("def ghost():\n    return 1\n")
    _git(root, "add", "-A", "-f")  # -f so .claude/ghost.py is tracked despite common ignores
    _git(root, "commit", "-q", "-m", "init")
    _scan(scan_index, root)
    index_path = root / ".cache" / "codemap" / f"{root.name}.json"
    return root, index_path


class TestExclusionAwareStaleness:
    """F4: scan-query's staleness diff applies the same exclusions scan-index used."""

    def test_fresh_excluded_repo_not_stale(self, excluded_git_project, scan_query):
        """A .codemapignore-excluded tracked .py must not force a false stale on a fresh index."""
        root, index_path = excluded_git_project
        data = _query(scan_query, root, index_path, "--no-heal", "deps", "consumer")
        assert data["index"]["stale"] is False

    def test_excluded_repo_local_complete(self, excluded_git_project, scan_query):
        """With no real change, local `deps` reaches completeness despite excluded/SKIP_DIR files."""
        root, index_path = excluded_git_project
        data = _query(scan_query, root, index_path, "--no-heal", "deps", "consumer")
        assert data["index"]["query_complete"] is True

    def test_excluded_repo_rdeps_complete(self, excluded_git_project, scan_query):
        """Global-in `rdeps` reaches completeness — excluded files are not phantom edges."""
        root, index_path = excluded_git_project
        data = _query(scan_query, root, index_path, "--no-heal", "rdeps", "leaf")
        assert data["index"]["stale"] is False
        assert data["index"]["query_complete"] is True

    def test_untracked_in_excluded_dir_does_not_poison(self, excluded_git_project, scan_query):
        """An untracked .py inside an excluded dir must not appear in untracked_py or block completeness."""
        root, index_path = excluded_git_project
        (root / "vendored" / "new_orphan.py").write_text("y = 2\n")  # untracked, inside excluded dir
        data = _query(scan_query, root, index_path, "--no-heal", "rdeps", "leaf")
        assert not any("new_orphan" in p for p in data["index"]["untracked_py"])
        assert data["index"]["query_complete"] is True

    def test_untracked_in_skip_dir_does_not_poison(self, excluded_git_project, scan_query):
        """An untracked .py inside a built-in SKIP_DIR must not poison query_complete either."""
        root, index_path = excluded_git_project
        (root / ".claude" / "new_scratch.py").write_text("z = 3\n")  # untracked, inside SKIP_DIR
        data = _query(scan_query, root, index_path, "--no-heal", "rdeps", "leaf")
        assert not any("new_scratch" in p for p in data["index"]["untracked_py"])
        assert data["index"]["query_complete"] is True
