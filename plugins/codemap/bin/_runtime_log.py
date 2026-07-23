#!/usr/bin/env python
"""_runtime_log.py — runtime-scoped codemap CLI logging (claude / codex / direct).

The only runtime-specific persistent project state is the logging subtree. This
module resolves a per-runtime log directory under the canonical project root so
Claude Code, Codex, and direct CLI never append to the same file, and a missing
session id never collapses concurrent writers into one unqualified ``cli.jsonl``.

Contract (plan §4.4 "Logging"):

- runtime identity is an allowlist ``{claude, codex, direct}``; an invalid value
  falls back to ``direct`` with a bounded diagnostic and never becomes a path
  component;
- the log root is ``<canonical-root>/.cache/codemap/logs`` regardless of CWD;
- ``CODEMAP_LOG_DIR`` overrides the log root but the ``<runtime>/`` component is
  still appended;
- log correlation uses the runtime's opaque session id when available, otherwise a
  process/invocation id;
- logging failure never blocks index build, validation, reuse, or query.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from _index_identity import Diagnostic, canonical_root
except ImportError:  # pragma: no cover - path bootstrap when bin/ is not yet on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _index_identity import Diagnostic, canonical_root

RUNTIME_ALLOWLIST = ("claude", "codex", "direct")
DEFAULT_RUNTIME = "direct"
INVALID_RUNTIME = "invalid_runtime_identity"
LOG_SUBDIR = Path(".cache", "codemap", "logs")

_SAFE = re.compile(r"[^A-Za-z0-9_-]")
_INVOCATION: tuple[int, str] | None = None


def resolve_runtime(raw: object) -> tuple[str, Diagnostic | None]:
    """Return an allowlisted runtime identity and any fallback diagnostic.

    Args:
        raw: Requested runtime identity (any value; typically a string or ``None``).

    Returns:
        ``(runtime, diagnostic)`` where *runtime* is always in
        :data:`RUNTIME_ALLOWLIST` and *diagnostic* is ``None`` unless *raw* was
        invalid and fell back to ``direct``.

    Examples:
        >>> resolve_runtime("codex")
        ('codex', None)
        >>> runtime, diag = resolve_runtime("bogus")
        >>> runtime, diag.code
        ('direct', 'invalid_runtime_identity')
    """
    if isinstance(raw, str) and raw in RUNTIME_ALLOWLIST:
        return raw, None
    return DEFAULT_RUNTIME, Diagnostic(
        INVALID_RUNTIME,
        f"unknown runtime identity {raw!r}; using {DEFAULT_RUNTIME!r}",
        {"requested": str(raw)},
    )


def invocation_id() -> str:
    """Return a stable per-process invocation id (``<pid>-<time_ns>``).

    Cached per process and regenerated after a fork so parent and child never
    share a correlation id.

    Returns:
        The process invocation id string.

    Examples:
        >>> invocation_id() == invocation_id()
        True
    """
    global _INVOCATION  # noqa: PLW0603 - per-process cache, reset only across forks
    pid = os.getpid()
    if _INVOCATION is None or _INVOCATION[0] != pid:
        _INVOCATION = (pid, f"{pid}-{time.time_ns()}")
    return _INVOCATION[1]


def log_dir_for(runtime: object, *, root: Path | None = None, override: str | None = None) -> Path:
    """Return the ``<log-root>/<runtime>/`` directory for *runtime*.

    Args:
        runtime: Requested runtime identity; normalized through
            :func:`resolve_runtime` so an invalid value maps to ``direct``.
        root: Canonical project root; resolved from the CWD when omitted.
        override: Explicit log-root override; defaults to ``CODEMAP_LOG_DIR``.

    Returns:
        The per-runtime log directory path (the ``<runtime>/`` component is always
        appended, including under an override).

    Examples:
        >>> log_dir_for("claude", root=Path("/proj")).as_posix()
        '/proj/.cache/codemap/logs/claude'
        >>> log_dir_for("codex", root=Path("/proj"), override="/shared/logs").as_posix()
        '/shared/logs/codex'
    """
    resolved, _ = resolve_runtime(runtime)
    override = override if override is not None else os.environ.get("CODEMAP_LOG_DIR")
    base = Path(override).expanduser() if override else (root or canonical_root()) / LOG_SUBDIR
    return base / resolved


def log_path(
    runtime: object,
    session: str | None = None,
    *,
    root: Path | None = None,
    override: str | None = None,
) -> Path:
    """Return the ``cli_<session-or-invocation>.jsonl`` path for *runtime*.

    Args:
        runtime: Requested runtime identity (normalized to the allowlist).
        session: Opaque session id when the runtime exposes one; a missing
            session falls back to a unique per-process invocation id so
            concurrent writers never collapse into one unqualified file.
        root: Canonical project root; resolved from the CWD when omitted.
        override: Explicit log-root override; defaults to ``CODEMAP_LOG_DIR``.

    Returns:
        The resolved per-session log file path.

    Examples:
        >>> log_path("claude", "sess/1", root=Path("/proj")).name
        'cli_sess-1.jsonl'
    """
    token = _SAFE.sub("-", session) if session else invocation_id()
    return log_dir_for(runtime, root=root, override=override) / f"cli_{token}.jsonl"


def write_log(
    runtime: object,
    record: dict,
    *,
    session: str | None = None,
    root: Path | None = None,
    override: str | None = None,
) -> Diagnostic | None:
    """Append one runtime-scoped log record; best-effort, never raises.

    Honors ``CODEMAP_LOGGING=false``. The stored record is stamped with a UTC
    timestamp and the resolved runtime; an invalid runtime is logged under
    ``direct`` and the returned diagnostic reports the fallback.

    Args:
        runtime: Requested runtime identity (normalized to the allowlist).
        record: JSON-serializable fields to merge into the stored record.
        session: Opaque session id, or ``None`` to use the invocation id.
        root: Canonical project root; resolved from the CWD when omitted.
        override: Explicit log-root override; defaults to ``CODEMAP_LOG_DIR``.

    Returns:
        A :class:`Diagnostic` when *runtime* was invalid, else ``None``.

    Examples:
        >>> write_log("claude", {"event": "cache_hit"}, root=Path("/tmp")) is None  # doctest: +SKIP
        True
    """
    resolved, diag = resolve_runtime(runtime)
    if os.environ.get("CODEMAP_LOGGING", "true").lower() == "false":
        return diag
    try:
        path = log_path(resolved, session, root=root, override=override)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runtime": resolved}
        if isinstance(record, dict):
            payload.update(record)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, separators=(",", ":")) + "\n")
    except Exception:  # noqa: BLE001 - logging failure must never block index work
        pass
    return diag
