#!/usr/bin/env python3
"""detect_codemap.py — detect codemap plugin availability and index presence.

consumers: resolve/SKILL.md, review/SKILL.md

Determines whether the codemap plugin is installed and an index exists for the
current project.  Writes result to ${TMPDIR:-/tmp}/<prefix>-codemap-enabled.

Usage:
    python detect_codemap.py --prefix resolve [--force-off] [--strict] [--proj <name>]

Flags:
    --prefix <name>   Prefix for temp-file name (e.g. resolve, review). Required.
    --force-off       CODEMAP_FORCE_OFF=true — always write false.
    --strict          CODEMAP_STRICT=true — exit 1 when codemap absent/index missing.
    --proj <name>     Project name override (default: basename of git toplevel).
    --idx-dir <path>  Codemap index directory override (default: .cache/codemap).

Temp file written:
    ${TMPDIR:-/tmp}/<prefix>-codemap-enabled   → "true" or "false"

Exit codes:
    0   success (CODEMAP_ENABLED written)
    1   --strict mode: codemap not installed or index missing (error printed)
    2   missing required --prefix argument
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_proj(proj_override: str | None) -> str:
    """Return project slug from git toplevel or override."""
    if proj_override:
        return proj_override
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            raw = Path(result.stdout.strip()).name
            # Keep only alphanumeric, dot, dash, underscore — same as bash `tr -cd 'a-zA-Z0-9._-'`
            safe = "".join(c for c in raw if c.isalnum() or c in "._-")
            return safe or "default"
    except Exception:
        pass
    return "default"


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    prefix: str | None = None
    force_off = False
    strict = False
    proj_override: str | None = None
    idx_dir = os.environ.get("CODEMAP_INDEX_DIR", ".cache/codemap")

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--prefix" and i + 1 < len(args):
            prefix = args[i + 1]
            i += 2
        elif a == "--force-off":
            force_off = True
            i += 1
        elif a == "--strict":
            strict = True
            i += 1
        elif a == "--proj" and i + 1 < len(args):
            proj_override = args[i + 1]
            i += 2
        elif a == "--idx-dir" and i + 1 < len(args):
            idx_dir = args[i + 1]
            i += 2
        else:
            i += 1

    if not prefix:
        print("Usage: detect_codemap.py --prefix <name> [--force-off] [--strict]", file=sys.stderr)
        return 2

    tmpdir = os.environ.get("TMPDIR", "/tmp")
    out_file = Path(tmpdir) / f"{prefix}-codemap-enabled"

    if force_off:
        out_file.write_text("false\n")
        return 0

    proj = _resolve_proj(proj_override)
    scan_query_available = shutil.which("scan-query") is not None
    index_path = Path(idx_dir) / f"{proj}.json"
    index_found = index_path.exists()

    if scan_query_available and index_found:
        out_file.write_text("true\n")
        return 0

    if strict:
        if not scan_query_available:
            print(
                "! --codemap passed but codemap plugin not installed.\n"
                "  Install: claude plugin install codemap@borda-ai-rig",
                file=sys.stderr,
            )
        else:
            print(
                f"! --codemap passed but no index found for project '{proj}'.\n"
                "  Build index: /codemap:scan-codebase (requires codemap plugin)",
                file=sys.stderr,
            )
        return 1

    out_file.write_text("false\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
