"""Deterministic candidate package builder contract.

Covers the builder CLI contract the install probes depend on, byte-for-byte determinism,
manifest-pair validation, and payload closure (no source-tree references, no
symlinks, no case collisions, no default ``skills/`` or ``hooks/hooks.json``).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_BUILDER = _PLUGIN_ROOT / "scripts" / "build_package.py"
if str(_BUILDER.parent) not in sys.path:
    sys.path.insert(0, str(_BUILDER.parent))

import build_package as builder  # noqa: E402  (needs the scripts path insert above)


def _run_builder(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the builder CLI under the current interpreter."""
    return subprocess.run(
        [sys.executable, str(_BUILDER), *args],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.fixture(scope="module")
def candidate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the candidate once via the CLI for read-only inspection."""
    out = tmp_path_factory.mktemp("candidate")
    result = _run_builder("--out", str(out))
    assert result.returncode == 0, result.stderr
    return out


# --- CLI contract ----------------------------------------------------------


def test_build_exits_zero_and_writes_manifest(candidate: Path) -> None:
    manifest = json.loads((candidate / "package-manifest.json").read_text())
    assert manifest["name"] == "codemap-py"
    assert manifest["version"] == "0.25.0-rc1"
    assert len(manifest["files"]) >= 1


def test_check_flag_reports_deterministic(candidate: Path) -> None:
    result = _run_builder("--out", str(candidate), "--check")
    assert result.returncode == 0, result.stderr


# --- determinism -----------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert _run_builder("--out", str(first)).returncode == 0
    assert _run_builder("--out", str(second)).returncode == 0
    assert builder._tree_bytes(first) == builder._tree_bytes(second)


# --- manifest-pair validation (plan §8.1) ----------------------------------


def test_manifest_pair_shares_identity(candidate: Path) -> None:
    claude = json.loads((candidate / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((candidate / ".codex-plugin" / "plugin.json").read_text())
    assert claude["name"] == codex["name"] == "codemap-py"
    assert claude["version"] == codex["version"] == "0.25.0-rc1"


def test_manifest_pair_has_identical_description_and_author(candidate: Path) -> None:
    """description + author are present and identical across both manifests (validate --strict)."""
    claude = json.loads((candidate / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((candidate / ".codex-plugin" / "plugin.json").read_text())
    assert claude["description"] and claude["description"] == codex["description"]
    assert claude["author"] and claude["author"] == codex["author"]


@pytest.mark.parametrize(
    ("manifest_rel", "expected_pointer"),
    [
        pytest.param(".claude-plugin/plugin.json", "./claude-skills/", id="claude"),
        pytest.param(".codex-plugin/plugin.json", "./codex-skills/", id="codex"),
    ],
)
def test_skills_pointer(candidate: Path, manifest_rel: str, expected_pointer: str) -> None:
    manifest = json.loads((candidate / manifest_rel).read_text())
    assert manifest["skills"] == expected_pointer


def test_codex_manifest_omits_hooks_key(candidate: Path) -> None:
    codex = json.loads((candidate / ".codex-plugin" / "plugin.json").read_text())
    assert "hooks" not in codex


def test_claude_manifest_omits_hooks_key(candidate: Path) -> None:
    claude = json.loads((candidate / ".claude-plugin" / "plugin.json").read_text())
    assert "hooks" not in claude


@pytest.mark.parametrize(
    "absent_rel",
    [
        pytest.param("skills", id="no-default-skills-dir"),
        pytest.param("hooks/hooks.json", id="no-default-hooks-json"),
    ],
)
def test_candidate_omits_default_paths(candidate: Path, absent_rel: str) -> None:
    assert not (candidate / absent_rel).exists()


@pytest.mark.parametrize(
    "skill_rel",
    [
        pytest.param("claude-skills/scan-codebase/SKILL.md", id="claude-adapter"),
        pytest.param("codex-skills/scan-codebase/SKILL.md", id="codex-adapter"),
    ],
)
def test_scan_codebase_adapter_present(candidate: Path, skill_rel: str) -> None:
    assert (candidate / skill_rel).is_file()


# --- payload closure -------------------------------------------------------


def test_no_symlinks_in_payload(candidate: Path) -> None:
    assert [p for p in candidate.rglob("*") if p.is_symlink()] == []


def test_no_case_collisions(candidate: Path) -> None:
    folded: dict[str, str] = {}
    for path in candidate.rglob("*"):
        if not path.is_file():
            continue
        key = path.relative_to(candidate).as_posix().casefold()
        assert key not in folded, f"case collision: {key}"
        folded[key] = path.name


def test_no_source_tree_references(candidate: Path) -> None:
    needle = str(builder.SOURCE_ROOT).encode("utf-8")
    offenders = [
        p.relative_to(candidate).as_posix() for p in candidate.rglob("*") if p.is_file() and needle in p.read_bytes()
    ]
    assert offenders == []


def test_package_manifest_hashes_match(candidate: Path) -> None:
    manifest = json.loads((candidate / "package-manifest.json").read_text())
    for record in manifest["files"]:
        payload = (candidate / record["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"], record["path"]
