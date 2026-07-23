#!/usr/bin/env python3
"""Assemble the deterministic codemap-py candidate package.

Builds a self-contained, deterministic candidate directory from the tracked
sources: generated Claude and Codex manifests, one minimal ``scan-codebase``
runtime adapter per host, the POSIX/Windows launchers, the Python entry and
dispatcher scripts, and the current ``bin/`` executables plus their private
``_*`` support modules. The candidate is DISPOSABLE — it is built under a run
directory or temp, never committed.

Determinism: stable file order, fixed modes, LF newlines, no timestamps. The
emitted ``package-manifest.json`` records a per-file SHA-256; ``--check``
rebuilds to a temporary directory and byte-compares.

CLI (install probes depend on this contract — do not deviate)::

    python plugins/codemap/scripts/build_package.py --out <dir> [--check]

Exit ``0`` on success; ``1`` on a ``--check`` mismatch; ``2`` on usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
NAME = "codemap-py"
VERSION = "0.25.0-rc1"
DESCRIPTION = "Deterministic Python structural index and query for Claude Code and Codex — one shared project index, runtime-isolated logs"
AUTHOR = {"name": "Jirka", "url": "https://github.com/Borda/AI-Rig"}
CLAUDE_SKILLS = "./claude-skills/"
CODEX_SKILLS = "./codex-skills/"
_MODE_EXEC = 0o755
_MODE_DATA = 0o644
_MANIFEST = "package-manifest.json"

# (source-relative path, candidate-relative path, mode) — copied byte-for-byte.
_COPY_PLAN: tuple[tuple[str, str, int], ...] = (
    ("bin/codemap-py", "bin/codemap-py", _MODE_EXEC),
    ("bin/codemap-py.cmd", "bin/codemap-py.cmd", _MODE_EXEC),
    ("bin/scan-index", "bin/scan-index", _MODE_EXEC),
    ("bin/scan-query", "bin/scan-query", _MODE_EXEC),
    ("bin/_exclusions.py", "bin/_exclusions.py", _MODE_DATA),
    ("bin/_schema.py", "bin/_schema.py", _MODE_DATA),
    ("bin/_telemetry.py", "bin/_telemetry.py", _MODE_DATA),
    ("scripts/codemap_py_entry.py", "scripts/codemap_py_entry.py", _MODE_DATA),
    ("scripts/codemap_py_cli.py", "scripts/codemap_py_cli.py", _MODE_DATA),
)

_CLAUDE_ADAPTER = """\
---
name: scan-codebase
description: "Build or refresh the codemap-py structural index for the current Python project."
allowed-tools: Bash
disable-model-invocation: true
---

<objective>
Phase-1 Claude runtime adapter. Builds the structural index through the codemap-py CLI.
</objective>

<workflow>
Run the bundled launcher from the resolved plugin root:

    "${CLAUDE_PLUGIN_ROOT}/bin/codemap-py" index

The launcher selects an eligible CPython (>=3.11,<3.15) and delegates to the current scanner.
Exit codes and JSON output follow the codemap-py CLI contract.
</workflow>
"""

_CODEX_ADAPTER = """\
---
name: scan-codebase
description: "Build or refresh the codemap-py structural index for the current Python project."
---

<objective>
Phase-1 Codex runtime adapter. Builds the structural index through the codemap-py CLI.
</objective>

<workflow>
Resolve PLUGIN_ROOT as the literal parent of this skill's directory, then run:

    <PLUGIN_ROOT>/bin/codemap-py index

On Windows use `<PLUGIN_ROOT>\\bin\\codemap-py.cmd`. The launcher selects an eligible
CPython (>=3.11,<3.15) and delegates to the current scanner.
</workflow>
"""


def _sha256(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact bytes."""
    return hashlib.sha256(payload).hexdigest()


