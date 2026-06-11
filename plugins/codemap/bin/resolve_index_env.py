#!/usr/bin/env python
"""resolve_index_env.py — resolve codemap PROJ + INDEX and write to temp files.

Calls ``bin/resolve_proj_index.py``, reads PROJ (line 1) and INDEX (line 2),
and writes each to ``${TMPDIR:-/tmp}/codemap-resolve-{proj,index}`` for the
caller to read back with ``cat`` — avoids the ``eval "$(...)"`` anti-pattern.

Usage:
    python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py"
    PROJ=$(cat "${TMPDIR:-/tmp}/codemap-resolve-proj")
    INDEX=$(cat "${TMPDIR:-/tmp}/codemap-resolve-index")

    python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" --check-exists
    # exit 1 when INDEX file missing; temp files still written for diagnostics

Flags:
    --check-exists   verify INDEX file exists; exit 1 with stderr message if missing.

Exit codes:
    0 — success (PROJ + INDEX written to temp files)
    1 — resolver produced no output, or (with ``--check-exists``) INDEX file missing
        (temp files still written so caller can read PROJ for diagnostics)
    2 — unknown flag
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


_SCRIPT_NAME = "resolve_index_env"


def parse_resolver_output(stdout: str) -> tuple[str, str]:
    """Extract PROJ (line 1) and INDEX (line 2) from resolver stdout.

    Trailing newlines on each line are stripped; lines beyond the second are ignored.
    Missing lines return empty strings — the caller treats either empty value as failure.

    Args:
        stdout: Raw stdout text from ``resolve_proj_index.py``.

    Returns:
        Tuple of ``(proj, index)`` strings; empty when the corresponding line is absent.

    Examples:
        >>> parse_resolver_output("myproj\\n/path/to/index.json\\n")
        ('myproj', '/path/to/index.json')
        >>> parse_resolver_output("only-one-line\\n")
        ('only-one-line', '')
        >>> parse_resolver_output("")
        ('', '')
        >>> parse_resolver_output("a\\nb\\nc\\nd\\n")
        ('a', 'b')
    """
    lines = stdout.splitlines()
    proj = lines[0] if len(lines) >= 1 else ""
    index = lines[1] if len(lines) >= 2 else ""
    return proj, index


def format_eval_line(proj: str, index: str) -> str:
    """Return a single eval-safe assignment line for ``PROJ`` and ``INDEX``.

    Uses :func:`shlex.quote` so any embedded single quotes, spaces, or shell
    metacharacters survive the round-trip through ``eval``.

    Args:
        proj: Project name string.
        index: Index file path string.

    Returns:
        Single line of the form ``PROJ=<quoted> INDEX=<quoted>`` (no trailing newline).

    Examples:
        >>> format_eval_line("myproj", "/tmp/index.json")
        'PROJ=myproj INDEX=/tmp/index.json'
        >>> format_eval_line("proj with space", "/tmp/index.json")
        "PROJ='proj with space' INDEX=/tmp/index.json"
        >>> "PROJ='proj'" in format_eval_line("proj'q", "/tmp/x.json")
        True
    """
    return f"PROJ={shlex.quote(proj)} INDEX={shlex.quote(index)}"


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for this script."""
    parser = argparse.ArgumentParser(
        prog=_SCRIPT_NAME,
        description="Resolve codemap PROJ + INDEX and emit eval-safe assignments.",
        add_help=True,
    )
    parser.add_argument(
        "--check-exists",
        action="store_true",
        help="Verify INDEX file exists; exit 1 with stderr message if missing.",
    )
    return parser


def _write_temp_vars(proj: str, index: str) -> None:
    """Write PROJ and INDEX to ``${TMPDIR:-/tmp}/codemap-resolve-{proj,index}`` temp files.

    Callers read back with ``cat`` — avoids the ``eval "$(...)"`` anti-pattern.
    Temp files are always written (even on resolver failure) so downstream ``cat``
    calls can supply their own ``|| echo ""`` fallback without extra conditionals.

    Args:
        proj: Project name string (may be empty on resolver failure).
        index: Index file path string (may be empty on resolver failure).
    """
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    for key, val in (("proj", proj), ("index", index)):
        Path(tmpdir, f"codemap-resolve-{key}").write_text(val, encoding="utf-8")


def _run_resolver(plugin_root: str) -> str:
    """Invoke ``resolve_proj_index.py`` via subprocess and return its stdout.

    Args:
        plugin_root: Plugin root directory (typically ``$CLAUDE_PLUGIN_ROOT``).

    Returns:
        Captured stdout text. Empty string on subprocess failure.
    """
    resolver = str(Path(plugin_root) / "bin" / "resolve_proj_index.py")
    try:
        result = subprocess.run(
            [sys.executable, resolver],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    Always writes PROJ/INDEX to temp files before any failure exit so callers
    can read partial results for diagnostics even when the script exits non-zero.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code — 0 success, 1 resolver/check failure, 2 unknown flag.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on unknown flags with its own stderr message.
        # Re-emit a stable, prefixed error line to match the legacy bash contract.
        if exc.code == 2:
            unknown = argv or sys.argv[1:]
            offending = next((a for a in unknown if a.startswith("-")), "")
            sys.stderr.write(f"{_SCRIPT_NAME}: unknown flag: {offending}\n")
            return 2
        return int(exc.code) if exc.code is not None else 0

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "plugins/codemap")
    stdout = _run_resolver(plugin_root)
    proj, index = parse_resolver_output(stdout)

    # Always write to temp files before any failure exit — callers read with cat.
    _write_temp_vars(proj, index)

    if not proj or not index:
        sys.stderr.write(f"{_SCRIPT_NAME}: resolve_proj_index.py produced no output (PROJ/INDEX empty)\n")
        return 1

    if args.check_exists and not Path(index).is_file():
        sys.stderr.write(f"{_SCRIPT_NAME}: INDEX file not found: {index}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
