#!/usr/bin/env python3
"""Reject hardcoded machine and temporary paths in benchmark source and docs.

Generated manifests, paid-run evidence, and regression fixtures are excluded:
they may preserve machine paths as immutable evidence or deliberate bad inputs.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


BENCHMARKS = Path(__file__).resolve().parent
POLICY_SEED = BENCHMARKS / "policy" / "provider-parity-methodology.json"
SOURCE_SUFFIXES = frozenset({".json", ".md", ".py", ".sh"})
EXCLUDED_DIRS = frozenset({"manifests", "results", "tests"})
_SLASH = re.escape(chr(47))
FORBIDDEN_PATH = re.compile(
    rf"{_SLASH}(?:Users|home){_SLASH}[A-Za-z0-9_-]+{_SLASH}|"
    rf"{_SLASH}(?:private{_SLASH})?tmp{_SLASH}"
)


def _python_strings(path: Path) -> list[tuple[int, str]]:
    """Return line-numbered Python string literals from one source file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno + offset, line)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        for offset, line in enumerate(node.value.splitlines())
    ]


def find_violations(path: Path) -> list[tuple[int, str]]:
    """Return forbidden absolute-path literals in one governed source file."""
    if path.suffix == ".py":
        lines = _python_strings(path)
    elif path.suffix in {".json", ".md", ".sh"}:
        lines = list(enumerate(path.read_text(encoding="utf-8").splitlines(), start=1))
    else:
        return []
    return [
        (line_number, line.strip())
        for line_number, line in lines
        if not line.lstrip().startswith("#") and FORBIDDEN_PATH.search(line)
    ]


def _default_sources() -> list[Path]:
    """Return executable benchmark sources governed by the portability gate."""
    sources = {
        path
        for path in BENCHMARKS.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not any(part in EXCLUDED_DIRS for part in path.relative_to(BENCHMARKS).parts[:-1])
    }
    sources.add(POLICY_SEED)
    return sorted(sources)


def main(paths: list[str] | None = None) -> int:
    """Check explicit pre-commit paths or all governed benchmark sources."""
    candidates = [Path(raw) for raw in paths] if paths else _default_sources()
    violations = [
        (path, line_number, line)
        for path in candidates
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
        for line_number, line in find_violations(path)
    ]
    for path, line_number, line in violations:
        print(f"{path}:{line_number}: hardcoded absolute machine or temporary path: {line}", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