def _encode_json(value: dict[str, Any]) -> bytes:
    """Encode a stable LF-terminated JSON document."""
    return (json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")


def _claude_manifest() -> bytes:
    """Claude manifest bytes — hooks are added by a later packaging stage, not here."""
    return _encode_json(
        {"name": NAME, "version": VERSION, "description": DESCRIPTION, "author": AUTHOR, "skills": CLAUDE_SKILLS}
    )


def _codex_manifest() -> bytes:
    """Codex manifest bytes — no hooks key."""
    return _encode_json(
        {"name": NAME, "version": VERSION, "description": DESCRIPTION, "author": AUTHOR, "skills": CODEX_SKILLS}
    )


def _write_file(path: Path, data: bytes, mode: int) -> None:
    """Write bytes with an explicit deterministic mode, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


def _generated_files() -> tuple[tuple[str, bytes, int], ...]:
    """Return generated candidate files (path, bytes, mode)."""
    return (
        (".claude-plugin/plugin.json", _claude_manifest(), _MODE_DATA),
        (".codex-plugin/plugin.json", _codex_manifest(), _MODE_DATA),
        ("claude-skills/scan-codebase/SKILL.md", _CLAUDE_ADAPTER.encode("utf-8"), _MODE_DATA),
        ("codex-skills/scan-codebase/SKILL.md", _CODEX_ADAPTER.encode("utf-8"), _MODE_DATA),
    )


def _iter_payload(out: Path) -> list[Path]:
    """Return candidate payload files in canonical order (manifest excluded)."""
    discovered: list[Path] = []
    folded: set[str] = set()
    for path in sorted(out.rglob("*")):
        relative = path.relative_to(out).as_posix()
        if relative == _MANIFEST:
            continue
        if path.is_symlink():
            raise ValueError(f"symlink payload forbidden: {relative}")
        if not path.is_file():
            continue
        key = relative.casefold()
        if key in folded:
            raise ValueError(f"case-colliding payload path: {relative}")
        folded.add(key)
        discovered.append(path)
    return discovered


def _file_record(path: Path, out: Path) -> dict[str, str]:
    """Build one stable file identity record."""
    return {
        "path": path.relative_to(out).as_posix(),
        "sha256": _sha256(path.read_bytes()),
        "mode": f"{stat.S_IMODE(path.stat().st_mode):04o}",
    }


def build_candidate(out: Path) -> dict[str, Any]:
    """Build the candidate into ``out`` and return the package manifest.

    The destination is cleared first, so a build is a pure function of the
    tracked sources.
    """
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel_src, rel_dst, mode in _COPY_PLAN:
        _write_file(out / rel_dst, (SOURCE_ROOT / rel_src).read_bytes(), mode)
    for rel_dst, data, mode in _generated_files():
        _write_file(out / rel_dst, data, mode)
    manifest = {
        "schema": 1,
        "name": NAME,
        "version": VERSION,
        "runtimes": {"claude": CLAUDE_SKILLS, "codex": CODEX_SKILLS},
        "files": [_file_record(path, out) for path in _iter_payload(out)],
    }
    _write_file(out / _MANIFEST, _encode_json(manifest), _MODE_DATA)
    return manifest


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file's bytes keyed by candidate-relative posix path."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _compare(built: Path, reference: Path) -> list[str]:
    """Return byte-difference descriptions between two candidate trees."""
    left, right = _tree_bytes(built), _tree_bytes(reference)
    diffs = [f"only in rebuild: {name}" for name in sorted(set(left) - set(right))]
    diffs += [f"only in reference: {name}" for name in sorted(set(right) - set(left))]
    diffs += [f"bytes differ: {name}" for name in sorted(set(left) & set(right)) if left[name] != right[name]]
    return diffs


def _run_check(out: Path) -> int:
    """Rebuild to a temp dir and byte-compare against a reference build."""
    with tempfile.TemporaryDirectory() as tmp:
        rebuild = Path(tmp) / "candidate"
        build_candidate(rebuild)
        if out.exists() and any(out.iterdir()):
            reference = out
        else:
            reference = Path(tmp) / "reference"
            build_candidate(reference)
        diffs = _compare(rebuild, reference)
    if diffs:
        sys.stderr.write("candidate rebuild is not deterministic:\n" + "\n".join(diffs) + "\n")
        return 1
    print("candidate build is deterministic")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the builder CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="candidate output directory")
    parser.add_argument("--check", action="store_true", help="rebuild to temp and byte-compare")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the candidate, or verify determinism with ``--check``."""
    args = _parse_args(argv)
    if args.check:
        return _run_check(args.out)
    manifest = build_candidate(args.out)
    print(f"built {NAME} {VERSION}: {len(manifest['files'])} files -> {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"build-candidate-error: {error}\n")
        raise SystemExit(2) from error
