#!/usr/bin/env python3
"""Emit Claude index context and trigger a lock-guarded background refresh."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MAX_PARSE_BYTES = 10 * 1024 * 1024
LOCK_TTL_MS = 10 * 60 * 1000
HEADER_PEEK_BYTES = 8 * 1024
NOINDEX_TTL_MS = 30 * 60 * 1000
SESSION_TTL_MS = 30 * 60 * 1000

#: Identity fields read out of the index header, compiled once at import. They used to be
#: matched by a pattern built — and an ``import re`` executed — inside a nested closure,
#: once per field, on every prompt.
_HEADER_FIELD_RES = {name: re.compile(rf'"{name}"\s*:\s*"([^"]*)"') for name in ("git_sha", "scanned_at", "scan_root")}


def now_ms() -> int:
    """Return the wall-clock millisecond timestamp used in hook sentinel files."""
    return int(time.time() * 1000)


def tmp_dir() -> Path:
    """Return the temp directory this hook's sentinel files live in."""
    return Path(os.environ.get("TMPDIR") or tempfile.gettempdir())


def read_timestamp(path: Path) -> int | None:
    """Return a sentinel timestamp, treating missing or corrupt content as absent."""
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_timestamp(path: Path) -> None:
    """Best-effort write of the current timestamp to a hook sentinel file."""
    try:
        path.write_text(str(now_ms()), encoding="utf-8")
    except OSError:
        pass


def within_ttl(flag: Path, ttl_ms: int = SESSION_TTL_MS) -> bool:
    """Return whether *flag* was written less than *ttl_ms* ago."""
    timestamp = read_timestamp(flag)
    return timestamp is not None and now_ms() - timestamp < ttl_ms


def git_output(args: list[str], cwd: Path) -> str:
    """Return a bounded git command result, or an empty string when unavailable."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=3,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def is_python_project(root: Path) -> bool:
    """Return whether bounded package or packaging markers identify a Python project."""
    try:
        if (root / "__init__.py").is_file() or any(
            (child / "__init__.py").is_file()
            for child in root.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        ):
            return True
        src = root / "src"
        if src.is_dir() and any(
            (child / "__init__.py").is_file()
            for child in src.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        ):
            return True
    except OSError:
        return False
    return any((root / marker).is_file() for marker in ("pyproject.toml", "setup.py"))


def handle_missing_index(root: Path, project: str) -> None:
    """Emit the once-per-session Python-project bootstrap directive when needed."""
    if not is_python_project(root):
        return
    flag = tmp_dir() / f"codemap-noindex-{project}"
    if within_ttl(flag, NOINDEX_TTL_MS):
        return
    write_timestamp(flag)
    print(
        f'[codemap] No structural index for "{project}" (.cache/codemap/{project}.json missing) - blast-radius / coupling queries unavailable.\n'
        "ACTION (ask once): call AskUserQuestion - ask the user whether to build the codemap index now.\n"
        "  - yes -> run scan-index (${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/scan-index) in the FOREGROUND and WAIT until it finishes, then continue using scan-query.\n"
        "  - no -> proceed without codemap; do not raise again this session."
    )


def write_session_marker(root: Path, session_id: str) -> None:
    """Write the live Claude session marker before any possible early return."""
    try:
        marker = root / ".cache" / "codemap" / "current-session"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"session_id": session_id, "ts": now_ms()}) + "\n", encoding="utf-8")
    except OSError:
        pass


def regular_file_stat(path: Path) -> os.stat_result | None:
    """Return *path*'s stat when it is a regular file, or ``None`` when it is not usable.

    Folds what used to be a ``stat()`` inside ``try`` followed by a separate ``is_file()``
    branch — a second syscall that could only ever fire for a directory or device node
    sitting where the index belongs. Both conditions now mean the same thing to the caller:
    there is no index to read.
    """
    try:
        info = path.stat()
    except OSError:
        return None
    return info if stat.S_ISREG(info.st_mode) else None


def header_fields(index_path: Path) -> dict[str, str]:
    """Return the index identity fields from a bounded prefix read.

    Deliberately *not* a ``json.loads`` of the whole file: this runs on every prompt, while
    the module count below is computed only on the turns that actually print. The cap that
    would have to guard a full decode is ``MAX_PARSE_BYTES`` (10 MB), and real indexes
    exceed it — the index of this repository is 131 MB — so a parse-or-nothing header would
    report every large project as ``unknown`` currency and never trigger a refresh.

    Args:
        index_path: Path to the codemap index JSON.

    Returns:
        Each known header field mapped to its value, or to ``""`` when absent from the
        prefix or unreadable.
    """
    try:
        header = index_path.read_bytes()[:HEADER_PEEK_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return dict.fromkeys(_HEADER_FIELD_RES, "")
    fields = {}
    for name, pattern in _HEADER_FIELD_RES.items():
        match = pattern.search(header)
        fields[name] = match.group(1) if match else ""
    return fields


def module_count(index_path: Path, size: int) -> int | str:
    """Return the indexed-module count, or ``"?"`` when the index is too large to parse."""
    if size > MAX_PARSE_BYTES:
        return "?"
    try:
        shas = json.loads(index_path.read_text(encoding="utf-8")).get("file_shas", {})
    except (OSError, ValueError, AttributeError):
        return "?"
    return len(shas) if isinstance(shas, dict) else "?"


def resolve_currency(head: str, git_sha: str, dirty: str) -> str:
    """Return ``current``/``stale``/``unknown`` for the index against the working tree."""
    if not head or not git_sha:
        return "unknown"
    return "stale" if head != git_sha or dirty else "current"


def acquire_refresh_lock(path: Path) -> int | None:
    """Atomically acquire a fresh or stale-taken-over refresh lock, else return ``None``."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, flags)
    except FileExistsError:
        if within_ttl(path, LOCK_TTL_MS):
            return None
        try:
            path.unlink()
            return os.open(path, flags)
        except OSError:
            return None
    except OSError:
        return None


