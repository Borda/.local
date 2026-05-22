#!/usr/bin/env python
"""Strip a leading ``#`` from an issue number and fetch the GitHub issue via ``gh``.

Usage:
    issue_fetch.py <issue-number-with-optional-hash>

Behaviour:
    Forwards ``gh issue view <num> --comments`` with stdout/stderr inherited from the
    caller. Validates that the stripped argument is digits-only and exits 1 with a stderr
    message otherwise. Propagates ``gh``'s exit code on success.

Exit codes:
    0   — success (``gh`` exited 0).
    1   — invalid (empty or non-numeric) issue number.
    *   — any other exit code reflects ``gh``'s own exit status.
"""

from __future__ import annotations

import subprocess
import sys
from shutil import which


def _resolve(cmd: str) -> str:
    """Resolve ``cmd`` to an absolute path using ``shutil.which``.

    Args:
        cmd: Bare executable name (e.g. ``"gh"``).

    Returns:
        Absolute path to the executable.

    Raises:
        FileNotFoundError: If ``cmd`` is not present on ``PATH``.
    """
    resolved = which(cmd)
    if resolved is None:
        raise FileNotFoundError(f"executable not found on PATH: {cmd}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``issue-fetch.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 on invalid input; ``gh``'s exit code otherwise.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)
    raw = args[0] if args else ""
    issue_num = raw.lstrip("#")
    if not issue_num or not issue_num.isdigit():
        print(f"issue-fetch: invalid issue number: '{issue_num}'", file=sys.stderr)
        return 1
    gh = _resolve("gh")
    # stdout/stderr inherited from caller — caller sees combined output as in bash `2>&1`.
    result = subprocess.run(  # noqa: S603 — resolved binary + fixed argv, no shell.
        [gh, "issue", "view", issue_num, "--comments"],
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
