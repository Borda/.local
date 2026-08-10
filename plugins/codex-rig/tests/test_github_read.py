"""Acceptance checks for the shared GitHub read-only transport boundary."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE = PLUGIN_ROOT / "shared" / "github_read.py"


def load_reader() -> ModuleType:
    """Load the standalone GitHub reader without package installation."""
    assert MODULE.is_file(), MODULE
    specification = importlib.util.spec_from_file_location("codex_rig_github_read", MODULE)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "issue", "view", "17", "--json", "title"],
        ["gh", "release", "view", "v1.2.3", "--json", "name"],
        ["gh", "repo", "view", "Borda/AI-Rig", "--json", "name"],
    ],
)
def test_run_gh_read_allows_view_commands(argv: list[str]) -> None:
    """Permit GitHub CLI view commands without widening mutating commands."""
    module = load_reader()
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"{}", stderr=b"")

    assert module.run_gh_read(runner, argv, timeout=5, label="gh-view") == b"{}"
    assert calls == [argv]


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "auth", "status"],
        ["gh", "pr", "merge", "17"],
        ["gh", "pr", "checkout", "--detach", "17"],
        ["gh", "issue", "view", "17", "--web"],
        ["gh", "issue", "view", "17", "--web=true"],
        ["gh", "issue", "view", "17", "-w=true"],
        ["gh", "api", "/repos/Borda/AI-Rig/issues", "--method", "POST"],
        ["gh", "api", "graphql", "-f", "query=mutation { closeIssue(input: {}) { issue { id } } }"],
    ],
)
def test_run_gh_read_rejects_non_read_only_commands(argv: list[str]) -> None:
    """Reject credential inspection, mutations, and browser-opening side effects."""
    module = load_reader()
    calls: list[list[str]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    with pytest.raises(module.GitHubReadError, match="unsafe-gh-command:unsafe"):
        module.run_gh_read(runner, argv, timeout=5, label="unsafe")

    assert calls == []


def test_run_gh_read_allows_graphql_query_but_not_mutation() -> None:
    """Permit a GraphQL query even though GitHub transports it with POST."""
    module = load_reader()

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, stdout=b'{"data": {}}', stderr=b"")

    query = ["gh", "api", "graphql", "-f", "query=query { viewer { login } }"]
    assert module.run_gh_read(runner, query, timeout=5, label="graphql") == b'{"data": {}}'


def test_default_gh_transport_rejects_oversized_output_without_returning_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep production CLI reads bounded before response bytes enter normal result handling."""
    module = load_reader()
    monkeypatch.setattr(module, "MAX_OUTPUT_BYTES", 8)

    with pytest.raises(module.GitHubReadError, match="command-output-oversized"):
        module._run_default_gh_command([sys.executable, "-c", "import sys; sys.stdout.write('x' * 9)"], timeout=5)


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "api", "/repos/Borda/AI-Rig/issues/17"],
        ["gh", "api", "/repos/Borda/AI-Rig/issues/17", "--method", "GET"],
    ],
)
def test_run_gh_read_allows_rest_get_commands(argv: list[str]) -> None:
    """Allow REST GET requests through the shared read boundary."""
    module = load_reader()

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 0, stdout=b"{}", stderr=b"")

    assert module.run_gh_read(runner, argv, timeout=5, label="rest-get") == b"{}"


