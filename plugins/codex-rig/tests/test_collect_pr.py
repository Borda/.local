"""Portable acceptance checks for authoritative PR evidence collection."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
COLLECTOR = PLUGIN_ROOT / "shared" / "collect_pr.py"
BASE_OID = "a" * 40
HEAD_OID = "b" * 40


def load_collector() -> ModuleType:
    """Load the standalone collector without requiring package installation."""
    assert COLLECTOR.is_file(), COLLECTOR
    specification = importlib.util.spec_from_file_location("codex_rig_collect_pr", COLLECTOR)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(COLLECTOR.parent))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def pr_payload(*, state: str = "OPEN", cross_repository: bool = False) -> dict[str, Any]:
    """Return one complete same-repository PR metadata fixture."""
    return {
        "number": 17,
        "title": "Portable collector",
        "body": "Fix checkpoint resume behavior described by the contributor.",
        "url": "https://github.com/Borda/AI-Rig/pull/17",
        "author": {"login": "contributor"},
        "baseRefName": "main",
        "baseRefOid": BASE_OID,
        "headRefName": "portable-pr",
        "headRefOid": HEAD_OID,
        "headRepository": {"nameWithOwner": "contributor/AI-Rig" if cross_repository else "Borda/AI-Rig"},
        "headRepositoryOwner": {"login": "contributor" if cross_repository else "Borda"},
        "isCrossRepository": cross_repository,
        "state": state,
        "isDraft": False,
        "reviewDecision": "CHANGES_REQUESTED",
        "mergeable": "MERGEABLE",
        "comments": [{"id": "comment-1"}],
        "reviews": [{"id": "review-1"}],
        "files": [{"path": "b.py"}, {"path": "a.py"}],
    }


def threads_payload(*, paginated: bool = False) -> dict[str, Any]:
    """Return one GraphQL review-thread response fixture."""
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": paginated, "endCursor": "cursor"},
                        "nodes": [
                            {"id": "resolved", "isResolved": True, "isOutdated": False, "comments": {"nodes": []}},
                            {
                                "id": "active",
                                "isResolved": False,
                                "isOutdated": False,
                                "comments": {"nodes": []},
                            },
                            {
                                "id": "outdated",
                                "isResolved": False,
                                "isOutdated": True,
                                "comments": {"nodes": []},
                            },
                        ],
                    }
                }
            }
        }
    }


class FakeRunner:
    """Return deterministic process results while recording exact argv calls."""

    def __init__(
        self,
        *,
        paginated: bool = False,
        statistics_unavailable: bool = False,
        current_base_oid: str = BASE_OID,
        recorded_base_is_ancestor: bool = True,
        pr_state: str = "OPEN",
        named_head_ref_missing: bool = False,
        review_threads_failure: bool = False,
        current_head_oid: str = "d" * 40,
        cross_repository: bool = False,
    ) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.paginated = paginated
        self.statistics_unavailable = statistics_unavailable
        self.current_base_oid = current_base_oid
        self.recorded_base_is_ancestor = recorded_base_is_ancestor
        self.pr_state = pr_state
        self.named_head_ref_missing = named_head_ref_missing
        self.review_threads_failure = review_threads_failure
        self.local_head_oid = current_head_oid
        self.cross_repository = cross_repository

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        """Simulate the Git, GitHub CLI, and remote-selector commands."""
        assert isinstance(argv, list)
        assert kwargs.get("shell", False) is False
        self.calls.append((argv, kwargs))
        stdout = b""
        if argv[:4] == ["git", "status", "--short", "--untracked-files=no"]:
            stdout = b""
        elif argv[:3] == ["git", "status", "--short"]:
            stdout = b" M local.txt\n"
        elif argv[:3] == ["gh", "pr", "view"]:
            stdout = json.dumps(pr_payload(state=self.pr_state, cross_repository=self.cross_repository)).encode()
        elif argv[:3] == ["gh", "api", "graphql"]:
            if self.review_threads_failure:
                return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"connection reset by peer")
            stdout = json.dumps(threads_payload(paginated=self.paginated)).encode()
        elif argv[:3] == ["gh", "pr", "diff"]:
            stdout = b"diff --git a/a.py b/a.py\n"
        elif argv[:2] == ["git", "diff"] and "--binary" in argv:
            stdout = b"diff --git a/a.py b/a.py\n"
        elif argv[:2] == ["git", "diff"] and "--stat" in argv:
            if self.statistics_unavailable:
                return subprocess.CompletedProcess(argv, 128, stdout=b"", stderr=b"binary patch has no stat\n")
            stdout = b" a.py | 1 +\n"
        elif argv[:2] == ["git", "diff"] and "--numstat" in argv:
            if self.statistics_unavailable:
                return subprocess.CompletedProcess(argv, 128, stdout=b"", stderr=b"binary patch has no numstat\n")
            stdout = b"1\t0\ta.py\n"
        elif argv[:2] == ["git", "apply"] and "--stat" in argv:
            if self.statistics_unavailable:
                return subprocess.CompletedProcess(argv, 128, stdout=b"", stderr=b"binary patch has no stat\n")
            stdout = b" a.py | 1 +\n"
        elif argv[:2] == ["git", "apply"] and "--numstat" in argv:
            if self.statistics_unavailable:
                return subprocess.CompletedProcess(argv, 128, stdout=b"", stderr=b"binary patch has no numstat\n")
            stdout = b"1\t0\ta.py\n"
        elif argv[0] == sys.executable and argv[1].endswith("select-git-remote.py"):
            if "--identity-only" in argv:
                stdout = b'{"repository":"Borda/AI-Rig","host":"github.com"}\n'
            else:
                stdout = b'{"remote":"origin","remote_url":"https://github.com/Borda/AI-Rig.git"}\n'
        elif argv[:3] == ["git", "fetch", "--no-tags"]:
            if self.named_head_ref_missing and "portable-pr" in argv[-1]:
                return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"missing branch")
            stdout = b""
        elif argv[:2] == ["git", "rev-parse"]:
            reference = argv[2]
            stdout = (
                HEAD_OID if "portable-pr" in reference or "/pull/" in reference else self.current_base_oid
            ).encode() + b"\n"
            if reference == "HEAD":
                stdout = f"{self.local_head_oid}\n".encode()
        elif argv[:3] == ["git", "merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(
                argv,
                0 if self.recorded_base_is_ancestor else 1,
                stdout=b"",
                stderr=b"",
            )
        elif argv[:3] == ["gh", "pr", "checkout"]:
            self.local_head_oid = HEAD_OID
            stdout = b"checked out\n"
        elif argv[:3] == ["git", "checkout", "--detach"]:
            self.local_head_oid = HEAD_OID
            stdout = b"checked out\n"
        elif argv[:3] == ["git", "branch", "--show-current"]:
            stdout = b"portable-pr\n"
        else:  # pragma: no cover - makes unexpected production commands diagnostic
            raise AssertionError(f"unexpected command: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")


def configure_collector(monkeypatch: pytest.MonkeyPatch, module: ModuleType, runner: FakeRunner) -> None:
    """Install deterministic command discovery and execution boundaries."""
    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")
    monkeypatch.setattr(module.subprocess, "run", runner)


def test_collect_pr_writes_complete_noncheckout_artifact_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Collect online review evidence with argv-only subprocess execution."""
    module = load_collector()
    runner = FakeRunner()
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5)

    assert result == 0, (output / "pr-error.txt").read_text() if (output / "pr-error.txt").exists() else ""
    assert {path.name for path in output.iterdir()} == {
        "comments.json",
        "diff.patch",
        "diffstat.txt",
        "files.txt",
        "numstat.txt",
        "online-review-summary.json",
        "pr-target.txt",
        "pr-routing.json",
        "pr.json",
        "review-threads.json",
        "review-threads.raw.json",
        "reviews.json",
        "status.txt",
        "unresolved-review-threads.json",
        "untracked.txt",
    }
    assert (output / "pr-target.txt").read_text(encoding="utf-8") == "17\n"
    assert (output / "files.txt").read_text(encoding="utf-8") == "a.py\nb.py\n"
    assert json.loads((output / "online-review-summary.json").read_text()) == {
        "review_threads_status": "available",
        "review_threads_error": None,
        "review_thread_count": 3,
        "unresolved_review_thread_count": 2,
        "active_unresolved_review_thread_count": 1,
        "outdated_unresolved_review_thread_count": 1,
        "top_level_comment_count": 1,
        "review_count": 1,
    }
    routing = json.loads((output / "pr-routing.json").read_text())
    assert routing["base_repo"] == "Borda/AI-Rig"
    assert routing["same_repo"] is True
    assert routing["local_checkout_command"] == "gh pr checkout 17"
    assert json.loads((output / "pr.json").read_text())["body"].startswith("Fix checkpoint")
    assert all(call[1]["timeout"] == 5 for call in runner.calls)


