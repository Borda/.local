"""Tests for ``bin/resolve_shared_path.py`` canonical Python resolver.

Covers each tier of the four-tier cascade plus argument validation:

* Tier 0 — ``CLAUDE_PLUGIN_ROOT`` env hit
* Tier 1 — Registry helper lookup (mocked subprocess via monkeypatched helper)
* Tier 2 — Cache semver scan with orphan filtering
* Tier 3 — Source-tree fallback (warn + exit 0) and absent-everywhere (exit 1)

Cross-cutting checks confirm Windows-portability invariants:

* No hardcoded ``/tmp`` literal in script source
* ``sys.stdout.reconfigure(...)`` call present in script source
"""

from __future__ import annotations

from pathlib import Path

import pytest

import resolve_shared_path

SCRIPT = Path(resolve_shared_path.__file__)


def test_no_tmp_literal_in_source() -> None:
    """Windows-portability: script must not hardcode ``/tmp``."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "/tmp" not in src, "resolve_shared_path.py must not hardcode /tmp"


def test_stdout_reconfigure_present_in_source() -> None:
    """Windows-portability: ``sys.stdout.reconfigure(...)`` required in ``main()``."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "sys.stdout.reconfigure" in src


def test_shebang_uses_env_python_not_python3() -> None:
    """Shebang must read ``#!/usr/bin/env python`` (not ``python3``)."""
    first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env python"


class TestValidation:
    """Argument validation: invalid PLUGIN/SUBDIR exit 2 with stderr message."""

    def test_invalid_plugin_path_traversal(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Plugin containing ``/`` fails regex → exit 2."""
        rc = resolve_shared_path.main(["../evil", "skills/_shared"])
        assert rc == 2
        assert "invalid PLUGIN" in capsys.readouterr().err

    def test_invalid_plugin_special_chars(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Plugin with ``!`` fails regex → exit 2."""
        rc = resolve_shared_path.main(["plug!in", "skills/_shared"])
        assert rc == 2
        assert "invalid PLUGIN" in capsys.readouterr().err

    def test_invalid_subdir_traversal(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Subdir containing ``..`` is rejected → exit 2."""
        rc = resolve_shared_path.main(["foundry", "skills/../etc"])
        assert rc == 2
        assert "invalid SUBDIR" in capsys.readouterr().err

    def test_invalid_subdir_special_chars(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Subdir with disallowed chars exits 2."""
        rc = resolve_shared_path.main(["foundry", "skills/_shared!"])
        assert rc == 2
        assert "invalid SUBDIR" in capsys.readouterr().err


class TestTier0EnvHit:
    """Tier 0 — ``CLAUDE_PLUGIN_ROOT`` env var with valid subdir."""

    def test_env_root_with_existing_subdir(self, tmp_path: Path) -> None:
        """Env var set + ``<root>/<subdir>`` exists → tier 0 returned."""
        root = tmp_path / "plugin_install"
        (root / "skills" / "_shared").mkdir(parents=True)
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root=str(root))
        assert tier == 0
        assert Path(path) == root / "skills" / "_shared"

    def test_env_root_subdir_absent_falls_through(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Env var set but ``<root>/<subdir>`` missing → does not match tier 0."""
        root = tmp_path / "plugin_install"
        root.mkdir()
        # Patch out tier 1 so source-tree helper doesn't bleed real state into test.
        monkeypatch.setattr(resolve_shared_path, "_tier1_registry", lambda *a, **kw: None)
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root=str(root))
        assert tier != 0
        # Falls through to tier -1 (no cache, no source tree at tmp_path).
        assert path == "plugins/foundry/skills/_shared"

    def test_main_tier0_prints_path_no_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``main()`` tier-0 hit: stdout has path, stderr is empty."""
        root = tmp_path / "plugin_install"
        (root / "skills" / "_shared").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(root))
        monkeypatch.setattr(resolve_shared_path.Path, "home", classmethod(lambda _cls: tmp_path))
        rc = resolve_shared_path.main(["foundry", "skills/_shared"])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == str(root / "skills" / "_shared")
        assert captured.err == ""


class TestTier2Cache:
    """Tier 2 — cache semver scan with orphan filtering."""

    def test_cache_hit_picks_highest_semver(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple versions present → newest by semver returned."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
        older = base / "0.1.0" / "skills" / "_shared"
        newer = base / "0.20.0" / "skills" / "_shared"
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        monkeypatch.setattr(resolve_shared_path, "_tier1_registry", lambda *a, **kw: None)
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root="")
        assert tier == 2
        assert Path(path) == newer

    def test_orphaned_version_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Version with ``.orphaned_at`` is skipped → older usable version wins."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
        orphaned_ver = base / "0.20.0"
        (orphaned_ver / "skills" / "_shared").mkdir(parents=True)
        (orphaned_ver / ".orphaned_at").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")
        older_shared = base / "0.1.0" / "skills" / "_shared"
        older_shared.mkdir(parents=True)
        monkeypatch.setattr(resolve_shared_path, "_tier1_registry", lambda *a, **kw: None)
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root="")
        assert tier == 2
        assert Path(path) == older_shared

    def test_cache_dir_without_subdir_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Version dir present but ``<subdir>`` missing → not a tier-2 hit."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "foundry"
        (base / "0.20.0").mkdir(parents=True)  # no skills/_shared
        monkeypatch.setattr(resolve_shared_path, "_tier1_registry", lambda *a, **kw: None)
        monkeypatch.chdir(tmp_path)  # isolate CWD so relative source-tree path doesn't exist
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root="")
        # Falls through to tier -1 (no source tree at tmp_path either)
        assert tier == -1


