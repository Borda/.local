"""Tests for personal-skill discovery and integration.json-driven canonical-site audit.

Covers:
  * ``discover_personal_candidates`` finds ``.claude/skills``, ``.claude/agents`` (project) and
    ``~/.claude/skills`` (user home) targets;
  * a project with only a personal ``.claude/skills/my-skill/SKILL.md`` → discovered, wired, and its
    site persisted to integration.json;
  * ``check_injection`` audits the persisted personal site by name (PASS) from integration.json,
    and falls back to the borda default list only when no record is present.
"""

from __future__ import annotations

from pathlib import Path

import _injection_block as ib
import check_injection as ci
import inject_codemap as ic


def _personal_skill(root: Path, name: str = "my-skill") -> Path:
    """Create ``root/.claude/skills/<name>/SKILL.md`` with inject-worthy content; return its path."""
    skill = root / ".claude" / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("import os\n\n```bash\nls\n```\n\n## Step 1\ndo the thing\n", encoding="utf-8")
    return skill


class TestDiscoverPersonalCandidates:
    """Personal skills/agents under .claude (project + user home) are discovered."""

    def test_finds_project_and_home_personal_targets(self, tmp_path: Path):
        """Project .claude/skills + .claude/agents and home ~/.claude/skills are all found."""
        project = tmp_path / "project"
        home = tmp_path / "home"
        proj_skill = _personal_skill(project)
        proj_agent = project / ".claude" / "agents" / "helper.md"
        proj_agent.parent.mkdir(parents=True, exist_ok=True)
        proj_agent.write_text("agent body\n", encoding="utf-8")
        home_skill = _personal_skill(home, name="home-skill")

        found = ic.discover_personal_candidates(project, home=home)

        assert proj_skill in found
        assert proj_agent in found
        assert home_skill in found

    def test_empty_when_no_personal_targets(self, tmp_path: Path):
        """No .claude tree under project or home → empty list, not an error."""
        assert ic.discover_personal_candidates(tmp_path / "project", home=tmp_path / "home") == []


class TestPersonalOnlyProjectRoundTrip:
    """A project with only a personal skill → discovered, wired, audited PASS by name."""

    def test_personal_skill_discovered_wired_and_recorded(self, tmp_path: Path):
        """The personal skill is injected and its site persisted to integration.json."""
        project = tmp_path / "project"
        home = tmp_path / "home"
        home.mkdir()
        skill = _personal_skill(project)
        # A plugin root with no skills of its own — all candidates come from the personal tree.
        plugin_root = tmp_path / "plugin"
        (plugin_root / "skills").mkdir(parents=True)
        integration_dir = project / ".cache" / "codemap"

        report = ic.build_report(
            plugin_root,
            apply=True,
            project_root=project,
            integration_dir=integration_dir,
            home=home,
        )

        assert report["summary"]["applied"] == 1
        assert ib.SCAN_QUERY_MARKER in skill.read_text(encoding="utf-8")
        sites = ib.load_integration_sites(integration_dir)
        assert sites == [".claude/skills/my-skill/SKILL.md"]

    def test_check_reports_personal_site_pass_by_name(self, tmp_path: Path):
        """check_injection audits the recorded personal site PASS by name from integration.json."""
        project = tmp_path / "project"
        home = tmp_path / "home"
        home.mkdir()
        _personal_skill(project)
        plugin_root = tmp_path / "plugin"
        (plugin_root / "skills").mkdir(parents=True)
        integration_dir = project / ".cache" / "codemap"
        ic.build_report(plugin_root, apply=True, project_root=project, integration_dir=integration_dir, home=home)

        # Audit uses the persisted record; a plugin cache with no skills produces no borda default.
        lines = ci.build_audit_lines(plugin_root, integration_dir=integration_dir)
        joined = "\n".join(lines)

        assert "integration.json" in joined
        assert "✓ .claude/skills/my-skill/SKILL.md" in joined


class TestCanonicalSiteSource:
    """The canonical-site source prefers integration.json, else the borda default when detected."""

    def test_borda_default_used_without_record(self, tmp_path: Path):
        """No integration.json + develop plugin present → borda default patterns drive the check."""
        (tmp_path / "develop").mkdir()
        assert ci.borda_default_sites(tmp_path) == ci.CANONICAL_INJECTION_SITES

    def test_no_default_for_stranger_cache(self, tmp_path: Path):
        """No borda plugins in cache → empty default (stranger project audited only by record)."""
        assert ci.borda_default_sites(tmp_path) == ()

    def test_record_takes_precedence_over_default(self, tmp_path: Path):
        """With both a record and develop present, the record's recorded sites drive the audit."""
        cache = tmp_path / "cache"
        (cache / "develop").mkdir(parents=True)
        project = tmp_path / "project"
        integration_dir = project / ".cache" / "codemap"
        ib.save_integration_sites(integration_dir, [".claude/skills/x/SKILL.md"])
        skill = project / ".claude" / "skills" / "x" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(ic.inject_block("intro\n\n## Step 1\ngo\n"), encoding="utf-8")

        lines = ci.build_audit_lines(cache, integration_dir=integration_dir)
        joined = "\n".join(lines)

        # Record-driven audit names the personal site; borda "missing injection in: develop/..." absent.
        assert "✓ .claude/skills/x/SKILL.md" in joined
        assert "missing injection in: develop/.*/skills/fix" not in joined
