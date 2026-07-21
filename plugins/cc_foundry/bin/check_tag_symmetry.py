#!/usr/bin/env python
"""check_tag_symmetry.py — Check structural XML tag symmetry in agent/skill .md files.

Detects three failure modes:
  1. Empty blocks — <tag></tag> with only whitespace between open and close.
  2. Unbalanced tags — <tag> count differs from </tag> count.
  3. Escaped structural tags — \\<tag> in prose; should be unescaped for Claude navigation [low].

Applies to structural tags: objective, workflow, inputs, notes, constants,
calibration, not-for, role, initialization, antipatterns_to_flag, core_knowledge.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_tag_symmetry.py" [files...] [--timeout SECS]

Output (stdout):
    One finding line per violation with prefix "! C14:", or a single pass line.

Exit codes:
    0   all files pass
    1   one or more violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

STRUCTURAL_TAGS = (
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
)


def check_file(path: Path) -> list[str]:
    """Return violation strings for path, empty list if clean.

    Args:
        path: Path to the .md file to check.

    Returns:
        List of human-readable violation messages with file path prepended.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path}: cannot read — {exc}"]

    violations: list[str] = []

    # Strip HTML comments (<!-- ... -->) first to avoid false positives from
    # convention-note comments that mention structural tag names by example.
    content_no_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)

    # For empty-block check: use comment-stripped content but preserve code fences
    # (a block is empty only when it has no content at all, including no code blocks).
    content_for_empty = content_no_comments

    # For balance check: also strip fences and inline backticks to avoid counting
    # tags that appear inside example code or inline code spans.
    content_for_balance = re.sub(r"```.*?```", "", content_no_comments, flags=re.DOTALL)
    content_for_balance = re.sub(r"`[^`\n]+`", "", content_for_balance)

    # Escaped structural tags: \<tag> in prose (after comment+fence+backtick stripping).
    # Severity: low — prevents Claude navigation; autofix unsafe (may be intentional).
    # Only flag open form \<tag>; closing \</tag> is rarer and not structural.
    escaped_tag_pattern = r"\\<(" + "|".join(re.escape(t) for t in STRUCTURAL_TAGS) + r")>"
    for match in re.finditer(escaped_tag_pattern, content_for_balance, re.IGNORECASE):
        violations.append(
            f"{path}: escaped structural tag \\<{match.group(1)}> — should be unescaped for Claude navigation [low]"
        )

    for tag in STRUCTURAL_TAGS:
        # Empty block: open + optional whitespace + close (check before fence-stripping)
        if re.search(rf"<{tag}>\s*</{tag}>", content_for_empty, re.IGNORECASE):
            violations.append(f"{path}: empty block <{tag}></{tag}>")

        # Unbalanced: open count != close count (check after fence+comment stripping).
        # Exclude backslash-escaped form \<tag> — those are flagged separately above.
        opens = len(re.findall(rf"(?<!\\)<{tag}>", content_for_balance, re.IGNORECASE))
        closes = len(re.findall(rf"(?<!\\)</{tag}>", content_for_balance, re.IGNORECASE))
        if opens != closes:
            violations.append(f"{path}: unbalanced <{tag}> — {opens} open, {closes} close")

    return violations


def main(argv: list[str] | None = None) -> int:
    """Run tag symmetry check on provided files.

    Args:
        argv: Argument list; defaults to sys.argv[1:] when None.

    Returns:
        0 if all files pass, 1 if violations found.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="*", help="Files to check")
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in seconds (default: 10; unused — pure file I/O)",
    )
    args = parser.parse_args(argv)

    if not args.files:
        print("✓: Check 14 — no files provided")
        return 0

    all_violations: list[str] = []
    checked = 0

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.is_file():
            continue
        checked += 1
        all_violations.extend(check_file(path))

    if all_violations:
        for v in all_violations:
            print(f"! C14a: {v}")
        return 1

    print(f"✓: Check 14a — no tag symmetry violations ({checked} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
