"""Tests for inject_codemap bin script.

Focuses on the append-fallback idempotency guard (HI-6): re-running injection on an
already-injected SKILL.md — via either the step-heading or the append-fallback path — must be a
byte-identical no-op rather than duplicating the block.
"""

from __future__ import annotations

from pathlib import Path


import inject_codemap as ic


# ---------------------------------------------------------------------------
# inject_block — idempotency
# ---------------------------------------------------------------------------


class TestInjectBlockIdempotency:
    """Cover the marker-guarded no-op on re-injection (HI-6)."""

    def test_append_fallback_second_run_is_byte_identical(self):
        """No step heading → append path; second run must not append a second block."""
        content = "intro prose only\nno step heading here\n"
        once = ic.inject_block(content)
        twice = ic.inject_block(once)
        assert once != content  # first run injected
        assert twice == once  # second run is a no-op
        assert once.count(ic.INJECTION_MARKER) == 1

    def test_step_heading_second_run_is_byte_identical(self):
        """Step-heading path likewise injects once and no-ops on re-run."""
        content = "intro\n## Step 1\ndo it\n"
        once = ic.inject_block(content)
        twice = ic.inject_block(once)
        assert once != content
        assert twice == once
        assert once.count(ic.INJECTION_MARKER) == 1

    def test_preexisting_marker_returns_content_unchanged(self):
        """Content already carrying the marker is returned verbatim (no second insertion)."""
        content = f"prose\n{ic.INJECTION_MARKER} (optional)\nmore\n## Step 1\nbody\n"
        assert ic.inject_block(content) == content


# ---------------------------------------------------------------------------
# evaluate_candidate + build_report — apply-mode idempotency on disk
# ---------------------------------------------------------------------------


class TestApplyIdempotency:
    """Double-apply on the same file yields a byte-identical result on disk."""

    def _make_plugin(self, root: Path, skill_body: str) -> Path:
        """Materialise ``<root>/skills/demo/SKILL.md`` with ``skill_body`` and return ``root``."""
        skill = root / "skills" / "demo" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(skill_body, encoding="utf-8")
        return root

    def test_double_apply_is_byte_identical(self, tmp_path: Path):
        """Applying injection twice leaves the SKILL.md byte-identical after the first run."""
        # Body scores >=2 (python marker + bash block) so the action is "inject".
        body = "import os\n\n```bash\nls\n```\n\n## Step 1\ndo the thing\n"
        root = self._make_plugin(tmp_path, body)
        skill = root / "skills" / "demo" / "SKILL.md"

        ic.build_report(root, apply=True)
        after_first = skill.read_text(encoding="utf-8")
        ic.build_report(root, apply=True)
        after_second = skill.read_text(encoding="utf-8")

        assert after_first != body  # first apply injected
        assert after_second == after_first  # second apply is a no-op
        assert after_first.count(ic.INJECTION_MARKER) == 1
