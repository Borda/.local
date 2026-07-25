#!/usr/bin/env python
"""index_paths.py — canonical project-root resolver and codemap index identity.

Every codemap entrypoint (launchers, skills, both runtimes) resolves the shared
project index through this module so Claude Code, Codex, and direct CLI use on the
same real project root land on one runtime-neutral index. Runtime/session identity
is never part of the resolved path — only the logging subtree is runtime-scoped
(see ``runtime_log``).

``bin/_index_identity.py`` is a compatibility shim that aliases this module in
``sys.modules``, so every public name is reachable unchanged through either
import path.

Resolution rules (plan §4.4 "Shared project index"):

- the canonical root is the git repository root (else the current directory),
  with symlinks/case aliases collapsed so an alias of the same project resolves
  to the same identity;
- the default index is ``<canonical-root>/.cache/codemap/<project>.json`` with a
  sibling ``.index-rw/`` coordination directory;
- ``CODEMAP_INDEX_DIR`` is a product-wide base override (never a runtime override).
  Its target is ``<override>/<root-key>/<project>.json`` where ``<root-key>`` is the
  full lowercase SHA-256 of the normalized canonical-root identity, so equal-basename
  projects get distinct reusable indexes;
- a legacy flat override at ``<override>/<project>.json`` is a read-only compatibility
  candidate only when its stored ``scan_root`` matches the canonical root; a mismatch
  is ignored with an ``index_root_collision`` diagnostic and never blocks the
  root-keyed target;
- ``split_index_roots`` is reported when two environments resolve different index paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_GIT_TIMEOUT_S = 5
INDEX_SUBDIR = Path(".cache", "codemap")
COORDINATION_DIRNAME = ".index-rw"

INDEX_ROOT_COLLISION = "index_root_collision"
SPLIT_INDEX_ROOTS = "split_index_roots"

_UNSET = object()


@dataclass(frozen=True)
class Diagnostic:
    """A bounded, machine-readable resolver diagnostic.

    Attributes:
        code: Stable diagnostic code (e.g. ``index_root_collision``).
        message: Human-readable one-line summary.
        detail: Structured supporting fields; never contains secrets.
    """

    code: str
    message: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IndexIdentity:
    """Resolved codemap index identity for one canonical project root.

    Attributes:
        project: Canonical-root basename.
        root: Canonical (symlink-collapsed) project root.
        root_key: Full lowercase SHA-256 of the normalized root identity.
        index_dir: Directory holding the resolved index and coordination subtree.
        index_path: Resolved ``<project>.json`` index path.
        coordination_dir: Sibling ``.index-rw/`` directory beside the index.
        override: ``True`` when ``CODEMAP_INDEX_DIR`` selected the base.
        legacy_candidate: Read-only legacy flat index path when it matches this
            root, else ``None``.
        diagnostics: Any diagnostics raised while resolving (e.g. collisions).
    """

    project: str
    root: Path
    root_key: str
    index_dir: Path
    index_path: Path
    coordination_dir: Path
    override: bool
    legacy_candidate: Path | None
    diagnostics: tuple[Diagnostic, ...]


def _real(path: Path) -> Path:
    """Return *path* with symlinks and ``..`` collapsed (best-effort)."""
    try:
        return path.resolve()
    except OSError:
        return Path(os.path.abspath(path))


def canonical_root(cwd: Path | str | None = None) -> Path:
    """Return the canonical project root for *cwd*.

    The root is the git repository top-level when *cwd* is inside a repository,
    otherwise *cwd* itself; either way the result is symlink-collapsed so an alias
    of the same project resolves to the same identity.

    Args:
        cwd: Working directory to resolve from (defaults to the process CWD).

    Returns:
        Absolute, symlink-collapsed canonical root path.

    Examples:
        >>> isinstance(canonical_root(), Path)  # doctest: +SKIP
        True
    """
    work = Path(cwd) if cwd is not None else Path.cwd()
    git = shutil.which("git")
    if git:
        try:
            out = subprocess.run(
                [git, "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(work),
                check=True,
                timeout=_GIT_TIMEOUT_S,
            ).stdout.strip()
            if out:
                return _real(Path(out))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            pass
    return _real(work)


def normalize_identity(root: Path | str, *, windows: bool | None = None) -> str:
    """Return the normalized string identity used to key an index for *root*.

    On Windows the identity casefolds and normalizes separators so drive-letter
    form and case differences collapse to one identity; on POSIX the resolved
    path string is already the identity.

    Args:
        root: Canonical root path (should already be symlink-collapsed).
        windows: Force Windows normalization; defaults to the host platform.

    Returns:
        The normalized identity string.

    Examples:
        >>> normalize_identity("/Repo/Proj", windows=False)
        '/Repo/Proj'
        >>> normalize_identity("C:/Repo/Proj", windows=True)
        'c:\\\\repo\\\\proj'
    """
    if windows is None:
        windows = os.name == "nt"
    raw = str(root)
    if windows:
        raw = raw.replace("/", "\\").casefold()
    return raw


def root_key(root: Path | str, *, windows: bool | None = None) -> str:
    """Return the full lowercase SHA-256 of the normalized identity of *root*.

    Args:
        root: Canonical root path.
        windows: Force Windows normalization; defaults to the host platform.

    Returns:
        64-character lowercase hex digest, stable and free of any raw path.

    Examples:
        >>> len(root_key("/repo/proj", windows=False))
        64
        >>> root_key("/a", windows=False) == root_key("/a", windows=False)
        True
    """
    identity = normalize_identity(root, windows=windows)
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _read_scan_root(path: Path) -> str | None:
    """Return the ``scan_root`` field stored in *path*, or ``None`` if unreadable."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    value = data.get("scan_root") if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def _legacy_candidate(path: Path, root: Path, diagnostics: list[Diagnostic]) -> Path | None:
    """Return *path* when it is a valid read-only legacy candidate for *root*.

    A legacy flat override index is reusable only when its stored ``scan_root``
    normalizes to the same identity as *root*; a mismatch appends an
    ``index_root_collision`` diagnostic and is never returned.
    """
    if not path.is_file():
        return None
    stored = _read_scan_root(path)
    if stored is not None and normalize_identity(_real(Path(stored))) == normalize_identity(root):
        return path
    diagnostics.append(
        Diagnostic(
            INDEX_ROOT_COLLISION,
            "legacy flat index does not match the canonical root; ignoring it",
            {"legacy_path": str(path), "stored_scan_root": stored, "canonical_root": str(root)},
        )
    )
    return None


