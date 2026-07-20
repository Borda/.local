"""Tests for trim_plugin_tables — Markdown table cell-padding normalizer."""

from __future__ import annotations

from pathlib import Path

from trim_plugin_tables import format_table_row, main, trim_file


class TestFormatTableRow:
    def test_pads_cells_to_single_space(self) -> None:
        assert format_table_row("", " a | b ", "\n") == "| a | b |\n"

    def test_collapses_wide_padding(self) -> None:
        assert format_table_row("", "  a   |  b   ", "\n") == "| a | b |\n"

    def test_normalizes_plain_separator_row(self) -> None:
        assert format_table_row("", "-----|------", "\n") == "| --- | --- |\n"

    def test_preserves_left_align_colon(self) -> None:
        assert format_table_row("", ":----|------", "\n") == "| :--- | --- |\n"

    def test_preserves_both_align_colons(self) -> None:
        assert format_table_row("", ":---|---:", "\n") == "| :--- | ---: |\n"

    def test_preserves_blockquote_prefix(self) -> None:
        assert format_table_row("> ", " a | b ", "") == "> | a | b |"

    def test_no_trailing_newline_on_last_line(self) -> None:
        assert format_table_row("", " a | b ", "") == "| a | b |"


class TestTrimFile:
    def test_rewrites_misaligned_table(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("| a   | b |\n|---|---|\n| 1 | 2   |\n")
        assert trim_file(f) is True
        assert f.read_text() == "| a | b |\n| --- | --- |\n| 1 | 2 |\n"

    def test_no_change_returns_false(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("| a | b |\n| --- | --- |\n")
        assert trim_file(f) is False
        assert f.read_text() == "| a | b |\n| --- | --- |\n"

    def test_skips_table_rows_inside_fenced_code_block(self, tmp_path: Path) -> None:
        content = "```\n| a   | b |\n```\n"
        f = tmp_path / "doc.md"
        f.write_text(content)
        assert trim_file(f) is False
        assert f.read_text() == content

    def test_leaves_non_table_lines_untouched(self, tmp_path: Path) -> None:
        content = "# Heading\n\nSome prose | not a table row\n"
        f = tmp_path / "doc.md"
        f.write_text(content)
        assert trim_file(f) is False
        assert f.read_text() == content


class TestMain:
    def test_returns_1_when_file_changed(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("| a   | b |\n")
        assert main([str(f)]) == 1

    def test_returns_0_when_no_file_changed(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("| a | b |\n")
        assert main([str(f)]) == 0

    def test_skips_missing_files(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.md"
        assert main([str(missing)]) == 0

    def test_returns_0_for_empty_argv(self) -> None:
        assert main([]) == 0
