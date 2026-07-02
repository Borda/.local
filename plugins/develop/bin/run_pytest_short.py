#!/usr/bin/env python
"""Run ``pytest`` with ``--tb=short -v`` and emit only the last N lines of combined output.

Usage:
    run_pytest_short.py [pytest_cmd] [target] [tail_n]

Behaviour:
    Validates ``pytest_cmd`` against an allowlist
    (``pytest``, ``uv run pytest``, ``python -m pytest``, ``poetry run pytest``,
    ``poetry run python -m pytest``) before any execution — the set must cover
    every runner ``runner-detection.md`` can emit.
    Captures combined stdout+stderr, then prints the last ``tail_n`` lines (default 20).
    Bad/non-integer ``tail_n`` silently falls back to 20.

Exit codes:
    0 — pytest passed.
    1-5 — pytest reported failure/collection error (propagated unchanged).
    2 — also used when ``pytest_cmd`` is not in the allowlist (before pytest runs).
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from shutil import which

_PYTEST_ALLOWLIST: frozenset[str] = frozenset(
    {
        "pytest",
        "uv run pytest",
        "python -m pytest",
        "poetry run pytest",
        "poetry run python -m pytest",
    }
)
_DEFAULT_TAIL_N: int = 20


def _validate_target_in_cwd(target: str) -> None:
    """Reject targets that resolve outside the current working directory.

    Args:
        target: Raw target string from argv (file/dir path or pytest node id).

    Raises:
        SystemExit: With exit code 1 if the resolved target escapes ``Path.cwd()``.
            Pytest node ids (``path::nodeid``) have the path portion validated.
    """
    path_part = target.split("::", 1)[0]
    if not path_part:
        return
    target_path = Path(path_part).resolve()
    cwd = Path.cwd().resolve()
    try:
        target_path.relative_to(cwd)
    except ValueError:
        print(
            f"run-pytest-short: rejected target outside project directory: {target_path}",
            file=sys.stderr,
        )
        sys.exit(1)


# Hard cap on captured subprocess output (50 MB) — guards against adversarial test floods.
_MAX_OUTPUT_BYTES: int = 50 * 1024 * 1024


def _resolve(cmd: str) -> str:
    """Resolve ``cmd`` to an absolute path using ``shutil.which``.

    Args:
        cmd: Bare executable name (e.g. ``"pytest"``, ``"uv"``, ``"python"``).

    Returns:
        Absolute path to the executable.

    Raises:
        FileNotFoundError: If ``cmd`` is not present on ``PATH``.
    """
    resolved = which(cmd)
    if resolved is None:
        raise FileNotFoundError(f"executable not found on PATH: {cmd}")
    return resolved


def _parse_tail_n(raw: str) -> int:
    """Parse ``raw`` as a non-negative int; fall back to default on bad input.

    Args:
        raw: Tail-line-count argument as a string (possibly empty or non-numeric).

    Returns:
        Parsed positive int, or ``_DEFAULT_TAIL_N`` on any parse failure.

    Examples:
        >>> _parse_tail_n("5")
        5
        >>> _parse_tail_n("abc")
        20
        >>> _parse_tail_n("")
        20
        >>> _parse_tail_n("-3")
        20
    """
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TAIL_N
    return n if n >= 0 else _DEFAULT_TAIL_N


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``run-pytest-short.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Pytest's exit code, or 2 when ``pytest_cmd`` is rejected by the allowlist.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)
    pytest_cmd = args[0] if len(args) >= 1 else "pytest"
    target = args[1] if len(args) >= 2 else "."
    tail_n = _parse_tail_n(args[2] if len(args) >= 3 else "")

    if pytest_cmd not in _PYTEST_ALLOWLIST:
        print(f"run-pytest-short: rejected unsafe PYTEST_CMD: {pytest_cmd}", file=sys.stderr)
        return 2

    _validate_target_in_cwd(target)

    parts = shlex.split(pytest_cmd)
    parts[0] = _resolve(parts[0])
    # Capture combined stdout+stderr so we can tail it; mirrors `2>&1 | tail -N`.
    # Read incrementally with a byte cap so adversarial test output cannot exhaust memory
    # before tail_n truncation is applied.
    proc = subprocess.Popen(  # noqa: S603 — allowlisted cmd + resolved binary, no shell.
        [*parts, "--tb=short", target, "-v"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    chunks: list[str] = []
    total = 0
    truncated = False
    assert proc.stdout is not None  # PIPE guarantees a stream.
    for chunk in iter(lambda: proc.stdout.read(64 * 1024), ""):
        remaining = _MAX_OUTPUT_BYTES - total
        if remaining <= 0:
            truncated = True
            # Drain remaining output without buffering so the child can exit cleanly.
            for _ in iter(lambda: proc.stdout.read(64 * 1024), ""):  # noqa: B023 — intentional rebinding per loop.
                pass
            break
        if len(chunk) > remaining:
            chunks.append(chunk[:remaining])
            total += remaining
            truncated = True
            for _ in iter(lambda: proc.stdout.read(64 * 1024), ""):  # noqa: B023 — intentional rebinding per loop.
                pass
            break
        chunks.append(chunk)
        total += len(chunk)
    returncode = proc.wait(timeout=600)  # 10-min hard cap; pytest_cmd callers set # timeout: 600000 in bash
    output = "".join(chunks)
    if truncated:
        output += f"\n[run-pytest-short: output truncated at {_MAX_OUTPUT_BYTES} bytes]"
    # splitlines drops the trailing newline if present; reattach to preserve newline semantics.
    lines = output.splitlines()
    tail = lines[-tail_n:] if tail_n > 0 else []
    if tail:
        print("\n".join(tail))
    return returncode


if __name__ == "__main__":
    sys.exit(main())