def resolve_index(
    cwd: Path | str | None = None,
    *,
    root: Path | str | None = None,
    index_dir_override: object = _UNSET,
) -> IndexIdentity:
    """Resolve the canonical codemap index identity.

    Args:
        cwd: Working directory used to derive the canonical root (ignored when
            *root* is given).
        root: Explicit canonical root; when omitted it is derived from *cwd*.
        index_dir_override: Base override path. ``_UNSET`` (default) reads
            ``CODEMAP_INDEX_DIR``; pass ``None`` to force the default layout even
            when the environment variable is set.

    Returns:
        An :class:`IndexIdentity` describing the resolved paths and diagnostics.

    Examples:
        >>> ident = resolve_index()  # doctest: +SKIP
        >>> ident.index_path.name.endswith(".json")  # doctest: +SKIP
        True
    """
    base_root = _real(Path(root)) if root is not None else canonical_root(cwd)
    project = base_root.name
    rk = root_key(base_root)
    override_raw = os.environ.get("CODEMAP_INDEX_DIR") if index_dir_override is _UNSET else index_dir_override
    diagnostics: list[Diagnostic] = []

    if override_raw:
        override_base = Path(str(override_raw)).expanduser().resolve()
        index_dir = override_base / rk
        legacy = _legacy_candidate(override_base / f"{project}.json", base_root, diagnostics)
        override = True
    else:
        index_dir = base_root / INDEX_SUBDIR
        legacy = None
        override = False

    index_path = index_dir / f"{project}.json"
    return IndexIdentity(
        project=project,
        root=base_root,
        root_key=rk,
        index_dir=index_dir,
        index_path=index_path,
        coordination_dir=index_dir / COORDINATION_DIRNAME,
        override=override,
        legacy_candidate=legacy,
        diagnostics=tuple(diagnostics),
    )


def diagnose_split_index_roots(path_a: Path, path_b: Path) -> Diagnostic | None:
    """Return a ``split_index_roots`` diagnostic when two paths disagree.

    ``codemap-py integrate check`` uses this to report — never to reconcile —
    when two runtime environments resolve different index paths.

    Args:
        path_a: Index path resolved in the first environment.
        path_b: Index path resolved in the second environment.

    Returns:
        A :class:`Diagnostic` when the paths differ, else ``None``.

    Examples:
        >>> diagnose_split_index_roots(Path("/a/i.json"), Path("/a/i.json")) is None
        True
        >>> diagnose_split_index_roots(Path("/a/i.json"), Path("/b/i.json")).code
        'split_index_roots'
    """
    if path_a == path_b:
        return None
    return Diagnostic(
        SPLIT_INDEX_ROOTS,
        "runtime environments resolve different index paths; not reconciling",
        {"path_a": str(path_a), "path_b": str(path_b)},
    )
