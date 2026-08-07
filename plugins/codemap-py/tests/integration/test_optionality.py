"""Symmetric optionality — provider-only lane (plan §8.5, acceptance F-08).

``-k provider_only``: with every declared consumer hidden/absent, ``codemap-py``'s own six
skills stay discoverable, the shared-index/logging surface resolves fine, and the
non-mutating ``integrate check`` inspection path names absent consumers from bytes on disk
alone — never by importing, locating, or installing a ``cc_*``/``codex-rig`` package.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from codemap_py import integration

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_CANONICAL_SKILLS = {"scan-codebase", "query-code", "test-impact", "rename-refs", "integration", "debrief-coding"}


def _write_manifest(plugin_dir: Path, runtime: integration.Runtime, name: str, version: str) -> None:
    manifest_dir = plugin_dir / (".claude-plugin" if runtime == integration.Runtime.CLAUDE else ".codex-plugin")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(json.dumps({"name": name, "version": version}))


def _provider_only_root(base: Path) -> Path:
    """A disposable tree with only ``codemap-py`` present — every declared consumer absent."""
    root = base / "provider-only"
    root.mkdir()
    _write_manifest(root / integration.PROVIDER_DIR, integration.Runtime.CLAUDE, integration.PROVIDER_NAME, "1.0.0")
    _write_manifest(root / integration.PROVIDER_DIR, integration.Runtime.CODEX, integration.PROVIDER_NAME, "1.0.0")
    return root


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def provider_only_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A provider-only fixture repo, chdir'd into, with native-CLI probing stubbed absent."""
    root = _provider_only_root(tmp_path)
    monkeypatch.chdir(root)
    monkeypatch.setattr(integration, "_native_json_probe", lambda argv: None)
    return root


# --------------------------------------------------------------------------------------
# No cc_* / codex_rig import anywhere in the shipped package source.
# --------------------------------------------------------------------------------------


def test_provider_only_no_cc_star_import_in_package_source() -> None:
    """No module under ``codemap_py`` imports a ``cc_*`` consumer package or ``codex_rig``."""
    pkg_root = Path(integration.__file__).resolve().parent
    offenders: list[tuple[Path, list[str]]] = []
    for path in pkg_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            bad = [name for name in names if name.startswith("cc_") or name.startswith("codex_rig")]
            if bad:
                offenders.append((path, bad))
    assert offenders == []


def test_provider_only_six_skills_discoverable_regardless_of_consumers() -> None:
    """The six-skill rosters are static package content — discoverable with zero consumers installed."""
    claude_names = {p.name for p in (_PLUGIN_ROOT / "claude-skills").iterdir() if (p / "SKILL.md").is_file()}
    codex_names = {p.name for p in (_PLUGIN_ROOT / "codex-skills").iterdir() if (p / "SKILL.md").is_file()}
    assert claude_names == _CANONICAL_SKILLS
    assert codex_names == _CANONICAL_SKILLS


# --------------------------------------------------------------------------------------
# `integrate check` names absent consumers from bytes only — zero-write, no import.
# --------------------------------------------------------------------------------------


def test_provider_only_check_names_absent_consumers_from_bytes(provider_only_repo: Path) -> None:
    """``check`` with every consumer hidden reports each as a named absent state, not an error."""
    report = integration.build_check_report("both", provider_only_repo / integration.PROVIDER_DIR)
    for runtime_name in ("claude", "codex"):
        block = report[runtime_name]
        assert block["available"] is False
        for consumer_status in block["consumers"].values():
            assert consumer_status == {
                "manifest_present": False,
                "name_matches": False,
                "source_version": None,
                "installed_version": None,
            }


def test_provider_only_check_is_zero_write(provider_only_repo: Path) -> None:
    """``check`` in the provider-only lane still never mutates the fixture tree."""
    before = _tree_snapshot(provider_only_repo)
    integration.build_check_report("both", provider_only_repo / integration.PROVIDER_DIR)
    assert _tree_snapshot(provider_only_repo) == before


def test_provider_only_check_cli_exits_zero(provider_only_repo: Path) -> None:
    """``integrate check`` at the CLI boundary exits 0 even with every consumer absent."""
    code = integration.run(["check", "--runtime", "both", "--json"], provider_only_repo / integration.PROVIDER_DIR)
    assert code == 0


def test_provider_only_plan_rejects_unknown_but_reports_known_absent(provider_only_repo: Path) -> None:
    """A known closed-set consumer name still resolves (as absent-on-disk), never a discovery lookup."""
    targets = integration.resolve_targets("claude", ["oss"])
    assert [t.consumer for t in targets] == ["oss"]  # known name resolves even though unwired on disk
    with pytest.raises(integration.IntegrationError) as exc:
        integration.resolve_targets("claude", ["not-a-real-consumer"])
    assert exc.value.code == "unknown_target"


# --------------------------------------------------------------------------------------
# Shared-index / logging resolve fine with zero consumers installed.
# --------------------------------------------------------------------------------------


def test_provider_only_shared_index_and_logging_resolve(provider_only_repo: Path) -> None:
    """Shared-index identity and runtime-log isolation resolve with no consumer installed."""
    report = integration.build_check_report("claude", provider_only_repo / integration.PROVIDER_DIR)
    assert report["shared_index"]["root"] == str(provider_only_repo.resolve())
    assert set(report["runtime_log_isolation"]) == {"claude", "codex", "direct"}
