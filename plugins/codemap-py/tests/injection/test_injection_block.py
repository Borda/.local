"""Tests for the canonical injection block (single source of truth) and inject→check round-trip.

Covers:
  * the shared block carries the scan-query probe, real queries, an evidence line, a version stamp,
    and the reference to the shared context contract;
  * inject then audit a fresh fixture project → the wired site is listed PASS by name;
  * the README's documented block markers stay consistent with the shipped BLOCK (drift guard).
"""

from __future__ import annotations

from pathlib import Path

import _injection_block as ib
import check_injection as ci
import inject_codemap as ic

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_README = _PLUGIN_ROOT / "README.md"
_SHARED_CONTEXT = _PLUGIN_ROOT / "claude-skills" / "_shared" / "codemap-context.md"


class TestBlockContent:
    """The canonical BLOCK carries every element init and check depend on."""

    def test_block_has_scan_query_probe(self):
        """check_injection keys on this literal token — it must be present in BLOCK."""
        assert ib.SCAN_QUERY_MARKER in ib.BLOCK
        assert ib.SCAN_QUERY_MARKER == "command -v scan-query"

    def test_block_runs_real_queries(self):
        """Block runs the central baseline plus a derived-target reverse-dependency query."""
        assert "central --top 3" in ib.BLOCK
        assert "fn-rdeps" in ib.BLOCK
        assert "rdeps" in ib.BLOCK

    def test_block_emits_evidence_line(self):
        """Every run emits a codemap_evidence: line for retrieval-reliability reporting."""
        assert "codemap_evidence:" in ib.BLOCK

    def test_block_carries_version_stamp(self):
        """Block carries the current codemap-block: vN stamp, parseable back to BLOCK_VERSION."""
        assert f"codemap-block: v{ib.BLOCK_VERSION}" in ib.BLOCK
        assert ib.parse_block_version(ib.BLOCK) == ib.BLOCK_VERSION

    def test_block_is_sentinel_bounded(self):
        """Begin/end sentinels bound the re-injectable region."""
        assert ib.BEGIN_SENTINEL in ib.BLOCK
        assert ib.END_SENTINEL in ib.BLOCK
        assert ib.BLOCK.index(ib.BEGIN_SENTINEL) < ib.BLOCK.index(ib.END_SENTINEL)

    def test_block_references_shared_contract(self):
        """Block is a loader — it points at the shared context contract file that exists on disk."""
        assert "claude-skills/_shared/codemap-context.md" in ib.BLOCK
        assert _SHARED_CONTEXT.is_file()

    def test_marker_matches_across_consumers(self):
        """inject and check import the same MARKER / SCAN_QUERY_MARKER — no drift between them."""
        assert ic.INJECTION_MARKER == ib.MARKER
        assert ci.SKILL_INJECTION_MARKER == ib.SCAN_QUERY_MARKER


class TestSharedContextStub:
    """The shared context stub carries the loader contract the block references."""

    def test_stub_has_consumer_header_and_contract(self):
        """Stub declares its consumer header and the evidence-line rule so it is not orphan-pruned."""
        text = _SHARED_CONTEXT.read_text(encoding="utf-8")
        assert "<!-- file: codemap-context.md" in text
        assert "codemap_evidence:" in text
        assert "central --top 3" in text


def _make_fixture_plugin(root: Path) -> Path:
    """Materialise a minimal plugin tree with one inject-worthy SKILL.md; return the plugin root."""
    skill = root / "skills" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    # Body scores >=2 (python marker + bash block) → action "inject".
    skill.write_text("import os\n\n```bash\nls\n```\n\n## Step 1\ndo the thing\n", encoding="utf-8")
    return root


class TestInjectCheckRoundTrip:
    """inject on a fresh fixture, then audit it → the wired site is listed PASS by name."""

    def test_round_trip_lists_wired_site_current(self, tmp_path: Path):
        """After apply, the injected SKILL.md is audited as current (PASS) via its recorded site."""
        plugin_root = _make_fixture_plugin(tmp_path / "plugin")
        (tmp_path / "plugin").mkdir(exist_ok=True)
        project_root = tmp_path / "project"
        project_root.mkdir()
        integration_dir = project_root / ".cache" / "codemap"
        empty_home = tmp_path / "home"  # hermetic — no real ~/.claude personal skills
        empty_home.mkdir()

        report = ic.build_report(
            plugin_root,
            apply=True,
            project_root=plugin_root,
            integration_dir=integration_dir,
            home=empty_home,
        )
        assert report["summary"]["applied"] == 1
        assert (integration_dir / "integration.json").is_file()

        skill = plugin_root / "skills" / "demo" / "SKILL.md"
        injected = skill.read_text(encoding="utf-8")
        assert ib.SCAN_QUERY_MARKER in injected
        assert ib.parse_block_version(injected) == ib.BLOCK_VERSION

        # Audit recorded sites directly (base_dir = plugin_root, where sites were recorded relative).
        sites = ib.load_integration_sites(integration_dir)
        assert sites == ["skills/demo/SKILL.md"]
        lines = ci.audit_recorded_sites(sites, plugin_root)
        joined = "\n".join(lines)
        assert "✓ skills/demo/SKILL.md" in joined
        assert "OUTDATED" not in joined
        assert "MISSING" not in joined


class TestReadmeDrift:
    """The README must not resurface the retired manual-injection wiring workflow."""

    # The positive "README documents the BLOCK markers" guard was retired in 0.26.0: the
    # manual-injection user workflow (`integration init`) is gone, so the README no longer
    # documents `_injection_block.py`'s hand-wiring markers. The `_injection_block.py`
    # machinery itself lingers as internal code until its Phase-5 removal.

    def test_readme_does_not_carry_stale_locate_helper(self):
        """The old locate_scan_query.py-based manual block must be gone from the README snippet."""
        readme = _README.read_text(encoding="utf-8")
        # The manual-injection section no longer hand-rolls a divergent soft-check block.
        assert "scan-query deps" not in readme
