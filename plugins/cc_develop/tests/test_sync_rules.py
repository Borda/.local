"""Filesystem regression tests for ``bin/sync_rules.py``.

Every mutation the helper can perform has a case here, because the reverted first
attempt at this feature shipped two unsafe ones: a foreign marketplace link was
refreshed, and a ``dotfiles/`` link was deleted, both because ownership was a
path substring match. The ownership cases below are the guard against that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import sync_rules
from sync_rules import SourceError, cache_lineage, dest_name, main, owns, sync

MARKETPLACE = "borda-ai-rig"
PLUGIN = "develop"


def _make_home(tmp_path: Path) -> Path:
    """Create a disposable home with an empty ``~/.claude/rules``."""
    home = tmp_path / "home"
    (home / ".claude" / "rules").mkdir(parents=True)
    return home


def _make_plugin(root: Path, name: str = PLUGIN, rules: dict[str, str] | None = None) -> Path:
    """Create a minimal plugin tree with a manifest and rule files."""
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": name, "version": "0.1.0"}), encoding="utf-8"
    )
    (root / "rules").mkdir(parents=True)
    for rule_name, body in (rules or {"quality-gates.md": "# gates\n"}).items():
        (root / "rules" / rule_name).write_text(body, encoding="utf-8")
    return root


def _installed_root(home: Path, version: str = "0.19.0", plugin: str = PLUGIN, marketplace: str = MARKETPLACE) -> Path:
    """Create an installed-cache plugin root under ``home``."""
    root = home / ".claude" / "plugins" / "cache" / marketplace / plugin / version
    return _make_plugin(root)


def _dest(home: Path, source_name: str = "quality-gates.md", plugin: str = PLUGIN) -> Path:
    """Namespaced destination path for a source rule."""
    return home / ".claude" / "rules" / dest_name(plugin, source_name)


# --- naming and lineage ------------------------------------------------------


def test_destination_is_plugin_prefixed(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    sync(PLUGIN, root, home)

    assert _dest(home).is_symlink()
    assert _dest(home).name == "develop-quality-gates.md"


def test_sibling_plugins_do_not_collide(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    develop = _installed_root(home)
    oss = _make_plugin(home / ".claude" / "plugins" / "cache" / MARKETPLACE / "oss" / "0.25.0", name="oss")

    sync(PLUGIN, develop, home)
    sync("oss", oss, home)

    assert _dest(home).is_symlink()
    assert _dest(home, plugin="oss").is_symlink()
    assert Path(_dest(home).readlink()).parent.parent == develop
    assert Path(_dest(home, plugin="oss").readlink()).parent.parent == oss


def test_cache_lineage_only_for_installed_roots(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    installed = _installed_root(home)

    assert cache_lineage(installed, home) == installed.parent
    assert cache_lineage(tmp_path / "checkout" / "plugins" / "cc_develop", home) is None


# --- ownership ---------------------------------------------------------------


def test_owns_current_root(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    dest = _dest(home)

    assert owns(dest, str(root / "rules" / "quality-gates.md"), root, cache_lineage(root, home))


def test_owns_same_lineage_stale_version(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home, version="0.19.0")
    stale = home / ".claude" / "plugins" / "cache" / MARKETPLACE / PLUGIN / "0.18.5" / "rules" / "quality-gates.md"

    assert owns(_dest(home), str(stale), root, cache_lineage(root, home))


@pytest.mark.parametrize(
    "target_rel",
    [
        # another marketplace, same plugin name — different lineage
        ".claude/plugins/cache/other-marketplace/develop/0.18.5/rules/quality-gates.md",
        # same marketplace, another plugin — different lineage
        ".claude/plugins/cache/borda-ai-rig/oss/0.24.5/rules/quality-gates.md",
        # arbitrary source checkout
        "src/AI-Rig/plugins/cc_develop/rules/quality-gates.md",
        # dotfiles path — the exact shape the reverted attempt deleted
        "dotfiles/plugins/cc_develop/rules/quality-gates.md",
    ],
)
def test_does_not_own_foreign_targets(tmp_path: Path, target_rel: str) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    assert not owns(_dest(home), str(home / target_rel), root, cache_lineage(root, home))


def test_does_not_own_sibling_version_prefix_collision(tmp_path: Path) -> None:
    """``…/develop-extra/0.1.0`` must not be adopted by ``…/develop``'s lineage."""
    home = _make_home(tmp_path)
    root = _installed_root(home)
    sneaky = (
        home / ".claude" / "plugins" / "cache" / MARKETPLACE / "develop-extra" / "0.1.0" / "rules" / "quality-gates.md"
    )

    assert not owns(_dest(home), str(sneaky), root, cache_lineage(root, home))


# --- install behaviour -------------------------------------------------------


