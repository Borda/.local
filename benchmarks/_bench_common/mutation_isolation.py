"""Run one mutable benchmark cell with evidence-preserving cleanup.

The lifecycle is provider-neutral. Callers supply creation, action, and
restoration mechanics; this boundary guarantees that cleanup is attempted on
every ordinary exit and that a cleanup failure cannot be mistaken for a valid
measurement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
import contextlib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, TypeVar

from .edit_patch_contracts import FixMultiContract, FixSingleContract, run_fix_multi_oracle, run_fix_single_oracle


ResultT = TypeVar("ResultT")


class MutationCleanupError(RuntimeError):
    """Raised when a cell's frozen baseline cannot be restored."""


@dataclass
class MutationEvidence:
    """Lifecycle evidence retained even when action or cleanup fails."""

    worktree: Path | None = None
    action_error: str | None = None
    cleanup_error: str | None = None
    restored: bool = False


class IsolatedMutationCell:
    """Coordinate create/action/restore operations for one disposable cell."""

    def __init__(self, create: Callable[[], Path], restore: Callable[[Path], None]) -> None:
        """Store the concrete worktree lifecycle owned by a benchmark runner."""
        self._create = create
        self._restore = restore
        self.last_evidence = MutationEvidence()

    def run(self, action: Callable[[Path], ResultT]) -> ResultT:
        """Run one action and fail closed if its disposable baseline is not restored."""
        worktree = self._create()
        evidence = MutationEvidence(worktree=worktree)
        self.last_evidence = evidence
        try:
            return action(worktree)
        except Exception as exc:
            evidence.action_error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            try:
                self._restore(worktree)
            except Exception as cleanup_error:
                evidence.cleanup_error = f"{type(cleanup_error).__name__}: {cleanup_error}"
                message = "mutable cell cleanup failed"
                if evidence.action_error:
                    message = f"{message} after {evidence.action_error}"
                raise MutationCleanupError(message) from cleanup_error
            evidence.restored = True


@dataclass(frozen=True)
class FixExecution:
    """Patch-application and oracle evidence from one candidate lifecycle."""

    baseline_failed: bool
    patch_applied: bool
    changed_paths: tuple[str, ...]
    targeted_test_passed: bool
    recount_recoverable: bool
    recount_oracle_passed: bool | None
    cleanup_verified: bool
    error: str | None

    def as_dict(self) -> dict[str, object]:
        """Return JSON-safe execution evidence."""
        return asdict(self)


