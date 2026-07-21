#!/usr/bin/env python
"""check_output_within_root.py — verify a candidate output path stays within the project root.

Pure path-containment guard for the run skill: resolves both paths with
``os.path.realpath`` and reports whether the candidate is the root itself or a
descendant of it. No filesystem writes, no subprocess (CWE-22 containment check).

Usage:
    check_output_within_root.py <candidate-path> <root-path>

Exit codes:
    0 — candidate is within root (or equal to root)
    1 — candidate is outside root
    2 — bad/missing required argument (argparse default)
"""

from __future__ import annotations

import argparse
import os
import sys


def is_within_root(candidate: str, root: str) -> bool:
    """Return True if candidate path is within or equal to root.

    Args:
        candidate: Candidate output path to check.
        root: Project root the candidate must stay within.

    Returns:
        True if the resolved candidate equals or descends from the resolved root.

    Examples:
        >>> import tempfile, os
        >>> td = tempfile.mkdtemp()
        >>> is_within_root(os.path.join(td, 'sub'), td)
        True
        >>> is_within_root(td, td)
        True
        >>> is_within_root('/tmp/evil', td)
        False
    """
    p = os.path.realpath(candidate)
    b = os.path.realpath(root)
    return p == b or p.startswith(b + os.sep)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the exit code.

    No doctest — argv-dependent; covered by pytest.

    Args:
        argv: Optional argv override (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` if candidate is within root, ``1`` if outside; argparse exits ``2`` on bad args.
    """
    parser = argparse.ArgumentParser(
        prog="check_output_within_root.py",
        description="Verify a candidate output path stays within the project root.",
    )
    parser.add_argument("candidate_path", help="Candidate output path to check.")
    parser.add_argument("root_path", help="Project root the candidate must stay within.")
    args = parser.parse_args(argv)

    return 0 if is_within_root(args.candidate_path, args.root_path) else 1


if __name__ == "__main__":
    sys.exit(main())
