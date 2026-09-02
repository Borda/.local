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
import tempfile
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
        out["error"] = _sanitize_error(error_val)
    return out


def _sanitize_error(raw_error: Any) -> str:
    """Sanitize an upstream error string before forwarding it into emitted JSON.

    Caps the message at 256 characters and strips non-printable / non-ASCII
    characters (The ``error`` field originates from a child process and
    must not be forwarded verbatim into terminal-facing output).

    Args:
        raw_error: Arbitrary error value from ``smoke_test_index.py``.

    Returns:
        A bounded, ASCII-only string safe to embed in JSON output.

    Examples:
        >>> _sanitize_error("boom")
        'boom'
        >>> len(_sanitize_error("x" * 500))
        256
        >>> _sanitize_error("a\\u00e9b")
        'a?b'
    """
    return str(raw_error)[:256].encode("ascii", errors="replace").decode("ascii")


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


def _expected_script_roots(plugin_root: Path) -> tuple[Path, ...]:
    """Return the directory roots the resolved smoke script must stay within.

    The script may legitimately live under ``~/.claude`` (installed plugin
    cache) or under the in-repo ``plugins/codemap`` plugin root resolved from
    ``$CLAUDE_PLUGIN_ROOT`` (local development). Any resolved script path
    outside both roots is treated as untrusted (CWE-22).

    Args:
        plugin_root: The plugin root the script was resolved against.

    Returns:
        Tuple of resolved base directories considered safe.
    """
    return (
        (Path(os.path.expanduser("~")) / ".claude").resolve(),
        plugin_root.resolve(),
    )


def _resolve_smoke_script() -> Path:
    """Return validated path to the upstream ``smoke_test_index.py`` script.

    Honors ``$CLAUDE_PLUGIN_ROOT`` (set by Claude Code at runtime) and falls
    back to the in-repo ``plugins/codemap`` layout for local development.

    The resolved script is validated before it can be forwarded to
    ``subprocess.run``: the path must exist as a regular file and must
    resolve within ``~/.claude`` or the plugin root. When ``$CLAUDE_PLUGIN_ROOT``
    is set it must be a non-empty, absolute path.

    Returns:
        The validated, resolved ``Path`` to ``smoke_test_index.py``.

    Raises:
        ValueError: If ``$CLAUDE_PLUGIN_ROOT`` is set but empty or non-absolute,
            or if the resolved script lies outside the expected roots.
        FileNotFoundError: If the resolved script is not an existing file.
    """
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root is not None:
        if not env_root.strip():
            raise ValueError("CLAUDE_PLUGIN_ROOT is set but empty")
        if not Path(env_root).is_absolute():
            raise ValueError(f"CLAUDE_PLUGIN_ROOT must be an absolute path: {env_root!r}")
        plugin_root = Path(env_root)
    else:
        plugin_root = Path(DEFAULT_PLUGIN_ROOT)

    smoke_script = (plugin_root / "bin" / "smoke_test_index.py").resolve()
    if not smoke_script.is_file():
        raise FileNotFoundError(f"smoke_test_index.py not found at expected location: {smoke_script}")
    if not any(smoke_script.is_relative_to(root) for root in _expected_script_roots(plugin_root)):
        raise ValueError(f"resolved smoke script escapes expected roots: {smoke_script}")
    return smoke_script


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
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": f"failed to invoke smoke_test_index.py: {exc}",
        }
    return project_smoke_result(completed.stdout)


def _validate_index_path(index_path: str) -> tuple[bool, str]:
    """Validate that ``index_path`` resolves within allowed roots (CWE-22).

    Allowed roots are the user home directory and the current working directory.
    An index path resolving outside both (e.g. ``/etc/passwd``) is rejected before
    it can be forwarded to the smoke-test subprocess.

    Args:
        index_path: The raw ``--index-path`` string from the caller.

    Returns:
        ``(True, "")`` when the path is within an allowed root; ``(False, reason)`` otherwise.

    Examples:
        >>> ok, _ = _validate_index_path(os.path.join(os.path.expanduser("~"), "foo.json"))
        >>> ok
        True
        >>> ok, reason = _validate_index_path("/etc/passwd")
        >>> ok
        False
        >>> "outside allowed roots" in reason
        True
    """
    resolved = Path(os.path.abspath(index_path)).resolve()
    allowed_roots = [
        Path(os.path.expanduser("~")).resolve(),
        Path.cwd().resolve(),
        Path(tempfile.gettempdir()).resolve(),  # pytest / CI temp dirs
        Path("/tmp").resolve(),  # macOS: /tmp → /private/tmp
    ]
    if any(resolved.is_relative_to(root) for root in allowed_roots):
        return True, ""
    return False, f"--index-path resolves outside allowed roots (home dir, cwd, tmp): {resolved}"


def main(argv: list[str] | None = None) -> int:
    """Run the index smoke check and return its process status.

    Args:
        argv: Optional argument override for tests. When ``None``, argparse reads from ``sys.argv[1:]`` as usual.

    Returns:
        ``0`` for a successful fresh index, ``1`` for a failed, stale, or empty result, or ``2`` for invalid arguments.
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

    # Validate ``--index-path`` before forwarding to subprocess (CWE-22 guard)
    path_ok, path_err = _validate_index_path(args.index_path)
    if not path_ok:
        projected: dict[str, Any] = {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": _sanitize_error(path_err),
        }
        sys.stdout.write(json.dumps(projected, separators=(",", ":")) + "\n")
        return 1

    try:
        smoke_script = _resolve_smoke_script()
    except (ValueError, FileNotFoundError) as exc:
        projected = {
            "ok": False,
            "stale": False,
            "age_hours": None,
            "error": _sanitize_error(f"could not resolve smoke_test_index.py: {exc}"),
        }
        sys.stdout.write(json.dumps(projected, separators=(",", ":")) + "\n")
        return derive_exit_code(projected)

    projected = run_smoke(smoke_script, args.index_path, args.max_age_hours)
    sys.stdout.write(json.dumps(projected, separators=(",", ":")) + "\n")
    return derive_exit_code(projected)


if __name__ == "__main__":
    sys.exit(main())