def spawn_refresh(scan_bin: Path, scan_root: Path, cwd: Path) -> bool:
    """Spawn a detached incremental scan with platform-specific process isolation."""
    # TODO(C-H3): this detached scan takes no rwgate write lease, so it can run concurrently
    # with a skill-invoked scan of the same index (unbounded parallel AST walks,
    # last-writer-wins). It cannot take one from here: `rwgate.write_index` scopes the lease
    # to a callback in *this* process, and this hook must return immediately on the prompt
    # path rather than block for the scan's 300s budget. The lease therefore belongs inside
    # `bin/scan-index` (the child), which covers this call site transitively.
    scan_args = ["--incremental", "--root", str(scan_root), "--timeout", "300"]
    kwargs: dict[str, object] = {
        "cwd": cwd,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        command = [os.environ.get("CODEMAP_PYTHON", sys.executable), str(scan_bin), *scan_args]
    else:
        kwargs["start_new_session"] = True
        command = [str(scan_bin), *scan_args]
    try:
        subprocess.Popen(command, **kwargs)
    except OSError:
        return False
    return True


def start_refresh(project: str, scan_root: Path, cwd: Path) -> str:
    """Take the refresh lock and spawn one background scan; return the preamble's note."""
    lock = tmp_dir() / f"codemap-refresh-{project}"
    descriptor = acquire_refresh_lock(lock)
    if descriptor is None:
        return " - refresh in progress"
    try:
        os.write(descriptor, str(now_ms()).encode("ascii"))
    finally:
        os.close(descriptor)
    scan_bin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parents[1])) / "bin" / "scan-index"
    if scan_bin.is_file() and spawn_refresh(scan_bin, scan_root, cwd):
        return " - refresh started"
    try:
        lock.unlink()
    except OSError:
        pass
    return ""


def collapse_stale_notice(project: str, refresh_note: str) -> bool:
    """Print the one-line stale notice when the full one already fired this session."""
    flag = tmp_dir() / f"codemap-stale-{project}"
    if within_ttl(flag):
        print(f"[codemap] index stale{refresh_note or ' - refresh pending'}")
        return True
    write_timestamp(flag)
    return False


def stdin_payload() -> dict:
    """Return the hook event as a dict, treating any unusable stdin as an empty event."""
    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    """Emit one fail-open preamble and optionally start a background incremental refresh."""
    try:
        cwd = Path.cwd()
        root = Path(git_output(["rev-parse", "--show-toplevel"], cwd) or cwd)
        project = root.name
        write_session_marker(root, str(stdin_payload().get("session_id", "")))
        index_dir = Path(os.environ.get("CODEMAP_INDEX_DIR", root / ".cache" / "codemap"))
        index_path = index_dir / f"{project}.json"
        index_stat = regular_file_stat(index_path)
        if index_stat is None:
            handle_missing_index(root, project)
            return 0
        fields = header_fields(index_path)
        git_sha = fields["git_sha"]
        raw_root = fields["scan_root"]
        scan_root = Path(raw_root).resolve() if raw_root and Path(raw_root).is_absolute() else cwd
        head = git_output(["rev-parse", "HEAD"], cwd)
        dirty = git_output(["status", "--porcelain", "--", "*.py"], cwd) if head and git_sha == head else ""
        currency = resolve_currency(head, git_sha, dirty)
        refresh_note = start_refresh(project, scan_root, cwd) if currency == "stale" else ""
        session_flag = tmp_dir() / f"codemap-preamble-{project}"
        if currency == "current" and within_ttl(session_flag):
            return 0
        write_timestamp(session_flag)
        if currency == "stale" and collapse_stale_notice(project, refresh_note):
            return 0
        sha_label = f" (git: {git_sha[:7]})" if currency == "current" else ""
        print(
            f"[codemap] {os.path.relpath(index_path, cwd)} - {module_count(index_path, index_stat.st_size)} modules"
            f" - {currency}{sha_label}{refresh_note} - scanned: {fields['scanned_at'][:10]}\n"
            "Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol."
        )
    except (OSError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
