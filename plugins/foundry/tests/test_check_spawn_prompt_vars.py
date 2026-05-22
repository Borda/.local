"""Tests for check_spawn_prompt_vars bin script.

Covers markdown block detection, $VAR flagging, caller-substituted var filtering,
non-markdown $VAR not flagged, and CLI integration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_spawn_prompt_vars as cspv


def _file(tmp_path: Path, content: str, name: str = "SKILL.md") -> Path:
    if name == "SKILL.md":
        skill_dir = tmp_path / "myplugin" / "skills" / "myskill"
        skill_dir.mkdir(parents=True, exist_ok=True)
        f = skill_dir / name
    else:
        tpl_dir = tmp_path / "myplugin" / "skills" / "myskill" / "templates"
        tpl_dir.mkdir(parents=True, exist_ok=True)
        f = tpl_dir / name
    f.write_text(content, encoding="utf-8")
    return f


class TestCheckFile:
    """Covers check_file() violation detection."""

    def test_clean_no_markdown_blocks(self, tmp_path: Path) -> None:
        """File with no markdown blocks has no violations."""
        f = _file(tmp_path, "```bash\n$_FOUNDRY_SHARED/foo.md\n```\n")
        assert cspv.check_file(f) == []

    def test_dollar_var_in_markdown_block_flagged(self, tmp_path: Path) -> None:
        """$VAR inside markdown block is flagged C42."""
        content = "```markdown\nRead $_FOUNDRY_SHARED/foo.md\n```\n"
        f = _file(tmp_path, content)
        findings = cspv.check_file(f)
        assert len(findings) == 1
        assert "C42-CRITICAL" in findings[0]
        assert "_FOUNDRY_SHARED" in findings[0]
        assert "markdown block 1" in findings[0]

    def test_braced_var_in_markdown_block_flagged(self, tmp_path: Path) -> None:
        """${VAR} inside markdown block is also flagged."""
        content = "```markdown\nRead ${_FOUNDRY_SHARED}/foo.md\n```\n"
        f = _file(tmp_path, content)
        findings = cspv.check_file(f)
        assert any("_FOUNDRY_SHARED" in x for x in findings)

    def test_caller_substituted_var_not_flagged(self, tmp_path: Path) -> None:
        """Known caller-substituted vars like $RUN_DIR are not flagged."""
        content = "```markdown\nWrite to $RUN_DIR/out.md\n```\n"
        f = _file(tmp_path, content)
        assert cspv.check_file(f) == []

    def test_arguments_not_flagged(self, tmp_path: Path) -> None:
        """$ARGUMENTS is a valid runtime-injected var — not flagged."""
        content = "```markdown\nProcess $ARGUMENTS\n```\n"
        f = _file(tmp_path, content)
        assert cspv.check_file(f) == []

    def test_angle_bracket_template_not_flagged(self, tmp_path: Path) -> None:
        """<VAR> templates (no $) are not flagged."""
        content = "```markdown\nWrite to <RUN_DIR>/out.md\n```\n"
        f = _file(tmp_path, content)
        assert cspv.check_file(f) == []

    def test_dollar_var_outside_markdown_block_not_flagged(self, tmp_path: Path) -> None:
        """$VAR in prose or bash blocks outside markdown fences is not flagged."""
        content = "Prose with $_FOUNDRY_SHARED.\n```bash\necho $_FOUNDRY_SHARED\n```\n"
        f = _file(tmp_path, content)
        assert cspv.check_file(f) == []

    def test_same_var_reported_once_per_block(self, tmp_path: Path) -> None:
        """Same var on multiple lines in one block yields one finding."""
        content = "```markdown\n$_SHARED/a.md\n$_SHARED/b.md\n```\n"
        f = _file(tmp_path, content)
        findings = [x for x in cspv.check_file(f) if "_SHARED" in x]
        assert len(findings) == 1

    def test_two_blocks_each_with_var_yield_two_findings(self, tmp_path: Path) -> None:
        """Distinct vars in two separate markdown blocks each produce a finding."""
        content = "```markdown\n$FOO_VAR/a\n```\n```markdown\n$BAR_VAR/b\n```\n"
        f = _file(tmp_path, content)
        findings = cspv.check_file(f)
        assert len(findings) == 2
        assert any("FOO_VAR" in x and "block 1" in x for x in findings)
        assert any("BAR_VAR" in x and "block 2" in x for x in findings)

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file returns no findings instead of raising."""
        assert cspv.check_file(tmp_path / "missing.md") == []

    def test_template_md_file_scanned(self, tmp_path: Path) -> None:
        """Non-SKILL.md template file is also checked."""
        content = "```markdown\nRead $_FOUNDRY_SHARED/x.md\n```\n"
        f = _file(tmp_path, content, name="audit-fix-prompt.md")
        findings = cspv.check_file(f)
        assert any("C42" in x for x in findings)

    @pytest.mark.parametrize("var", ["_FOUNDRY_SHARED", "_FS", "CODEX_AVAILABLE", "BATCH_SZ"])
    def test_various_unexpanded_vars_flagged(self, tmp_path: Path, var: str) -> None:
        """Any unrecognised $VAR in markdown block is flagged."""
        content = f"```markdown\necho ${var}\n```\n"
        f = _file(tmp_path, content)
        assert any(var in x for x in cspv.check_file(f))


class TestMain:
    """Covers main() CLI integration."""

    def test_clean_file_exits_zero(self, tmp_path: Path) -> None:
        """All-clean files produce exit code 0."""
        _file(tmp_path, "```bash\necho hi\n```\n")
        assert cspv.main(["--scan-dir", str(tmp_path)]) == 0

    def test_violation_exits_one(self, tmp_path: Path) -> None:
        """File with unexpanded var produces exit code 1."""
        _file(tmp_path, "```markdown\nRead $_FOUNDRY_SHARED/x.md\n```\n")
        assert cspv.main(["--scan-dir", str(tmp_path)]) == 1

    def test_explicit_file_arg(self, tmp_path: Path) -> None:
        """Explicit file path argument is checked."""
        f = _file(tmp_path, "```markdown\nRead $_FOUNDRY_SHARED/x.md\n```\n")
        assert cspv.main([str(f)]) == 1

    def test_timeout_arg_accepted(self, tmp_path: Path) -> None:
        """--timeout flag is accepted without error."""
        _file(tmp_path, "no fences\n")
        assert cspv.main(["--scan-dir", str(tmp_path), "--timeout", "10"]) == 0
