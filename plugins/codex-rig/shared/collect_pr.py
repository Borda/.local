#!/usr/bin/env python3
"""Collect authoritative pull-request evidence and an optional verified local checkout.

## Purpose

Assemble the PR-specific metadata, review threads, patch, Git target/head evidence, and local checkout required before a source review. The bundle makes the authoritative base repository and exact PR head explicit before any reviewer inspects source.

## Scope

It orchestrates one PR evidence recipe and writes its artifact bundle; every GitHub read delegates to ``github_read.py`` and remote mutation is forbidden. With ``--checkout``, it additionally selects the matching local remote, fetches the target/head evidence, and records checkout identity without using forced Git operations.

## Usage

Run ``python collect_pr.py --target <number-or-url> --out <directory> [--checkout]`` from code-review or code-remediate PR mode. Reusing an output directory is supported because the collector removes its own prior evidence before starting a new attempt.

## Used by

The PR code-review/remediation workflows and collector acceptance tests use this module; it is not a general issue or discussion reader. Its review-thread GraphQL query is intentionally limited to the PR identified by the fetched ``pr.json`` payload.

## Outputs

It writes PR metadata, threads, diff/stat files, routing, target/head checks, optional checkout evidence, and classified terminal failure markers. A successful bundle includes files such as ``pr.json``, ``review-threads.json``, ``diff.patch``, ``pr-routing.json``, and checkout identity records when checkout was requested.

## Failure

Missing tools, unsafe GitHub command, failed authenticated evidence, invalid PR data, or checkout mismatch returns ``2`` and blocks source review. On a terminal ``CollectionError``, source-evidence artifacts from the current or prior attempt are cleared, ``pr-error.txt`` is written, and command diagnostics are retained separately when available.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


# Keep this executable helper importable when pytest discovers it as a module.
SHARED_DIRECTORY = Path(__file__).resolve().parent
if str(SHARED_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SHARED_DIRECTORY))

from github_read import GitHubReadError, run_gh_read  # noqa: E402


MAX_OUTPUT_BYTES = 16 * 1024 * 1024
VALID_PR_STATES = frozenset({"OPEN", "MERGED", "CLOSED"})
COLLECTOR_EVIDENCE_ARTIFACTS = (
    "comments.json",
    "checkout-state.json",
    "diff.patch",
    "diffstat.txt",
    "files.txt",
    "local-checkout.json",
    "numstat.txt",
    "online-review-summary.json",
    "pr-head-fetch.json",
    "pr-routing.json",
    "pr.json",
    "remote-selection-error.txt",
    "remote-selection.json",
    "remote.txt",
    "review-threads.raw.json",
    "review-threads.json",
    "reviews.json",
    "status.txt",
    "target-branch.json",
    "unresolved-review-threads.json",
    "untracked.txt",
)
PR_FIELDS = (
    "number,title,url,author,baseRefName,baseRefOid,headRefName,headRefOid,"
    "headRepository,headRepositoryOwner,isCrossRepository,state,isDraft,"
    "reviewDecision,mergeable,comments,reviews,files"
)
GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id isResolved isOutdated path line startLine originalLine originalStartLine diffSide
          comments(first: 100) {
            nodes { id author { login } body url path position originalPosition line originalLine diffHunk createdAt updatedAt }
          }
        }
      }
    }
  }
}
"""
RunCommand = Callable[..., subprocess.CompletedProcess[bytes]]


class CollectionError(RuntimeError):
    """Carry one stable bounded collection failure code."""

    def __init__(self, code: str, *, diagnostics: dict[str, Any] | None = None) -> None:
        """Initialize a stable code with optional credential-opaque metadata."""
        super().__init__(code)
        self.diagnostics = diagnostics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the portable PR collector command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="Artifact directory")
    parser.add_argument("--target", default="", help="PR number, URL, or gh-compatible selector")
    parser.add_argument("--checkout", action="store_true", help="Fetch and update the verified local PR checkout")
    parser.add_argument("--timeout-seconds", type=int, default=60, help="Per-command timeout")
    arguments = parser.parse_args(argv)
    if arguments.timeout_seconds < 1:
        parser.error("--timeout-seconds must be positive")
    return arguments


