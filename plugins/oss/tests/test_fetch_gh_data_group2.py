"""Tests for ``bin/fetch_gh_data_group2.py``.

Arg-validation tests run without any subprocess calls. The happy-path
and decode tests monkeypatch ``subprocess.run`` and ``which`` so no
real ``gh`` invocation occurs.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

import fetch_gh_data_group2 as fgd


class _FakeCompleted:
    """Minimal stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, returncode: int = 0, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _b64(text: str) -> str:
    """Helper: encode UTF-8 ``text`` as base64 (no trailing newline)."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# --- arg validation ---------------------------------------------------------


def test_missing_owner_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """No ``--owner`` → exit 1 with '--owner required' on stderr."""
    rc = fgd.main(
        [
            "--repo",
            "repo",
            "--default-branch",
            "main",
            "--data-file",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    assert "--owner required" in capsys.readouterr().err


def test_missing_repo_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """``--owner`` but no ``--repo`` → exit 1 with '--repo required' on stderr."""
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--default-branch",
            "main",
            "--data-file",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    assert "--repo required" in capsys.readouterr().err


def test_missing_default_branch_exits_1(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """No ``--default-branch`` → exit 1 with '--default-branch required' on stderr."""
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--repo",
            "repo",
            "--data-file",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    assert "--default-branch required" in capsys.readouterr().err


def test_missing_data_file_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    """No ``--data-file`` → exit 1 with '--data-file required' on stderr."""
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--repo",
            "repo",
            "--default-branch",
            "main",
        ]
    )
    assert rc == 1
    assert "--data-file required" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("owner", "repo", "branch", "needle"),
    [
        pytest.param("../evil", "repo", "main", "--owner must match", id="owner-traversal"),
        pytest.param("owner", "../evil", "main", "--repo must match", id="repo-traversal"),
        pytest.param("owner", "repo", "..", "--default-branch must match", id="branch-traversal"),
        pytest.param("owner", "repo", "a/../b", "--default-branch must match", id="branch-embedded-traversal"),
    ],
)
def test_path_traversal_rejected(
    owner: str,
    repo: str,
    branch: str,
    needle: str,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """Path-traversal patterns in identifier args → exit 1 with regex hint on stderr."""
    rc = fgd.main(
        [
            "--owner",
            owner,
            "--repo",
            repo,
            "--default-branch",
            branch,
            "--data-file",
            str(tmp_path / "out.jsonl"),
        ]
    )
    assert rc == 1
    assert needle in capsys.readouterr().err


# --- pure helpers -----------------------------------------------------------


def test_decode_b64_roundtrip() -> None:
    """``_decode_b64`` round-trips arbitrary UTF-8 text."""
    assert fgd._decode_b64(_b64("hello world\nline 2")) == "hello world\nline 2"


def test_decode_b64_empty_input_returns_empty() -> None:
    """Empty raw string short-circuits to empty result."""
    assert fgd._decode_b64("") == ""


def test_decode_b64_invalid_returns_empty() -> None:
    """Non-base64 garbage yields empty string (no exception)."""
    assert fgd._decode_b64("!!!definitely-not-base64$$$") == ""


def test_validate_args_happy_path() -> None:
    """All valid args → ``None``."""
    assert fgd._validate_args("owner", "repo", "main", "/tmp/x.jsonl") is None


def test_validate_args_slash_in_branch_allowed() -> None:
    """Branch may contain ``/`` (e.g. ``release/1.x``)."""
    assert fgd._validate_args("o", "r", "release/1.x", "/tmp/x.jsonl") is None


# --- happy-path with mocked subprocess --------------------------------------


def _stub_gh_run(payload_map: dict[str, str]):
    """Build a ``subprocess.run`` stub that maps full api-path → stdout.

    Args:
        payload_map: Mapping from exact api path suffix to stdout payload.
            Match is suffix-based — first matching key wins; unmatched
            calls return rc=1 + empty (simulates 404).
    """

    # Order keys longest-first so more-specific paths (e.g.
    # ``/contents/.github/CODEOWNERS``) match before less-specific
    # prefixes (``/contents/.github``).
    ordered_keys = sorted(payload_map, key=len, reverse=True)

    def _run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        # cmd = [gh_path, "api", api_path, "--jq", expr?]
        api_path = cmd[2] if len(cmd) >= 3 else ""
        for needle in ordered_keys:
            if api_path.endswith(needle):
                return _FakeCompleted(returncode=0, stdout=payload_map[needle])
        return _FakeCompleted(returncode=1, stdout="")

    return _run


def test_happy_path_writes_jsonl_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mocked gh returning README + .github/ listing + CODEOWNERS → matching JSONL records appended."""
    payloads = {
        "/readme": _b64("# Hello\n"),
        # `.content` jq extracts the inline base64 — stub returns it directly.
        "/contents/CONTRIBUTING.md": _b64("Contributing guide.\n"),
        "/contents/.github": json.dumps(["CODEOWNERS", "workflows"]),
        "/contents/.github/CODEOWNERS": _b64("* @owner\n"),
        # branches/main/protection returns full JSON, no jq filter
        "/branches/main/protection": json.dumps({"required_status_checks": {"strict": True}}),
        # workflows listing
        "/contents/.github/workflows": json.dumps(["ci.yml"]),
        "/contents/.github/workflows/ci.yml": _b64("name: ci\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n"),
        # dependabot config — no jq, raw JSON returned
        "/contents/.github/dependabot.yml": json.dumps({"name": "dependabot.yml", "type": "file"}),
    }
    monkeypatch.setattr(fgd.subprocess, "run", _stub_gh_run(payloads))
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    data_file = tmp_path / "out.jsonl"
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--repo",
            "repo",
            "--default-branch",
            "main",
            "--data-file",
            str(data_file),
        ]
    )
    assert rc == 0
    assert data_file.exists()
    lines = data_file.read_text(encoding="utf-8").strip().splitlines()
    records = [json.loads(line) for line in lines]
    types = {rec["type"] for rec in records}
    assert "readme_content" in types
    assert "contributing_text" in types
    assert "github_dir" in types
    assert "codeowners_text" in types
    assert "branch_protection" in types
    assert "workflows_list" in types
    assert "workflow_files" in types
    assert "dependabot_config" in types
    # README content decoded correctly
    readme = next(rec for rec in records if rec["type"] == "readme_content")
    assert readme["data"] == "# Hello\n"
    # CODEOWNERS records source path
    co = next(rec for rec in records if rec["type"] == "codeowners_text")
    assert co["source"] == ".github/CODEOWNERS"
    assert co["data"] == "* @owner\n"
    # branch_protection echoes branch name
    bp = next(rec for rec in records if rec["type"] == "branch_protection")
    assert bp["branch"] == "main"
    # workflow_files concatenation includes per-workflow header
    wf = next(rec for rec in records if rec["type"] == "workflow_files")
    assert "--- workflow: ci.yml ---" in wf["data"]
    assert "name: ci" in wf["data"]


