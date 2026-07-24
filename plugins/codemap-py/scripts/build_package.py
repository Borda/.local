#!/usr/bin/env python3
"""Assemble the deterministic codemap-py distribution package.

Packages the REAL tracked plugin tree (not a synthetic mini-candidate): both
runtime manifest directories, every ``bin/`` executable and support module, the
``scripts/`` entrypoints, the Claude skill roster, the hook wiring, and the
top-level product documents. Identity (name, version) is read from
``.claude-plugin/plugin.json`` at build time — never hardcoded — so a single
manifest edit is the sole source of truth.

Determinism: stable file order, LF-terminated generated manifest, fixed on-disk
modes, no timestamps. The per-file ``exec`` flag is a platform-neutral boolean
taken from git's tracked mode (``100755``), never from the build host's
``st_mode`` — a Windows and a POSIX build of the same commit therefore emit a
byte-identical ``package-manifest.json`` (review F10 closure). ``--check``
rebuilds to a temporary directory and byte-compares.

CLI (install probes depend on this contract — do not deviate)::

    python plugins/codemap-py/scripts/build_package.py --out <dir> [--check]

Exit ``0`` on success; ``1`` on a ``--check`` mismatch; ``2`` on usage or a
payload-closure error (missing required document, symlink, case collision).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = "package-manifest.json"
_SCHEMA = 2
_MODE_EXEC = 0o755
_MODE_DATA = 0o644

# Directory subtrees copied whole (minus the exclusions below).
_INCLUDE_DIRS: tuple[str, ...] = (
    ".claude-plugin",
    ".codex-plugin",
    "bin",
    "scripts",
    "claude-skills",
    "hooks",
)
# Top-level product documents — all required; a missing one is a closure error.
_REQUIRED_DOCS: tuple[str, ...] = ("README.md", "LICENSE", "NOTICE", "CHANGELOG.md")
# Path components that are never shipped (runtime caches, evidence, state).
_EXCLUDE_COMPONENTS: frozenset[str] = frozenset(
    {"__pycache__", ".cache", ".reports", ".temp", ".pytest_cache", ".claude", "tests"}
)
_EXCLUDE_NAMES: frozenset[str] = frozenset({".DS_Store"})
# Human-readable exclusion policy recorded in the manifest.
_EXCLUSIONS: tuple[str, ...] = (
    "__pycache__/",
    ".cache/",
    ".reports/",
    ".temp/",
    ".pytest_cache/",
    ".claude/",
    "tests/",
    "*.pyc",
    ".coverage*",
    ".DS_Store",
)


def _sha256(payload: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact bytes.

    Examples:
        >>> _sha256(b"")[:8]
        'e3b0c442'
    """
    return hashlib.sha256(payload).hexdigest()


