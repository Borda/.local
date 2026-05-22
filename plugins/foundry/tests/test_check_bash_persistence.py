"""Tests for check_bash_persistence bin script.

Covers block extraction, assignment/reference detection, cross-block violation
detection, env-var filtering, and CLI integration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_bash_persistence as cbp


def _skill(tmp_path: Path, content: str) -> Path:
    skill_dir = tmp_path / "myplugin" / "skills" / "myskill"
    skill_dir.mkdir(parents=True)
    f = skill_dir / "SKILL.md"
    f.write_text(content, encoding="utf-8")
    return f


class TestExtractBashBlocks:
    """Covers extract_bash_blocks() block boundary detection."""

    def test_single_block_returned(self) -> None:
        """Single bash fence yields one block body."""
        assert cbp.extract_bash_blocks("```bash\nFOO=1\n```\n") == ["FOO=1\n"]

    def test_two_blocks_returned_in_order(self) -> None:
        """Two bash fences yield two bodies in document order."""
        text = "```bash\nA=1\n```\nprose\n```bash\nB=2\n```\n"
        blocks = cbp.extract_bash_blocks(text)
        assert len(blocks) == 2
        assert "A=1" in blocks[0]
        assert "B=2" in blocks[1]

    def test_no_fences_returns_empty(self) -> None:
        """File with no bash fences returns empty list."""
        assert cbp.extract_bash_blocks("just prose\n") == []

    def test_non_bash_fence_ignored(self) -> None:
        """Python fenced block is not included."""
        assert cbp.extract_bash_blocks("```python\nFOO=1\n```\n") == []


class TestAssignedVars:
    """Covers assigned_vars() variable assignment detection."""

    def test_simple_assignment(self) -> None:
        """Plain VAR=value is detected."""
        assert "FOO" in cbp.assigned_vars("FOO=bar\n")

    def test_export_prefix(self) -> None:
        """export VAR=value is detected."""
        assert "FOO" in cbp.assigned_vars("export FOO=bar\n")

    def test_local_prefix(self) -> None:
        """local VAR=value is detected."""
        assert "FOO" in cbp.assigned_vars("local FOO=bar\n")

    def test_comment_line_skipped(self) -> None:
        """Assignment on a comment line is not detected."""
        assert cbp.assigned_vars("# FOO=bar\n") == frozenset()

    def test_indented_assignment(self) -> None:
        """Indented assignment is detected."""
        assert "FOO" in cbp.assigned_vars("  FOO=bar\n")

    def test_subshell_assignment(self) -> None:
        """FOO=$(cmd) is detected."""
        assert "FOO" in cbp.assigned_vars("FOO=$(date)\n")

    @pytest.mark.parametrize("line", ["echo $FOO\n", '[ "$FOO" = "x" ]\n'])
    def test_reference_not_treated_as_assignment(self, line: str) -> None:
        """Variable reference without = at correct position is not an assignment."""
        assert cbp.assigned_vars(line) == frozenset()


class TestReferencedVars:
    """Covers referenced_vars() variable reference detection."""

    def test_dollar_var(self) -> None:
        """$VAR is detected."""
        assert "FOO" in cbp.referenced_vars("echo $FOO\n")

    def test_braced_var(self) -> None:
        """${VAR} is detected."""
        assert "FOO" in cbp.referenced_vars("echo ${FOO}\n")

    def test_env_var_filtered(self) -> None:
        """Known env vars like $HOME are not returned."""
        assert "HOME" not in cbp.referenced_vars("echo $HOME\n")

    def test_single_char_filtered(self) -> None:
        """Single-char vars like $f are not returned."""
        assert "f" not in cbp.referenced_vars("for f in *; do echo $f; done\n")

    def test_multiple_refs_on_one_line(self) -> None:
        """Multiple $VAR references on one line are all detected."""
        refs = cbp.referenced_vars("cp $SRC $DEST\n")
        assert "SRC" in refs
        assert "DEST" in refs

    def test_empty_block_returns_empty(self) -> None:
        """Empty block yields no references."""
        assert cbp.referenced_vars("") == frozenset()


class TestCheckFile:
    """Covers check_file() end-to-end violation detection."""

    def test_clean_single_block(self, tmp_path: Path) -> None:
        """Single bash block with no cross-block refs passes."""
        f = _skill(tmp_path, "```bash\nFOO=1\necho $FOO\n```\n")
        assert cbp.check_file(f) == []

    def test_clean_same_block_assign_and_ref(self, tmp_path: Path) -> None:
        """Assign and reference in same block — not a violation."""
        content = "```bash\nBAR=x\n```\n```bash\nBAZ=y\necho $BAZ\n```\n"
        f = _skill(tmp_path, content)
        assert cbp.check_file(f) == []

    def test_cross_block_violation_detected(self, tmp_path: Path) -> None:
        """Var assigned in block 1, referenced in block 2 is flagged C41."""
        content = "```bash\nFOO=bar\n```\n```bash\necho $FOO\n```\n"
        f = _skill(tmp_path, content)
        findings = cbp.check_file(f)
        assert len(findings) == 1
        assert "C41-CRITICAL" in findings[0]
        assert "FOO" in findings[0]
        assert "block 1" in findings[0]
        assert "block 2" in findings[0]

    def test_skip_var_assigned_env_var_not_flagged(self, tmp_path: Path) -> None:
        """LOCAL_MODE referenced but never assigned — not flagged (env var)."""
        content = '```bash\necho start\n```\n```bash\n[ "$LOCAL_MODE" = "true" ]\n```\n'
        f = _skill(tmp_path, content)
        assert cbp.check_file(f) == []

    def test_var_assigned_in_block2_referenced_in_block3_flagged(self, tmp_path: Path) -> None:
        """Assign in block 2, reference in block 3 is flagged with correct block numbers."""
        content = "```bash\necho a\n```\n```bash\nTS=$(date)\n```\n```bash\necho $TS\n```\n"
        f = _skill(tmp_path, content)
        findings = cbp.check_file(f)
        assert any("block 2" in x and "block 3" in x for x in findings)

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        """Missing file returns no findings instead of raising."""
        assert cbp.check_file(tmp_path / "missing.md") == []

    def test_file_with_one_block_skipped(self, tmp_path: Path) -> None:
        """Single-block files are skipped — no cross-block issue possible."""
        f = _skill(tmp_path, "```bash\nFOO=1\n```\n")
        assert cbp.check_file(f) == []


class TestMain:
    """Covers main() CLI integration."""

    def test_clean_file_exits_zero(self, tmp_path: Path) -> None:
        """All-clean files produce exit code 0."""
        _skill(tmp_path, "```bash\nFOO=1\necho $FOO\n```\n")
        rc = cbp.main(["--scan-dir", str(tmp_path)])
        assert rc == 0

    def test_violation_exits_one(self, tmp_path: Path) -> None:
        """File with cross-block ref produces exit code 1."""
        _skill(tmp_path, "```bash\nFOO=1\n```\n```bash\necho $FOO\n```\n")
        rc = cbp.main(["--scan-dir", str(tmp_path)])
        assert rc == 1

    def test_explicit_file_arg(self, tmp_path: Path) -> None:
        """Explicit file path argument is checked."""
        f = _skill(tmp_path, "```bash\nFOO=1\n```\n```bash\necho $FOO\n```\n")
        assert cbp.main([str(f)]) == 1

    def test_timeout_arg_accepted(self, tmp_path: Path) -> None:
        """--timeout flag is accepted without error."""
        _skill(tmp_path, "```bash\nFOO=1\necho $FOO\n```\n")
        assert cbp.main(["--scan-dir", str(tmp_path), "--timeout", "15"]) == 0
