#!/usr/bin/env python
"""check_index_smoke.py — run codemap index smoke test, emit compact JSON, set exit code.

Wraps ``bin/smoke_test_index.py``: invokes it with ``--index-path`` /
``--max-age-hours``, projects the result down to
``{"ok":bool,"stale":bool,"age_hours":N}``, and uses the projected fields
to drive the exit code. Caller parses STALE/OK from the emitted JSON
without needing ``jq`` in the SKILL.md block.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_index_smoke.py" --index-path <path> [--max-age-hours <N>]

Output (stdout):
    Single JSON object: ``{"ok":true,"stale":false,"age_hours":2.31}``
    On smoke failure the underlying error field is preserved::

        {"ok":false,"stale":false,"age_hours":null,"error":"index file not found"}

Exit codes:
    0 — ok=true AND stale=false
    1 — ok=false OR stale=true OR empty smoke output
    2 — invalid arguments
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_PLUGIN_ROOT = "plugins/codemap"


def project_smoke_result(raw: str) -> dict[str, Any]:
    """Project a raw smoke-test JSON line down to the caller-facing subset.

    Only ``ok``, ``stale``, ``age_hours`` are forwarded by default; the
    upstream ``error`` field is preserved when present so callers can
    surface the underlying failure message.

    Args:
        raw: A single JSON line produced by ``smoke_test_index.py``. Empty
            or whitespace-only input is treated as a "no output" failure.

    Returns:
        A dict shaped ``{"ok": bool, "stale": bool, "age_hours": float|None}``
        plus an optional ``"error"`` key on failure paths.

    Examples:
        >>> project_smoke_result('{"ok": true, "stale": false, "age_hours": 1.5, "path": "/x"}')
        {'ok': True, 'stale': False, 'age_hours': 1.5}
        >>> project_smoke_result('{"ok": false, "stale": false, "age_hours": null, "error": "boom"}')
        {'ok': False, 'stale': False, 'age_hours': None, 'error': 'boom'}
        >>> project_smoke_result('')
        {'ok': False, 'stale': False, 'age_hours': None, 'error': 'smoke_test_index.py produced no output'}
        >>> project_smoke_result('not-json')['ok']
        False
    """
    if not raw or not raw.strip():
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": "smoke_test_index.py produced no output",
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": f"smoke_test_index.py emitted invalid JSON: {exc}",
        }
    if not isinstance(data, dict):
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": "smoke_test_index.py emitted non-object JSON",
        }
    out: dict[str, Any] = {
        "ok": bool(data.get("ok")) if data.get("ok") is not None else None,
        "stale": bool(data.get("stale")) if data.get("stale") is not None else None,
        "age_hours": data.get("age_hours"),
    }
    error_val = data.get("error")
    if error_val is not None:
        out["error"] = error_val
    return out


def derive_exit_code(projected: dict[str, Any]) -> int:
    """Return 0 only when ``ok is True`` and ``stale is False``; otherwise 1.

    Args:
        projected: Output of :func:`project_smoke_result`.

    Returns:
        ``0`` for ok+fresh; ``1`` for any failure or staleness.

    Examples:
        >>> derive_exit_code({"ok": True, "stale": False, "age_hours": 0.1})
        0
        >>> derive_exit_code({"ok": True, "stale": True, "age_hours": 999.0})
        1
        >>> derive_exit_code({"ok": False, "stale": False, "age_hours": None, "error": "x"})
        1
    """
    return 0 if projected.get("ok") is True and projected.get("stale") is False else 1


def _resolve_smoke_script() -> Path:
    """Return path to the upstream ``smoke_test_index.py`` script.

    Honors ``$CLAUDE_PLUGIN_ROOT`` (set by Claude Code at runtime) and falls
    back to the in-repo ``plugins/codemap`` layout for local development.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", DEFAULT_PLUGIN_ROOT)
    return Path(plugin_root) / "bin" / "smoke_test_index.py"


def run_smoke(
    smoke_script: Path,
    index_path: str,
    max_age_hours: int,
) -> dict[str, Any]:
    """Invoke ``smoke_test_index.py`` and return its projected result.

    The upstream script returns exit code 0 (ok+fresh) or 1 (invalid/stale);
    this wrapper re-derives the exit code from the projected JSON, so the
    subprocess return code is intentionally ignored.

    Args:
        smoke_script: Path to ``smoke_test_index.py``.
        index_path: Value passed through as ``--index-path``.
        max_age_hours: Value passed through as ``--max-age-hours``.

    Returns:
        Projected dict from :func:`project_smoke_result` (always well-formed,
        with an ``error`` key on failure).
    """
    # Defense-in-depth: validate index_path exists locally before forwarding to subprocess
    # (child process validates too, but this catches obvious errors cheaply)
    if not Path(index_path).is_file():
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": f"index file not found: {index_path}",
        }
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(smoke_script),
                "--index-path",
                index_path,
                "--max-age-hours",
                str(max_age_hours),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": f"failed to invoke smoke_test_index.py: {exc}",
        }
    return project_smoke_result(completed.stdout)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the derived exit code.

    Args:
        argv: Optional argv override (for tests). When ``None`` argparse
            reads from ``sys.argv[1:]`` as usual.

    Returns:
        ``0`` ok+fresh, ``1`` failed/stale/no-output, ``2`` bad arguments.
    """
    parser = argparse.ArgumentParser(
        prog="check_index_smoke.py",
        description="Run codemap index smoke test, emit compact JSON, set exit code.",
    )
    parser.add_argument("--index-path", required=True, help="Path to the codemap index JSON file.")
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"Max index age in hours before flagging stale (default: {DEFAULT_MAX_AGE_HOURS}).",
    )

    # argparse exits with code 2 on bad/missing args — matches legacy bash contract.
    args = parser.parse_args(argv)

    projected = run_smoke(_resolve_smoke_script(), args.index_path, args.max_age_hours)
    sys.stdout.write(json.dumps(projected, separators=(",", ":")) + "\n")
    return derive_exit_code(projected)


if __name__ == "__main__":
    sys.exit(main())
