#!/usr/bin/env python
"""check_tag_symmetry.py — Check structural XML tag symmetry in agent/skill .md files.

Detects three failure modes, each independently selectable via ``--check``:

  empty-block  — <tag></tag> with only whitespace between open and close.
  unbalanced   — <tag> count differs from </tag> count.
  escaped-tag  — \\<tag> in prose; should be unescaped for Claude navigation [low].

All three are facts about the source tree, so each drives exit code 1 on its own.
The ``escaped-tag`` mode carries [low] severity in its message; splitting it into a
separate pre-commit entry is what makes it independently skippable, not a demotion of
its exit code (bare invocation must keep reporting all three and exiting identically).

Read errors are reported unconditionally regardless of ``--check`` — a file that cannot
be opened is never silently dropped by a subset run.

Applies to structural tags: objective, workflow, inputs, notes, constants,
calibration, not-for, role, initialization, antipatterns_to_flag, core_knowledge.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_tag_symmetry.py" [files...] [options]

Options:
    --check KINDS    Comma-separated modes to run: empty-block, unbalanced, escaped-tag
                     (default: all three).
    --timeout SECS   Accepted for call-site uniformity; unused (pure file I/O).

Output (stdout):
    One finding line per violation with prefix "! C14a:", or a single pass line.

Exit codes:
    0   all files pass
    1   one or more violations found
    2   argument error (unknown --check mode)
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class FindingKind(str, Enum):
    """Which subcheck produced a finding — the ``--check`` selector token.

    Subclasses ``str`` rather than ``enum.StrEnum`` because ``requires-python`` is
    ``>=3.10`` and ``StrEnum`` landed in 3.11. The ``str`` mixin keeps
    ``FindingKind.UNBALANCED == "unbalanced"`` true for comparison and f-strings.

    ``READ_ERROR`` is not a selectable mode: it is emitted by every run so that an
    unreadable file cannot be hidden by narrowing ``--check``.

    Examples:
        >>> FindingKind.EMPTY_BLOCK == "empty-block"
        True
        >>> FindingKind("escaped-tag") is FindingKind.ESCAPED_TAG
        True
    """

    EMPTY_BLOCK = "empty-block"
    UNBALANCED = "unbalanced"
    ESCAPED_TAG = "escaped-tag"
    READ_ERROR = "read-error"


#: Modes a caller may name in ``--check``, in default run order.
SELECTABLE_KINDS: tuple[FindingKind, ...] = (
    FindingKind.EMPTY_BLOCK,
    FindingKind.UNBALANCED,
    FindingKind.ESCAPED_TAG,
)


@dataclass
class Finding:
    """One tag-symmetry violation, tagged with the subcheck that found it.

    Attributes:
        kind: The subcheck responsible — used to filter by ``--check``.
        message: Human-readable violation text, file path already prepended.
    """

    kind: FindingKind
    message: str


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


def check_file(path: Path) -> list[Finding]:
    """Return every violation for path, empty list if clean.

    All subchecks always run; callers filter by :attr:`Finding.kind`. Findings keep
    their historical order — escaped tags first, then per-tag empty/unbalanced pairs —
    so a bare run prints byte-identical output to the pre-split version.

    Args:
        path: Path to the .md file to check.

    Returns:
        List of Finding objects with file path already prepended to each message.

    Examples:
        >>> import tempfile, pathlib
        >>> p = pathlib.Path(tempfile.mktemp(suffix=".md"))
        >>> _ = p.write_text("<objective>\\ncontent\\n</objective>\\n")
        >>> check_file(p)
        []
        >>> _ = p.write_text("<notes></notes>\\n")
        >>> [f.kind.value for f in check_file(p)]
        ['empty-block']
        >>> import os; os.unlink(p)
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [Finding(FindingKind.READ_ERROR, f"{path}: cannot read — {exc}")]

    violations: list[Finding] = []

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
            Finding(
                FindingKind.ESCAPED_TAG,
                f"{path}: escaped structural tag \\<{match.group(1)}> "
                f"— should be unescaped for Claude navigation [low]",
            )
        )

    for tag in STRUCTURAL_TAGS:
        # Empty block: open + optional whitespace + close (check before fence-stripping)
        if re.search(rf"<{tag}>\s*</{tag}>", content_for_empty, re.IGNORECASE):
            violations.append(Finding(FindingKind.EMPTY_BLOCK, f"{path}: empty block <{tag}></{tag}>"))

        # Unbalanced: open count != close count (check after fence+comment stripping).
        # Exclude backslash-escaped form \<tag> — those are flagged separately above.
        opens = len(re.findall(rf"(?<!\\)<{tag}>", content_for_balance, re.IGNORECASE))
        closes = len(re.findall(rf"(?<!\\)</{tag}>", content_for_balance, re.IGNORECASE))
        if opens != closes:
            violations.append(
                Finding(FindingKind.UNBALANCED, f"{path}: unbalanced <{tag}> — {opens} open, {closes} close")
            )

    return violations


def parse_kinds(spec: str) -> set[FindingKind]:
    """Parse a comma-separated ``--check`` spec into selectable kinds.

    Args:
        spec: Comma-separated mode tokens, e.g. ``"empty-block,unbalanced"``.

    Returns:
        Set of selected FindingKind members.

    Raises:
        ValueError: When any token is not a selectable mode. The message lists the
            unknown tokens so the CLI can surface them verbatim.

    Examples:
        >>> sorted(k.value for k in parse_kinds("unbalanced,empty-block"))
        ['empty-block', 'unbalanced']
        >>> parse_kinds("read-error")
        Traceback (most recent call last):
        ...
        ValueError: unknown check mode(s): read-error
    """
    selectable = {k.value: k for k in SELECTABLE_KINDS}
    tokens = [t.strip().lower() for t in spec.split(",") if t.strip()]
    unknown = sorted({t for t in tokens if t not in selectable})
    if unknown:
        raise ValueError(f"unknown check mode(s): {', '.join(unknown)}")
    return {selectable[t] for t in tokens}


def main(argv: list[str] | None = None) -> int:
    """Run the selected tag symmetry subchecks on provided files.

    Args:
        argv: Argument list; defaults to sys.argv[1:] when None.

    Returns:
        0 if all files pass, 1 if violations found, 2 on an unknown ``--check`` mode.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="*", help="Files to check")
    parser.add_argument(
        "--check",
        default=",".join(k.value for k in SELECTABLE_KINDS),
        metavar="KINDS",
        help="Comma-separated subchecks to run: empty-block, unbalanced, escaped-tag (default: all).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout in seconds (default: 10; unused — pure file I/O)",
    )
    args = parser.parse_args(argv)

    try:
        active = parse_kinds(args.check)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.files:
        print("✓: Check 14 — no files provided")
        return 0

    # Read errors are never filtered out — a subset run must not hide an unreadable file.
    keep = active | {FindingKind.READ_ERROR}
    label = "" if active == set(SELECTABLE_KINDS) else f" [{','.join(sorted(k.value for k in active))}]"
    all_violations: list[Finding] = []
    checked = 0

    for file_arg in args.files:
        path = Path(file_arg)
        if not path.is_file():
            continue
        checked += 1
        all_violations.extend(f for f in check_file(path) if f.kind in keep)

    if all_violations:
        for v in all_violations:
            print(f"! C14a: {v.message}")
        return 1

    print(f"✓: Check 14a{label} — no tag symmetry violations ({checked} files checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
