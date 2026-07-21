#!/usr/bin/env python3
"""state.py — persist small shell values across Bash tool calls.

Each Bash tool call runs in a fresh shell, so a variable assigned in one
```bash block is empty when a later block references it. Skills work around this
by writing values to a temp file and re-sourcing it. This helper standardizes
that pattern behind one tested idiom instead of ad-hoc per-skill code:

    # persist (early block)
    python "${CLAUDE_PLUGIN_ROOT}/bin/state.py" set audit-$RUN RUN_DIR="$RUN_DIR" SCOPE="$SCOPE"
    # reload (later block, fresh shell)
    eval "$(python "${CLAUDE_PLUGIN_ROOT}/bin/state.py" load audit-$RUN)"

The namespace is chosen by the caller; include a run-unique component
(timestamp / run-id) when concurrent sessions of the same skill could otherwise
collide on a fixed name. Values are stored under
``${TMPDIR:-/tmp}/claude-state-<namespace>.env`` and emitted single-quote-quoted
so ``eval`` is injection-safe.

Usage:
    state.py set <namespace> KEY=VALUE [KEY=VALUE ...]   # merge (create/update)
    state.py load <namespace>                            # print `KEY='VALUE'` lines for eval
    state.py clear <namespace>                           # remove the state file

Exit code 0 on success, 2 on usage error.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_NS_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def state_path(namespace: str) -> Path:
    """Return the state file path for a namespace.

    Args:
        namespace: Caller-chosen namespace (sanitized to a safe filename).

    Returns:
        Path under ``${TMPDIR:-/tmp}`` for this namespace's values.

    Examples:
        >>> state_path("audit-123").name
        'claude-state-audit-123.env'
    """
    safe = _NS_SAFE.sub("_", namespace)
    base = os.environ.get("TMPDIR", "/tmp")
    return Path(base) / f"claude-state-{safe}.env"


def _read(path: Path) -> dict[str, str]:
    """Return existing KEY=VALUE pairs from a state file (empty if absent)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, _, val = line.partition("=")
            values[key.strip()] = val
    return values


def set_values(namespace: str, assignments: list[str]) -> int:
    """Merge KEY=VALUE assignments into a namespace's state file.

    Args:
        namespace: Target namespace.
        assignments: Strings of the form ``KEY=VALUE`` (VALUE may be empty or contain ``=``).

    Returns:
        0 on success, 2 if any assignment is malformed.
    """
    path = state_path(namespace)
    values = _read(path)
    for item in assignments:
        if "=" not in item:
            sys.stderr.write(f"state.py: malformed assignment (want KEY=VALUE): {item!r}\n")
            return 2
        key, _, val = item.partition("=")
        key = key.strip()
        if not key:
            sys.stderr.write(f"state.py: empty key in {item!r}\n")
            return 2
        values[key] = val
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return 0


def load_values(namespace: str) -> int:
    """Print ``KEY='VALUE'`` lines for a namespace, safe to ``eval`` in bash.

    Single quotes inside values are escaped as ``'\\''`` so the emitted lines are
    injection-safe.

    Args:
        namespace: Namespace to load.

    Returns:
        0 always (absent file → no output).
    """
    for key, val in _read(state_path(namespace)).items():
        escaped = val.replace("'", "'\\''")
        print(f"{key}='{escaped}'")
    return 0


def clear(namespace: str) -> int:
    """Remove a namespace's state file (no-op if absent). Returns 0."""
    state_path(namespace).unlink(missing_ok=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Persist small shell values across Bash tool calls")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_set = sub.add_parser("set", help="merge KEY=VALUE assignments")
    p_set.add_argument("namespace")
    p_set.add_argument("assignments", nargs="+")
    p_load = sub.add_parser("load", help="print KEY='VALUE' lines for eval")
    p_load.add_argument("namespace")
    p_clear = sub.add_parser("clear", help="remove the state file")
    p_clear.add_argument("namespace")
    args = parser.parse_args(argv)

    if args.cmd == "set":
        return set_values(args.namespace, args.assignments)
    if args.cmd == "load":
        return load_values(args.namespace)
    return clear(args.namespace)


if __name__ == "__main__":
    sys.exit(main())
