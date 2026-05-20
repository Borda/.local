#!/usr/bin/env python
"""jq_write.py — atomic ``jq`` edit of a JSON file via temp-file + rename.

Mirrors the original ``jq-write.sh`` interface: read ``<target>``, apply
``<jq-filter>`` with optional ``--arg <name> <value>`` pairs, write to
``<target>.tmp``, then ``shutil.move`` over ``<target>``. The atomic rename
ensures readers never see a half-written file.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/jq_write.py" <target-file> <jq-filter> [--arg <name> <value>]...

Exit codes:
    0  Success
    1  Target file missing
    2  jq subprocess error (non-zero exit or jq not on PATH)
    3  Bad args (odd number of --arg trailing tokens, or no target/filter)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


_ALLOWED_FLAGS = {"--arg", "--argjson", "--indent"}


def _parse_jq_args(extras: list[str]) -> list[str] | None:
    """Validate and return passthrough jq flag tokens.

    Only flags in :data:`_ALLOWED_FLAGS` are accepted; any other ``--`` token
    is rejected (raises :class:`ValueError`). This blocks dangerous jq flags
    such as ``--slurpfile`` / ``--rawfile`` that read arbitrary filesystem
    paths.

    Args:
        extras: Tokens after ``<target> <filter>`` (e.g. ``["--arg", "k", "v"]``).

    Returns:
        The same list if every ``--arg`` is followed by two tokens, else None
        to signal malformed args.

    Raises:
        ValueError: When a disallowed ``--`` flag is encountered.
    """
    for token in extras:
        if token.startswith("--") and token.split("=", 1)[0] not in _ALLOWED_FLAGS:
            raise ValueError(f"jq_write: disallowed flag: {token!r}")
    i = 0
    while i < len(extras):
        token = extras[i]
        if token == "--arg":
            # Need exactly two more tokens: name + value.
            if i + 2 >= len(extras):
                return None
            i += 3
        else:
            i += 1
    return extras


def run_jq_write(target: Path, jq_filter: str, extras: list[str]) -> int:
    """Apply ``jq_filter`` to ``target`` atomically.

    Args:
        target: JSON file to rewrite in place.
        jq_filter: jq program string.
        extras: Additional jq CLI tokens (e.g. ``["--arg", "k", "v"]``).

    Returns:
        0 on success, 1 if target missing, 2 on jq subprocess error.
    """
    if not target.is_file():
        print(f"! target not found: {target}", file=sys.stderr)
        return 1

    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            completed = subprocess.run(
                ["jq", *extras, jq_filter, str(target)],
                stdout=fh,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
            )
    except (FileNotFoundError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        print(f"! jq invocation failed for {target}: {exc}", file=sys.stderr)
        return 2

    if completed.returncode != 0:
        tmp.unlink(missing_ok=True)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        print(f"! jq filter failed for {target}", file=sys.stderr)
        return 2

    shutil.move(str(tmp), str(target))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code.

    Hand-parses ``argv`` (no argparse): the bash original passes ``--arg name
    value`` triplets straight through to jq, which argparse would mangle.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) < 2:
        print(
            "Usage: jq_write.py <target-file> <jq-filter> [--arg <name> <value>]...",
            file=sys.stderr,
        )
        return 3

    target_str, jq_filter, *extras = args
    try:
        parsed = _parse_jq_args(extras)
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 3
    if parsed is None:
        print("! malformed --arg: each --arg requires <name> <value>", file=sys.stderr)
        return 3

    return run_jq_write(Path(target_str), jq_filter, parsed)


if __name__ == "__main__":
    sys.exit(main())
