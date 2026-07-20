#!/usr/bin/env python
"""trim_plugin_tables.py — normalize Markdown table cell padding in plugin docs.

Rewrites every ``| cell | cell |`` row to single-space padding and collapses
separator rows (``---``, ``:---``, ``---:``) to a uniform 3-dash form. Lines
inside fenced code blocks (``` or ~~~) are left untouched. Blockquoted tables
(``> | cell |``) are supported — the ``>`` prefix is preserved.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/trim_plugin_tables.py" [files...]

Output:
    Rewrites each input file in place when its table padding changes.

Exit codes:
    0   no file changed
    1   one or more files were rewritten
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW_RE = re.compile(r"^(\s*(?:>\s*)?)\|(.*)\|\s*$")
_SEPARATOR_CELL_RE = re.compile(r":?-{3,}:?")


def format_table_row(prefix: str, raw: str, end: str) -> str:
    """Reformat one Markdown table row to single-space cell padding.

    Args:
        prefix: Leading whitespace/blockquote marker before the opening ``|``.
        raw: Row content between the outer ``|`` delimiters.
        end: Trailing line terminator (``"\\n"`` or ``""`` for the last line).

    Returns:
        The reformatted row, including prefix and trailing terminator.

    Examples:
        >>> format_table_row("", " a | b ", "\\n")
        '| a | b |\\n'
        >>> format_table_row("", ":---|---:", "\\n")
        '| :--- | ---: |\\n'
        >>> format_table_row("> ", " a | b ", "")
        '> | a | b |'
    """
    cells = [c.strip() for c in raw.split("|")]
    rows: list[list[str]] = []
    row: list[str] = []
    for c in cells:
        if c == "" and row:
            rows.append(row)
            row = []
        elif c != "":
            row.append(c)
    if row:
        rows.append(row)

    lines: list[str] = []
    for r in rows or [cells]:
        if all(_SEPARATOR_CELL_RE.fullmatch(c or "") for c in r):
            r = [(":" if c.startswith(":") else "") + "---" + (":" if c.endswith(":") else "") for c in r]
        lines.append(f"{prefix}| {' | '.join(r)} |{end}")
    if len(lines) > 1 and not end:
        lines[-1] = lines[-1].removesuffix("\n")
    return "".join(lines)


def trim_file(path: Path) -> bool:
    """Rewrite a file's table rows in place; return True if it changed.

    Args:
        path: Markdown file to process.

    Returns:
        True if any line's padding was rewritten.
    """
    original = path.read_text(encoding="utf-8").splitlines(True)
    out: list[str] = []
    changed = False
    in_code_block = False
    for line in original:
        if _FENCE_RE.match(line):
            in_code_block = not in_code_block
            out.append(line)
            continue
        end = "\n" if line.endswith("\n") else ""
        body = line[:-1] if end else line
        match = None if in_code_block else _TABLE_ROW_RE.match(body)
        new_line = format_table_row(match.group(1), match.group(2), end) if match else line
        if new_line != line:
            changed = True
        out.append(new_line)
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="trim_plugin_tables",
        description="Normalize Markdown table cell padding in plugin docs.",
    )
    parser.add_argument("files", nargs="*", help="Markdown files to process")
    args = parser.parse_args(argv)

    changed = False
    for file_arg in args.files:
        p = Path(file_arg)
        if not p.is_file():
            continue
        if trim_file(p):
            changed = True

    return 1 if changed else 0


if __name__ == "__main__":
    sys.exit(main())
