#!/usr/bin/env python
"""Build the review pre-flight ``scan-query batch`` request for changed modules.

Derives changed modules from ``git diff HEAD --name-only`` (reusing the
``codemap_scan.py`` mapping: strip ``./``/``src/``/``.py``, ``/`` → ``.``, drop
``__init__``; directory fallback when the strip yields nothing) and writes one
JSON array with ``central --top 5`` plus the seven per-module pre-flight queries.
One ``scan-query batch`` process then shares a single coverage block instead of
paying the per-call spawn + coverage cost 7×N times.

Extracted from an inline bash+python heredoc in the review SKILL — heredoc
python in skill bodies is banned (audit Check 23a/30e); ``bin/*.py`` is the
sanctioned home for this transform.

Usage:
    build_codemap_batch.py <out.json>

Output (stdout):
    Batch request JSON written to ``<out.json>``; derived module names printed
    space-separated on stdout (empty line when no ``.py`` files changed).

Exit codes:
    0 — success (including zero changed modules: writes ``central``-only request).
    1 — missing required output-path argument.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Sibling import: resolved by Python's script-dir sys.path entry on direct execution,
# and by plugins/cc_develop/conftest.py during pytest --doctest-modules collection.
from codemap_scan import _git_diff_files, derive_modules_from_diff

FALLBACK_LIMIT = 10

PER_MODULE_QUERIES: tuple[tuple[str, ...], ...] = (
    ("rdeps",),  # importer count → risk tier
    ("fn-rdeps", "--exclude-tests"),
    ("fn-blast",),
    ("mock-rdeps",),
    ("uncovered", "--top", "20"),
    ("xrefs", "--broken"),
    ("undocumented",),
)


def build_batch_request(modules: list[str]) -> list[dict[str, object]]:
    """Assemble the ordered batch request: one ``central`` plus seven queries per module.

    Args:
        modules: Dotted module names derived from the diff (possibly empty).

    Returns:
        List of ``{"cmd": ..., "args": [...]}`` items in scan-query batch order.

    Examples:
        >>> req = build_batch_request(["pkg.mod"])
        >>> req[0]
        {'cmd': 'central', 'args': ['--top', '5']}
        >>> len(req)
        8
        >>> req[1]
        {'cmd': 'rdeps', 'args': ['pkg.mod']}
        >>> req[5]["args"]
        ['--top', '20', 'pkg.mod']
        >>> build_batch_request([])
        [{'cmd': 'central', 'args': ['--top', '5']}]
    """
    items: list[dict[str, object]] = [{"cmd": "central", "args": ["--top", "5"]}]
    for mod in modules:
        for cmd, *flags in PER_MODULE_QUERIES:
            args = [*flags, mod] if cmd == "uncovered" else [mod, *flags]
            items.append({"cmd": cmd, "args": args})
    return items


def main(argv: list[str] | None = None) -> int:
    """Derive changed modules, write the batch request JSON, print the module list.

    Args:
        argv: Optional argv override (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` on success; ``1`` when the output-path argument is missing.

    No doctest — writes a file and shells out to git; covered by pytest with monkeypatch.
    """
    parser = argparse.ArgumentParser(
        prog="build_codemap_batch.py",
        description="Build the review pre-flight scan-query batch request for changed modules.",
    )
    # nargs="?" (not a plain required positional) so a missing path returns exit 1 — argparse's
    # own missing-required exit is 2, but callers and tests rely on the legacy exit-1 contract.
    parser.add_argument("out_json", nargs="?", help="Output path for the batch request JSON.")
    args = parser.parse_args(argv)
    if args.out_json is None:
        print("usage: build_codemap_batch.py <out.json>", file=sys.stderr)
        return 1
    modules = derive_modules_from_diff(_git_diff_files(), limit=FALLBACK_LIMIT)
    Path(args.out_json).write_text(json.dumps(build_batch_request(modules)), encoding="utf-8")
    print(" ".join(modules))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
