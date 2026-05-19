#!/usr/bin/env python
"""resolve_target_module.py — derive a Python dotted module name from a file path.

Usage:
    python3 "${CLAUDE_PLUGIN_ROOT}/bin/resolve_target_module.py" <path_or_file>

Examples:
    src/foo/bar.py    → foo.bar
    ./src/foo/bar.py  → foo.bar
    tests/test_x.py   → tests.test_x
    pkg/__init__.py   → pkg.__init__

Output:
    Dotted module name on stdout. Empty string when the input is empty or
    cannot be normalised. Never fails on input.

Exit codes:
    0  always.
"""

from __future__ import annotations

import sys
from pathlib import Path


def resolve_target_module(path_or_file: str) -> str:
    """Convert a Python source path to a dotted module name.

    Transform pipeline (mirrors the original sed pipeline):
        1. Strip a leading ``./``
        2. Strip a leading ``src/``
        3. Strip a trailing ``.py``
        4. Replace each ``/`` with ``.``

    When the transform produces an empty string (e.g. the input was empty),
    fall back to the filename stem of the original input.

    Args:
        path_or_file: Input file path. May be relative, absolute, or already
            dotted; empty string is allowed.

    Returns:
        Dotted module name, or empty string when the input is empty and the
        fallback also yields nothing.

    Examples:
        >>> resolve_target_module("src/foo/bar.py")
        'foo.bar'
        >>> resolve_target_module("./src/foo/bar.py")
        'foo.bar'
        >>> resolve_target_module("tests/test_x.py")
        'tests.test_x'
        >>> resolve_target_module("pkg/__init__.py")
        'pkg.__init__'
        >>> resolve_target_module("foo.bar")
        'foo.bar'
        >>> resolve_target_module("")
        ''
        >>> resolve_target_module("standalone.py")
        'standalone'
    """
    target = path_or_file
    if target.startswith("./"):
        target = target[2:]
    if target.startswith("src/"):
        target = target[4:]
    if target.endswith(".py"):
        target = target[:-3]
    target = target.replace("/", ".")

    if not target:
        # Fallback: basename of the original input without the .py extension.
        return Path(path_or_file).stem
    return target


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: read positional path, print dotted module, return 0.

    Args:
        argv: Optional argv override for testing. Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code (always 0).
    """
    args = sys.argv[1:] if argv is None else argv
    path_or_file = args[0] if args else ""
    print(resolve_target_module(path_or_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
