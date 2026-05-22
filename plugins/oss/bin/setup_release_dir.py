#!/usr/bin/env python
"""setup_release_dir.py — create release dir, symlink changelog, back up artifacts.

Creates RELEASE_DIR (including parents), force-symlinks CHANGELOG_FILE
into it as ``CHANGELOG.md``, then backs up any pre-existing release
artifact files to ``.bak`` before overwrite. Extracted from oss:release
prepare Phase 3 setup block (P2).

Re-running prepare for the same version is legitimate (post-audit-fix
retry); silently overwriting hand-edited notes is destructive, hence
the backups. CHANGELOG.md is excluded from the backup loop — it is a
symlink; re-linking on re-run is safe and intentional.

Usage:
    setup_release_dir.py RELEASE_DIR CHANGELOG_FILE
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

_ARTIFACTS: tuple[str, ...] = ("HIGHLIGHTS.md", "DRAFT.md", "SUMMARY.md", "MIGRATION.md", "demo.py")


def _allowed_abs_roots() -> tuple[Path, ...]:
    """Return the allowlist of absolute-path roots, computed at call time.

    Computed lazily rather than at import time so test runs that ``chdir`` after
    import still see the up-to-date project root.  ``tempfile.gettempdir()`` is
    included to support pytest's ``tmp_path`` fixture and other sandboxed runs.
    """
    return (
        Path.cwd().resolve(),
        (Path(os.path.expanduser("~")) / ".claude").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    )


def _is_within(target: Path, root: Path) -> bool:
    """Return ``True`` when ``target`` resolves under ``root`` (post-resolution).

    Args:
        target: Resolved path to test.
        root: Resolved allowed-root path.

    Returns:
        ``True`` when ``target`` is identical to or nested under ``root``.

    Examples:
        >>> _is_within(Path("/tmp/x/y"), Path("/tmp"))
        True
        >>> _is_within(Path("/etc/passwd"), Path("/tmp"))
        False
    """
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_path_arg(raw: str, label: str) -> Path:
    """Resolve and validate a path argument, rejecting unsafe absolute paths.

    Relative paths are accepted unconditionally (resolved against the caller's
    cwd).  Absolute paths must resolve under :func:`_allowed_abs_roots`.  Any
    ``..`` traversal token in the raw input is rejected.

    Args:
        raw: Path string from argv.
        label: Argument label used in error messages.

    Returns:
        ``Path`` object suitable for use by the caller.

    Raises:
        ValueError: When the path is rejected for any of the above reasons.
    """
    if not raw:
        raise ValueError(f"{label} must not be empty")
    if ".." in Path(raw).parts:
        raise ValueError(f"{label} must not contain '..': {raw!r}")
    p = Path(raw)
    if not p.is_absolute():
        return p
    resolved = p.expanduser().resolve()
    for root in _allowed_abs_roots():
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return p
    raise ValueError(f"{label} resolves outside project root, ~/.claude, and temp dir: {raw!r} → {resolved.as_posix()}")


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``setup_release_dir.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 on missing args; 0 on success.

    Examples:
        No doctest — filesystem I/O; covered by pytest with ``tmp_path``.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 1:
        print("setup_release_dir: release_dir required", file=sys.stderr)
        return 1
    if len(args) < 2:
        print("setup_release_dir: changelog_file required", file=sys.stderr)
        return 1

    try:
        release_dir = _validate_path_arg(args[0], "release_dir")
        changelog_file = _validate_path_arg(args[1], "changelog_file")
    except ValueError as exc:
        print(f"setup_release_dir: {exc}", file=sys.stderr)
        return 1

    release_dir.mkdir(parents=True, exist_ok=True)

    link_path = release_dir / "CHANGELOG.md"
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    # Re-validate the *resolved* symlink target — _validate_path_arg validated
    # the raw input, but the post-resolve path could escape the allowed roots
    # via an existing symlink in the changelog_file path. Refuse to create
    # the symlink in that case rather than embedding a path-escape primitive
    # in the release directory.
    resolved_target = changelog_file.resolve()
    if not any(_is_within(resolved_target, root) for root in _allowed_abs_roots()):
        print(
            f"setup_release_dir: resolved changelog target outside allowed roots: {resolved_target.as_posix()}",
            file=sys.stderr,
        )
        return 1
    link_path.symlink_to(resolved_target)

    for name in _ARTIFACTS:
        target = release_dir / name
        if target.is_file():
            shutil.copy2(target, release_dir / f"{name}.bak")
            print(f"⚠ {target} exists — backed up to {name}.bak before overwrite")

    return 0


if __name__ == "__main__":
    sys.exit(main())
