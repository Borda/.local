"""Tests for check_injection bin script.

Validates plugin-root discovery, marker detection, canonical site coverage, and CLI output.
"""

from __future__ import annotations

from pathlib import Path

import pytest


import check_injection as ci


# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------


def _build_fake_cache(
    root: Path,
    skill_sites: list[str] | None = None,
    agent_sites: list[str] | None = None,
) -> Path:
    """Materialise a fake ``cache/<plugin>/<version>/skills/<name>/SKILL.md`` tree.

    Args:
        root: temporary directory acting as the ``~/.claude/plugins/cache`` root.
        skill_sites: list of cache-relative skill directories (e.g. ``"develop/0.1/skills/fix"``)
            whose ``SKILL.md`` should contain the injection marker.
        agent_sites: list of cache-relative agent file paths (e.g. ``"foundry/0.1/agents/x.md"``)
            whose contents should contain the agent injection marker.

    Returns:
        The ``cache`` directory path (== ``root``).
    """
    for rel in skill_sites or []:
        target = root / rel / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"workflow uses {ci.SKILL_INJECTION_MARKER} for centrality\n", encoding="utf-8")
    for rel in agent_sites or []:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"## {ci.AGENT_INJECTION_MARKER}) block here\n", encoding="utf-8")
    return root


def _make_plugin_root(cache_root: Path) -> Path:
    """Build a plausible plugin-install-root path under ``cache_root``.

    Mirrors ``${CLAUDE_PLUGIN_ROOT}`` semantics — two levels deeper than the marketplace cache root,
    so ``derive_cache_root(plugin_root)`` walks back to ``cache_root``.

    Drops a ``skills/`` marker so SEC-CD-3's plugin-directory plausibility check
    accepts the path; without a marker, ``resolve_plugin_root`` rejects an
    arbitrary explicit argument as untrusted.
    """
    plugin_root = cache_root / "codemap" / "0.1.0"
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "skills").mkdir(exist_ok=True)
    return plugin_root


# ---------------------------------------------------------------------------
# resolve_plugin_root
# ---------------------------------------------------------------------------


