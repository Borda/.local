"""Shared fixtures for benchmarks test suite."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

BENCHMARKS_DIR = Path(__file__).parent.parent
REPO_ROOT = BENCHMARKS_DIR.parent


def _load_module(module_name: str, filename: str):
    """Load a benchmarks script by filename via importlib.

    Args:
        module_name: Name to register in sys.modules (must be a valid identifier).
        filename: Filename of the script relative to BENCHMARKS_DIR.

    Returns:
        The loaded module with all public symbols accessible.
    """
    path = BENCHMARKS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def script_run_agentic():
    """Loaded run-codemap-agentic module."""
    return _load_module("run_codemap_agentic", "run-codemap-agentic.py")


@pytest.fixture(scope="session")
def script_run_bench():
    """Loaded run-codemap-bench module."""
    return _load_module("run_codemap_bench", "run-codemap-bench.py")


@pytest.fixture(scope="session")
def script_run_cli():
    """Loaded run-codemap-cli module."""
    return _load_module("run_codemap_cli", "run-codemap-cli.py")


@pytest.fixture(scope="session")
def script_gen_bench():
    """Loaded generate-tasks-bench module."""
    return _load_module("generate_tasks_bench", "generate-tasks-bench.py")


@pytest.fixture(scope="session")
def script_gen_real_issues():
    """Loaded generate-tasks-real-issues module."""
    return _load_module("generate_tasks_real_issues", "generate-tasks-real-issues.py")


# ---------------------------------------------------------------------------
# Integration fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def scan_query_binary() -> Path:
    """Path to scan-query binary; skips if not present.

    Returns:
        Absolute path to the scan-query executable.
    """
    binary = REPO_ROOT / "plugins" / "codemap" / "bin" / "scan-query"
    if not binary.exists():
        pytest.skip(f"scan-query binary not found at {binary}")
    return binary


@pytest.fixture(scope="session")
def scan_index_binary() -> Path:
    """Path to scan-index binary; skips if not present.

    Returns:
        Absolute path to the scan-index executable.
    """
    binary = REPO_ROOT / "plugins" / "codemap" / "bin" / "scan-index"
    if not binary.exists():
        pytest.skip(f"scan-index binary not found at {binary}")
    return binary


@pytest.fixture(scope="session")
def sample_repo(tmp_path_factory: pytest.TempPathFactory, scan_index_binary: Path) -> tuple[Path, Path]:
    """Clone psf/requests (shallow) and build a codemap index.

    Skips if git clone fails (no network access).

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
        pytest.skip(f"git clone failed (no network?): {exc}")

    try:
        subprocess.run(
            [str(scan_index_binary), "--root", str(clone_dir)],
            check=True,
            capture_output=True,
            timeout=120,
            cwd=str(clone_dir),
        )
    except subprocess.CalledProcessError as exc:
        pytest.skip(f"scan-index failed: {exc.stderr.decode()}")

    index_candidates = sorted(clone_dir.rglob(".cache/codemap/*.json"))
    if not index_candidates:
        pytest.skip("scan-index ran but produced no index file")

    return clone_dir, index_candidates[0]


@pytest.fixture(scope="session")
def pytorch_lightning_repo() -> Path:
    """Path to a pytorch-lightning checkout; skips if not found.

    Checks ``PL_REPO_PATH`` env var first, then
    ``~/Workspace/pytorch-lightning-master`` as a dev-machine default.

    Returns:
        Absolute path to the pytorch-lightning repository root.
    """
    default = Path.home() / "Workspace" / "pytorch-lightning-master"
    repo = Path(os.environ.get("PL_REPO_PATH", str(default)))
    if not repo.exists():
        pytest.skip(f"pytorch-lightning repo not found at {repo}; set PL_REPO_PATH env var")
    return repo


@pytest.fixture(scope="session")
def pytorch_lightning_index(pytorch_lightning_repo: Path, scan_query_binary: Path) -> Path:
    """Pre-built codemap index for pytorch-lightning; skips if not found.

    The index is expected at ``.cache/codemap/<repo-name>.json`` inside the
    repo.  Run ``scan-index --root <repo>`` once to create it.

    Args:
        pytorch_lightning_repo: Root of the pytorch-lightning checkout.
        scan_query_binary: Ensures the binary fixture was resolved first.

    Returns:
        Absolute path to the JSON index file.
    """
    _ = scan_query_binary  # ensure binary fixture resolved
    candidates = sorted(pytorch_lightning_repo.rglob(".cache/codemap/*.json"))
    if not candidates:
        pytest.skip(
            f"No codemap index found under {pytorch_lightning_repo}/.cache/codemap/; run: scan-index --root <repo>"
        )
    return candidates[0]