def test_collect_pr_degrades_incomplete_review_thread_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep source review available while recording incomplete supplemental thread evidence."""
    module = load_collector()
    runner = FakeRunner(paginated=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="", output=output, checkout=False, timeout_seconds=5)

    assert result == 0
    assert not (output / "pr-error.txt").exists()
    assert (output / "review-threads-error.txt").read_text(encoding="utf-8") == (
        "review-thread-pagination-incomplete\n"
    )
    summary = json.loads((output / "online-review-summary.json").read_text())
    assert summary["review_threads_status"] == "unavailable"
    assert summary["review_threads_error"] == "review-thread-pagination-incomplete"
    assert json.loads((output / "review-threads.json").read_text()) == []


def test_collect_pr_records_unavailable_diff_statistics_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep binary or rename-only PR evidence when derived statistics are unsupported."""
    module = load_collector()
    runner = FakeRunner(statistics_unavailable=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0
    assert (output / "diff.patch").read_bytes() == b"diff --git a/a.py b/a.py\n"
    assert (output / "diffstat.txt").read_text(encoding="utf-8") == "unavailable:command-failed:diff-stat\n"
    assert (output / "numstat.txt").read_text(encoding="utf-8") == "unavailable:command-failed:diff-numstat\n"
    assert json.loads((output / "local-checkout.json").read_text())["head_matches_pr"] is True
    assert not (output / "pr-error.txt").exists()


def test_collect_pr_uses_verified_local_diff_when_review_thread_fetch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recover a fork-style PR from supplemental integration failure through exact local source."""
    module = load_collector()
    runner = FakeRunner(review_threads_failure=True, cross_repository=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0, (output / "pr-error.txt").read_text() if (output / "pr-error.txt").exists() else ""
    assert json.loads((output / "pr.json").read_text())["body"].startswith("Fix checkpoint")
    assert (output / "review-threads-error.txt").read_text() == "github-network:gh-review-threads\n"
    assert (output / "diff.patch").read_bytes() == b"diff --git a/a.py b/a.py\n"
    assert any(argv == ["gh", "pr", "checkout", "17"] for argv, _ in runner.calls)
    assert any(argv == ["git", "diff", "--binary", f"{BASE_OID}...{HEAD_OID}", "--"] for argv, _ in runner.calls)
    assert not any(argv[:3] == ["gh", "pr", "diff"] for argv, _ in runner.calls)
    checkout = json.loads((output / "local-checkout.json").read_text())
    assert checkout["diff_source"] == "verified-local-checkout"
    assert checkout["diff_base_oid"] == BASE_OID
    assert checkout["diff_head_oid"] == HEAD_OID


def test_collect_pr_reuses_already_exact_pr_head_for_local_diff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid a fragile checkout call when the current fork branch already matches PR metadata."""
    module = load_collector()
    runner = FakeRunner(current_head_oid=HEAD_OID, cross_repository=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0
    assert not any(argv[:3] == ["gh", "pr", "checkout"] for argv, _ in runner.calls)
    checkout = json.loads((output / "local-checkout.json").read_text())
    assert checkout["command"] == "not-run: already at expected PR head"
    assert checkout["head_matches_pr"] is True
    assert (output / "diff.patch").read_bytes() == b"diff --git a/a.py b/a.py\n"


def test_collect_pr_checkout_writes_verified_fetch_and_checkout_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bind target refresh and local checkout to PR metadata OIDs without force."""
    module = load_collector()
    runner = FakeRunner()
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0, (output / "pr-error.txt").read_text() if (output / "pr-error.txt").exists() else ""
    target = json.loads((output / "target-branch.json").read_text())
    assert target["local_head"] == BASE_OID
    assert target["base_matches_pr_metadata"] is True
    assert target["expected_base_is_ancestor"] is True
    assert target["base_relation"] == "matches-pr-metadata"
    head = json.loads((output / "pr-head-fetch.json").read_text())
    assert head["local_head"] == HEAD_OID
    assert head["head_matches_pr_metadata"] is True
    checkout = json.loads((output / "local-checkout.json").read_text())
    assert checkout["local_head"] == HEAD_OID
    assert checkout["head_matches_pr"] is True
    assert checkout["command"] == "gh pr checkout 17"
    assert checkout["diff_source"] == "verified-local-checkout"
    assert "no --force was used" in checkout["force_policy"]
    assert all("--force" not in argument for argv, _ in runner.calls for argument in argv)


def test_collect_pr_records_target_branch_divergence_without_rejecting_verified_pr_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Allow historical target divergence while still requiring the exact PR head."""
    module = load_collector()
    runner = FakeRunner(current_base_oid="c" * 40, recorded_base_is_ancestor=False, pr_state="MERGED")
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0
    target = json.loads((output / "target-branch.json").read_text())
    assert target["local_head"] == "c" * 40
    assert target["expected_base_oid"] == BASE_OID
    assert target["base_matches_pr_metadata"] is False
    assert target["expected_base_is_ancestor"] is False
    assert target["base_relation"] == "diverged"
    assert json.loads((output / "local-checkout.json").read_text())["head_matches_pr"] is True


def test_collect_pr_accepts_open_pr_when_target_advanced_from_recorded_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep reviewing an exact PR head after its target branch advances."""
    module = load_collector()
    runner = FakeRunner(current_base_oid="c" * 40)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0, (output / "pr-error.txt").read_text() if (output / "pr-error.txt").exists() else ""
    target = json.loads((output / "target-branch.json").read_text())
    assert target["base_relation"] == "advanced"
    assert target["expected_base_is_ancestor"] is True
    assert json.loads((output / "local-checkout.json").read_text())["head_matches_pr"] is True


def test_collect_pr_rejects_open_pr_when_target_diverged_from_recorded_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed when the fetched target no longer descends from the recorded base."""
    module = load_collector()
    runner = FakeRunner(current_base_oid="c" * 40, recorded_base_is_ancestor=False)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 2
    assert (output / "pr-error.txt").read_text().startswith("target-branch-diverged:")


def test_git_ancestry_probe_rejects_unverifiable_commits() -> None:
    """Keep a Git ancestry error distinct from a proven target divergence."""
    module = load_collector()

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(argv, 128, stdout=b"", stderr=b"unknown revision")

    with pytest.raises(module.CollectionError, match="command-failed:target-branch-ancestry") as error:
        module._git_is_ancestor(runner, 5, BASE_OID, "c" * 40)

    assert error.value.diagnostics == {
        "exit_code": 128,
        "failure_class": "command-failed",
        "label": "target-branch-ancestry",
    }


def test_collect_pr_rejects_unknown_pr_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail closed instead of treating an unrecognized GitHub state as historical evidence."""
    module = load_collector()
    runner = FakeRunner(pr_state="UNKNOWN")
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "unsupported-pr-state\n"


def test_collect_pr_preserves_checkout_started_state_after_checkout_command_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain conservative local-state evidence if checkout may already have changed files."""
    module = load_collector()
    success_runner = FakeRunner()

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[:3] == ["gh", "pr", "checkout"]:
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"checkout failed")
        return success_runner(argv, **kwargs)

    configure_collector(monkeypatch, module, success_runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5, run=runner)

    assert result == 2
    assert json.loads((output / "checkout-state.json").read_text()) == {
        "status": "checkout-command-started",
        "local_state": "changed-or-unknown",
    }
    assert (output / "pr.json").is_file()
    assert (output / "comments.json").is_file()
    assert (output / "review-threads.json").is_file()


def test_collect_pr_checks_out_merged_pr_when_its_named_head_branch_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use GitHub's pull ref and exact SHA check when a historical source branch is deleted."""
    module = load_collector()
    runner = FakeRunner(pr_state="MERGED", named_head_ref_missing=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=True, timeout_seconds=5)

    assert result == 0
    routing = json.loads((output / "pr-routing.json").read_text())
    assert routing["pr_state"] == "MERGED"
    head_fetch = json.loads((output / "pr-head-fetch.json").read_text())
    assert head_fetch["status"] == "fetched"
    checkout = json.loads((output / "local-checkout.json").read_text())
    assert checkout["head_matches_pr"] is True
    assert checkout["command"] == "git checkout --detach refs/remotes/origin/pull/17/head"
    assert not any(argv[:3] == ["git", "fetch", "--no-tags"] and "portable-pr" in argv[-1] for argv, _ in runner.calls)


def test_collect_pr_timeout_is_bounded_and_records_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Convert a stalled external command into the stable collection failure contract."""
    module = load_collector()
    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")

    def timeout(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[:3] == ["gh", "pr", "view"]:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(module.subprocess, "run", timeout)
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=1)

    assert result == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "command-timeout:gh-pr-view\n"


def test_collect_pr_removes_terminal_failure_markers_after_successful_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure a successful retry cannot be mistaken for the previous unavailable review."""
    module = load_collector()
    success_runner = FakeRunner()
    attempts = 0

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal attempts
        if argv[:3] == ["gh", "pr", "view"] and attempts == 0:
            attempts += 1
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"error connecting to api.github.com")
        return success_runner(argv, **kwargs)

    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")
    output = tmp_path / "pr"

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=runner) == 2
    assert (output / "pr-error.txt").is_file()
    assert (output / "command-failure.json").is_file()

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=runner) == 0
    assert not (output / "pr-error.txt").exists()
    assert not (output / "command-failure.json").exists()
    assert (output / "pr.json").is_file()


