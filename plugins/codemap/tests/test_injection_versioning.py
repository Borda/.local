"""Tests for versioned injection blocks: OUTDATED detection, marker-bounded re-inject, MISSING-after-update.

Covers:
  * an injected block whose version stamp trails the shipped version audits as OUTDATED (distinct from
    MISSING and current);
  * re-inject replaces only the sentinel-bounded region, preserving user text outside the markers;
  * a wired site whose block was removed (simulating a plugin update) audits as MISSING, and the
    re-inject path restores the current block.
"""

from __future__ import annotations

from pathlib import Path

import _injection_block as ib
import check_injection as ci
import inject_codemap as ic


def _inject_at_version(content: str, version: int) -> str:
    """Return ``content`` with a block at ``version`` injected (helper for OUTDATED simulation)."""
    return ic.inject_block(content, block=ib._render_block(version))


class TestOutdatedDetection:
    """A trailing-version block is classified OUTDATED, not current and not missing."""

    def test_current_block_classifies_current(self, tmp_path: Path):
        """A block stamped at the shipped version classifies as current."""
        skill = tmp_path / "SKILL.md"
        skill.write_text(ic.inject_block("intro\n\n## Step 1\ngo\n"), encoding="utf-8")
        assert ci.classify_block_version(skill) == "current"

    def test_trailing_version_classifies_outdated(self, tmp_path: Path):
        """A block stamped below the shipped version classifies as outdated."""
        skill = tmp_path / "SKILL.md"
        skill.write_text(_inject_at_version("intro\n\n## Step 1\ngo\n", ib.BLOCK_VERSION - 1), encoding="utf-8")
        assert ci.classify_block_version(skill) == "outdated"

    def test_audit_recorded_site_reports_outdated(self, tmp_path: Path):
        """A recorded site with a trailing-version block is reported OUTDATED by name."""
        skill = tmp_path / "skills" / "s" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text(_inject_at_version("intro\n\n## Step 1\ngo\n", ib.BLOCK_VERSION - 1), encoding="utf-8")
        lines = ci.audit_recorded_sites(["skills/s/SKILL.md"], tmp_path)
        joined = "\n".join(lines)
        assert "OUTDATED" in joined
        assert "skills/s/SKILL.md" in joined


class TestMarkerBoundedReinject:
    """Re-inject swaps only the sentinel-bounded region, preserving surrounding user text."""

    def test_reinject_preserves_user_text_outside_markers(self):
        """User text before and after the block survives a version-bump re-inject."""
        base = _inject_at_version("HEADER\n\n## Step 1\nbody\n", ib.BLOCK_VERSION - 1)
        with_user = base.replace("## Step 1", "USER NOTE\n\n## Step 1")

        refreshed = ic.inject_block(with_user)  # default block = current version

        assert "USER NOTE" in refreshed
        assert refreshed.startswith("HEADER")
        assert ib.parse_block_version(refreshed) == ib.BLOCK_VERSION
        assert refreshed.count(ib.BEGIN_SENTINEL) == 1

    def test_current_block_reinject_is_noop(self):
        """Re-injecting a current block is a byte-identical no-op."""
        once = ic.inject_block("intro\n\n## Step 1\ngo\n")
        assert ic.inject_block(once) == once


class TestMissingAfterUpdate:
    """A wired site whose block was removed (plugin update) audits MISSING; re-inject restores it."""

    def test_removed_block_reports_missing_then_reinjects(self, tmp_path: Path):
        """Simulate a plugin update wiping the block: check reports MISSING, re-inject restores it."""
        skill = tmp_path / "skills" / "s" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        original = "intro\n\n## Step 1\ngo\n"
        skill.write_text(ic.inject_block(original), encoding="utf-8")

        # Plugin update: the whole file is replaced by the upstream copy with no injection block.
        skill.write_text(original, encoding="utf-8")

        missing = ci.audit_recorded_sites(["skills/s/SKILL.md"], tmp_path)
        assert any("MISSING" in line for line in missing)

        # Re-inject path restores the current block.
        skill.write_text(ic.inject_block(skill.read_text(encoding="utf-8")), encoding="utf-8")
        restored = ci.audit_recorded_sites(["skills/s/SKILL.md"], tmp_path)
        joined = "\n".join(restored)
        assert "MISSING" not in joined
        assert "OUTDATED" not in joined
        assert "✓ skills/s/SKILL.md" in joined
