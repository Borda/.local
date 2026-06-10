"""Tests for check_tag_symmetry bin script.

Covers empty-block detection, unbalanced tag detection, clean files, and CLI integration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import check_tag_symmetry as cts


class TestCheckFile:
    """Covers check_file() for individual file scenarios."""

    def test_clean_file_returns_empty(self, tmp_path: Path) -> None:
        """File with properly balanced non-empty tags returns no violations."""
        f = tmp_path / "ok.md"
        f.write_text("<objective>\ncontent\n</objective>\n", encoding="utf-8")
        assert cts.check_file(f) == []

    def test_empty_block_detected(self, tmp_path: Path) -> None:
        """Empty structural block returns one violation."""
        f = tmp_path / "bad.md"
        f.write_text("<objective></objective>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert len(violations) == 1
        assert "empty block <objective></objective>" in violations[0]

    def test_whitespace_only_block_detected(self, tmp_path: Path) -> None:
        """Block with only whitespace between tags is flagged as empty."""
        f = tmp_path / "ws.md"
        f.write_text("<notes>   </notes>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert any("empty block" in v and "<notes>" in v for v in violations)

    def test_unbalanced_open_without_close(self, tmp_path: Path) -> None:
        """Tag opened but never closed is flagged as unbalanced."""
        f = tmp_path / "unclosed.md"
        f.write_text("<workflow>\ncontent\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert any("unbalanced" in v and "<workflow>" in v for v in violations)

    def test_unbalanced_close_without_open(self, tmp_path: Path) -> None:
        """Close tag without matching open tag is flagged as unbalanced."""
        f = tmp_path / "unopened.md"
        f.write_text("content\n</inputs>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert any("unbalanced" in v and "<inputs>" in v for v in violations)

    def test_unreadable_file_returns_error(self, tmp_path: Path) -> None:
        """Non-existent path returns cannot-read violation instead of raising."""
        fake = tmp_path / "ghost.md"
        result = cts.check_file(fake)
        assert len(result) == 1
        assert "cannot read" in result[0]

    def test_multiple_tags_each_violation_reported(self, tmp_path: Path) -> None:
        """File with two empty blocks returns two violations."""
        f = tmp_path / "multi.md"
        f.write_text("<objective></objective>\n<notes></notes>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert len(violations) == 2

    def test_non_structural_tag_ignored(self, tmp_path: Path) -> None:
        """Tags not in the structural list are not checked."""
        f = tmp_path / "other.md"
        f.write_text("<example></example>\n<code></code>\n", encoding="utf-8")
        assert cts.check_file(f) == []

    def test_html_comment_with_tag_names_not_flagged(self, tmp_path: Path) -> None:
        """Structural tag names mentioned inside HTML comments don't inflate open count."""
        f = tmp_path / "comment.md"
        f.write_text(
            "<!-- Tag convention: <role>, <workflow>, <notes> are structural. -->\n"
            "<role>\ncontent\n</role>\n"
            "<workflow>\ncontent\n</workflow>\n"
            "<notes>\ncontent\n</notes>\n",
            encoding="utf-8",
        )
        assert cts.check_file(f) == []

    def test_code_fence_content_not_flagged_as_empty(self, tmp_path: Path) -> None:
        """Block containing only a code fence is not flagged as empty."""
        f = tmp_path / "fence.md"
        f.write_text(
            "<constants>\n\n```yaml\nKEY: value\n```\n\n</constants>\n",
            encoding="utf-8",
        )
        assert cts.check_file(f) == []

    def test_truly_empty_block_still_flagged(self, tmp_path: Path) -> None:
        """Block with only whitespace (no code fence) is still flagged as empty."""
        f = tmp_path / "empty.md"
        f.write_text("<constants>\n\n</constants>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert any("empty block" in v and "constants" in v for v in violations)

    def test_escaped_structural_tag_flagged_as_low(self, tmp_path: Path) -> None:
        """Backslash-escaped structural tag in prose is flagged with [low] severity."""
        f = tmp_path / "escaped.md"
        f.write_text(
            "<role>\ncontent\n</role>\nProse mentioning \\<antipatterns_to_flag> should be flagged.\n",
            encoding="utf-8",
        )
        violations = cts.check_file(f)
        assert any("escaped structural tag" in v and "antipatterns_to_flag" in v for v in violations)
        assert any("[low]" in v for v in violations)

    def test_escaped_tag_inside_backtick_not_flagged(self, tmp_path: Path) -> None:
        """Escaped structural tag inside inline backtick span is not flagged."""
        f = tmp_path / "backtick.md"
        f.write_text(
            "<role>\ncontent\n</role>\nUse `\\<notes>` to suppress navigation.\n",
            encoding="utf-8",
        )
        violations = cts.check_file(f)
        assert not any("escaped structural tag" in v for v in violations)

    def test_escaped_tag_inside_code_fence_not_flagged(self, tmp_path: Path) -> None:
        """Escaped structural tag inside fenced code block is not flagged."""
        f = tmp_path / "fence.md"
        f.write_text(
            "<role>\ncontent\n</role>\n```markdown\n\\<workflow>\nexample\n```\n",
            encoding="utf-8",
        )
        violations = cts.check_file(f)
        assert not any("escaped structural tag" in v for v in violations)

    @pytest.mark.parametrize(
        "tag",
        [
            "objective",
            "workflow",
            "inputs",
            "notes",
            "constants",
            "calibration",
            "not-for",
            "role",
            "initialization",
            "antipatterns_to_flag",
            "core_knowledge",
        ],
    )
    def test_all_structural_tags_covered(self, tmp_path: Path, tag: str) -> None:
        """Every structural tag name triggers an empty-block finding when empty."""
        f = tmp_path / "tag.md"
        f.write_text(f"<{tag}></{tag}>\n", encoding="utf-8")
        violations = cts.check_file(f)
        assert any("empty block" in v for v in violations)


class TestMain:
    """Covers main() CLI integration."""

    def test_no_files_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """No files argument exits 0 and prints pass line."""
        rc = cts.main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "no files provided" in out

    def test_clean_file_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Single clean file exits 0 with pass line."""
        f = tmp_path / "clean.md"
        f.write_text("<objective>\ncontent\n</objective>\n", encoding="utf-8")
        rc = cts.main([str(f)])
        out = capsys.readouterr().out
        assert rc == 0
        assert "✓" in out

    def test_violation_exits_one(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """File with empty block exits 1 with violation prefixed ! C14a:."""
        f = tmp_path / "bad.md"
        f.write_text("<constants></constants>\n", encoding="utf-8")
        rc = cts.main([str(f)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "! C14a:" in out

    def test_nonexistent_file_skipped_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Non-existent file path is silently skipped; exits 0."""
        rc = cts.main(["/tmp/_nonexistent_tag_symmetry_test_file.md"])
        assert rc == 0

    def test_timeout_flag_accepted(self, tmp_path: Path) -> None:
        """--timeout flag is accepted and does not affect exit code."""
        f = tmp_path / "clean.md"
        f.write_text("<workflow>\nok\n</workflow>\n", encoding="utf-8")
        rc = cts.main([str(f), "--timeout", "5"])
        assert rc == 0