def test_collect_pr_removes_stale_diagnostic_before_nondiagnostic_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure a later parse failure cannot retain a stale GitHub failure classifier."""
    module = load_collector()
    attempts = 0

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        nonlocal attempts
        if argv[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[:3] == ["gh", "pr", "view"]:
            if attempts == 0:
                attempts += 1
                return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"error connecting to api.github.com")
            return subprocess.CompletedProcess(argv, 0, stdout=b"not-json", stderr=b"")
        raise AssertionError(f"unexpected command: {argv}")

    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")
    output = tmp_path / "pr"

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=runner) == 2
    assert (output / "command-failure.json").is_file()

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=runner) == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "invalid-json:pr-view\n"
    assert not (output / "command-failure.json").exists()


def test_collect_pr_failure_clears_prior_attempt_before_retaining_current_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prevent stale source evidence while retaining diagnostics produced by the failed attempt."""
    module = load_collector()
    output = tmp_path / "pr"
    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=FakeRunner()) == 0
    assert (output / "pr.json").is_file()
    assert (output / "diff.patch").is_file()

    def failing_runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        if argv[:3] == ["gh", "pr", "view"]:
            return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=b"connection reset by peer")
        raise AssertionError(f"unexpected command: {argv}")

    assert module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=failing_runner) == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "github-network:gh-pr-view\n"
    retained = {filename for filename in module.COLLECTOR_EVIDENCE_ARTIFACTS if (output / filename).exists()}
    assert retained == {"status.txt"}


