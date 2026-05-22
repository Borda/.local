#!/usr/bin/env python
"""commit_action_item.py — sentinel-aware commit helper for /oss:resolve Step 8.

Touches the commit-auth sentinel for the current repo+branch (required by
git-commit.md Gate 1) immediately before ``git commit``, so the pre-commit
hook approves the commit. Cleans the sentinel afterwards regardless of exit
status. Accepts the fully-formed commit message via --message-file so the
caller can embed Codex/Claude co-author trailers and per-item attribution.

Usage:
    commit_action_item.py --message-file <path> --files <file1> [<file2>...]

Exit codes:
    0 — commit succeeded (or staging area was empty — no-op)
    1 — bad args, message file missing, or commit failed
"""

from __future__ import annotations

import atexit
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import which

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    """Convert text to a filesystem/path-safe slug.

    Lowercases, replaces non-alphanumeric runs with ``-``, strips trailing
    hyphens.

    Args:
        text: Input string.

    Returns:
        Slugified string.

    Examples:
        >>> _slug("My/Repo Name")
        'my-repo-name'
        >>> _slug("main")
        'main'
        >>> _slug("feature/add-thing!")
        'feature-add-thing'
    """
    return _SLUG_RE.sub("-", text.lower()).rstrip("-")


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``commit_action_item.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 on bad args or commit failure; 0 on success or empty stage.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)

    msg_file = ""
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--message-file":
            i += 1
            msg_file = args[i] if i < len(args) else ""
        elif a == "--files":
            i += 1
            while i < len(args) and not args[i].startswith("--"):
                files.append(args[i])
                i += 1
            continue
        else:
            print(f"commit_action_item: unknown arg '{a}'", file=sys.stderr)
            return 1
        i += 1

    if not msg_file:
        print("commit_action_item: --message-file required", file=sys.stderr)
        return 1
    if not Path(msg_file).is_file():
        print(f"commit_action_item: message file not found: {msg_file}", file=sys.stderr)
        return 1
    if not files:
        print("commit_action_item: --files requires at least one path", file=sys.stderr)
        return 1

    git = which("git")
    if git is None:
        raise FileNotFoundError("executable not found on PATH: git")

    # --- Compute Gate 1 sentinel path ----------------------------------------
    root_proc = subprocess.run(  # noqa: S603
        [git, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch_proc = subprocess.run(  # noqa: S603
        [git, "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    repo_slug = _slug(Path(root_proc.stdout.strip()).name if root_proc.returncode == 0 else "repo")
    branch_slug = _slug(branch_proc.stdout.strip() if branch_proc.returncode == 0 else "main")

    # Prefer per-user temp dirs over a world-readable `/tmp` (macOS `/tmp`
    # is mode 1777 — sentinel name leaks branch metadata). Order: TMPDIR
    # (per-user on macOS) → XDG_RUNTIME_DIR (per-user on Linux) → fallback.
    # On Windows, `tempfile.gettempdir()` already returns the per-user temp dir.
    if sys.platform == "win32":
        _tmp = Path(tempfile.gettempdir())
    else:
        _tmp_str = os.environ.get("TMPDIR") or os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        _tmp = Path(_tmp_str)
    sentinel = _tmp / f"claude-commit-auth-{repo_slug}-{branch_slug}"

    # Touch sentinel and register cleanup (mirrors bash `trap EXIT INT TERM`).
    sentinel.touch()
    atexit.register(lambda: sentinel.unlink(missing_ok=True))

    # --- Stage files ----------------------------------------------------------
    add_proc = subprocess.run([git, "add", "--", *files], check=False)  # noqa: S603
    if add_proc.returncode != 0:
        print(f"commit_action_item: git add failed (exit {add_proc.returncode})", file=sys.stderr)
        return add_proc.returncode

    # Empty staging area → nothing to commit.
    cached_proc = subprocess.run(  # noqa: S603
        [git, "diff", "--cached", "--quiet"],
        check=False,
    )
    if cached_proc.returncode == 0:
        print(
            "commit_action_item: staging area empty after add — no commit created",
            file=sys.stderr,
        )
        return 0

    result = subprocess.run([git, "commit", "-F", msg_file], check=False)  # noqa: S603
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
