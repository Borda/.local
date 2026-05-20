"""Tests for ``bin/symlink_with_guard.py``.

Doctests cover the pure helpers (``_is_foundry_managed``, ``_is_current``,
``_conflict_label``). This file exercises the end-to-end behaviours of
``cleanup`` and ``scan`` against a real temporary filesystem so the
symlink-handling logic is verified without mocks.
"""

from __future__ import annotations

from pathlib import Path

import pytest


import symlink_with_guard  # noqa: E402
from symlink_with_guard import cleanup, main, scan  # noqa: E402

_MARKER = "borda-ai-rig/foundry/"


@pytest.fixture
def env(tmp_path: Path) -> tuple[Path, Path]:
    """Build a current plugin tree + an empty fake $HOME, return both.

    Layout::

        tmp/plugin/{rules,skills/curator,TEAM_PROTOCOL.md}
        tmp/home/.claude/{rules,skills,agents}/
    """
    plugin = tmp_path / "plugin"
    (plugin / "rules").mkdir(parents=True)
    (plugin / "rules" / "current.md").write_text("current\n")
    (plugin / "rules" / "another.md").write_text("another\n")
    (plugin / "TEAM_PROTOCOL.md").write_text("team\n")
    (plugin / "skills" / "curator").mkdir(parents=True)
    (plugin / "skills" / "shepherd").mkdir(parents=True)

    home = tmp_path / "home"
    (home / ".claude" / "rules").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    (home / ".claude" / "agents").mkdir(parents=True)
    return plugin, home


def _ln(target: str, link: Path) -> None:
    """Create a symlink with an arbitrary text target (no exists-check)."""
    link.symlink_to(target)


