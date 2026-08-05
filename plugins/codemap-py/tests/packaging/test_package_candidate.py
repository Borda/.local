"""Deterministic real-package builder contract.

Covers the builder CLI contract the install probes depend on, byte-for-byte
determinism, single-source identity (manifest version equals the tracked
``.claude-plugin/plugin.json`` version), and payload closure of the real tracked
tree — skills, hooks, bin, and scripts present; tests, default ``skills/``, and
``hooks/hooks.json`` absent; no source-tree references, symlinks, or case
collisions.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_BUILDER = _PLUGIN_ROOT / "scripts" / "build_package.py"
if str(_BUILDER.parent) not in sys.path:
    sys.path.insert(0, str(_BUILDER.parent))

import build_package as builder  # noqa: E402  (needs the scripts path insert above)

_TEXT_LAUNCHERS = (
    "bin/check-index-currency",
    "bin/codemap-py",
    "bin/codemap-py.cmd",
    "bin/scan-index",
    "bin/scan-query",
)
_TEXT_PACKAGE_METADATA = ("LICENSE", "NOTICE")


def _plugin_identity() -> tuple[str, str]:
    """Return ``(name, version)`` from the tracked Claude manifest."""
    manifest = json.loads((_PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return manifest["name"], manifest["version"]


def _run_builder(*args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the builder CLI under the current interpreter."""
    return subprocess.run(
        [sys.executable, str(_BUILDER), *args],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the package once via the CLI for read-only inspection."""
    out = tmp_path_factory.mktemp("package")
    result = _run_builder("--out", str(out))
    assert result.returncode == 0, result.stderr
    return out


# --- CLI + single-source identity ------------------------------------------


def test_build_exits_zero_and_writes_manifest(package: Path) -> None:
    """Manifest carries the tracked plugin identity and a non-empty file list."""
    name, version = _plugin_identity()
    manifest = json.loads((package / "package-manifest.json").read_text())
    assert manifest["name"] == name
    assert manifest["version"] == version
    assert len(manifest["files"]) >= 1


def test_manifest_version_is_not_hardcoded(package: Path) -> None:
    """The builder reads version from plugin.json rather than a literal."""
    _, version = _plugin_identity()
    assert json.loads((package / "package-manifest.json").read_text())["version"] == version


def test_check_flag_reports_deterministic(package: Path) -> None:
    """``--check`` against a populated reference build exits zero."""
    result = _run_builder("--out", str(package), "--check")
    assert result.returncode == 0, result.stderr


# --- determinism -----------------------------------------------------------


def test_two_builds_are_byte_identical(tmp_path: Path) -> None:
    """Two independent CLI builds produce byte-identical trees."""
    first, second = tmp_path / "a", tmp_path / "b"
    assert _run_builder("--out", str(first)).returncode == 0
    assert _run_builder("--out", str(second)).returncode == 0
    assert builder._tree_bytes(first) == builder._tree_bytes(second)


# --- manifest shape --------------------------------------------------------


def test_both_runtime_manifests_present(package: Path) -> None:
    """Both the Claude and Codex plugin manifests ship in the package."""
    assert (package / ".claude-plugin" / "plugin.json").is_file()
    assert (package / ".codex-plugin" / "plugin.json").is_file()


def test_manifest_pair_shares_identity(package: Path) -> None:
    """Claude and Codex manifests agree on name and version."""
    claude = json.loads((package / ".claude-plugin" / "plugin.json").read_text())
    codex = json.loads((package / ".codex-plugin" / "plugin.json").read_text())
    assert claude["name"] == codex["name"]
    assert claude["version"] == codex["version"]


def test_codex_manifest_ships_six_skill_roster_and_no_hooks(package: Path) -> None:
    """The Codex manifest advertises the ``codex-skills/`` roster and still no hooks (Phase 4)."""
    codex = json.loads((package / ".codex-plugin" / "plugin.json").read_text())
    assert codex["skills"] == "./codex-skills/"
    assert "hooks" not in codex


def test_manifest_skill_rosters(package: Path) -> None:
    """The package manifest lists the same six skills for both Claude and Codex (plan §8.2 parity)."""
    rosters = json.loads((package / "package-manifest.json").read_text())["skills"]
    expected = {
        "scan-codebase",
        "query-code",
        "test-impact",
        "rename-refs",
        "integration",
        "debrief-coding",
    }
    assert set(rosters["claude"]) == expected
    assert set(rosters["codex"]) == expected


@pytest.mark.parametrize(
    "absent_rel",
    [
        pytest.param("skills", id="no-default-skills-dir"),
        pytest.param("hooks/hooks.json", id="no-default-hooks-json"),
        pytest.param("tests", id="no-tests-dir"),
    ],
)
def test_package_omits_paths(package: Path, absent_rel: str) -> None:
    """Default/source-only paths are excluded from the shipped package."""
    assert not (package / absent_rel).exists()


# --- payload closure -------------------------------------------------------


@pytest.mark.parametrize(
    "present_rel",
    [
        pytest.param("claude-skills/query-code/SKILL.md", id="skill"),
        pytest.param("claude-skills/_shared/codemap-context.md", id="shared-doc"),
        pytest.param("codex-skills/query-code/SKILL.md", id="codex-skill"),
        pytest.param("hooks/claude-hooks.json", id="hook-manifest"),
        pytest.param("hooks/inject-preamble.py", id="hook-python"),
        pytest.param("bin/scan-index", id="cli-alias"),
        pytest.param("bin/codemap-py", id="launcher"),
        pytest.param("scripts/codemap_py_cli.py", id="cli-script"),
        pytest.param("README.md", id="readme"),
        pytest.param("LICENSE", id="license"),
        pytest.param("NOTICE", id="notice"),
    ],
)
def test_payload_includes_expected_members(package: Path, present_rel: str) -> None:
    """The real tracked tree's load-bearing members ship in the package."""
    assert (package / present_rel).is_file()


def test_all_six_python_hooks_ship(package: Path) -> None:
    """Exactly the six retained Python hook helpers ship and no JavaScript remains."""
    helpers = sorted(p.name for p in (package / "hooks").glob("*.py"))
    assert helpers == [
        "guard-redundant-scan.py",
        "inject-preamble.py",
        "log-skill-start.py",
        "log-tool-use.py",
        "record-exhausted.py",
        "seed-session.py",
    ]
    assert list((package / "hooks").glob("*.js")) == []


@pytest.mark.parametrize(
    ("member", "expected_exec"),
    [
        pytest.param("bin/scan-index", True, id="executable-cli"),
        pytest.param("bin/scan-query", True, id="executable-query"),
        pytest.param("bin/codemap-py", True, id="executable-launcher"),
        pytest.param("bin/_schema.py", False, id="library-module"),
        pytest.param("README.md", False, id="document"),
    ],
)
def test_manifest_exec_flag_is_platform_neutral(package: Path, member: str, expected_exec: bool) -> None:
    """The manifest ``exec`` flag mirrors git's tracked mode, not host st_mode (F10)."""
    manifest = json.loads((package / "package-manifest.json").read_text())
    record = next(entry for entry in manifest["files"] if entry["path"] == member)
    assert record["exec"] is expected_exec


def test_hashed_text_inputs_have_platform_neutral_line_endings(package: Path) -> None:
    """Git attributes and packaged bytes must keep exact package hashes cross-platform."""
    text_inputs = (*_TEXT_LAUNCHERS, *_TEXT_PACKAGE_METADATA)
    result = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *text_inputs],
        cwd=str(_PLUGIN_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    expected_attributes = [line for member in text_inputs for line in (f"{member}: text: set", f"{member}: eol: lf")]
    assert result.stdout.splitlines() == expected_attributes
    for member in text_inputs:
        assert b"\r" not in (package / member).read_bytes(), member


def test_no_symlinks_in_payload(package: Path) -> None:
    """No payload member is a symlink."""
    assert [p for p in package.rglob("*") if p.is_symlink()] == []


def test_no_case_collisions(package: Path) -> None:
    """No two payload members collide under case folding."""
    folded: dict[str, str] = {}
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        key = path.relative_to(package).as_posix().casefold()
        assert key not in folded, f"case collision: {key}"
        folded[key] = path.name


def test_no_source_tree_references(package: Path) -> None:
    """No payload member embeds the absolute source-root path."""
    needle = str(builder.SOURCE_ROOT).encode("utf-8")
    offenders = [
        p.relative_to(package).as_posix() for p in package.rglob("*") if p.is_file() and needle in p.read_bytes()
    ]
    assert offenders == []


def test_package_manifest_hashes_match(package: Path) -> None:
    """Every manifest SHA-256 matches its on-disk payload bytes."""
    manifest = json.loads((package / "package-manifest.json").read_text())
    for record in manifest["files"]:
        payload = (package / record["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"], record["path"]


# --- pure builder helpers (filesystem-independent) -------------------------


@pytest.mark.parametrize(
    ("relative", "excluded"),
    [
        pytest.param("bin/__pycache__/x.pyc", True, id="pycache"),
        pytest.param("bin/foo.pyc", True, id="pyc-suffix"),
        pytest.param(".coverage.host", True, id="coverage"),
        pytest.param(".claude/state/x", True, id="dot-claude"),
        pytest.param("tests/test_x.py", True, id="tests-dir"),
        pytest.param("bin/scan-index", False, id="kept-cli"),
        pytest.param(".claude-plugin/plugin.json", False, id="kept-manifest"),
    ],
)
def test_is_excluded(relative: str, excluded: bool) -> None:
    """The exclusion predicate drops caches/state/tests but keeps real payload."""
    assert builder._is_excluded(relative) is excluded


def test_admit_rejects_case_collision() -> None:
    """Two payload paths differing only by case are rejected as a collision."""
    folded: set[str] = set()
    pairs: list[tuple[Path, str]] = []
    builder._admit(Path("Bin/Scan"), "Bin/Scan", folded, pairs)
    with pytest.raises(ValueError, match="case-colliding"):
        builder._admit(Path("bin/scan"), "bin/scan", folded, pairs)


# --- build hygiene gates (residuals #3, #5) --------------------------------


def _git_porcelain() -> str:
    """Return repo-wide ``git status --porcelain`` output from the plugin tree."""
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(_PLUGIN_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout


def test_builder_mutates_nothing_tracked(tmp_path: Path) -> None:
    """A build to an external dir leaves the tracked working tree byte-identical."""
    before = _git_porcelain()
    assert _run_builder("--out", str(tmp_path / "pkg")).returncode == 0
    assert _git_porcelain() == before


@pytest.mark.skipif(sys.platform.startswith("win"), reason="executable bit is unreliable off POSIX")
def test_check_flags_tampered_reference_exec_mode(tmp_path: Path) -> None:
    """``--check`` fails when a reference file's on-disk mode drifts from the manifest."""
    out = tmp_path / "pkg"
    assert _run_builder("--out", str(out)).returncode == 0
    (out / "README.md").chmod(0o755)
    assert _run_builder("--out", str(out), "--check").returncode == 1