@pytest.mark.parametrize(
    ("argv", "label"),
    [
        (["gh", "pr", "merge", "17", "--merge"], "gh-pr-merge"),
        (["gh", "auth", "status"], "gh-auth-status"),
        (
            [
                "gh",
                "api",
                "graphql",
                "-f",
                "owner=Borda",
                "-f",
                "name=AI-Rig",
                "-F",
                "number=17",
                "-f",
                "query=mutation { closePullRequest(input: {}) { pullRequest { id } } }",
            ],
            "gh-review-threads",
        ),
    ],
)
def test_run_rejects_non_read_only_gh_command(argv: list[str], label: str) -> None:
    """Reject a GitHub CLI command outside the shared read-only boundary."""
    module = load_collector()
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    with pytest.raises(module.CollectionError, match=f"unsafe-gh-command:{label}"):
        module._run(runner, argv, 5, label)

    assert calls == []


def test_run_preserves_classified_gh_failure_details() -> None:
    """Record a transport failure without exposing credentials."""
    module = load_collector()

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=b"",
            stderr=b"error connecting to api.github.com with ghp_exampletoken\n",
        )

    with pytest.raises(module.CollectionError, match="github-network:gh-pr-view") as error:
        module._run(runner, ["gh", "pr", "view", "17", "--json", module.PR_FIELDS], 5, "gh-pr-view")

    assert error.value.diagnostics == {"exit_code": 1, "failure_class": "github-network", "label": "gh-pr-view"}


def test_collect_pr_writes_classified_opaque_failure_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Publish actionable, credential-safe evidence when GitHub collection fails."""
    module = load_collector()

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if argv[:3] == ["git", "status", "--short"]:
            return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout=b"",
            stderr=b"error connecting to api.github.com using github_pat_exampletoken\n",
        )

    monkeypatch.setattr(module.shutil, "which", lambda command: f"/fixture/{command}")
    output = tmp_path / "pr"

    result = module.collect_pr(target="17", output=output, checkout=False, timeout_seconds=5, run=runner)

    assert result == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "github-network:gh-pr-view\n"
    assert json.loads((output / "command-failure.json").read_text(encoding="utf-8")) == {
        "exit_code": 1,
        "failure_class": "github-network",
        "label": "gh-pr-view",
    }


def test_collect_pr_does_not_ship_a_shell_compatibility_wrapper() -> None:
    """Keep the plugin collector surface Python-only across supported platforms."""
    assert not (PLUGIN_ROOT / "shared" / "collect-pr.sh").exists()
