#!/usr/bin/env python3
"""Emit Claude index context and trigger a lock-guarded background refresh."""

from __future__ import annotations

import json
import os
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


def now_ms() -> int:
    """Return the wall-clock millisecond timestamp used in hook sentinel files."""
    return int(time.time() * 1000)


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
    flag = Path(tempfile.gettempdir()) / f"codemap-noindex-{project}"
    timestamp = read_timestamp(flag)
    if timestamp is not None and now_ms() - timestamp < NOINDEX_TTL_MS:
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


def acquire_refresh_lock(path: Path) -> int | None:
    """Atomically acquire a fresh or stale-taken-over refresh lock, else return ``None``."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, flags)
    except FileExistsError:
        timestamp = read_timestamp(path)
        if timestamp is not None and now_ms() - timestamp < LOCK_TTL_MS:
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


def main() -> int:
    """Emit one fail-open preamble and optionally start a background incremental refresh."""
    try:
        try:
            payload = json.load(sys.stdin)
        except (ValueError, TypeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        cwd = Path.cwd()
        root = Path(git_output(["rev-parse", "--show-toplevel"], cwd) or cwd)
        project = root.name
        write_session_marker(root, str(payload.get("session_id", "")))
        index_dir = Path(os.environ.get("CODEMAP_INDEX_DIR", root / ".cache" / "codemap"))
        index_path = index_dir / f"{project}.json"
        try:
            index_stat = index_path.stat()
        except OSError:
            handle_missing_index(root, project)
            return 0
        if not index_path.is_file():
            handle_missing_index(root, project)
            return 0
        header = index_path.read_bytes()[:HEADER_PEEK_BYTES].decode("utf-8", errors="replace")

        def field(name: str) -> str:
            import re

            match = re.search(rf'"{re.escape(name)}"\s*:\s*"([^"]*)"', header)
            return match.group(1) if match else ""

        git_sha = field("git_sha")
        scanned_at = field("scanned_at")[:10]
        raw_root = field("scan_root")
        scan_root = Path(raw_root).resolve() if raw_root and Path(raw_root).is_absolute() else cwd
        head = git_output(["rev-parse", "HEAD"], cwd)
        dirty = git_output(["status", "--porcelain", "--", "*.py"], cwd) if head and git_sha == head else ""
        currency = "unknown" if not head or not git_sha else "stale" if head != git_sha or dirty else "current"
        refresh_note = ""
        if currency == "stale":
            lock = Path(tempfile.gettempdir()) / f"codemap-refresh-{project}"
            descriptor = acquire_refresh_lock(lock)
            if descriptor is None:
                refresh_note = " - refresh in progress"
            else:
                try:
                    os.write(descriptor, str(now_ms()).encode("ascii"))
                finally:
                    os.close(descriptor)
                scan_bin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).parents[1])) / "bin" / "scan-index"
                if scan_bin.is_file() and spawn_refresh(scan_bin, scan_root, cwd):
                    refresh_note = " - refresh started"
                else:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
        session_flag = Path(tempfile.gettempdir()) / f"codemap-preamble-{project}"
        if currency == "current":
            timestamp = read_timestamp(session_flag)
            if timestamp is not None and now_ms() - timestamp < SESSION_TTL_MS:
                return 0
        write_timestamp(session_flag)
        if currency == "stale":
            stale_flag = Path(tempfile.gettempdir()) / f"codemap-stale-{project}"
            timestamp = read_timestamp(stale_flag)
            if timestamp is not None and now_ms() - timestamp < SESSION_TTL_MS:
                print(f"[codemap] index stale{refresh_note or ' - refresh pending'}")
                return 0
            write_timestamp(stale_flag)
        module_count: int | str = "?"
        if index_stat.st_size <= MAX_PARSE_BYTES:
            try:
                module_count = len(json.loads(index_path.read_text(encoding="utf-8")).get("file_shas", {}))
            except (OSError, ValueError, AttributeError):
                pass
        relative_index = os.path.relpath(index_path, cwd)
        sha_label = f" (git: {git_sha[:7]})" if currency == "current" else ""
        print(
            f"[codemap] {relative_index} - {module_count} modules - {currency}{sha_label}{refresh_note} - scanned: {scanned_at}\n"
            "Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol."
        )
    except (OSError, TypeError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
