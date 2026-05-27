"""Verify that a candidate output path stays within the project root.

Exit 0 if candidate is within root (or equal to root); exit 1 otherwise.
Usage: check_output_within_root.py <candidate_path> <root_path>
"""

import os
import sys


def is_within_root(candidate: str, root: str) -> bool:
    """Return True if candidate path is within or equal to root.

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


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <candidate_path> <root_path>", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if is_within_root(sys.argv[1], sys.argv[2]) else 1)