class TestCleanup:
    """cleanup: removes only foundry-managed symlinks whose source vanished."""

    def test_removes_obsolete_foundry_rule_link(self, env: tuple[Path, Path]) -> None:
        """Stale foundry symlink whose source no longer exists is removed."""
        plugin, home = env
        link = home / ".claude" / "rules" / "obsolete.md"
        _ln("/old/borda-ai-rig/foundry/0.10.0/rules/obsolete.md", link)

        log = cleanup(plugin, home, _MARKER)

        assert not link.is_symlink()
        assert "removed obsolete: obsolete.md" in log

    def test_keeps_current_foundry_rule_link(self, env: tuple[Path, Path]) -> None:
        """Symlink already pointing into current plugin root is untouched."""
        plugin, home = env
        link = home / ".claude" / "rules" / "current.md"
        _ln(str(plugin / "rules" / "current.md"), link)

        log = cleanup(plugin, home, _MARKER)

        assert link.is_symlink()
        assert log == []

    def test_keeps_non_foundry_rule_link(self, env: tuple[Path, Path]) -> None:
        """Symlink to a non-foundry path is left alone (user owns it)."""
        plugin, home = env
        link = home / ".claude" / "rules" / "user.md"
        _ln("/somewhere/else/user.md", link)

        cleanup(plugin, home, _MARKER)

        assert link.is_symlink()

    def test_keeps_real_file(self, env: tuple[Path, Path]) -> None:
        """Real files are never deleted by cleanup."""
        plugin, home = env
        real = home / ".claude" / "rules" / "myown.md"
        real.write_text("hand-written\n")

        cleanup(plugin, home, _MARKER)

        assert real.is_file()

    def test_removes_obsolete_team_protocol(self, env: tuple[Path, Path]) -> None:
        """Stale foundry TEAM_PROTOCOL.md symlink is removed when source absent."""
        plugin, home = env
        # source file removed from current plugin → cleanup should drop the stale link
        (plugin / "TEAM_PROTOCOL.md").unlink()
        link = home / ".claude" / "TEAM_PROTOCOL.md"
        _ln("/old/borda-ai-rig/foundry/0.10.0/TEAM_PROTOCOL.md", link)

        log = cleanup(plugin, home, _MARKER)

        assert not link.is_symlink()
        assert "removed obsolete: TEAM_PROTOCOL.md" in log

    def test_keeps_team_protocol_when_source_still_present(self, env: tuple[Path, Path]) -> None:
        """Even a stale foundry TEAM_PROTOCOL.md link stays when source exists (Phase 4 will refresh)."""
        plugin, home = env
        link = home / ".claude" / "TEAM_PROTOCOL.md"
        _ln("/old/borda-ai-rig/foundry/0.10.0/TEAM_PROTOCOL.md", link)

        cleanup(plugin, home, _MARKER)

        assert link.is_symlink()  # not obsolete — Phase 4 handles refresh

    def test_removes_obsolete_skill_dir_link(self, env: tuple[Path, Path]) -> None:
        """Stale foundry skill symlink whose source dir vanished is removed."""
        plugin, home = env
        link = home / ".claude" / "skills" / "oldskill"
        _ln("/old/borda-ai-rig/foundry/0.10.0/skills/oldskill", link)

        log = cleanup(plugin, home, _MARKER)

        assert not link.is_symlink()
        assert "removed obsolete skill: oldskill" in log

    def test_empty_when_no_obsolete_entries(self, env: tuple[Path, Path]) -> None:
        """Clean state → no removals, empty log."""
        plugin, home = env

        log = cleanup(plugin, home, _MARKER)

        assert log == []

    def test_removes_stale_foundry_agent_symlink(self, env: tuple[Path, Path]) -> None:
        """Foundry-managed agent symlink under a non-current root is removed unconditionally."""
        plugin, home = env
        link = home / ".claude" / "agents" / "sw-engineer.md"
        _ln("/old/borda-ai-rig/foundry/0.10.0/agents/sw-engineer.md", link)

        log = cleanup(plugin, home, _MARKER)

        assert not link.is_symlink()
        assert "removed obsolete agent: sw-engineer.md" in log

    def test_keeps_non_foundry_agent_symlink(self, env: tuple[Path, Path]) -> None:
        """Agent symlink pointing outside foundry is left alone (user owns it)."""
        plugin, home = env
        link = home / ".claude" / "agents" / "my-agent.md"
        _ln("/home/user/.claude/agents/my-agent.md", link)

        cleanup(plugin, home, _MARKER)

        assert link.is_symlink()

    def test_keeps_current_version_agent_symlink(self, env: tuple[Path, Path]) -> None:
        """Agent symlink pointing into the current plugin root is left alone.

        Init never re-creates these, so any link pointing at the current root
        was placed by something external; leaving it intact gives the operator
        a clear signal to investigate without silently destroying state.
        """
        plugin, home = env
        link = home / ".claude" / "agents" / "sw-engineer.md"
        _ln(str(plugin / "agents" / "sw-engineer.md"), link)

        cleanup(plugin, home, _MARKER)

        assert link.is_symlink()

    def test_keeps_real_agent_file(self, env: tuple[Path, Path]) -> None:
        """Real (non-symlink) files under ~/.claude/agents/ are never deleted."""
        plugin, home = env
        real = home / ".claude" / "agents" / "user.md"
        real.write_text("user-authored\n")

        cleanup(plugin, home, _MARKER)

        assert real.is_file()
        assert not real.is_symlink()


