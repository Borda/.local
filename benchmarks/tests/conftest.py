"""Shared fixtures for benchmarks test suite.

Generated-manifest session hooks live in the parent ``benchmarks/conftest.py``: only conftests for the ``testpaths``
collection roots load before ``pytest_sessionstart``, so hooks placed here never ran on a fresh clone.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

BENCHMARKS_DIR = Path(__file__).parent.parent
REPO_ROOT = BENCHMARKS_DIR.parent
TESTS_DIR = Path(__file__).parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
PYTORCH_LIGHTNING_REPO = Path(os.environ.get("PL_REPO_PATH", str(REPO_ROOT / ".sandbox" / "pytorch-lightning")))
PYTORCH_LIGHTNING_INDEXES = (
    tuple(sorted(PYTORCH_LIGHTNING_REPO.rglob(".cache/codemap/*.json"))) if PYTORCH_LIGHTNING_REPO.exists() else ()
)


def _load_module(module_name: str, filename: str):
    """Load a benchmarks script by filename via importlib.

    Args:
        module_name: Name to register in sys.modules (must be a valid identifier).
        filename: Filename of the script relative to BENCHMARKS_DIR.

    Returns:
        The loaded module with all public symbols accessible.
    """
    # Runners import private benchmark packages from their own directory; add it
    # because spec_from_file_location does not set it as sys.path[0].
    if str(BENCHMARKS_DIR) not in sys.path:
        sys.path.insert(0, str(BENCHMARKS_DIR))
    path = BENCHMARKS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def script_claude_stream():
    """Load the shared Claude stream implementation."""
    return _load_module("benchmarks_claude_transport", "_bench_common/claude_transport.py")


@pytest.fixture(scope="session")
def script_python_source():
    """Load shared Python-source import graph helpers."""
    return _load_module("benchmarks_python_source", "_bench_common/python_source.py")


@pytest.fixture(scope="session")
def script_benchmark_paths():
    """Load shared benchmark-task paths and metadata helpers."""
    return _load_module("benchmarks_benchmark_paths", "_bench_common/benchmark_paths.py")


@pytest.fixture(scope="session")
def script_run_agentic():
    """Load the Claude-only agentic runner."""
    return _load_module("run_claude_agentic", "run-claude-agentic.py")


@pytest.fixture(scope="session")
def script_run_bench():
    """Load the Claude-only structural runner."""
    return _load_module("run_claude_structural", "run-claude-structural.py")


@pytest.fixture(scope="session")
def script_run_cli():
    """Provide the loaded Codemap CLI module."""
    return _load_module("run_cli", "run-codemap-cli.py")


@pytest.fixture(scope="session")
def script_gen_bench():
    """Provide the loaded benchmark-task generator module."""
    return _load_module("generate_tasks_bench", "generate-tasks-bench.py")


@pytest.fixture(scope="session")
def script_gen_real_issues():
    """Provide the loaded real-issue task generator module."""
    return _load_module("generate_tasks_real_issues", "generate-tasks-real-issues.py")


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def scan_query_binary() -> Path:
    """Path to scan-query binary; fails on POSIX when the tracked binary is absent.

    The enclosing tests use a collection-time launchability marker. Once selected,
    a missing tracked binary means a broken checkout, so fail loudly rather than
    yielding a false-green skip.

    Returns:
        Absolute path to the scan-query executable.
    """
    binary = REPO_ROOT / "plugins" / "codemap-py" / "bin" / "scan-query"
    if not binary.exists():
        pytest.fail(f"tracked scan-query binary missing at {binary} — broken checkout")
    return binary


@pytest.fixture(scope="session")
def scan_index_binary() -> Path:
    """Path to scan-index binary; fails on POSIX when the tracked binary is absent.

    The enclosing tests use a collection-time launchability marker. Once selected,
    a missing tracked binary means a broken checkout, so fail loudly rather than
    yielding a false-green skip.

    Returns:
        Absolute path to the scan-index executable.
    """
    binary = REPO_ROOT / "plugins" / "codemap-py" / "bin" / "scan-index"
    if not binary.exists():
        pytest.fail(f"tracked scan-index binary missing at {binary} — broken checkout")
    return binary


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory: pytest.TempPathFactory, scan_index_binary: Path) -> tuple[Path, Path]:
    """Clone psf/requests (shallow) and build a codemap index.

    Fails if clone or indexing fails after collection.

    Args:
        tmp_path_factory: pytest factory for session-scoped temp directories.
        scan_index_binary: Path to the scan-index executable.

    Returns:
        Tuple of (repo_path, index_path) for use in integration tests.
    """
    clone_dir = tmp_path_factory.mktemp("sample-repo") / "requests"
    try:
        subprocess.run(
            ["git", "clone", "--depth=1", "https://github.com/psf/requests.git", str(clone_dir)],
            check=True,
            capture_output=True,
            timeout=120,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        pytest.fail(f"git clone failed (no network?): {exc}")

    try:
        subprocess.run(
            [str(scan_index_binary), "--root", str(clone_dir)],
            check=True,
            capture_output=True,
            timeout=120,
            cwd=str(clone_dir),
        )
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"scan-index failed: {exc.stderr.decode()}")

    index_candidates = sorted(clone_dir.rglob(".cache/codemap/*.json"))
    if not index_candidates:
        pytest.fail("scan-index ran but produced no index file")

    return clone_dir, index_candidates[0]


@pytest.fixture(scope="session")
def pytorch_lightning_repo() -> Path:
    """Path to a decorator-validated pytorch-lightning checkout.

    Checks ``PL_REPO_PATH`` env var first, then the pinned in-project clone
    ``.sandbox/pytorch-lightning`` (created by ``run-all.sh``).

    Returns:
        Absolute path to the pytorch-lightning repository root.
    """
    assert PYTORCH_LIGHTNING_REPO.is_dir(), "pytorch-lightning test lacks checkout marker"
    return PYTORCH_LIGHTNING_REPO


@pytest.fixture(scope="session")
def pytorch_lightning_index(pytorch_lightning_repo: Path, scan_query_binary: Path) -> Path:
    """Decorator-validated pre-built Codemap index for pytorch-lightning.

    The index is expected at ``.cache/codemap/<repo-name>.json`` inside the
    repo.  Run ``scan-index --root <repo>`` once to create it.

    Args:
        pytorch_lightning_repo: Root of the pytorch-lightning checkout.
        scan_query_binary: Ensures the binary fixture was resolved first.

    Returns:
        Absolute path to the JSON index file.
    """
    _ = scan_query_binary  # ensure binary fixture resolved
    assert PYTORCH_LIGHTNING_INDEXES, "pytorch-lightning index test lacks index marker"
    return PYTORCH_LIGHTNING_INDEXES[0]