def _run(run: RunCommand, argv: list[str], timeout: int, label: str, *, input_bytes: bytes | None = None) -> bytes:
    """Run one argv-only command and return bounded stdout bytes."""
    if argv and argv[0] == "gh":
        if input_bytes is not None:
            raise CollectionError(f"unsafe-gh-command:{label}")
        try:
            return run_gh_read(run, argv, timeout=timeout, label=label)
        except GitHubReadError as error:
            raise CollectionError(str(error), diagnostics=error.diagnostics) from error
    try:
        completed = run(
            argv,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            shell=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as error:
        raise CollectionError(f"command-timeout:{label}") from error
    except OSError as error:
        raise CollectionError(f"command-unavailable:{label}") from error
    if len(completed.stdout) > MAX_OUTPUT_BYTES or len(completed.stderr) > MAX_OUTPUT_BYTES:
        raise CollectionError(f"command-output-oversized:{label}")
    if completed.returncode != 0:
        failure_class = "command-failed"
        raise CollectionError(
            f"{failure_class}:{label}",
            diagnostics={
                "exit_code": completed.returncode,
                "failure_class": failure_class,
                "label": label,
            },
        )
    return completed.stdout


def _json(payload: bytes, label: str) -> dict[str, Any]:
    """Decode one bounded UTF-8 JSON object."""
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CollectionError(f"invalid-json:{label}") from error
    if not isinstance(value, dict):
        raise CollectionError(f"invalid-json:{label}")
    return value


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic human-readable JSON artifact."""
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _derived_diff_output(
    run: RunCommand,
    argv: list[str],
    timeout: int,
    label: str,
    diff: bytes,
) -> bytes:
    """Return derived diff output or record its non-applicable command failure."""
    try:
        return _run(run, argv, timeout, label, input_bytes=diff)
    except CollectionError as error:
        if str(error) != f"command-failed:{label}":
            raise
        return f"unavailable:{error}\n".encode()


def _head_repository(payload: dict[str, Any]) -> str:
    """Normalize GitHub's head-repository object variants."""
    value = payload.get("headRepository")
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("nameWithOwner", "name_with_owner"):
        candidate = value.get(key)
        if isinstance(candidate, str) and "/" in candidate:
            return candidate
    name = value.get("name")
    owner: object = value.get("owner", payload.get("headRepositoryOwner"))
    if isinstance(owner, dict):
        owner = owner.get("login") or owner.get("name")
    return f"{owner}/{name}" if isinstance(owner, str) and isinstance(name, str) else ""


def _review_artifacts(
    payload: dict[str, Any],
    thread_payload: dict[str, Any],
    output: Path,
    *,
    base_repo: str,
    base_host: str,
) -> dict[str, Any]:
    """Validate online evidence and emit normalized review artifacts."""
    try:
        container = thread_payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        threads = container.get("nodes") or []
        page_info = container.get("pageInfo") or {}
    except (KeyError, TypeError) as error:
        raise CollectionError("invalid-json:review-threads") from error
    if not isinstance(threads, list) or not isinstance(page_info, dict):
        raise CollectionError("invalid-json:review-threads")
    if page_info.get("hasNextPage"):
        raise CollectionError("review-thread-pagination-incomplete")
    comments = payload.get("comments") or []
    reviews = payload.get("reviews") or []
    files = payload.get("files") or []
    if not isinstance(comments, list) or not isinstance(reviews, list) or not isinstance(files, list):
        raise CollectionError("invalid-json:pr-view")
    file_names = sorted(item["path"] for item in files if isinstance(item, dict) and isinstance(item.get("path"), str))
    unresolved = [item for item in threads if isinstance(item, dict) and item.get("isResolved") is False]
    active = [item for item in unresolved if item.get("isOutdated") is not True]
    outdated = [item for item in unresolved if item.get("isOutdated") is True]
    summary = {
        "review_thread_count": len(threads),
        "unresolved_review_thread_count": len(unresolved),
        "active_unresolved_review_thread_count": len(active),
        "outdated_unresolved_review_thread_count": len(outdated),
        "top_level_comment_count": len(comments),
        "review_count": len(reviews),
    }
    pr_state = payload.get("state")
    if pr_state not in VALID_PR_STATES:
        raise CollectionError("unsupported-pr-state")
    head_repo = _head_repository(payload)
    routing = {
        "base_repo": base_repo,
        "base_host": base_host,
        "base_identity_source": "pr_url",
        "pr_number": payload.get("number"),
        "pr_url": payload.get("url"),
        "pr_state": pr_state,
        "base_ref": payload.get("baseRefName"),
        "base_oid": payload.get("baseRefOid"),
        "head_ref": payload.get("headRefName"),
        "head_oid": payload.get("headRefOid"),
        "head_repo": head_repo,
        "is_cross_repository": bool(payload.get("isCrossRepository")),
        "same_repo": bool(head_repo and base_repo and head_repo.casefold() == base_repo.casefold()),
        "local_checkout_required": True,
        "local_checkout_command": f"gh pr checkout {payload.get('url')}",
        "force_policy": "never pass --force to git or gh automatically; stop and ask the user first",
        "source_policy": "inspect local checkout; use gh only for PR metadata, diff, and review-thread evidence",
    }
    (output / "files.txt").write_text("".join(f"{name}\n" for name in file_names), encoding="utf-8")
    _write_json(output / "comments.json", comments)
    _write_json(output / "reviews.json", reviews)
    _write_json(output / "review-threads.json", threads)
    _write_json(output / "unresolved-review-threads.json", unresolved)
    _write_json(output / "online-review-summary.json", summary)
    _write_json(output / "pr-routing.json", routing)
    return routing


def _selector(
    run: RunCommand,
    timeout: int,
    script: Path,
    url: str,
    *,
    identity_only: bool,
) -> dict[str, Any]:
    """Resolve repository identity or matching local remote through the packaged selector."""
    argv = [sys.executable, str(script), "--expected-url", url]
    if identity_only:
        argv.append("--identity-only")
    return _json(_run(run, argv, timeout, "select-git-remote"), "select-git-remote")


def _checkout(
    run: RunCommand,
    timeout: int,
    output: Path,
    payload: dict[str, Any],
    routing: dict[str, Any],
    selector: Path,
) -> None:
    """Fetch verified target/head refs and update the local PR checkout without force."""
    url = routing.get("pr_url")
    number = routing.get("pr_number")
    base_ref = routing.get("base_ref")
    base_oid = routing.get("base_oid")
    head_ref = routing.get("head_ref")
    head_oid = routing.get("head_oid")
    if not all(isinstance(value, str) and value for value in (url, base_ref, base_oid, head_oid)):
        raise CollectionError("missing-pr-checkout-identity")
    remote = _selector(run, timeout, selector, url, identity_only=False)
    remote_name = remote.get("remote")
    remote_url = remote.get("remote_url")
    if not isinstance(remote_name, str) or not isinstance(remote_url, str):
        raise CollectionError("missing-matching-git-remote-for-pr-base")
    _write_json(output / "remote-selection.json", remote)
    (output / "remote-selection-error.txt").write_bytes(b"")
    (output / "remote.txt").write_text(f"{remote_name} {remote_url}\n", encoding="utf-8")

    base_remote_ref = f"refs/remotes/{remote_name}/{base_ref}"
    _run(
        run,
        ["git", "fetch", "--no-tags", remote_name, f"{base_ref}:{base_remote_ref}"],
        timeout,
        "target-branch-fetch",
    )
    base_local = _run(run, ["git", "rev-parse", base_remote_ref], timeout, "target-branch-rev-parse").decode().strip()
    target = {
        "status": "fetched",
        "remote": remote_name,
        "remote_url": remote_url,
        "base_ref": base_ref,
        "remote_ref": base_remote_ref,
        "local_head": base_local,
        "expected_base_oid": base_oid,
        "base_matches_pr_metadata": base_local == base_oid,
        "base_relation": "matches-pr-metadata" if base_local == base_oid else "advanced-or-diverged",
        "command": f"git fetch --no-tags {remote_name} {base_ref}:{base_remote_ref}",
        "source_policy": "target branch is refreshed before PR conflict or review-item resolution; historical PRs may record divergence from the PR's saved base SHA",
    }
    _write_json(output / "target-branch.json", target)
    if routing.get("pr_state") == "OPEN" and base_local != base_oid:
        raise CollectionError(f"target-branch-oid-mismatch:{base_local}:{base_oid}")

    if (
        routing.get("same_repo") is True
        and routing.get("pr_state") == "OPEN"
        and isinstance(head_ref, str)
        and head_ref
    ):
        head_remote_ref = f"refs/remotes/{remote_name}/{head_ref}"
        _run(
            run,
            ["git", "fetch", "--no-tags", remote_name, f"{head_ref}:{head_remote_ref}"],
            timeout,
            "pr-head-fetch",
        )
        head_local = _run(run, ["git", "rev-parse", head_remote_ref], timeout, "pr-head-rev-parse").decode().strip()
        head = {
            "status": "fetched",
            "remote": remote_name,
            "head_ref": head_ref,
            "remote_ref": head_remote_ref,
            "local_head": head_local,
            "expected_head_oid": head_oid,
            "head_matches_pr_metadata": head_local == head_oid,
            "command": f"git fetch --no-tags {remote_name} {head_ref}:{head_remote_ref}",
            "source_policy": "PR branch is refreshed before local checkout and conflict analysis",
        }
        _write_json(output / "pr-head-fetch.json", head)
        if head_local != head_oid:
            raise CollectionError(f"pr-head-oid-mismatch:{head_local}:{head_oid}")
    elif routing.get("pr_state") != "OPEN" and isinstance(number, int):
        historical_head_ref = f"refs/remotes/{remote_name}/pull/{number}/head"
        _run(
            run,
            ["git", "fetch", "--no-tags", remote_name, f"refs/pull/{number}/head:{historical_head_ref}"],
            timeout,
            "historical-pr-head-fetch",
        )
        head_local = (
            _run(run, ["git", "rev-parse", historical_head_ref], timeout, "historical-pr-head-rev-parse")
            .decode()
            .strip()
        )
        head = {
            "status": "fetched",
            "remote": remote_name,
            "head_ref": historical_head_ref,
            "local_head": head_local,
            "expected_head_oid": head_oid,
            "head_matches_pr_metadata": head_local == head_oid,
            "command": f"git fetch --no-tags {remote_name} refs/pull/{number}/head:{historical_head_ref}",
            "source_policy": "historical PR head is refreshed from GitHub's pull ref and verified against metadata before detached local checkout",
        }
        _write_json(output / "pr-head-fetch.json", head)
        if head_local != head_oid:
            raise CollectionError(f"historical-pr-head-oid-mismatch:{head_local}:{head_oid}")
    else:
        _write_json(
            output / "pr-head-fetch.json",
            {
                "status": "skipped",
                "same_repo": routing.get("same_repo"),
                "head_ref": head_ref,
                "reason": "cross-repository PR head is refreshed by gh pr checkout",
            },
        )

    dirty = _run(
        run,
        ["git", "status", "--short", "--untracked-files=no"],
        timeout,
        "tracked-worktree-status",
    )
    if dirty.strip():
        raise CollectionError("dirty-tracked-worktree-before-pr-checkout")
    # gh can update local refs or the worktree before it reports an error, so preserve conservative state first.
    _write_json(
        output / "checkout-state.json",
        {"status": "checkout-command-started", "local_state": "changed-or-unknown"},
    )
    checkout_argv = ["gh", "pr", "checkout", url]
    if routing.get("pr_state") != "OPEN" and isinstance(number, int):
        checkout_argv = ["git", "checkout", "--detach", f"refs/remotes/{remote_name}/pull/{number}/head"]
    routing["local_checkout_command"] = " ".join(checkout_argv)
    _write_json(output / "pr-routing.json", routing)
    _run(run, checkout_argv, timeout, "local-pr-checkout")
    _write_json(
        output / "checkout-state.json",
        {"status": "checkout-command-succeeded-unverified", "local_state": "changed-or-unknown"},
    )
    branch = _run(run, ["git", "branch", "--show-current"], timeout, "checkout-branch").decode().strip()
    local_head = _run(run, ["git", "rev-parse", "HEAD"], timeout, "checkout-head").decode().strip()
    matches = local_head == head_oid
    _write_json(
        output / "local-checkout.json",
        {
            "status": "checked-out",
            "pr_number": number,
            "pr_url": url,
            "local_branch": branch,
            "local_head": local_head,
            "expected_head": head_oid,
            "head_matches_pr": matches,
            "command": " ".join(checkout_argv),
            "target_branch_artifact": "target-branch.json",
            "pr_head_fetch_artifact": "pr-head-fetch.json",
            "force_policy": "no --force was used; ask the user before any forced checkout",
            "source_policy": "local checkout is authoritative for code inspection and edits",
        },
    )
    if not matches:
        raise CollectionError("local-checkout-head-mismatch")


def _clear_collector_artifacts(output: Path) -> None:
    """Remove this collector's prior evidence so one output directory never mixes attempts."""
    for filename in (*COLLECTOR_EVIDENCE_ARTIFACTS, "command-failure.json", "pr-error.txt"):
        (output / filename).unlink(missing_ok=True)


def collect_pr(
    *,
    target: str,
    output: Path,
    checkout: bool,
    timeout_seconds: int,
    run: RunCommand | None = None,
) -> int:
    """Collect one PR context pack and optionally update its verified checkout."""
    output.mkdir(parents=True, exist_ok=True)
    _clear_collector_artifacts(output)
    (output / "pr-target.txt").write_text(f"{target.strip() or 'current-branch-pr'}\n", encoding="utf-8")
    command_runner = subprocess.run if run is None else run
    try:
        for command in ("git", "gh"):
            if shutil.which(command) is None:
                raise CollectionError(f"missing-command:{command}")
        try:
            status = _run(command_runner, ["git", "status", "--short"], timeout_seconds, "git-status")
        except CollectionError:
            status = b""
        (output / "status.txt").write_bytes(status)
        selector = Path(__file__).resolve().with_name("select-git-remote.py")
        pr_args = [target] if target else []
        payload_bytes = _run(
            command_runner,
            ["gh", "pr", "view", *pr_args, "--json", PR_FIELDS],
            timeout_seconds,
            "gh-pr-view",
        )
        payload = _json(payload_bytes, "pr-view")
        url = payload.get("url")
        number = payload.get("number")
        if not isinstance(url, str) or not url or not isinstance(number, int):
            raise CollectionError("missing-pr-identity")
        (output / "pr.json").write_bytes(payload_bytes)
        identity = _selector(command_runner, timeout_seconds, selector, url, identity_only=True)
        base_repo = identity.get("repository")
        base_host = identity.get("host")
        if not isinstance(base_repo, str) or "/" not in base_repo or not isinstance(base_host, str):
            raise CollectionError("invalid-pr-base-url")
        owner, repository = base_repo.split("/", 1)
        threads_bytes = _run(
            command_runner,
            [
                "gh",
                "api",
                "graphql",
                "-f",
                f"owner={owner}",
                "-f",
                f"name={repository}",
                "-F",
                f"number={number}",
                "-f",
                f"query={GRAPHQL_QUERY}",
            ],
            timeout_seconds,
            "gh-review-threads",
        )
        (output / "review-threads.raw.json").write_bytes(threads_bytes)
        diff = _run(command_runner, ["gh", "pr", "diff", *pr_args], timeout_seconds, "gh-pr-diff")
        (output / "diff.patch").write_bytes(diff)
        routing = _review_artifacts(
            payload,
            _json(threads_bytes, "review-threads"),
            output,
            base_repo=base_repo,
            base_host=base_host,
        )
        (output / "diffstat.txt").write_bytes(
            _derived_diff_output(
                command_runner,
                ["git", "apply", "--stat"],
                timeout_seconds,
                "diff-stat",
                diff,
            )
        )
        (output / "numstat.txt").write_bytes(
            _derived_diff_output(
                command_runner,
                ["git", "apply", "--numstat"],
                timeout_seconds,
                "diff-numstat",
                diff,
            )
        )
        (output / "untracked.txt").write_bytes(b"")
        if checkout:
            _checkout(command_runner, timeout_seconds, output, payload, routing, selector)
        return 0
    except CollectionError as error:
        # Terminal failures must contain no source evidence from a prior or partial attempt.
        checkout_state = (
            (output / "checkout-state.json").read_bytes() if (output / "checkout-state.json").is_file() else None
        )
        _clear_collector_artifacts(output)
        if checkout_state is not None:
            (output / "checkout-state.json").write_bytes(checkout_state)
        if error.diagnostics is not None:
            _write_json(output / "command-failure.json", error.diagnostics)
        (output / "pr-error.txt").write_text(f"{error}\n", encoding="utf-8")
        return 2


def main(argv: list[str] | None = None) -> int:
    """Run the command-line collector."""
    arguments = parse_args(argv)
    return collect_pr(
        target=arguments.target,
        output=arguments.out,
        checkout=arguments.checkout,
        timeout_seconds=arguments.timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
