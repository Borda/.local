#!/usr/bin/env python3
"""Resolve CODEMAP_ENABLED from auto/strict/off to true/false.

Python (not shell) because plugins must run on Windows, where a `#!` shebang is
not honoured — see plugins/CLAUDE.md §Installability. Behaviour is a 1:1 port of
the former `bin/codemap-resolve` bash script; differential parity was verified
across the full mode/index matrix before the shell version was removed.

Also writes currency status to ${TMPDIR}/dev-codemap-currency-${CSID} when
check-index-currency is available ("current", "stale", or "no_index").
Usage: CODEMAP_ENABLED=$(python .../codemap_resolve.py "$CODEMAP_ENABLED") || exit 1
Exits 0: prints "true" or "false" to stdout
Exits 1: strict mode and binary/index missing — error to stderr
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CURRENCY_PREFIX = "dev-codemap-currency"
TOOL_LABEL = "codemap-py"     # warn prefix
QUERY_LABEL = "codemap-py"    # binary name in the strict BREAKING message


def _currency_file() -> Path:
    csid = os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "shared"
    tmp = os.environ.get("TMPDIR") or tempfile.gettempdir()
    return Path(tmp) / f"{CURRENCY_PREFIX}-{csid}"


def _write_currency(value: str) -> None:
    try:
        _currency_file().write_text(value + "\n")
    except OSError:
        pass  # currency status is advisory; never fail the gate on it


def _project_name() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        root = out.stdout.strip() if out.returncode == 0 and out.stdout.strip() else "default"
    except (OSError, subprocess.SubprocessError):
        root = "default"
    return re.sub(r"[^a-zA-Z0-9._-]", "", Path(root).name) or "default"


def _currency_field(cic: str, index: Path, field: str, fallback: str) -> str:
    try:
        out = subprocess.run(
            [sys.executable, cic, "--index-path", str(index), "--field", field],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() if out.returncode == 0 else fallback
    except (OSError, subprocess.SubprocessError):
        return fallback


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"

    if mode in ("off", "false"):
        print("false")
        _write_currency("off")
        return 0
    if mode == "true":
        print("true")
        return 0

    if not shutil.which("codemap-py"):
        _write_currency("no_index")
        if mode == "strict":
            print(
                f"! BREAKING — --codemap strict: {TOOL_LABEL} query not found. Install {TOOL_LABEL} plugin.",
                file=sys.stderr,
            )
            return 1
        print("false")
        return 0

    index = Path(os.environ.get("CODEMAP_INDEX_DIR", ".cache/codemap")) / f"{_project_name()}.json"

    if not index.is_file():
        _write_currency("no_index")
        if mode == "strict":
            print(
                f"! BREAKING — --codemap strict: index {index} not found. Run /codemap-py:scan-codebase first.",
                file=sys.stderr,
            )
            return 1
        print(
            f"⚠ {TOOL_LABEL}: no index for project '{_project_name()}' at {index}\n"
            "  Run /codemap-py:scan-codebase to build it, then re-run this skill.",
            file=sys.stderr,
        )
        print("false")
        return 0

    cic = shutil.which("check-index-currency")
    if cic:
        currency = _currency_field(cic, index, "status", "current")
        reason = _currency_field(cic, index, "reason", "")
        _write_currency(currency)
        if currency == "stale":
            print(
                f"⚠ {TOOL_LABEL}: index is stale — {reason}\n  Run /codemap-py:scan-codebase to refresh it.",
                file=sys.stderr,
            )
    else:
        _write_currency("current")
    print("true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
