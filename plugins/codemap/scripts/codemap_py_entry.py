#!/usr/bin/env python3
"""codemap-py source-tree bootstrap (plan §7.2).

Single Python entrypoint shared by POSIX launchers, Windows launchers, an
editable developer install, and runtime skills. It resolves the real plugin
root, validates the running interpreter, prepends the import roots, and hands
control to ``codemap_py_cli`` without remapping arguments.

Transitional fallback: the current tracked layout has no ``src/`` package yet, so the
entry prepends ``<root>/scripts`` (the dispatcher shim ``codemap_py_cli``) and
``<root>/bin`` (the current executables plus their private ``_*`` modules). It
performs no install, download, cache mutation, or dependency setup.

Examples:
    Run from a POSIX launcher::

        python3 scripts/codemap_py_entry.py doctor --json
"""

from __future__ import annotations

import sys
from pathlib import Path

# Interpreter bound is duplicated (not imported) so the gate runs *before* any
# codemap import, honouring plan §7.1 "validated before importing codemap_py".
_MAJOR = 3
_MIN_MINOR = 11
_MAX_MINOR_EXCLUSIVE = 15
_INTERPRETER_DIAGNOSTIC = (
    "codemap-py: unsupported interpreter {impl} {major}.{minor}; "
    "requires CPython >=3.11,<3.15 (set CODEMAP_PYTHON to an eligible interpreter)"
)
_INTERPRETER_EXIT = 127


def _interpreter_supported() -> bool:
    """Return whether the running interpreter satisfies the CPython bound."""
    info = sys.version_info
    return (
        sys.implementation.name == "cpython"
        and info.major == _MAJOR
        and _MIN_MINOR <= info.minor < _MAX_MINOR_EXCLUSIVE
    )


def main() -> int:
    """Validate the interpreter, wire the import roots, and delegate to the CLI.

    Returns:
        The dispatcher exit code, or ``127`` when the running interpreter is not
        an eligible CPython. On rejection stdout stays empty and a single
        actionable diagnostic is written to stderr (plan §7.5).

    Examples:
        >>> isinstance(main, object)
        True
    """
    if not _interpreter_supported():
        info = sys.version_info
        sys.stderr.write(
            _INTERPRETER_DIAGNOSTIC.format(impl=sys.implementation.name, major=info.major, minor=info.minor) + "\n"
        )
        return _INTERPRETER_EXIT

    root = Path(__file__).resolve().parents[1]
    for sub in ("src", "scripts", "bin"):
        candidate = root / sub
        if candidate.is_dir():
            entry = str(candidate)
            if entry not in sys.path:
                sys.path.insert(0, entry)

    import codemap_py_cli  # imported after the interpreter gate and path wiring

    return codemap_py_cli.main(sys.argv[1:], plugin_root=root)


if __name__ == "__main__":
    raise SystemExit(main())