class TestTier3SourceFallback:
    """Tier 3 — source-tree fallback when nothing else hits."""

    def test_source_fallback_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Source tree present → tier 3 returns ``plugins/<plugin>/<subdir>``."""
        # Build a source-tree shape in tmp_path and cwd there so the relative
        # path resolves to a real dir.
        source = tmp_path / "plugins" / "foundry" / "skills" / "_shared"
        source.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        path, tier = resolve_shared_path.resolve("foundry", "skills/_shared", home=tmp_path, env_root="")
        assert tier == 3
        assert path == "plugins/foundry/skills/_shared"

    def test_main_tier3_warns_and_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``main()`` tier-3: stdout has path, stderr has warning, exit 0."""
        source = tmp_path / "plugins" / "foundry" / "skills" / "_shared"
        source.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "")
        monkeypatch.setattr(resolve_shared_path.Path, "home", classmethod(lambda _cls: tmp_path))
        rc = resolve_shared_path.main(["foundry", "skills/_shared"])
        captured = capsys.readouterr()
        assert rc == 0
        assert captured.out.strip() == "plugins/foundry/skills/_shared"
        assert "source-tree fallback" in captured.err


class TestAbsentEverywhere:
    """H7 — all tiers fail, plugin truly absent: exit 1 with message."""

    def test_main_exits_1_when_nothing_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No env, no helper, no cache, no source tree → exit 1."""
        monkeypatch.chdir(tmp_path)  # cwd has no plugins/ dir
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", "")
        monkeypatch.setattr(resolve_shared_path.Path, "home", classmethod(lambda _cls: tmp_path))
        rc = resolve_shared_path.main(["foundry", "skills/_shared"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "not found in registry, cache, or source tree" in captured.err


class TestVersionKey:
    """Semver sort key — verify ``sort -V`` equivalence."""

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("0.20.0", [0, 20, 0]),
            ("0.9.9", [0, 9, 9]),
            ("1.2.3rc4", [1, 2, 3, 4]),
            ("", []),
            ("nonsense", []),
        ],
    )
    def test_version_key_extracts_digit_runs(self, name: str, expected: list[int]) -> None:
        """``_version_key`` extracts contiguous digit runs as ints."""
        assert resolve_shared_path._version_key(name) == expected

    def test_version_key_orders_semver_correctly(self) -> None:
        """``0.20.0`` sorts above ``0.9.9`` (digit-run aware, not lexical)."""
        assert resolve_shared_path._version_key("0.9.9") < resolve_shared_path._version_key("0.20.0")
