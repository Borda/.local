"""Tests for the plugin-agnostic codemap context/gates contract and its consumer wrappers.

Covers:
  * the shipped context contract carries its version header + every required section;
  * the shipped gates contract carries Gate A / Gate B machinery with all options;
  * develop/oss wrapper files reference the contract via the sanctioned cache-path pattern,
    keep a graceful-degradation fallback, and add only their per-plugin surface;
  * stranger-fixture — injecting the block on a fresh project yields a reference line that
    resolves to the shipped contract file.

Sibling-plugin wrapper tests skip when the sibling files are absent (installed-plugin isolation:
a lone codemap install has no develop/oss tree next to it).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from codemap_py import integration

_PLUGIN_ROOT = Path(__file__).parent.parent.parent
_PLUGINS_DIR = _PLUGIN_ROOT.parent
_SHARED = _PLUGIN_ROOT / "claude-skills" / "_shared"
_CONTEXT_CONTRACT = _SHARED / "codemap-context.md"
_GATES_CONTRACT = _SHARED / "codemap-gates.md"

# The sanctioned installed-plugin resolution pattern wrappers must use (never a bare relative path).
_CACHE_PATTERN = "ls -td ~/.claude/plugins/cache/borda-ai-rig/codemap-py/*/claude-skills/_shared"
_SOURCE_FALLBACK = "plugins/codemap-py/claude-skills/_shared"

_DEVELOP_CONTEXT = _PLUGINS_DIR / "cc_develop" / "skills" / "_shared" / "codemap-context.md"
_DEVELOP_GATES = _PLUGINS_DIR / "cc_develop" / "skills" / "_shared" / "codemap-gates.md"
_OSS_GATES = _PLUGINS_DIR / "cc_oss" / "skills" / "_shared" / "codemap-gates.md"


class TestContextContract:
    """The shipped context contract is the plugin-agnostic single source of truth."""

    def test_has_version_header(self):
        """Contract header carries an explicit version string feeding the injection version check."""
        text = _CONTEXT_CONTRACT.read_text(encoding="utf-8")
        assert "# Codemap context contract — v2" in text

    def test_declares_cross_plugin_consumers(self):
        """Consumer header names the managed-block contract and wrapper consumers."""
        text = _CONTEXT_CONTRACT.read_text(encoding="utf-8")
        assert "<!-- file: codemap-context.md" in text
        assert "codemap-py.integration.v1" in text

    @pytest.mark.parametrize(
        "section",
        [
            pytest.param("## Target derivation — pluggable (consumer supplies)", id="pluggable-target"),
            pytest.param("## Core query map", id="core-query-map"),
            pytest.param("## Batch pre-flight pattern", id="batch-preflight"),
            pytest.param("## Evidence-line contract", id="evidence-line"),
            pytest.param("## Coverage metadata in output", id="coverage-metadata"),
            pytest.param("## Effort-tier guidance", id="effort-tier"),
            pytest.param("## Extended scan — multi-file / API changes", id="extended-scan"),
            pytest.param("## Targeted-edit pattern (known symbol, large file)", id="targeted-edit"),
        ],
    )
    def test_carries_required_section(self, section: str):
        """Every generic section the wrappers delegate to must be present in the contract."""
        assert section in _CONTEXT_CONTRACT.read_text(encoding="utf-8")

    def test_target_derivation_is_pluggable(self):
        """Target derivation is explicitly consumer-supplied, not baked into the generic contract."""
        text = _CONTEXT_CONTRACT.read_text(encoding="utf-8")
        assert "consumer-supplied inputs" in text
        assert "contract doesn't derive them" in text

    def test_carries_evidence_line_and_completeness_semantics(self):
        """The evidence line and all four completeness states are defined once in the contract."""
        text = _CONTEXT_CONTRACT.read_text(encoding="utf-8")
        assert "codemap_evidence:" in text
        for state in ("exhaustive", "partial", "stale", "unknown"):
            assert state in text

    def test_block_reference_target_matches_contract(self):
        """The managed block identifies the shipped integration contract."""
        body = integration._managed_block_body("claude", "develop", "1.0.0")
        rendered = integration._render_managed_block(body)
        assert "Contract: shared/integration-contract.md" in rendered
        assert (_PLUGIN_ROOT / "shared" / "integration-contract.md").is_file()


class TestGatesContract:
    """The shipped gates contract carries the plugin-agnostic Gate A / Gate B machinery."""

    def test_has_version_header_and_consumer_declaration(self):
        """Gates contract carries its version header and a cross-plugin consumer declaration."""
        text = _GATES_CONTRACT.read_text(encoding="utf-8")
        assert "# Codemap gates contract — v2" in text
        assert "<!-- file: codemap-gates.md" in text

    @pytest.mark.parametrize(
        "marker",
        [
            pytest.param("## Gate A — missing index", id="gate-a"),
            pytest.param("## Gate B — stale index", id="gate-b"),
            pytest.param("Continue without codemap", id="a-continue"),
            pytest.param("Build index now", id="a-build"),
            pytest.param("Abort", id="a-abort"),
            pytest.param("Rebuild now", id="b-rebuild"),
            pytest.param("Continue with stale data", id="b-stale"),
            pytest.param("Skip codemap", id="b-skip"),
            pytest.param("run `scan-index` in the foreground", id="build-scan-index"),
        ],
    )
    def test_carries_gate_machinery(self, marker: str):
        """Both gates and every option/action survive in the generic gates contract."""
        assert marker in _GATES_CONTRACT.read_text(encoding="utf-8")

    def test_build_action_never_model_invokes_disabled_skill(self):
        """Build/rebuild action must not Skill()-call scan-codebase — it is disable-model-invocation:true."""
        assert 'Skill(skill="codemap:scan-codebase")' not in _GATES_CONTRACT.read_text(encoding="utf-8")


@pytest.mark.skipif(not _DEVELOP_CONTEXT.is_file(), reason="develop plugin sibling tree absent")
class TestDevelopWrapper:
    """The develop context wrapper references the contract and keeps only its per-plugin surface."""

    def test_references_contract_via_cache_pattern(self):
        """Wrapper resolves the contract via the sanctioned cache path with source-tree fallback."""
        text = _DEVELOP_CONTEXT.read_text(encoding="utf-8")
        assert _CACHE_PATTERN in text
        assert _SOURCE_FALLBACK in text
        assert "codemap-context.md" in text

    def test_never_uses_bare_relative_cross_plugin_path(self):
        """Wrapper must not cross-reference the codemap plugin via a bare relative path."""
        text = _DEVELOP_CONTEXT.read_text(encoding="utf-8")
        assert "../codemap" not in text

    def test_keeps_graceful_fallback(self):
        """Wrapper degrades gracefully when the codemap plugin is absent — never a broken load."""
        text = _DEVELOP_CONTEXT.read_text(encoding="utf-8")
        assert "Fallback when codemap plugin absent" in text
        assert "Never break load." in text

    @pytest.mark.parametrize(
        "surface",
        [
            pytest.param("uncovered --top 20", id="qa-uncovered"),
            pytest.param("mock-rdeps", id="qa-mock"),
            pytest.param("undocumented", id="doc-undocumented"),
            pytest.param("codemap_scan.py", id="batch-producer"),
            pytest.param("codemap_cache.py", id="review-resolve-cache"),
            pytest.param("Semble companion", id="semble"),
        ],
    )
    def test_retains_per_plugin_surface(self, surface: str):
        """Develop-specific dimensions, batch/cache scripts, and semble stay in the wrapper."""
        assert surface in _DEVELOP_CONTEXT.read_text(encoding="utf-8")


@pytest.mark.skipif(not _DEVELOP_GATES.is_file(), reason="develop plugin sibling tree absent")
class TestDevelopGatesWrapper:
    """The develop gates wrapper references the gates contract and supplies its skip flag."""

    def test_references_gates_contract_via_cache_pattern(self):
        """Wrapper resolves the gates contract via the sanctioned cache path with fallback."""
        text = _DEVELOP_GATES.read_text(encoding="utf-8")
        assert _CACHE_PATTERN in text
        assert _SOURCE_FALLBACK in text
        assert "codemap-gates.md" in text

    def test_supplies_develop_skip_flag_and_fallback(self):
        """Wrapper carries develop's skip flag and a graceful fallback."""
        text = _DEVELOP_GATES.read_text(encoding="utf-8")
        assert "CODEMAP_RAW=auto" in text
        assert "Never break load." in text


