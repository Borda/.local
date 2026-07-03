#!/usr/bin/env python
"""Strip a leading ``#`` from an issue number and fetch the GitHub issue via ``gh``.

Usage:
    issue_fetch.py <issue-number-with-optional-hash> [--repo <owner/repo>]

Behaviour:
    Forwards ``gh issue view <num> --comments [--repo <owner/repo>]`` with
    stdout/stderr inherited from the caller. Validates that the stripped
    argument is digits-only and exits 1 with a stderr message otherwise.
    Propagates ``gh``'s exit code on success.

    The first positional argument may contain trailing flags (e.g. the full
    ``$ARGUMENTS`` shell variable including ``--repo owner/repo``). Only the
    first whitespace-separated token is used as the issue number; the rest is
    ignored. Pass ``--repo <owner/repo>`` as a separate argument to route the
    request to an upstream repository (fork workflow).

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

    # Extract --repo flag (supports fork/upstream workflow).
    repo: str | None = None
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--repo" and i + 1 < len(args):
            repo = args[i + 1]
            i += 2
        else:
            positional.append(args[i])
            i += 1

    # The first positional arg may be the raw ``$ARGUMENTS`` string which can include
    # trailing flags (e.g. "123 --repo owner/repo"). Extract only the first token.
    raw_str = positional[0] if positional else ""
    raw = raw_str.split()[0] if raw_str.strip() else ""
    issue_num = raw[1:] if raw.startswith("#") else raw
    if not issue_num or not issue_num.isdigit():
        print(f"issue-fetch: invalid issue number: '{issue_num}'", file=sys.stderr)
        return 1
    gh = _resolve("gh")
    cmd = [gh, "issue", "view", issue_num, "--comments"]
    if repo:
        cmd += ["--repo", repo]
    # stdout/stderr inherited from caller — caller sees combined output as in bash `2>&1`.
    result = subprocess.run(cmd, check=False, timeout=30)  # noqa: S603 — resolved binary + fixed argv, no shell.
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
