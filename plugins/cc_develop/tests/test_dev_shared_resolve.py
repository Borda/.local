"""Tests for ``develop/bin/dev_shared_resolve.py``.

Output contract:

* No flag → one stdout line (develop shared path).
* ``--foundry`` → two stdout lines (develop, then foundry).
* Cache hit returns newest semver; orphaned versions are skipped.
* Absent cache → source-tree fallback ``plugins/<plugin>/skills/_shared``
  with stderr warning (foundry side only emits the warning).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import dev_shared_resolve

SCRIPT = Path(dev_shared_resolve.__file__)


def test_no_tmp_literal_in_source() -> None:
    """Windows-portability: no hardcoded ``/tmp``."""
    assert "/tmp" not in SCRIPT.read_text(encoding="utf-8")


def test_stdout_reconfigure_present() -> None:
    """Windows-portability: ``sys.stdout.reconfigure(...)`` required."""
    assert "sys.stdout.reconfigure" in SCRIPT.read_text(encoding="utf-8")


def test_shebang_uses_env_python() -> None:
    """Shebang must read ``#!/usr/bin/env python``."""
    first_line = SCRIPT.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/usr/bin/env python"


class TestDevelopOnly:
    """Default invocation (no ``--foundry``) emits one line."""

    def test_cache_hit_returns_newest_version(self, tmp_path: Path) -> None:
        """Newest cached develop version's ``_shared`` is returned."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop"
        (base / "0.1.0" / "skills" / "_shared").mkdir(parents=True)
        newer = base / "0.6.2" / "skills" / "_shared"
        newer.mkdir(parents=True)
        paths = dev_shared_resolve.resolve_paths(include_foundry=False, home=tmp_path)
        assert paths == [str(newer)]

    @pytest.mark.parametrize(
        "older_version,newer_version",
        [
            ("0.9.0", "0.10.0"),
            ("0.99.0", "1.0.0"),
        ],
    )
    def test_cache_hit_uses_semver_ordering(self, tmp_path: Path, older_version: str, newer_version: str) -> None:
        """Newest cached develop version is selected semantically, not lexicographically."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop"
        (base / older_version / "skills" / "_shared").mkdir(parents=True)
        newer = base / newer_version / "skills" / "_shared"
        newer.mkdir(parents=True)
        paths = dev_shared_resolve.resolve_paths(include_foundry=False, home=tmp_path)
        assert paths == [str(newer)]

    def test_orphaned_develop_version_skipped(self, tmp_path: Path) -> None:
        """``.orphaned_at`` on newest develop version → older one wins."""
        base = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop"
        orphaned = base / "0.20.0"
        (orphaned / "skills" / "_shared").mkdir(parents=True)
        (orphaned / ".orphaned_at").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")
        older = base / "0.6.2" / "skills" / "_shared"
        older.mkdir(parents=True)
        paths = dev_shared_resolve.resolve_paths(include_foundry=False, home=tmp_path)
        assert paths == [str(older)]

    def test_source_fallback(self, tmp_path: Path) -> None:
        """Empty cache → source-tree fallback path string."""
        paths = dev_shared_resolve.resolve_paths(include_foundry=False, home=tmp_path)
        assert paths == ["plugins/cc_develop/skills/_shared"]

    def test_main_prints_single_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``main()`` no-flag: one line on stdout."""
        monkeypatch.setattr(dev_shared_resolve.Path, "home", classmethod(lambda _cls: tmp_path))
        rc = dev_shared_resolve.main([])
        captured = capsys.readouterr()
        assert rc == 0
        lines = [line for line in captured.out.splitlines() if line]
        assert lines == ["plugins/cc_develop/skills/_shared"]


class TestWithFoundry:
    """``--foundry`` invocation emits two lines."""

    def test_two_lines_both_from_cache(self, tmp_path: Path) -> None:
        """Both develop and foundry cached → two cache paths returned."""
        cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig"
        dev = cache / "develop" / "0.6.2" / "skills" / "_shared"
        foundry = cache / "foundry" / "0.20.0" / "skills" / "_shared"
        dev.mkdir(parents=True)
        foundry.mkdir(parents=True)
        paths = dev_shared_resolve.resolve_paths(include_foundry=True, home=tmp_path)
        assert paths == [str(dev), str(foundry)]

    def test_foundry_orphaned_newest_version_skipped(self, tmp_path: Path) -> None:
        """Foundry cache selection skips orphaned newest versions just like develop."""
        cache = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig"
        dev = cache / "develop" / "0.6.2" / "skills" / "_shared"
        dev.mkdir(parents=True)
        orphaned = cache / "foundry" / "0.20.0"
        (orphaned / "skills" / "_shared").mkdir(parents=True)
        (orphaned / ".orphaned_at").write_text("2026-01-01T00:00:00Z\n", encoding="utf-8")
        older = cache / "foundry" / "0.10.0" / "skills" / "_shared"
        older.mkdir(parents=True)
        paths = dev_shared_resolve.resolve_paths(include_foundry=True, home=tmp_path)
        assert paths == [str(dev), str(older)]

    def test_foundry_missing_warns_and_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No foundry cache → source-tree fallback + stderr warning."""
        dev = tmp_path / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "develop" / "0.6.2" / "skills" / "_shared"
        dev.mkdir(parents=True)
        monkeypatch.setattr(dev_shared_resolve.Path, "home", classmethod(lambda _cls: tmp_path))
        rc = dev_shared_resolve.main(["--foundry"])
        captured = capsys.readouterr()
        assert rc == 0
        lines = [line for line in captured.out.splitlines() if line]
        assert lines == [str(dev), "plugins/cc_foundry/skills/_shared"]
        assert "foundry plugin not in cache" in captured.err