class TestResolvePluginRoot:
    """Cover explicit-arg and HOME-fallback resolution paths."""

    def test_returns_explicit_path_when_given(self, tmp_path: Path):
        """Explicit non-empty argument bypasses HOME discovery.

        SEC-CD-3 requires the directory to look like a real plugin (plugin.json,
        ``.claude-plugin/plugin.json``, ``agents/``, or ``skills/``); create the
        cheapest marker (``skills/``) so the validator accepts the path.
        """
        (tmp_path / "skills").mkdir()
        assert ci.resolve_plugin_root(str(tmp_path)) == tmp_path.resolve()

    def test_falls_back_to_home_glob(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Empty arg triggers ``~/.claude/plugins/cache`` glob and picks the result."""
        fake_home = tmp_path / "home"
        cache = fake_home / ".claude/plugins/cache"
        plugin_root = cache / "borda-ai-rig/codemap-py/0.5.0"
        plugin_root.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(fake_home))
        assert ci.resolve_plugin_root("") == plugin_root

    def test_returns_none_when_nothing_found(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No fallback path → ``None``."""
        monkeypatch.setenv("HOME", str(tmp_path))
        assert ci.resolve_plugin_root(None) is None


# ---------------------------------------------------------------------------
# derive_cache_root
# ---------------------------------------------------------------------------


def test_derive_cache_root_walks_two_levels():
    """Walks up two parents to reach the cache directory."""
    assert ci.derive_cache_root(Path("/a/b/c/d/e")) == Path("/a/b/c")


# ---------------------------------------------------------------------------
# find_files_with_marker
# ---------------------------------------------------------------------------


class TestFindFilesWithMarker:
    """Cover filename glob + marker substring + optional path-substring filter."""

    def test_returns_only_files_containing_marker(self, tmp_path: Path):
        """Files without the marker are excluded; matches are sorted."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "SKILL.md").write_text("hello scan-query world\n", encoding="utf-8")
        (tmp_path / "b").mkdir()
        (tmp_path / "b" / "SKILL.md").write_text("unrelated content\n", encoding="utf-8")
        (tmp_path / "c").mkdir()
        (tmp_path / "c" / "SKILL.md").write_text("command -v scan-query check\n", encoding="utf-8")

        result = ci.find_files_with_marker(tmp_path, "SKILL.md", "command -v scan-query")
        assert result == [tmp_path / "c" / "SKILL.md"]

    def test_path_substring_filter(self, tmp_path: Path):
        """``path_substr`` filters by path even when filename + marker match."""
        (tmp_path / "agents").mkdir()
        (tmp_path / "agents" / "foo.md").write_text("Structural context (codemap line\n", encoding="utf-8")
        (tmp_path / "skills").mkdir()
        (tmp_path / "skills" / "foo.md").write_text("Structural context (codemap line\n", encoding="utf-8")

        result = ci.find_files_with_marker(tmp_path, "*.md", "Structural context (codemap", "/agents/")
        assert result == [tmp_path / "agents" / "foo.md"]

    def test_empty_directory_returns_empty_list(self, tmp_path: Path):
        """No files → empty list (not an exception)."""
        assert ci.find_files_with_marker(tmp_path, "SKILL.md", "anything") == []


# ---------------------------------------------------------------------------
# missing_canonical_sites
# ---------------------------------------------------------------------------


class TestMissingCanonicalSites:
    """Cover regex matching for canonical injection sites."""

    def test_all_sites_present(self):
        """Every pattern matched → no missing sites."""
        patterns = ("develop/.*/skills/fix", "oss/.*/skills/review")
        paths = ["develop/0.1/skills/fix/SKILL.md", "oss/0.2/skills/review/SKILL.md"]
        assert ci.missing_canonical_sites(paths, patterns) == []

    def test_missing_sites_returned_in_order(self):
        """Patterns are returned in input order when not matched."""
        patterns = ("develop/.*/skills/fix", "develop/.*/skills/feature", "develop/.*/skills/refactor")
        paths = ["develop/0.1/skills/fix/SKILL.md"]
        assert ci.missing_canonical_sites(paths, patterns) == [
            "develop/.*/skills/feature",
            "develop/.*/skills/refactor",
        ]

    def test_no_paths_means_all_missing(self):
        """Empty path list returns every pattern."""
        patterns = ("oss/.*/skills/review", "oss/.*/skills/resolve")
        assert ci.missing_canonical_sites([], patterns) == list(patterns)


# ---------------------------------------------------------------------------
# build_audit_lines
# ---------------------------------------------------------------------------


class TestBuildAuditLines:
    """End-to-end formatter check on a synthetic cache layout."""

    def test_reports_injected_skills_and_missing_sites(self, tmp_path: Path):
        """Lists injected files, surfaces missing canonical sites, and reports agent state."""
        cache = _build_fake_cache(
            tmp_path,
            skill_sites=[
                "develop/0.1.0/skills/fix",
                "develop/0.1.0/skills/feature",
            ],
            agent_sites=[
                "foundry/0.1.0/agents/sw-engineer.md",
            ],
        )
        lines = ci.build_audit_lines(cache)
        joined = "\n".join(lines)

        assert "✓ 2 SKILL.md file(s) have the injection block:" in joined
        assert "develop/0.1.0/skills/fix/SKILL.md" in joined
        assert "develop/0.1.0/skills/feature/SKILL.md" in joined
        # Missing canonical sites surfaced individually.
        assert "missing injection in: develop/.*/skills/refactor/SKILL.md" in joined
        assert "missing injection in: oss/.*/skills/review/SKILL.md" in joined
        # Agent block found.
        assert "✓ 1 agent file(s) have codemap injection block" in joined

    def test_reports_empty_when_no_skill_files(self, tmp_path: Path):
        """No injected SKILL.md → warning + init recommendation."""
        lines = ci.build_audit_lines(tmp_path)
        joined = "\n".join(lines)
        assert "⚠ 0 SKILL.md files have injection block" in joined
        assert "Run /codemap-py:integration init" in joined
        assert "⚠ 0 agent .md files have codemap injection block" in joined


# ---------------------------------------------------------------------------
# run_audit + main
# ---------------------------------------------------------------------------


class TestRunAudit:
    """Cover ``run_audit`` outcome handling."""

    def test_missing_plugin_root_returns_exit_one(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """No plugin root found → exit code 1 with install hint."""
        monkeypatch.setenv("HOME", str(tmp_path))
        result = ci.run_audit(None)
        assert result.exit_code == 1
        assert any("Could not locate codemap plugin" in line for line in result.lines)

    def test_explicit_plugin_root_produces_audit(self, tmp_path: Path):
        """Explicit plugin root resolves cache and runs audit (exit 0)."""
        cache = _build_fake_cache(tmp_path, skill_sites=["develop/0.1/skills/fix"])
        plugin_root = _make_plugin_root(cache)
        result = ci.run_audit(str(plugin_root))
        assert result.exit_code == 0
        assert any("Skill injection audit" in line for line in result.lines)


class TestMain:
    """End-to-end CLI behaviour via ``main(argv)``."""

    def test_main_with_explicit_plugin_root(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
        """Explicit plugin root prints audit and returns 0."""
        cache = _build_fake_cache(tmp_path, skill_sites=["oss/0.2/skills/review"])
        plugin_root = _make_plugin_root(cache)
        rc = ci.main([str(plugin_root)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "Skill injection audit" in out
        assert "oss/0.2/skills/review/SKILL.md" in out

    def test_main_without_plugin_root_when_none_installed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """Empty arg + nothing under HOME → exit 1."""
        monkeypatch.setenv("HOME", str(tmp_path))
        rc = ci.main([])
        out = capsys.readouterr().out
        assert rc == 1
        assert "Could not locate codemap plugin" in out
