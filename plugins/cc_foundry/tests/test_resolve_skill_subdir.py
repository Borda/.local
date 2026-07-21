"""Tests for ``bin/resolve_skill_subdir.py``.

Doctests in the source cover ``_validate_token`` and ``resolve``'s miss-path.
This file covers the four-tier cascade against a real filesystem, plus the
CLI surface (stdout, stderr, exit codes).
"""

from __future__ import annotations

from pathlib import Path

import pytest


import resolve_skill_subdir  # noqa: E402
from resolve_skill_subdir import main, resolve  # noqa: E402


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a fake $HOME with an empty plugin cache subtree."""
    home = tmp_path / "home"
    (home / ".claude" / "plugins" / "cache").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    return home


@pytest.fixture
def cwd_with_local_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Chdir to a fake project root containing a ``plugins/cc_foundry/skills`` tree."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestResolveCascade:
    """resolve: tier-1 → tier-2 → tier-3 → tier-4 ordering."""

    def test_tier1_claude_plugin_root_wins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """When CLAUDE_PLUGIN_ROOT is set and the dir exists, that's the answer."""
        plugin_root = tmp_path / "installed"
        target = plugin_root / "skills" / "calibrate" / "modes"
        target.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

        result = resolve("calibrate", "modes", local=False, home=fake_home)

        assert result == target

    def test_tier2_local_skipped_when_local_false(
        self,
        cwd_with_local_tree: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """Local source dir exists but --local was not passed → tier 2 bypassed."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        local = cwd_with_local_tree / "plugins" / "cc_foundry" / "skills" / "audit" / "templates"
        local.mkdir(parents=True)

        # No project-local override, no cache match → final result is None
        result = resolve("audit", "templates", local=False, home=fake_home)

        assert result is None

    def test_tier2_local_hit_when_local_true(
        self,
        cwd_with_local_tree: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """--local flag pulls the source tree into the cascade after CLAUDE_PLUGIN_ROOT."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        local = cwd_with_local_tree / "plugins" / "cc_foundry" / "skills" / "audit" / "templates"
        local.mkdir(parents=True)

        result = resolve("audit", "templates", local=True, home=fake_home)

        assert result == Path("plugins") / "cc_foundry" / "skills" / "audit" / "templates"

    def test_tier3_project_local_override(
        self,
        cwd_with_local_tree: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """``.claude/skills/`` override resolves when no higher tier matches."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        override = cwd_with_local_tree / ".claude" / "skills" / "manage" / "templates"
        override.mkdir(parents=True)

        result = resolve("manage", "templates", local=False, home=fake_home)

        assert result == Path(".claude") / "skills" / "manage" / "templates"

    def test_tier4_cache_scan_picks_highest(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """Cache fallback returns the lexically-greatest path (semver-friendly)."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        cache = fake_home / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
        for version in ("0.10.0", "0.18.0", "0.9.0"):
            (cache / version / "skills" / "calibrate" / "modes").mkdir(parents=True)

        result = resolve("calibrate", "modes", local=False, home=fake_home)

        assert result is not None
        assert "0.18.0" in str(result)

    def test_all_tiers_miss_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
    ) -> None:
        """Nothing exists → None (CLI surface translates this to exit 1)."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        assert resolve("nope", "missing", local=False, home=fake_home) is None


class TestMain:
    """main: CLI surface — exit codes, stdout, stderr."""

    def test_success_prints_path_exit_0(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Resolved path printed to stdout, exit 0."""
        plugin_root = tmp_path / "installed"
        (plugin_root / "skills" / "audit" / "templates").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))

        rc = main(["audit", "templates", "--home", str(fake_home)])

        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out.endswith("/installed/skills/audit/templates")

    def test_missing_prints_breaking_exit_1(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unresolvable → ! BREAKING line on stderr, exit 1."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)

        rc = main(["nope", "missing", "--home", str(fake_home)])

        assert rc == 1
        err = capsys.readouterr().err
        assert "! BREAKING" in err
        assert "nope/missing not found" in err

    @pytest.mark.parametrize(
        "skill,subdir",
        [
            ("", "templates"),
            ("audit", ""),
            ("../etc", "templates"),
            ("audit", "../sneaky"),
            ("audit/sub", "templates"),
        ],
    )
    def test_invalid_token_exits_2(
        self,
        skill: str,
        subdir: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Bad characters in skill or subdir → exit 2, stderr explains."""
        rc = main([skill, subdir])
        assert rc == 2
        err = capsys.readouterr().err
        assert "error:" in err

    def test_local_flag_propagates(
        self,
        cwd_with_local_tree: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--local flag enables tier-2 resolution at the CLI surface."""
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        (cwd_with_local_tree / "plugins" / "cc_foundry" / "skills" / "manage" / "templates").mkdir(parents=True)

        rc = main(["manage", "templates", "--local", "--home", str(fake_home)])

        assert rc == 0
        out = capsys.readouterr().out.strip()
        assert out == "plugins/cc_foundry/skills/manage/templates"


def test_module_exposes_expected_helpers() -> None:
    """Smoke check: module surface includes the documented entry points."""
    assert callable(resolve_skill_subdir.resolve)
    assert callable(resolve_skill_subdir.main)