def test_read_with_fallback_uses_public_https_get_without_gh_credentials() -> None:
    """Use the public API only after the preferred GitHub CLI is unavailable."""
    module = load_reader()
    requested: list[tuple[str, str]] = []

    def unavailable(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise OSError("gh not installed")

    class Response(io.BytesIO):
        """Provide the context-manager protocol expected from urllib responses."""

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def open_url(request: Any, *, timeout: int) -> Response:
        requested.append((request.full_url, request.get_method()))
        return Response(b'{"number": 17}')

    payload, transport = module.read_with_fallback(
        unavailable,
        ["gh", "issue", "view", "17", "--json", "title"],
        timeout=5,
        label="gh-issue-view",
        fallback_url="https://api.github.com/repos/Borda/AI-Rig/issues/17",
        open_url=open_url,
    )

    assert payload == b'{"number": 17}'
    assert transport == "public-https-fallback"
    assert requested == [("https://api.github.com/repos/Borda/AI-Rig/issues/17", "GET")]


def test_read_with_fallback_rejects_non_github_url() -> None:
    """Keep fallback requests limited to the public GitHub API host."""
    module = load_reader()

    def unavailable(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise OSError("gh not installed")

    with pytest.raises(module.GitHubReadError, match="unsafe-github-fallback-url:gh-issue-view"):
        module.read_with_fallback(
            unavailable,
            ["gh", "issue", "view", "17", "--json", "title"],
            timeout=5,
            label="gh-issue-view",
            fallback_url="https://example.invalid/metadata",
        )


@pytest.mark.parametrize(
    "argv",
    [
        ["gh", "evil", "view", "17"],
        ["gh", "auth", "view"],
        ["gh", "api", "graphql", "-F", "query=@/private/secret"],
        ["gh", "api", "/repos/Borda/AI-Rig/issues", "-F", "body=@/private/secret"],
    ],
)
def test_run_gh_read_rejects_extensions_and_file_backed_fields(argv: list[str]) -> None:
    """Prevent extensions or field expansion from escaping the read-only boundary."""
    module = load_reader()

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise AssertionError("unsafe command must not run")

    with pytest.raises(module.GitHubReadError, match="unsafe-gh-command:unsafe"):
        module.run_gh_read(runner, argv, timeout=5, label="unsafe")


def test_public_fallback_rejects_tokenized_url_and_normalizes_transport_error() -> None:
    """Keep fallback unauthenticated and never surface transport detail in its failure."""
    module = load_reader()

    def unavailable(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise OSError("gh unavailable")

    with pytest.raises(module.GitHubReadError, match="unsafe-github-fallback-url:gh-issue-view"):
        module.read_with_fallback(
            unavailable,
            ["gh", "issue", "view", "17"],
            timeout=5,
            label="gh-issue-view",
            fallback_url="https://api.github.com/repos/Borda/AI-Rig/issues/17?access_token=secret",
        )

    def offline(*args: Any, **kwargs: Any) -> None:
        raise OSError("https://api.github.com/repos/Borda/AI-Rig/issues/17?token=secret")

    with pytest.raises(module.GitHubReadError, match="github-network:gh-issue-view") as error:
        module.read_with_fallback(
            unavailable,
            ["gh", "issue", "view", "17"],
            timeout=5,
            label="gh-issue-view",
            fallback_url="https://api.github.com/repos/Borda/AI-Rig/issues/17",
            open_url=offline,
        )

    assert "token" not in str(error.value)


@pytest.mark.parametrize(
    "stderr",
    [
        b"could not resolve host: api.github.com",
        b"dial tcp: lookup api.github.com: no such host",
        b"temporary failure in name resolution",
    ],
)
def test_dns_failures_enable_public_last_resort_transport(stderr: bytes) -> None:
    """Classify common GitHub CLI DNS failures as network and use public fallback."""
    module = load_reader()

    def unavailable(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=stderr)

    class Response(io.BytesIO):
        """Provide the context-manager protocol expected from urllib responses."""

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *args: object) -> None:
            self.close()

    def open_url(request: Any, *, timeout: int) -> Response:
        assert request.get_method() == "GET"
        return Response(b'{"number": 17}')

    payload, transport = module.read_with_fallback(
        unavailable,
        ["gh", "issue", "view", "17"],
        timeout=5,
        label="gh-issue-view",
        fallback_url="https://api.github.com/repos/Borda/AI-Rig/issues/17",
        open_url=open_url,
    )

    assert module.github_failure_class(stderr) == "github-network"
    assert payload == b'{"number": 17}'
    assert transport == "public-https-fallback"


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        (b"run gh auth login to authenticate", "github-auth"),
        (b"HTTP 401: authentication required", "github-auth"),
        (b"request requires authentication", "github-auth"),
        (b"context deadline exceeded", "github-network"),
        (b"read: connection reset by peer", "github-network"),
        (b"failed to connect to api.github.com port 443", "github-network"),
        (b"Client.Timeout exceeded while awaiting headers", "github-network"),
        (b"oauth token has expired", "github-auth"),
    ],
)
def test_gh_failure_classifies_common_auth_and_transport_diagnostics(stderr: bytes, expected: str) -> None:
    """Route opaque CLI diagnostics to the safe recovery category without retaining them."""
    module = load_reader()

    assert module.github_failure_class(stderr) == expected


def test_read_with_fallback_preserves_gh_permission_failure() -> None:
    """Do not bypass an authenticated GitHub permission decision with public HTTPS."""
    module = load_reader()
    calls: list[object] = []

    def denied(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 1, stdout=b"", stderr=b"resource not accessible")

    def open_url(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))
        raise AssertionError("public fallback must not run after a permission failure")

    with pytest.raises(module.GitHubReadError, match="github-permission:gh-issue-view"):
        module.read_with_fallback(
            denied,
            ["gh", "issue", "view", "17", "--json", "title"],
            timeout=5,
            label="gh-issue-view",
            fallback_url="https://api.github.com/repos/Borda/AI-Rig/issues/17",
            open_url=open_url,
        )

    assert calls == []
