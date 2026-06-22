import contextlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

MAX_INDEX_SIZE = 50_000_000  # 50 MB — refuse to load oversized index files (SEC-M10: DoS guard)
MAX_SCAN_ARGS = 4096  # chars — cap SCAN_ARGS before shlex.split to bound parsing cost (SEC-L8: DoS guard)


def _resolve_root(scan_args: str, timeout: int = 15) -> str:
    """Return project root: --root arg → git toplevel → cwd.

    --root is validated against CWD to block directory traversal via SCAN_ARGS.

    Raises:
        ValueError: if ``scan_args`` exceeds ``MAX_SCAN_ARGS`` characters — a
            pathologically large value would make ``shlex.split`` expensive
            (SEC-L8). Raised before the suppress block so it is not swallowed.
    """
    if len(scan_args) > MAX_SCAN_ARGS:
        raise ValueError(f"SCAN_ARGS too large ({len(scan_args)} chars); max {MAX_SCAN_ARGS}")
    with contextlib.suppress(Exception):
        args = shlex.split(scan_args) if scan_args else []
        i = args.index("--root")
        root = args[i + 1]
        abs_root = Path(root).resolve()
        cwd = Path.cwd().resolve()
        if not abs_root.is_relative_to(cwd):
            print(f"scan-stats: --root path outside project root: {abs_root}", file=sys.stderr)
            sys.exit(2)
        return str(abs_root)

    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
                timeout=timeout,
            )
            .decode()
            .strip()
        )
    except Exception:
        return os.getcwd()


def _allowed_index_roots() -> tuple[Path, ...]:
    """Return allowed root directories for CODEMAP_INDEX_DIR validation (SEC-M1: CWE-22).

    Returns:
        Tuple of resolved base paths: the default cache dir under ``~/.cache/codemap``
        and the project-local ``.cache/codemap`` under the git root (or cwd).
    """
    home_cache = (Path(os.path.expanduser("~")) / ".cache" / "codemap").resolve()
    try:
        git_root = (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            .decode()
            .strip()
        )
        project_cache = (Path(git_root) / ".cache" / "codemap").resolve()
    except Exception:
        project_cache = (Path.cwd() / ".cache" / "codemap").resolve()
    return (home_cache, project_cache)


def _validate_index_dir(custom_dir: str) -> bool:
    """Return True when ``custom_dir`` resolves within an allowed cache root (SEC-M1: CWE-22).

    An attacker-controlled ``CODEMAP_INDEX_DIR`` could point ``json.load`` at an
    arbitrary filesystem path. This check restricts it to the two expected locations.

    Args:
        custom_dir: Raw value of the ``CODEMAP_INDEX_DIR`` environment variable.

    Returns:
        True if resolved path is within an allowed root; False otherwise.
    """
    resolved = Path(os.path.abspath(custom_dir)).resolve()
    return any(_is_within_dir(resolved, root) for root in _allowed_index_roots())


def _is_within_dir(path: Path, root: Path) -> bool:
    """Return True when ``path`` resolves inside ``root``.

    Args:
        path: Already-resolved candidate path.
        root: Already-resolved base directory.

    Returns:
        ``True`` if ``path`` is ``root`` or a descendant.
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _load_index(root: str) -> dict:
    """Load codemap index; exit 1 if missing or if CODEMAP_INDEX_DIR fails the path-containment check.

    Respects ``CODEMAP_INDEX_DIR`` env var — when set, reads
    ``$CODEMAP_INDEX_DIR/<proj>.json`` instead of ``<root>/.cache/codemap/<proj>.json``.
    ``CODEMAP_INDEX_DIR`` is validated against allowed roots before use (SEC-M1: CWE-22).
    """
    proj = os.path.basename(root)
    custom_dir = os.environ.get("CODEMAP_INDEX_DIR")
    if custom_dir:
        if not _validate_index_dir(custom_dir):
            print(
                f"scan-stats: CODEMAP_INDEX_DIR resolves outside allowed cache roots: {custom_dir!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        index_dir = custom_dir
    else:
        index_dir = os.path.join(root, ".cache", "codemap")
    index_path = os.path.join(index_dir, f"{proj}.json")
    # DoS guard (SEC-M10): refuse oversized index files before json.load to avoid memory exhaustion.
    try:
        size = os.path.getsize(index_path)
    except FileNotFoundError:
        print(f"Index not found: {index_path} — run /codemap:scan-codebase first")
        sys.exit(1)
    if size > MAX_INDEX_SIZE:
        print(f"Index too large ({size} bytes; max {MAX_INDEX_SIZE}): {index_path}")
        sys.exit(1)
    try:
        with open(index_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Index not found: {index_path} — run /codemap:scan-codebase first")
        sys.exit(1)


_DEFAULT_TIMEOUT = 15


def main() -> None:
    """Print codemap index summary: module count, symbols, top central modules."""
    root = _resolve_root(os.environ.get("SCAN_ARGS", ""), timeout=_DEFAULT_TIMEOUT)
    d = _load_index(root)

    ok = [m for m in d["modules"] if m.get("status") == "ok"]
    deg = [m for m in d["modules"] if m.get("status") == "degraded"]

    if not ok:
        print("No modules indexed.")
        sys.exit(0)

    top = sorted(ok, key=lambda m: m.get("rdep_count", 0), reverse=True)[:5]
    total_syms = sum(len(m.get("symbols", [])) for m in ok)
    total_calls = sum(len(s.get("calls", [])) for m in ok for s in m.get("symbols", []))

    print(f"Modules: {len(ok)} indexed, {len(deg)} degraded")
    print(f"Symbols: {total_syms} (functions, classes, methods)")
    if total_calls:
        print(f"Calls:   {total_calls} resolved call edges (v3 index)")
    print("Most central (by rdep_count):")
    for m in top:
        print(f"  {m.get('rdep_count', 0):>3}  {m['name']}")


if __name__ == "__main__":
    main()
