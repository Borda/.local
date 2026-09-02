#!/usr/bin/env python
"""verify_perm.py — verify a permission rule's presence/absence across two files.

Checks whether ``<rule>``:

1. Appears in ``.permissions.allow[]`` of the given ``settings.json``.
2. Appears as a backticked code reference in ``permissions-guide.md``
   (matches the literal substring ``\\`<rule>\\``` — same as the bash version's
   ``grep -qF "\\`<rule>\\`"``).

Prints two lines::

    settings: OK|MISSING|STILL_PRESENT
    guide: OK|MISSING|STILL_PRESENT

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/verify_perm.py" <rule> <settings-json> <guide-md> <present|absent>

Exit codes:
    0  Both files consistent with mode
    1  At least one mismatch
    2  Bad args (invalid mode)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal, get_args

Mode = Literal["present", "absent"]
Status = Literal["OK", "MISSING", "STILL_PRESENT"]


def rule_in_settings(rule: str, settings_path: Path) -> bool:
    """Return True if ``rule`` is an element of ``.permissions.allow`` in JSON.

    Missing file, malformed JSON, missing ``permissions`` key, missing ``allow``
    key, or non-list ``allow`` all return False — matching the bash ``jq -e`` behavior.

    Args:
        rule: Permission rule string to look for (exact match).
        settings_path: Path to ``settings.json``.

    Returns:
        True if rule present in allow list; False otherwise.
    """
    if not settings_path.is_file():
        return False
    try:
        with settings_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(data, dict):
        return False
    permissions = data.get("permissions")
    if not isinstance(permissions, dict):
        return False
    allow = permissions.get("allow")
    if not isinstance(allow, list):
        return False
    return rule in allow


def rule_in_guide(rule: str, guide_path: Path) -> bool:
    """Return True if ``\\`<rule>\\``` appears in the guide markdown file.

    Matches the bash version's ``grep -qF "\\`${rule}\\`"`` — a literal substring
    search (no regex) for the backtick-wrapped form.

    Args:
        rule: Permission rule string.
        guide_path: Path to ``permissions-guide.md``.

    Returns:
        True if backticked rule found in file contents; False otherwise.
    """
    if not guide_path.is_file():
        return False
    needle = f"`{rule}`"
    try:
        text = guide_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return needle in text


def status_for(present: bool, mode: Mode) -> Status:
    """Map presence + mode to the status token.

    Args:
        present: Whether the rule was found.
        mode: ``"present"`` (rule expected) or ``"absent"`` (rule should not exist).

    Returns:
        ``"OK"`` when consistent, ``"MISSING"`` when expected but absent,
        ``"STILL_PRESENT"`` when forbidden but found.

    Examples:
        >>> status_for(True, "present")
        'OK'
        >>> status_for(False, "present")
        'MISSING'
        >>> status_for(True, "absent")
        'STILL_PRESENT'
        >>> status_for(False, "absent")
        'OK'
    """
    if mode == "present":
        return "OK" if present else "MISSING"
    return "STILL_PRESENT" if present else "OK"


def main(argv: list[str] | None = None) -> int:
    """Verify that a path has the requested permissions."""
    parser = argparse.ArgumentParser(
        description="Verify permission rule presence/absence in settings.json and permissions-guide.md.",
        add_help=True,
    )
    parser.add_argument("rule", help="Permission rule string to check.")
    parser.add_argument("settings_json", help="Path to settings.json.")
    parser.add_argument("guide_md", help="Path to permissions-guide.md.")
    parser.add_argument(
        "mode",
        help="Verification mode.",
        choices=list(get_args(Mode)),
    )

    # argparse exits with code 2 for usage errors (invalid mode, missing args) — matches bash version.
    args = parser.parse_args(argv)
    mode: Mode = args.mode
    settings_present = rule_in_settings(args.rule, Path(args.settings_json))
    guide_present = rule_in_guide(args.rule, Path(args.guide_md))

    settings_status = status_for(settings_present, mode)
    guide_status = status_for(guide_present, mode)

    print(f"settings: {settings_status}\nguide: {guide_status}")

    if settings_status == "OK" and guide_status == "OK":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
