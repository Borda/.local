#!/usr/bin/env python
"""dev_shared_resolve.py — resolve develop plugin _shared/ (Windows-portable).

Locates the develop plugin's ``skills/_shared`` directory from the
installed cache, with a source-tree fallback for local development.
Pure-Python replacement for ``dev-shared-resolve.sh``; no shell
interpolation, no ``find``/``sort`` pipelines.

With ``--foundry``: also emits the foundry plugin's ``skills/_shared``
path on a second stdout line so the develop skills can dispatch foundry
agents in installed-plugin contexts.

Output contract
---------------
* No flag: ``<develop-shared-path>\\n``
* ``--foundry``: ``<develop-shared-path>\\n<foundry-shared-path>\\n``
* Exits 0 always; the caller validates that the printed paths exist.

Tier cascade (per plugin)
-------------------------
* **Tier 1** — Cache semver scan under
  ``~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/_shared``,
  skipping versions marked ``.orphaned_at``.
* **Tier 2** — Source-tree fallback ``plugins/<plugin>/skills/_shared``
  (with stderr warning).

<!-- file: dev_shared_resolve.py — consumers: dev-shared-resolve.sh -->
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_MARKETPLACE = "borda-ai-rig"
_SHARED_SUBDIR = "skills/_shared"


def _resolve(cmd: str) -> str:
    """Resolve executable basename to absolute path via :func:`shutil.which`.

    Args:
        cmd: Executable basename.

    Returns:
        Absolute path on ``PATH``.

    Raises:
        FileNotFoundError: When ``cmd`` is not on ``PATH``.

    Examples:
        >>> import os
        >>> os.path.isabs(_resolve("python"))
        True
    """
    resolved = shutil.which(cmd)
    if not resolved:
        raise FileNotFoundError(f"required executable not on PATH: {cmd!r}")
    return resolved


def _version_key(name: str) -> list[int]:
    """Extract digit runs from a version dir name for semver-aware sorting.

    Args:
        name: Directory basename.

    Returns:
        Integer list of digit runs (``0.20.0`` → ``[0, 20, 0]``).

    Examples:
        >>> _version_key("0.20.0")
        [0, 20, 0]
        >>> _version_key("0.9.0") < _version_key("0.20.0")
        True
    """
    return [int(t) for t in re.findall(r"\d+", name)]


def _cache_root(home: Path) -> Path:
    """Return marketplace-scoped plugin cache root under ``home``.

    Examples:
        >>> _cache_root(Path("/h")).as_posix()
        '/h/.claude/plugins/cache/borda-ai-rig'
    """
    return home / ".claude" / "plugins" / "cache" / _MARKETPLACE


def _resolve_plugin_shared(plugin: str, home: Path) -> str | None:
    """Cache scan for ``<plugin>/skills/_shared`` skipping orphaned dirs.

    Args:
        plugin: Plugin short-name (``develop`` or ``foundry``).
        home: User home directory.

    Returns:
        Resolved cache path string, or ``None`` if cache has no usable hit.
    """
    plugin_cache = _cache_root(home) / plugin
    if not plugin_cache.is_dir():
        return None
    candidates: list[tuple[list[int], Path]] = []
    for version_dir in plugin_cache.iterdir():
        if not version_dir.is_dir():
            continue
        if (version_dir / ".orphaned_at").exists():
            continue
        target = version_dir / _SHARED_SUBDIR
        if target.is_dir():
            candidates.append((_version_key(version_dir.name), target))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return str(candidates[-1][1])


def resolve_paths(*, include_foundry: bool, home: Path | None = None) -> list[str]:
    """Resolve develop (and optionally foundry) shared paths.

    Tier 1: cache scan via :func:`_resolve_plugin_shared`.
    Tier 2: source-tree fallback ``plugins/<plugin>/skills/_shared``.

    Args:
        include_foundry: When ``True``, append foundry's path as second entry.
        home: Override for ``Path.home()`` (testing).

    Returns:
        Ordered list of path strings — index 0 is develop, index 1 is foundry
        (only when ``include_foundry`` is set).

    Examples:
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     out = resolve_paths(include_foundry=False, home=Path(d))
        ...     out  # source-tree fallback
        ['plugins/develop/skills/_shared']
    """
    home = home if home is not None else Path.home()
    paths: list[str] = []
    dev_path = _resolve_plugin_shared("develop", home)
    if dev_path is None:
        dev_path = (Path("plugins") / "develop" / _SHARED_SUBDIR).as_posix()
    paths.append(dev_path)
    if include_foundry:
        foundry_path = _resolve_plugin_shared("foundry", home)
        if foundry_path is None:
            print(
                "dev_shared_resolve: foundry plugin not in cache — using source-tree fallback",
                file=sys.stderr,
            )
            foundry_path = (Path("plugins") / "foundry" / _SHARED_SUBDIR).as_posix()
        paths.append(foundry_path)
    return paths


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code (0 always)."""
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    parser = argparse.ArgumentParser(
        prog="dev_shared_resolve",
        description="Resolve develop plugin's skills/_shared path (and optionally foundry's).",
    )
    parser.add_argument(
        "--foundry",
        action="store_true",
        help="Also emit the foundry plugin's _shared path on a second line.",
    )
    args = parser.parse_args(argv)
    for line in resolve_paths(include_foundry=args.foundry):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