class TestScan:
    """scan: surfaces only conflicts requiring user confirmation."""

    def test_skips_current_foundry_link(self, env: tuple[Path, Path]) -> None:
        """Current symlink is not a conflict."""
        plugin, home = env
        _ln(
            str(plugin / "rules" / "current.md"),
            home / ".claude" / "rules" / "current.md",
        )

        assert scan(plugin, home, _MARKER) == []

    def test_skips_stale_foundry_link(self, env: tuple[Path, Path]) -> None:
        """Stale foundry symlink is auto-replaced in Phase 4 — not a conflict."""
        plugin, home = env
        _ln(
            "/old/borda-ai-rig/foundry/0.10.0/rules/current.md",
            home / ".claude" / "rules" / "current.md",
        )

        assert scan(plugin, home, _MARKER) == []

    def test_reports_non_foundry_symlink(self, env: tuple[Path, Path]) -> None:
        """Symlink to a non-foundry path surfaces as a conflict descriptor."""
        plugin, home = env
        _ln("/home/user/dotfiles/another.md", home / ".claude" / "rules" / "another.md")

        conflicts = scan(plugin, home, _MARKER)

        assert conflicts == ["rules/another.md → /home/user/dotfiles/another.md"]

    def test_reports_real_file_conflict(self, env: tuple[Path, Path]) -> None:
        """Real file at dest path surfaces with the (real file) suffix."""
        plugin, home = env
        (home / ".claude" / "rules" / "current.md").write_text("hand-written\n")

        conflicts = scan(plugin, home, _MARKER)

        assert "rules/current.md  (real file)" in conflicts

    def test_reports_team_protocol_conflict(self, env: tuple[Path, Path]) -> None:
        """TEAM_PROTOCOL.md conflict is labeled without the rules/ or skills/ prefix."""
        plugin, home = env
        _ln("/somewhere/else/team.md", home / ".claude" / "TEAM_PROTOCOL.md")

        conflicts = scan(plugin, home, _MARKER)

        assert "TEAM_PROTOCOL.md → /somewhere/else/team.md" in conflicts

    def test_reports_skill_real_entry_conflict(self, env: tuple[Path, Path]) -> None:
        """A real directory at dest surfaces with (real entry) suffix for skills."""
        plugin, home = env
        (home / ".claude" / "skills" / "curator").mkdir()

        conflicts = scan(plugin, home, _MARKER)

        assert "skills/curator  (real entry)" in conflicts

    def test_no_conflicts_on_empty_dest(self, env: tuple[Path, Path]) -> None:
        """Absent dest entries are not conflicts — Phase 4 will create them."""
        plugin, home = env

        assert scan(plugin, home, _MARKER) == []


class TestMain:
    """main: CLI surface — stdout, stderr, exit codes."""

    def test_cleanup_prints_log_lines_indented(
        self,
        env: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """cleanup mode emits ``  removed obsolete: ...`` lines (two-space indent)."""
        plugin, home = env
        _ln(
            "/old/borda-ai-rig/foundry/0.10.0/rules/another.md",
            home / ".claude" / "rules" / "another.md",
        )
        # required: source file deleted to mark it obsolete
        (plugin / "rules" / "another.md").unlink()

        rc = main(["cleanup", "--plugin-root", str(plugin), "--home", str(home)])

        assert rc == 0
        out = capsys.readouterr().out
        assert "  removed obsolete: another.md" in out

    def test_scan_prints_one_conflict_per_line(
        self,
        env: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """scan mode emits the bash-array-ready format on stdout."""
        plugin, home = env
        _ln("/elsewhere/foo.md", home / ".claude" / "rules" / "current.md")

        rc = main(["scan", "--plugin-root", str(plugin), "--home", str(home)])

        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["rules/current.md → /elsewhere/foo.md"]

    def test_missing_plugin_root_exits_1(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Non-existent plugin root path is a hard error."""
        rc = main(["scan", "--plugin-root", str(tmp_path / "nope")])
        assert rc == 1
        assert "is not a directory" in capsys.readouterr().err

    def test_custom_marker_respected(
        self,
        env: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--marker override changes the substring used to detect foundry links."""
        plugin, home = env
        _ln(
            "/x/custom-marker/0.1/rules/another.md",
            home / ".claude" / "rules" / "another.md",
        )
        (plugin / "rules" / "another.md").unlink()

        rc = main(
            [
                "cleanup",
                "--plugin-root",
                str(plugin),
                "--home",
                str(home),
                "--marker",
                "custom-marker/",
            ],
        )

        assert rc == 0
        out = capsys.readouterr().out
        assert "  removed obsolete: another.md" in out


def test_module_exposes_expected_helpers() -> None:
    """Smoke check: module surface includes the documented entry points."""
    assert callable(symlink_with_guard.cleanup)
    assert callable(symlink_with_guard.scan)
    assert callable(symlink_with_guard.main)