def _encode_json(value: dict[str, Any]) -> bytes:
    """Encode a stable, LF-terminated, key-sorted JSON document.

    Examples:
        >>> _encode_json({"b": 1, "a": 2})
        b'{\\n  "a": 2,\\n  "b": 1\\n}\\n'
    """
    return (json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n").encode("utf-8")


def _is_excluded(relative: str) -> bool:
    """Return whether a source-relative posix path is excluded from the payload.

    Examples:
        >>> _is_excluded("bin/__pycache__/x.pyc")
        True
        >>> _is_excluded("bin/scan-index")
        False
    """
    parts = relative.split("/")
    if any(part in _EXCLUDE_COMPONENTS for part in parts):
        return True
    name = parts[-1]
    return name in _EXCLUDE_NAMES or name.endswith(".pyc") or name.startswith(".coverage")


def _load_identity(source_root: Path) -> tuple[str, str]:
    """Return ``(name, version)`` read from the Claude manifest (single source)."""
    manifest = json.loads((source_root / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return str(manifest["name"]), str(manifest["version"])


def _skill_roster(source_root: Path) -> list[str]:
    """Return the sorted Claude skill names (directories holding a ``SKILL.md``)."""
    skills_dir = source_root / "claude-skills"
    if not skills_dir.is_dir():
        return []
    return sorted(child.name for child in skills_dir.iterdir() if (child / "SKILL.md").is_file())


def _git_exec_modes(source_root: Path) -> dict[str, bool]:
    """Return ``{relative_posix_path: is_executable}`` from git's tracked modes.

    The executable bit is read from git (``100755``) rather than the working
    tree's ``st_mode`` so the flag is identical on every OS. This is a hard
    dependency: a deterministic, faithful candidate cannot be built without git's
    tracked modes, so a missing git or a non-git ``SOURCE_ROOT`` raises rather than
    silently marking every payload file non-executable (a determinism hole that
    would strip the launcher's executable bit).

    Raises:
        ValueError: when git is unavailable or ``source_root`` is not a git working
            tree, so the executable-mode metadata cannot be derived.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(source_root), "ls-files", "--stage", "--", "."],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise ValueError("git not found; the deterministic build requires git to derive tracked modes") from error
    except subprocess.CalledProcessError as error:
        raise ValueError(
            f"cannot derive tracked executable modes: {source_root} is not a git working tree "
            f"({error.stderr.strip() or error})"
        ) from error
    except subprocess.SubprocessError as error:
        raise ValueError(f"cannot derive tracked executable modes: git ls-files failed: {error}") from error
    modes: dict[str, bool] = {}
    for line in completed.stdout.splitlines():
        meta, _, relative = line.partition("\t")
        if relative:
            modes[relative] = meta.split(" ", 1)[0] == "100755"
    return modes


def _iter_source_payload(source_root: Path) -> list[tuple[Path, str]]:
    """Return ``(absolute_source, relative_posix)`` payload pairs in canonical order.

    Raises:
        ValueError: on a symlink in the payload, a case-folding collision, or a
            missing required document.
    """
    pairs: list[tuple[Path, str]] = []
    folded: set[str] = set()
    for name in _REQUIRED_DOCS:
        doc = source_root / name
        if not doc.is_file():
            raise ValueError(f"missing required document: {name}")
        _admit(doc, name, folded, pairs)
    for dir_name in _INCLUDE_DIRS:
        root = source_root / dir_name
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(source_root).as_posix()
            if _is_excluded(relative):
                continue
            if path.is_symlink():
                raise ValueError(f"symlink payload forbidden: {relative}")
            if path.is_file():
                _admit(path, relative, folded, pairs)
    return pairs


def _admit(path: Path, relative: str, folded: set[str], pairs: list[tuple[Path, str]]) -> None:
    """Record one payload pair, rejecting a case-folding collision."""
    key = relative.casefold()
    if key in folded:
        raise ValueError(f"case-colliding payload path: {relative}")
    folded.add(key)
    pairs.append((path, relative))


def _write_file(path: Path, data: bytes, executable: bool) -> None:
    """Write bytes with a fixed deterministic mode, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(_MODE_EXEC if executable else _MODE_DATA)


def build_package(source_root: Path, out: Path) -> dict[str, Any]:
    """Build the package into ``out`` and return its manifest.

    The destination is cleared first, so a build is a pure function of the
    tracked sources plus git's recorded modes.

    Args:
        source_root: Plugin root holding the tracked tree.
        out: Destination directory (created fresh).

    Returns:
        The ``package-manifest.json`` document as a dict.
    """
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    name, version = _load_identity(source_root)
    exec_modes = _git_exec_modes(source_root)
    records: list[dict[str, Any]] = []
    for src, relative in _iter_source_payload(source_root):
        data = src.read_bytes()
        executable = exec_modes.get(relative, False)
        _write_file(out / relative, data, executable)
        records.append({"path": relative, "sha256": _sha256(data), "exec": executable})
    manifest = {
        "schema": _SCHEMA,
        "name": name,
        "version": version,
        "skills": {"claude": _skill_roster(source_root), "codex": []},
        "files": records,
        "exclusions": list(_EXCLUSIONS),
    }
    _write_file(out / _MANIFEST, _encode_json(manifest), executable=False)
    return manifest


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Return every file's bytes keyed by package-relative posix path."""
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _compare(built: Path, reference: Path) -> list[str]:
    """Return byte-difference descriptions between two package trees."""
    left, right = _tree_bytes(built), _tree_bytes(reference)
    diffs = [f"only in rebuild: {name}" for name in sorted(set(left) - set(right))]
    diffs += [f"only in reference: {name}" for name in sorted(set(right) - set(left))]
    diffs += [f"bytes differ: {name}" for name in sorted(set(left) & set(right)) if left[name] != right[name]]
    return diffs


def _exec_mode_mismatches(out: Path, manifest: dict[str, Any]) -> list[str]:
    """On POSIX, return files whose on-disk executable bit disagrees with the manifest.

    The manifest ``exec`` flag is the platform-neutral source of truth; this
    verifies the build actually applied it. On non-POSIX hosts the executable bit
    is unreliable, so no mismatch is reported.
    """
    if os.name != "posix":
        return []
    mismatches: list[str] = []
    for record in manifest["files"]:
        disk = out / record["path"]
        if disk.is_file() and bool(disk.stat().st_mode & 0o111) != bool(record["exec"]):
            mismatches.append(record["path"])
    return mismatches


def _run_check(source_root: Path, out: Path) -> int:
    """Rebuild to a temp dir, byte-compare, and verify on-disk executable modes."""
    with tempfile.TemporaryDirectory() as tmp:
        rebuild = Path(tmp) / "rebuild"
        manifest = build_package(source_root, rebuild)
        if out.exists() and any(out.iterdir()):
            reference = out
        else:
            reference = Path(tmp) / "reference"
            build_package(source_root, reference)
        diffs = _compare(rebuild, reference)
        # Verify executable modes on BOTH the temp rebuild and the --out reference: a
        # byte-identical file whose mode was tampered in --out is invisible to _compare.
        mode_mismatches = sorted(
            set(_exec_mode_mismatches(rebuild, manifest)) | set(_exec_mode_mismatches(reference, manifest))
        )
    if diffs:
        sys.stderr.write("package rebuild is not deterministic:\n" + "\n".join(diffs) + "\n")
        return 1
    if mode_mismatches:
        sys.stderr.write("on-disk executable modes disagree with manifest:\n" + "\n".join(mode_mismatches) + "\n")
        return 1
    print("package build is deterministic")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the builder CLI arguments."""
    parser = argparse.ArgumentParser(description="Build the deterministic codemap-py package.")
    parser.add_argument("--out", required=True, type=Path, help="package output directory")
    parser.add_argument("--check", action="store_true", help="rebuild to temp and byte-compare")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Build the package, or verify determinism with ``--check``."""
    args = _parse_args(argv)
    if args.check:
        return _run_check(SOURCE_ROOT, args.out)
    manifest = build_package(SOURCE_ROOT, args.out)
    print(f"built {manifest['name']} {manifest['version']}: {len(manifest['files'])} files -> {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        sys.stderr.write(f"build-package-error: {error}\n")
        raise SystemExit(2) from error
