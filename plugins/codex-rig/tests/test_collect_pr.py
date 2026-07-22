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
    specification.loader.exec_module(module)
    return module


def pr_payload() -> dict[str, Any]:
    """Return one complete same-repository PR metadata fixture."""
    return {
        "number": 17,
        "title": "Portable collector",
        "url": "https://github.com/Borda/AI-Rig/pull/17",
        "author": {"login": "contributor"},
        "baseRefName": "main",
        "baseRefOid": BASE_OID,
        "headRefName": "portable-pr",
        "headRefOid": HEAD_OID,
        "headRepository": {"nameWithOwner": "Borda/AI-Rig"},
        "headRepositoryOwner": {"login": "Borda"},
        "isCrossRepository": False,
        "state": "OPEN",
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

    def __init__(self, *, paginated: bool = False, statistics_unavailable: bool = False) -> None:
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.paginated = paginated
        self.statistics_unavailable = statistics_unavailable

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
            stdout = json.dumps(pr_payload()).encode()
        elif argv[:3] == ["gh", "api", "graphql"]:
            stdout = json.dumps(threads_payload(paginated=self.paginated)).encode()
        elif argv[:3] == ["gh", "pr", "diff"]:
            stdout = b"diff --git a/a.py b/a.py\n"
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
            stdout = b""
        elif argv[:2] == ["git", "rev-parse"]:
            reference = argv[2]
            stdout = (HEAD_OID if "portable-pr" in reference or reference == "HEAD" else BASE_OID).encode() + b"\n"
        elif argv[:3] == ["gh", "pr", "checkout"]:
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
        "pr-routing.json",
        "pr.json",
        "review-threads.json",
        "review-threads.raw.json",
        "reviews.json",
        "status.txt",
        "unresolved-review-threads.json",
        "untracked.txt",
    }
    assert (output / "files.txt").read_text(encoding="utf-8") == "a.py\nb.py\n"
    assert json.loads((output / "online-review-summary.json").read_text()) == {
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
    assert routing["local_checkout_command"] == "gh pr checkout https://github.com/Borda/AI-Rig/pull/17"
    assert all(call[1]["timeout"] == 5 for call in runner.calls)


def test_collect_pr_refuses_incomplete_review_thread_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed when the GraphQL response omits later review-thread pages."""
    module = load_collector()
    runner = FakeRunner(paginated=True)
    configure_collector(monkeypatch, module, runner)
    output = tmp_path / "pr"

    result = module.collect_pr(target="", output=output, checkout=False, timeout_seconds=5)

    assert result == 2
    assert (output / "pr-error.txt").read_text(encoding="utf-8") == "review-thread-pagination-incomplete\n"


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
    head = json.loads((output / "pr-head-fetch.json").read_text())
    assert head["local_head"] == HEAD_OID
    assert head["head_matches_pr_metadata"] is True
    checkout = json.loads((output / "local-checkout.json").read_text())
    assert checkout["local_head"] == HEAD_OID
    assert checkout["head_matches_pr"] is True
    assert "no --force was used" in checkout["force_policy"]
    assert all("--force" not in argument for argv, _ in runner.calls for argument in argv)


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


def test_collect_pr_does_not_ship_a_shell_compatibility_wrapper() -> None:
    """Keep the plugin collector surface Python-only across supported platforms."""
    assert not (PLUGIN_ROOT / "shared" / "collect-pr.sh").exists()
