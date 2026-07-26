#!/usr/bin/env python
"""resolve_centrality.py — turn ``codemap-py query central`` output into a centrality map
plus a file→canonical-module resolver for oss:resolve Step 8 Phase 3.

Phase 3 orders whole worktree groups most-central-first (see
``merge_specialist_batch.order_plan``). That needs two things keyed the **same** way:

1. a ``{module: rdep_count}`` centrality map, and
2. each plan item's module name — and it must equal a key in (1) or the lookup
   silently scores 0.

The earlier approach derived the plan module with a hand-rolled
``sed 's|^src/||; s|/|.|g; s|\\.py$||'`` while the map was keyed by codemap's own
``name``. The two disagree — notably ``pkg/__init__.py`` becomes ``pkg.__init__``
by sed but ``pkg`` in codemap — so package-init items never matched and were
mis-ordered with no error. This helper removes the divergence: both the map and
the per-file resolution come from the **one** ``codemap-py query central`` payload, which
carries ``name``, ``path`` and ``rdep_count`` per module. Files are matched to
modules by path suffix (robust to a scan-root prefix on the index path), so the
returned module name is always a real centrality key.

Usage:
    codemap-py query central --top 100000 | resolve_centrality.py --files a.py,b/c.py

Output (stdout, JSON):
    {"centrality": {name: rdep_count, ...},
     "file_module": {file: name_or_empty, ...}}
"""

from __future__ import annotations

import argparse
import json
import sys


def match_module(file: str, paths: list[tuple[str, str]]) -> str | None:
    """Resolve one repo-relative file path to its canonical codemap module name.

    Matches ``file`` against each module ``path`` by suffix so a scan-root prefix on
    the index path (e.g. ``project-master/src/pkg/mod.py`` vs ``src/pkg/mod.py``) still
    matches. When several modules match, the one with the longest path wins (most
    specific). Comparison is on ``/``-posix paths as given — callers pass repo-relative
    strings on both sides.

    Args:
        file: Repo-relative file path of the edited item (e.g. ``"src/pkg/auth.py"``).
        paths: ``(name, path)`` pairs for every indexed module.

    Returns:
        The matching module ``name``, or None when nothing matches (non-Python file,
        or a path the index does not know).

    Examples:
        >>> mods = [("pkg", "src/pkg/__init__.py"), ("pkg.auth", "src/pkg/auth.py")]
        >>> match_module("src/pkg/auth.py", mods)
        'pkg.auth'
        >>> match_module("src/pkg/__init__.py", mods)
        'pkg'
        >>> match_module("proj-main/src/pkg/auth.py", mods)  # index path has no prefix
        'pkg.auth'
        >>> match_module("src/pkg/auth.py", [("pkg", "a/b/src/pkg/auth.py")])  # prefix on index side
        'pkg'
        >>> match_module("README.md", mods) is None
        True
    """
    best_name: str | None = None
    best_len = -1
    for name, path in paths:
        if path == file or path.endswith("/" + file) or file.endswith("/" + path):
            if len(path) > best_len:
                best_name, best_len = name, len(path)
    return best_name


def build_maps(central: dict[str, object], files: list[str]) -> dict[str, object]:
    """Build the centrality map and the file→module resolution from a central payload.

    Args:
        central: Parsed ``codemap-py query central`` output — ``{"central": [{"name",
            "rdep_count", "path"}, ...]}``.
        files: Repo-relative file paths to resolve to module names.

    Returns:
        ``{"centrality": {name: rdep_count}, "file_module": {file: name_or_empty}}``.
        Unresolved files map to ``""`` (scored 0 downstream, ordered last).

    Examples:
        >>> payload = {"central": [{"name": "pkg.auth", "rdep_count": 9, "path": "src/pkg/auth.py"}]}
        >>> build_maps(payload, ["src/pkg/auth.py", "docs/x.md"])
        {'centrality': {'pkg.auth': 9}, 'file_module': {'src/pkg/auth.py': 'pkg.auth', 'docs/x.md': ''}}
    """
    modules = central.get("central", []) or []
    centrality = {str(m["name"]): int(m.get("rdep_count", 0)) for m in modules}
    paths = [(str(m["name"]), str(m.get("path", ""))) for m in modules if m.get("path")]
    file_module = {f: (match_module(f, paths) or "") for f in files}
    return {"centrality": centrality, "file_module": file_module}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — read central JSON from stdin, print maps as JSON.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code 0 on success; 1 when stdin is not valid central JSON.

    Examples:
        No doctest — reads stdin; covered by pytest with monkeypatch/capsys.
    """
    parser = argparse.ArgumentParser(prog="resolve_centrality.py", description=__doc__)
    parser.add_argument("--files", default="", help="Comma-separated repo-relative file paths to resolve.")
    args = parser.parse_args(argv)

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    try:
        central = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 1

    files = [f for f in args.files.split(",") if f]
    print(json.dumps(build_maps(central, files)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
