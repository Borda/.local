import contextlib
import json
import os
import shlex
import subprocess
import sys


def _resolve_root(scan_args: str, timeout: int = 15) -> str:
    """Return project root: --root arg → git toplevel → cwd."""
    with contextlib.suppress(Exception):
        args = shlex.split(scan_args) if scan_args else []
        i = args.index("--root")
        return os.path.abspath(args[i + 1])

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
    """Load .cache/scan/<project>.json; exit 1 if missing."""
    proj = os.path.basename(root)
    index_path = os.path.join(root, ".cache", "scan", f"{proj}.json")
    try:
        with open(index_path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Index not found: {index_path} — run /codemap:scan first")
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
