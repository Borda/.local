#!/usr/bin/env python
"""Structural codemap scan: derive affected modules and emit rdeps + optional coupled output.

Usage:
    codemap_scan.py --source=find --target <path> [--limit N]
    codemap_scan.py --source=diff [--limit N]

Sources:
    find — enumerate ``.py`` files under ``<path>``, derive module names via codemap's
        ``resolve_target_module`` rules.
    diff — derive modules from ``git diff HEAD --name-only``; flat-layout fallback when
        ``src/`` strip yields nothing.

Output:
    Concatenated ``scan-query`` JSON blocks per module on stdout; ``coupled --top N`` appended
    for find mode.

Exit codes:
    0 — success (including no-results; missing ``scan-query`` binary; missing index file).
    1 — missing prerequisite (required CLI arg).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path


def derive_module_from_path(path: str) -> str:
    """Convert a Python file path to its module dotted name.

    Strips leading ``./`` and ``src/`` prefixes and the ``.py`` suffix, then replaces ``/`` with ``.``.

    Args:
        path: Filesystem path to a ``.py`` file (relative or absolute-ish).

    Returns:
        The dotted module name (empty string if input collapses to nothing).

    Examples:
        >>> derive_module_from_path("./src/pkg/mod.py")
        'pkg.mod'
        >>> derive_module_from_path("src/pkg/mod.py")
        'pkg.mod'
        >>> derive_module_from_path("./pkg/mod.py")
        'pkg.mod'
        >>> derive_module_from_path("pkg/__init__.py")
        'pkg.__init__'
        >>> derive_module_from_path("mod.py")
        'mod'
    """
    s = path
    if s.startswith("./"):
        s = s[2:]
    if s.startswith("src/"):
        s = s[4:]
    if s.endswith(".py"):
        s = s[:-3]
    return s.replace("/", ".")


def derive_modules_from_find(files: Iterable[str]) -> list[str]:
    """Derive module dotted names from an iterable of ``.py`` file paths (find-mode rules).

    Empty entries are dropped. Order preserved.

    Args:
        files: Iterable of file path strings, typically from a ``find ... -name '*.py'`` walk.

    Returns:
        List of dotted module names, in input order, with empty entries dropped.

    Examples:
        >>> derive_modules_from_find(["./src/a.py", "./src/pkg/b.py", ""])
        ['a', 'pkg.b']
        >>> derive_modules_from_find([])
        []
    """
    out: list[str] = []
    for f in files:
        if not f:
            continue
        mod = derive_module_from_path(f)
        if mod:
            out.append(mod)
    return out


def derive_modules_from_diff(diff_files: Iterable[str], limit: int) -> list[str]:
    """Derive module dotted names from git diff output (diff-mode rules).

    Drops non-``.py`` paths and ``__init__`` modules. If the ``src/``-stripped derivation yields
    no modules, falls back to flat layout: directory containing the file, sorted and unique,
    capped at ``limit`` entries.

    Args:
        diff_files: Iterable of file path strings from ``git diff HEAD --name-only``.
        limit: Cap applied to the flat-layout fallback list.

    Returns:
        Primary list of module dotted names; flat-layout dir fallback when primary is empty.

    Examples:
        >>> derive_modules_from_diff(["src/pkg/a.py", "src/pkg/__init__.py", "README.md"], 10)
        ['pkg.a']
        >>> derive_modules_from_diff(["pkg/__init__.py"], 10)
        ['pkg']
        >>> derive_modules_from_diff(["lib/x.py", "lib/y.py", "other/z.py"], 10)
        ['lib.x', 'lib.y', 'other.z']
        >>> derive_modules_from_diff(["lib/__init__.py", "other/__init__.py"], 10)
        ['lib', 'other']
        >>> derive_modules_from_diff([], 10)
        []
    """
    py_files = [f for f in diff_files if f.endswith(".py")]
    primary: list[str] = []
    for f in py_files:
        s = f
        if s.startswith("src/"):
            s = s[4:]
        s = s[:-3]  # strip .py
        mod = s.replace("/", ".")
        if mod and not mod.endswith("__init__"):
            primary.append(mod)

    if primary:
        return primary

    # Flat-layout fallback: containing directory (sort -u | head -N).
    dirs: set[str] = set()
    for f in py_files:
        parent = str(Path(f).parent)
        if parent and parent != ".":
            dirs.add(parent)
    return sorted(dirs)[:limit]


def _git_diff_files(timeout: int = 15) -> list[str]:
    """Return ``.py`` file paths from ``git diff HEAD --name-only`` (empty list on failure)."""
    try:
        out = subprocess.check_output(  # noqa: S603 — fixed argv, no shell.
            ["git", "diff", "HEAD", "--name-only"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line for line in out.splitlines() if line]


def _git_project_name(timeout: int = 15) -> str:
    """Return basename of git toplevel, falling back to current dir basename."""
    try:
        out = subprocess.check_output(  # noqa: S603 — fixed argv, no shell.
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        ).strip()
        if out:
            return Path(out).name
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path.cwd().name


_MAX_FIND_FILES = 2000


def _find_py_files(target: str) -> list[str]:
    """Walk ``target`` and return ``./``-prefixed paths of regular ``.py`` files.

    Security guards:
        * ``target`` must resolve to a path inside the current working directory;
          paths escaping CWD (e.g. ``/``, ``~/.ssh``) are refused.
        * Walk is capped at ``_MAX_FIND_FILES`` to prevent resource exhaustion.
    """
    root = Path(target)
    if not root.exists():
        return []
    # Restrict scans to CWD subtree — refuse arbitrary filesystem paths.
    resolved_root = root.resolve()
    cwd = Path.cwd().resolve()
    try:
        resolved_root.relative_to(cwd)
    except ValueError:
        print(
            f"codemap_scan: --target path outside project root: {resolved_root}",
            file=sys.stderr,
        )
        return []
    paths: list[str] = []
    for p in sorted(root.rglob("*.py")):
        if p.is_file():
            # Match bash semantics: paths start with ./ when target starts with ./
            s = str(p)
            if target.startswith("./") and not s.startswith("./"):
                s = "./" + s
            paths.append(s)
            if len(paths) >= _MAX_FIND_FILES:
                break
    return paths


def _scan_query(args: list[str], timeout: int = 15) -> None:
    """Invoke ``scan-query`` with given args; stream stdout; swallow non-zero exits."""
    try:
        subprocess.run(  # noqa: S603 — fixed binary name + caller-controlled args.
            ["scan-query", *args],
            check=False,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # scan-query missing or timed out — silent skip.
        return


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI args matching the bash interface (``--source=...`` and ``--source ...`` forms)."""
    parser = argparse.ArgumentParser(
        prog="codemap_scan.py",
        description="Derive affected modules and emit scan-query rdeps + optional coupled output.",
        add_help=True,
    )
    parser.add_argument("--source", choices=("find", "diff"), default=None)
    parser.add_argument("--target", default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Subprocess timeout in seconds for git and scan-query calls (default: 15).",
    )
    # Bash version silently ignored unrecognised positional tokens — mirror that.
    args, _unknown = parser.parse_known_args(argv)
    return args


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``codemap-scan.sh`` behaviour exactly.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (0 success or soft-skip; 1 missing prerequisite arg).
    """
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))

    if not args.source:
        print("codemap_scan.py: --source=find|diff required", file=sys.stderr)
        return 1

    # scan-query missing → silent skip (caller decides whether to warn).
    if shutil.which("scan-query") is None:
        return 0

    # Index file missing → silent exit 0.
    project = _git_project_name(timeout=args.timeout)
    index_path = Path(".cache") / "scan" / f"{project}.json"
    if not index_path.is_file():
        return 0

    if args.source == "find":
        if not args.target:
            print("codemap_scan.py: --target required for --source=find", file=sys.stderr)
            return 1
        modules = derive_modules_from_find(_find_py_files(args.target))
    else:  # diff
        modules = derive_modules_from_diff(_git_diff_files(timeout=args.timeout), args.limit)

    if not modules:
        return 0

    for mod in modules:
        if mod:
            _scan_query(["rdeps", mod], timeout=args.timeout)

    if args.source == "find":
        _scan_query(["coupled", "--top", str(args.limit)], timeout=args.timeout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
