#!/usr/bin/env python3
"""detect_codemap.py — detect codemap plugin availability, index presence, and currency.

consumers: resolve/SKILL.md, review/SKILL.md, analyse/modes/codemap-signals.md

Determines whether the codemap plugin is installed and an index exists for the
current project.  Writes result to ${TMPDIR:-/tmp}/<prefix>-codemap-enabled-<CSID>.
When check-index-currency is on PATH, also writes currency status to
${TMPDIR:-/tmp}/<prefix>-codemap-currency-<CSID> ("current", "stale", or "no_index").

Usage:
    python detect_codemap.py --prefix resolve [--force-off] [--strict] [--proj <name>]

Flags:
    --prefix <name>   Prefix for temp-file name (e.g. resolve, review). Required.
    --force-off       CODEMAP_FORCE_OFF=true — always write false.
    --strict          CODEMAP_STRICT=true — exit 1 when codemap absent/index missing.
    --proj <name>     Project name override (default: basename of git toplevel).
    --idx-dir <path>  Codemap index directory override (default: .cache/codemap).

Temp files written:
    ${TMPDIR:-/tmp}/<prefix>-codemap-enabled-<CSID>   → "true" or "false"
    ${TMPDIR:-/tmp}/<prefix>-codemap-currency-<CSID>  → "current", "stale", or "no_index"

Exit codes:
    0   success (CODEMAP_ENABLED written)
    1   --strict mode: codemap not installed or index missing (error printed)
    2   missing required --prefix argument
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

    # Honour only -h/--help via argparse; every other flag flows through the manual
    # loop below, which ignores unknowns and keeps the legacy exit-2-on-missing-prefix
    # contract (argparse's native errors would change both behaviors).
    if args in (["-h"], ["--help"]):
        argparse.ArgumentParser(
            prog="detect_codemap.py",
            description="Detect codemap plugin availability, index presence, and currency.",
        ).parse_args(["-h"])

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

    csid = os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "shared"
    tmpdir = os.environ.get("TMPDIR") or tempfile.gettempdir()
    out_file = Path(tmpdir) / f"{prefix}-codemap-enabled-{csid}"
    currency_file = Path(tmpdir) / f"{prefix}-codemap-currency-{csid}"

    if force_off:
        out_file.write_text("false\n")
        currency_file.write_text("off\n")
        return 0

    proj = _resolve_proj(proj_override)
    scan_query_available = shutil.which("scan-query") is not None
    index_path = Path(idx_dir) / f"{proj}.json"
    index_found = index_path.exists()

    if not scan_query_available or not index_found:
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
        if scan_query_available and not index_found:
            print(
                f"⚠ codemap: no index for project '{proj}' at {index_path}\n"
                "  Run /codemap:scan-codebase to build it, then re-run this skill.",
            )
        currency_file.write_text("no_index\n")
        out_file.write_text("false\n")
        return 0

    # Index found — check currency when check-index-currency is available
    currency_bin = shutil.which("check-index-currency")
    currency = "current"
    currency_reason = ""
    if currency_bin:
        try:
            result = subprocess.run(
                [sys.executable, currency_bin, "--index-path", str(index_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            data = json.loads(result.stdout.strip())
            currency = data.get("status", "current")
            currency_reason = data.get("reason", "")
        except Exception:
            currency = "current"  # parse/timeout error → assume current

    currency_file.write_text(f"{currency}\n")

    if currency == "stale":
        print(
            f"⚠ codemap: index is stale — {currency_reason}\n  Run /codemap:scan-codebase to refresh it.",
        )

    out_file.write_text("true\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
