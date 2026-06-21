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


def _load_index(root: str) -> dict:
    """Load codemap index; exit 1 if missing.

    Respects ``CODEMAP_INDEX_DIR`` env var — when set, reads
    ``$CODEMAP_INDEX_DIR/<proj>.json`` instead of ``<root>/.cache/codemap/<proj>.json``.
    """
    proj = os.path.basename(root)
    custom_dir = os.environ.get("CODEMAP_INDEX_DIR")
    index_dir = custom_dir if custom_dir else os.path.join(root, ".cache", "codemap")
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