def test_creates_link_when_absent(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    result = sync(PLUGIN, root, home)

    assert result.linked == ["develop-quality-gates.md"]
    assert _dest(home).readlink() == root / "rules" / "quality-gates.md"


def test_creates_rules_dir_when_missing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    root = _installed_root(home)

    sync(PLUGIN, root, home)

    assert _dest(home).is_symlink()


def test_relative_plugin_root_still_links_absolutely(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative --plugin-root must not become a dangling relative symlink target."""
    home = _make_home(tmp_path)
    root = _installed_root(home)
    monkeypatch.chdir(root.parent)

    sync(PLUGIN, Path(root.name), home)

    assert _dest(home).readlink().is_absolute()
    assert _dest(home).resolve().is_file()


def test_idempotent_rerun_reports_unchanged(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    sync(PLUGIN, root, home)
    second = sync(PLUGIN, root, home)

    assert second.linked == []
    assert second.unchanged == ["develop-quality-gates.md"]


def test_refreshes_same_lineage_stale_link(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    old = _installed_root(home, version="0.18.5")
    new = _installed_root(home, version="0.19.0")
    _dest(home).symlink_to(old / "rules" / "quality-gates.md")

    result = sync(PLUGIN, new, home)

    assert result.linked == ["develop-quality-gates.md"]
    assert _dest(home).readlink() == new / "rules" / "quality-gates.md"


def test_refreshes_broken_owned_link(tmp_path: Path) -> None:
    """A dangling link into the current root is owned, so it is repaired."""
    home = _make_home(tmp_path)
    root = _installed_root(home)
    _dest(home).symlink_to(root / "rules" / "renamed-away.md")

    result = sync(PLUGIN, root, home)

    assert result.linked == ["develop-quality-gates.md"]
    assert _dest(home).readlink() == root / "rules" / "quality-gates.md"


# --- conflicts ---------------------------------------------------------------


def test_real_file_is_preserved_as_conflict(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    _dest(home).write_text("user content\n", encoding="utf-8")

    result = sync(PLUGIN, root, home)

    assert result.conflicts == ["develop-quality-gates.md  (real file)"]
    assert _dest(home).read_text(encoding="utf-8") == "user content\n"
    assert not _dest(home).is_symlink()


def test_foreign_link_is_preserved_as_conflict(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    foreign = home / "dotfiles" / "rules" / "quality-gates.md"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("mine\n", encoding="utf-8")
    _dest(home).symlink_to(foreign)

    result = sync(PLUGIN, root, home)

    assert result.conflicts == [f"develop-quality-gates.md → {foreign}"]
    assert _dest(home).readlink() == foreign
    assert foreign.is_file()


def test_relative_foreign_target_is_preserved(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    _dest(home).symlink_to(Path("../../dotfiles/quality-gates.md"))

    result = sync(PLUGIN, root, home)

    assert result.conflicts
    assert _dest(home).readlink() == Path("../../dotfiles/quality-gates.md")


def test_relative_owned_target_is_recognised(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    relative = Path("..") / ".." / root.relative_to(home) / "rules" / "quality-gates.md"
    _dest(home).symlink_to(relative)

    result = sync(PLUGIN, root, home)

    assert result.conflicts == []
    assert result.unchanged == ["develop-quality-gates.md"]
    assert _dest(home).resolve() == root / "rules" / "quality-gates.md"


def test_broken_foreign_link_is_preserved(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    dangling = home / "src" / "AI-Rig" / "plugins" / "cc_develop" / "rules" / "quality-gates.md"
    _dest(home).symlink_to(dangling)

    result = sync(PLUGIN, root, home)

    assert result.conflicts == [f"develop-quality-gates.md → {dangling}"]
    assert _dest(home).readlink() == dangling


def test_approve_replaces_conflicts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    _dest(home).write_text("user content\n", encoding="utf-8")

    result = sync(PLUGIN, root, home, approve=True)

    assert result.replaced == ["develop-quality-gates.md"]
    assert _dest(home).readlink() == root / "rules" / "quality-gates.md"


# --- obsolete pruning --------------------------------------------------------


def test_removes_obsolete_owned_link(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    obsolete = home / ".claude" / "rules" / "develop-retired.md"
    obsolete.symlink_to(root / "rules" / "retired.md")

    result = sync(PLUGIN, root, home)

    assert result.removed == ["develop-retired.md"]
    assert not obsolete.is_symlink()


def test_keeps_obsolete_foreign_link(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    foreign = home / ".claude" / "rules" / "develop-retired.md"
    foreign.symlink_to(home / "dotfiles" / "retired.md")

    result = sync(PLUGIN, root, home)

    assert result.removed == []
    assert foreign.is_symlink()


def test_keeps_obsolete_real_file(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    user_file = home / ".claude" / "rules" / "develop-notes.md"
    user_file.write_text("mine\n", encoding="utf-8")

    result = sync(PLUGIN, root, home)

    assert result.removed == []
    assert user_file.read_text(encoding="utf-8") == "mine\n"


def test_never_touches_other_plugins_namespace(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    other = home / ".claude" / "rules" / "foundry-quality-gates.md"
    other.symlink_to(
        home / ".claude" / "plugins" / "cache" / MARKETPLACE / "foundry" / "0.40.0" / "rules" / "quality-gates.md"
    )

    sync(PLUGIN, root, home)

    assert other.is_symlink()


# --- source validation -------------------------------------------------------


def test_missing_manifest_aborts_before_mutation(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / ".claude-plugin" / "plugin.json").unlink()

    with pytest.raises(SourceError, match="missing plugin manifest"):
        sync(PLUGIN, root, home)
    assert list((home / ".claude" / "rules").iterdir()) == []


def test_invalid_manifest_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / ".claude-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(SourceError, match="unreadable plugin manifest"):
        sync(PLUGIN, root, home)


def test_mismatched_manifest_name_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "oss"}), encoding="utf-8")

    with pytest.raises(SourceError, match="declares 'oss'"):
        sync(PLUGIN, root, home)


def test_missing_rules_dir_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / "rules" / "quality-gates.md").unlink()
    (root / "rules").rmdir()

    with pytest.raises(SourceError, match="rules directory missing"):
        sync(PLUGIN, root, home)


def test_symlinked_rules_dir_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "quality-gates.md").write_text("# gates\n", encoding="utf-8")
    (root / "rules" / "quality-gates.md").unlink()
    (root / "rules").rmdir()
    (root / "rules").symlink_to(elsewhere)

    with pytest.raises(SourceError, match="not a real directory"):
        sync(PLUGIN, root, home)


def test_empty_rules_dir_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / "rules" / "quality-gates.md").unlink()

    with pytest.raises(SourceError, match="no \\*.md rules found"):
        sync(PLUGIN, root, home)


def test_empty_rule_file_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    (root / "rules" / "quality-gates.md").write_text("", encoding="utf-8")

    with pytest.raises(SourceError, match="rule is empty"):
        sync(PLUGIN, root, home)


def test_symlinked_rule_escaping_root_aborts(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    outside = tmp_path / "outside.md"
    outside.write_text("# elsewhere\n", encoding="utf-8")
    (root / "rules" / "escape.md").symlink_to(outside)

    with pytest.raises(SourceError, match="rule is a symlink"):
        sync(PLUGIN, root, home)
    assert not _dest(home, "escape.md").exists()


def test_validation_failure_leaves_existing_links_untouched(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)
    sync(PLUGIN, root, home)
    (root / "rules" / "broken.md").write_text("", encoding="utf-8")

    with pytest.raises(SourceError):
        sync(PLUGIN, root, home)
    assert _dest(home).readlink() == root / "rules" / "quality-gates.md"


# --- containment -------------------------------------------------------------


def test_writes_nothing_outside_claude_rules(tmp_path: Path) -> None:
    home = _make_home(tmp_path)
    codex = home / ".codex"
    codex.mkdir()
    (codex / "config.toml").write_text("keep\n", encoding="utf-8")
    root = _installed_root(home)

    before = sorted(p.relative_to(home) for p in home.rglob("*") if ".claude/rules" not in p.as_posix())
    sync(PLUGIN, root, home, approve=True)
    after = sorted(p.relative_to(home) for p in home.rglob("*") if ".claude/rules" not in p.as_posix())

    assert before == after
    assert (codex / "config.toml").read_text(encoding="utf-8") == "keep\n"


# --- CLI ---------------------------------------------------------------------


def test_main_reports_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    code = main(["--plugin-name", PLUGIN, "--plugin-root", str(root), "--home", str(home)])

    assert code == 0
    assert "linked: develop-quality-gates.md" in capsys.readouterr().out


def test_main_exits_one_on_source_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = _make_home(tmp_path)

    code = main(["--plugin-name", PLUGIN, "--plugin-root", str(tmp_path / "nope"), "--home", str(home)])

    assert code == 1
    assert "not a directory" in capsys.readouterr().err


def test_main_dry_run_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    code = main(["--plugin-name", PLUGIN, "--plugin-root", str(root), "--home", str(home), "--dry-run"])

    assert code == 0
    assert "linked: develop-quality-gates.md" in capsys.readouterr().out
    assert list((home / ".claude" / "rules").iterdir()) == []


def test_main_reports_failure_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = _make_home(tmp_path)
    root = _installed_root(home)

    def _boom(link: sync_rules.RuleLink) -> None:
        raise OSError("symlinks unsupported")

    monkeypatch.setattr(sync_rules, "_replace_link", _boom)
    code = main(["--plugin-name", PLUGIN, "--plugin-root", str(root), "--home", str(home)])

    assert code == 1
    assert "FAILED: develop-quality-gates.md: symlinks unsupported" in capsys.readouterr().out