@pytest.mark.skipif(not _OSS_GATES.is_file(), reason="oss plugin sibling tree absent")
class TestOssGatesWrapper:
    """The oss gates wrapper references the gates contract and supplies its skip flag."""

    def test_references_gates_contract_via_cache_pattern(self):
        """Wrapper resolves the gates contract via the sanctioned cache path with fallback."""
        text = _OSS_GATES.read_text(encoding="utf-8")
        assert _CACHE_PATTERN in text
        assert _SOURCE_FALLBACK in text
        assert "codemap-gates.md" in text

    def test_supplies_oss_skip_flag_and_fallback(self):
        """Wrapper carries oss's skip flag and a graceful fallback."""
        text = _OSS_GATES.read_text(encoding="utf-8")
        assert "CODEMAP_FORCE_OFF=false" in text
        assert "Never break the load." in text


def _commit_fixture(root: Path) -> None:
    """Commit the fixture baseline so apply's dirty-overlap guard can run honestly."""
    for args in (
        ("init", "-q"),
        ("config", "user.email", "t@t.t"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-q", "-m", "baseline"),
    ):
        result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
        assert result.returncode == 0, result.stderr


class TestStrangerFixtureManagedBlock:
    """A fresh consumer uses the current plan/apply protocol, never legacy injection."""

    def test_apply_plan_writes_contract_bound_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Plan then apply writes the allowlisted oss gates block with the contract reference."""
        root = tmp_path / "fixture"
        manifest = root / "plugins" / "cc_oss" / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "oss", "version": "1.0.0"}) + "\n", encoding="utf-8")
        _commit_fixture(root)
        monkeypatch.chdir(root)

        plan = integration.build_plan("claude", ["oss"], None, root / "plugins" / "codemap-py")
        result = integration.apply_plan(
            plan, plan["plan_sha256"], root / "plugins" / "codemap-py", tmp_path / "journal"
        )

        assert result["state"] == "complete"
        target = root / "plugins" / "cc_oss" / "skills" / "_shared" / "codemap-gates.md"
        assert "Contract: shared/integration-contract.md" in target.read_text(encoding="utf-8")