def _workspace_git(repo_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one bounded Git command against an explicit benchmark repository."""
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _verified_source_baseline(repo_path: Path, baseline_commit: str) -> None:
    """Reject a dirty or wrong-revision source before a mutable scoring worktree."""
    try:
        head = _workspace_git(repo_path, "rev-parse", "HEAD").stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ValueError("source repository must be a readable Git checkout") from exc
    if head != baseline_commit:
        raise ValueError(f"source revision {head!r} does not match {baseline_commit!r}")
    if _workspace_git(repo_path, "status", "--porcelain").stdout.strip():
        raise ValueError("source repository must be clean before a patch cell")


def execute_executable_patch(
    repo_path: Path, *, baseline_commit: str, oracle: Callable[[Path], bool], diff: str
) -> FixExecution:
    """Apply a candidate patch in a clean scoring worktree and retain diagnostics.

    Normal application and the independent oracle determine the primary result.
    ``--recount`` is recorded only to explain a malformed candidate; it never
    upgrades ``patch_applied`` or the primary score.
    """
    source = repo_path.resolve()
    _verified_source_baseline(source, baseline_commit)
    root = Path(tempfile.mkdtemp(prefix="codemap-executable-patch-"))
    worktree = root / "repo"
    baseline_failed = patch_applied = targeted_test_passed = recount_recoverable = cleanup_verified = created = False
    changed_paths: tuple[str, ...] = ()
    recount_oracle_passed: bool | None = None
    error: str | None = None
    try:
        _workspace_git(source, "worktree", "add", "--detach", str(worktree), baseline_commit)
        created = True
        baseline_failed = not oracle(worktree)
        if not baseline_failed:
            error = "baseline unexpectedly satisfies the task oracle"
        if baseline_failed:
            patch_path = root / "candidate.diff"
            patch_path.write_text(diff, encoding="utf-8")
            check = _workspace_git(worktree, "apply", "--check", str(patch_path), check=False)
            if check.returncode != 0:
                recount_recoverable = (
                    _workspace_git(worktree, "apply", "--check", "--recount", str(patch_path), check=False).returncode
                    == 0
                )
                if recount_recoverable:
                    _workspace_git(worktree, "apply", "--recount", "--whitespace=nowarn", str(patch_path))
                    recount_oracle_passed = oracle(worktree)
                error = f"patch does not apply cleanly: {check.stderr.strip()[:300]}"
            else:
                _workspace_git(worktree, "apply", "--whitespace=nowarn", str(patch_path))
                patch_applied = True
                changed_paths = tuple(
                    line for line in _workspace_git(worktree, "diff", "--name-only").stdout.splitlines() if line.strip()
                )
                targeted_test_passed = oracle(worktree)
    except (OSError, ValueError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        error = str(exc)[:1000]
    finally:
        try:
            if created:
                _workspace_git(worktree, "reset", "--hard", "HEAD")
                _workspace_git(source, "worktree", "remove", str(worktree))
            cleanup_verified = (
                not worktree.exists()
                and str(worktree) not in _workspace_git(source, "worktree", "list", "--porcelain").stdout
            )
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            error = error or f"cleanup failed: {exc}"
        shutil.rmtree(root, ignore_errors=True)
    return FixExecution(
        baseline_failed,
        patch_applied,
        changed_paths,
        targeted_test_passed,
        recount_recoverable,
        recount_oracle_passed,
        cleanup_verified,
        error,
    )


def execute_fix_single_patch(repo_path: Path, contract: FixSingleContract, diff: str) -> FixExecution:
    """Score one Fix-Single patch in an isolated clean worktree."""
    return execute_executable_patch(
        repo_path,
        baseline_commit=contract.baseline_commit,
        oracle=lambda worktree: run_fix_single_oracle(worktree, contract),
        diff=diff,
    )


def execute_fix_multi_patch(repo_path: Path, contract: FixMultiContract, diff: str) -> FixExecution:
    """Score one Fix-Multi patch in an isolated clean worktree."""
    return execute_executable_patch(
        repo_path,
        baseline_commit=contract.baseline_commit,
        oracle=lambda worktree: run_fix_multi_oracle(worktree, contract),
        diff=diff,
    )


@dataclass
class ExecutableAgentWorkspace:
    """One benchmark-owned editable worktree and its private relocated index."""

    source: Path
    root: Path
    worktree: Path
    index_path: Path
    baseline_commit: str
    index_relocation: Mapping[str, str]

    def index_unchanged(self) -> bool:
        """Return whether the model left the derived frozen graph untouched."""
        try:
            current_sha256 = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        except OSError:
            return False
        return current_sha256 == self.index_relocation["derived_index_sha256"]

    def capture_diff(self) -> str:
        """Return the canonical Git diff produced by direct agent edits."""
        return _workspace_git(self.worktree, "diff", "--binary", "--no-ext-diff").stdout

    def changed_paths(self) -> tuple[str, ...]:
        """Return the exact tracked paths changed by the agent."""
        return tuple(
            line for line in _workspace_git(self.worktree, "diff", "--name-only").stdout.splitlines() if line.strip()
        )

    def cleanup(self) -> bool:
        """Restore and remove only this known disposable worktree, else fail closed."""
        try:
            _workspace_git(self.worktree, "reset", "--hard", "HEAD")
            _workspace_git(self.source, "worktree", "remove", str(self.worktree))
            cleaned = (
                not self.worktree.exists()
                and str(self.worktree) not in _workspace_git(self.source, "worktree", "list", "--porcelain").stdout
            )
        except (OSError, subprocess.SubprocessError):
            cleaned = False
        if cleaned:
            shutil.rmtree(self.root, ignore_errors=True)
        return cleaned


def _non_root_index_sha256(payload: Mapping[str, Any]) -> str:
    """Hash index content after excluding its environment-specific scan root."""
    normalized = dict(payload)
    normalized.pop("scan_root", None)
    return hashlib.sha256(json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def relocate_frozen_index_for_worktree(
    frozen_bytes: bytes, *, source_root: Path, worktree_root: Path
) -> tuple[bytes, dict[str, str]]:
    """Relocate only ``scan_root`` in a frozen index for a byte-identical worktree.

    This derived copy keeps the static graph immutable while allowing Codemap's
    root-mismatch completeness guard to evaluate the benchmark-owned checkout.
    The caller records both hashes and rejects a cell that modifies the copy.
    """
    try:
        frozen_payload = json.loads(frozen_bytes)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("executable agent workspace index must be valid JSON") from exc
    if not isinstance(frozen_payload, dict):
        raise ValueError("executable agent workspace index must be a JSON object")
    expected_root = str(source_root.resolve())
    if frozen_payload.get("scan_root") != expected_root:
        raise ValueError("executable agent workspace index scan_root must match the frozen source repository")
    derived_payload = dict(frozen_payload)
    derived_payload["scan_root"] = str(worktree_root.resolve())
    frozen_content_sha256 = _non_root_index_sha256(frozen_payload)
    if _non_root_index_sha256(derived_payload) != frozen_content_sha256:
        raise RuntimeError("executable index relocation changed frozen graph content")
    derived_bytes = (json.dumps(derived_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return derived_bytes, {
        "frozen_index_sha256": hashlib.sha256(frozen_bytes).hexdigest(),
        "derived_index_sha256": hashlib.sha256(derived_bytes).hexdigest(),
        "non_root_content_sha256": frozen_content_sha256,
        "source_scan_root": expected_root,
        "worktree_scan_root": str(worktree_root.resolve()),
    }


def create_executable_agent_workspace(source: Path, index_path: Path, baseline_commit: str) -> ExecutableAgentWorkspace:
    """Create an editable worktree with a root-relocated immutable graph copy."""
    source = source.resolve(strict=True)
    index_path = index_path.resolve(strict=True)
    if not index_path.is_relative_to(source):
        raise ValueError("executable agent workspace requires an index inside the frozen source repository")
    _verified_source_baseline(source, baseline_commit)
    root = Path(tempfile.mkdtemp(prefix="codemap-executable-agent-")).resolve(strict=True)
    worktree = root / "repo"
    copied_index = worktree / ".cache" / "codemap" / f"{worktree.name}.json"
    try:
        _workspace_git(source, "worktree", "add", "--detach", str(worktree), baseline_commit)
        copied_index.parent.mkdir(parents=True, exist_ok=True)
        derived_bytes, index_relocation = relocate_frozen_index_for_worktree(
            index_path.read_bytes(), source_root=source, worktree_root=worktree
        )
        copied_index.write_bytes(derived_bytes)
        if hashlib.sha256(copied_index.read_bytes()).hexdigest() != index_relocation["derived_index_sha256"]:
            raise RuntimeError("executable agent workspace derived index write is incomplete")
        return ExecutableAgentWorkspace(source, root, worktree, copied_index, baseline_commit, index_relocation)
    except BaseException:
        if worktree.exists():
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                _workspace_git(worktree, "reset", "--hard", "HEAD")
                _workspace_git(source, "worktree", "remove", str(worktree))
        shutil.rmtree(root, ignore_errors=True)
        raise
