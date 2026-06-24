#!/usr/bin/env python
"""extract_contributors.py — list unique non-bot contributors in a git range.

Runs ``git log`` over a commit range, collects commit authors plus
``Co-authored-by`` trailer names, deduplicates by email, and drops bot
accounts (``[bot]`` logins and ``noreply`` addresses). Emits one
``Name <email>`` line per contributor to stdout, sorted.

Extracted from the ``oss:release`` *Extract contributors* phase, where the
same ``git log --format=… | grep -v '^$' | sort -u`` pipeline appeared in the
delegation agent prompt and the inline fallback. This script owns only the
deterministic list-building step; GitHub-handle and LinkedIn resolution stays
in the skill prose (requires API reasoning, not a pure transform).

Usage:
    extract_contributors.py --range <git-range>
    extract_contributors.py --from <ref> --to <ref>

Args:
    --range:  Full git range string, e.g. ``v1.2.0..HEAD`` or ``v1..v2``.
    --from:   Range lower bound (used with ``--to``); ``..`` joins them.
    --to:     Range upper bound (defaults to ``HEAD`` when ``--from`` given).
    --repo:   Optional repo root passed to ``git -C`` (default: cwd).

Exit codes:
    0 — listing emitted (possibly empty if range has no non-bot authors)
    1 — bad args (no range given, or both --range and --from/--to)
    2 — git invocation failed
"""

from __future__ import annotations

import re
import subprocess
import sys
from shutil import which

_BOT_LOGIN_RE = re.compile(r"\[bot\]", re.IGNORECASE)
_NOREPLY_RE = re.compile(r"noreply", re.IGNORECASE)
_LINE_RE = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^>]+)>\s*$")

_GIT_FORMAT = "%aN <%aE>%n%(trailers:key=Co-authored-by,valueonly)"


def is_bot(line: str) -> bool:
    """Return True when a ``Name <email>`` line denotes a bot account.

    Args:
        line: A ``Name <email>`` contributor line.

    Returns:
        True if the line contains ``[bot]`` or a ``noreply`` address (covers both
        ``noreply@host`` and GitHub ``user@users.noreply.github.com`` forms).

    Examples:
        >>> is_bot("dependabot[bot] <49699333+dependabot[bot]@users.noreply.github.com>")
        True
        >>> is_bot("Jane Doe <jane@example.com>")
        False
        >>> is_bot("CI <ci@noreply.example.com>")
        True
    """
    return bool(_BOT_LOGIN_RE.search(line) or _NOREPLY_RE.search(line))


def dedupe_by_email(lines: list[str]) -> list[str]:
    """Deduplicate contributor lines by email, dropping bots, sorted by name.

    First occurrence of each email wins (preserves its display name). Lines
    without a parseable ``<email>`` are kept and keyed on the whole line.

    Args:
        lines: Raw ``Name <email>`` lines (blank lines and bots may be present).

    Returns:
        Sorted, de-duplicated, bot-free list of ``Name <email>`` lines.

    Examples:
        >>> dedupe_by_email([
        ...     "Jane Doe <jane@example.com>",
        ...     "J. Doe <jane@example.com>",
        ...     "bot[bot] <bot@noreply.github.com>",
        ...     "Al Pace <al@example.com>",
        ... ])
        ['Al Pace <al@example.com>', 'Jane Doe <jane@example.com>']
    """
    seen: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or is_bot(line):
            continue
        match = _LINE_RE.match(line)
        key = match.group("email").lower() if match else line
        seen.setdefault(key, line)
    return sorted(seen.values(), key=str.casefold)


def _build_range(range_arg: str, from_ref: str, to_ref: str) -> str:
    """Resolve the effective git range from CLI args.

    Args:
        range_arg: Value of ``--range`` (empty when unset).
        from_ref: Value of ``--from`` (empty when unset).
        to_ref: Value of ``--to`` (empty when unset).

    Returns:
        The git range string, or empty string when none was provided.

    Examples:
        >>> _build_range("v1..v2", "", "")
        'v1..v2'
        >>> _build_range("", "v1", "v2")
        'v1..v2'
        >>> _build_range("", "v1", "")
        'v1..HEAD'
        >>> _build_range("", "", "")
        ''
    """
    if range_arg:
        return range_arg
    if from_ref:
        return f"{from_ref}..{to_ref or 'HEAD'}"
    return ""


def main(argv: list[str] | None = None) -> int:
    """Entry point — parse args, run ``git log``, print contributor list.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 on bad args, 2 on git failure, 0 otherwise.

    Examples:
        No doctest — subprocess-dependent; covered by pytest with monkeypatch.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)

    range_arg = from_ref = to_ref = repo = ""
    i = 0
    while i < len(args):
        flag = args[i]
        value = args[i + 1] if i + 1 < len(args) else ""
        if flag == "--range":
            range_arg = value
        elif flag == "--from":
            from_ref = value
        elif flag == "--to":
            to_ref = value
        elif flag == "--repo":
            repo = value
        else:
            print(f"extract_contributors: unknown arg '{flag}'", file=sys.stderr)
            return 1
        i += 2

    if range_arg and (from_ref or to_ref):
        print("extract_contributors: pass either --range or --from/--to, not both", file=sys.stderr)
        return 1

    git_range = _build_range(range_arg, from_ref, to_ref)
    if not git_range:
        print("extract_contributors: --range or --from required", file=sys.stderr)
        return 1

    git = which("git")
    if git is None:
        raise FileNotFoundError("executable not found on PATH: git")

    cmd = [git]
    if repo:
        cmd += ["-C", repo]
    cmd += ["log", git_range, "--no-merges", f"--format={_GIT_FORMAT}"]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    if proc.returncode != 0:
        print(f"extract_contributors: git log failed: {proc.stderr.strip()}", file=sys.stderr)
        return 2

    contributors = dedupe_by_email(proc.stdout.splitlines())
    if contributors:
        print("\n".join(contributors))
    return 0


if __name__ == "__main__":
    sys.exit(main())