def test_all_404s_writes_no_records(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """All gh calls return rc=1 (404) → no records written, exit 0."""
    monkeypatch.setattr(
        fgd.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(returncode=1, stdout=""),
    )
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    data_file = tmp_path / "out.jsonl"
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--repo",
            "repo",
            "--default-branch",
            "main",
            "--data-file",
            str(data_file),
        ]
    )
    assert rc == 0
    # No records appended → file never opened for write; absent or empty both fine.
    if data_file.exists():
        assert data_file.read_text(encoding="utf-8") == ""


def test_codeowners_fallback_to_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``.github/CODEOWNERS`` 404 → falls back to root ``CODEOWNERS`` and records ``source=CODEOWNERS``."""

    def _run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        api_path = cmd[2] if len(cmd) >= 3 else ""
        if api_path.endswith(".github/CODEOWNERS"):
            return _FakeCompleted(returncode=1, stdout="")
        if api_path.endswith("/contents/CODEOWNERS"):
            return _FakeCompleted(returncode=0, stdout=_b64("* @root-owner\n"))
        return _FakeCompleted(returncode=1, stdout="")

    monkeypatch.setattr(fgd.subprocess, "run", _run)
    monkeypatch.setattr(fgd, "which", lambda _: "/fake/gh")
    data_file = tmp_path / "out.jsonl"
    rc = fgd.main(
        [
            "--owner",
            "owner",
            "--repo",
            "repo",
            "--default-branch",
            "main",
            "--data-file",
            str(data_file),
        ]
    )
    assert rc == 0
    records = [json.loads(line) for line in data_file.read_text(encoding="utf-8").splitlines() if line]
    co = [rec for rec in records if rec["type"] == "codeowners_text"]
    assert len(co) == 1
    assert co[0]["source"] == "CODEOWNERS"
    assert co[0]["data"] == "* @root-owner\n"


def test_gh_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``which`` returns None → FileNotFoundError propagates."""
    monkeypatch.setattr(fgd, "which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="gh"):
        fgd.main(
            [
                "--owner",
                "owner",
                "--repo",
                "repo",
                "--default-branch",
                "main",
                "--data-file",
                str(tmp_path / "out.jsonl"),
            ]
        )
