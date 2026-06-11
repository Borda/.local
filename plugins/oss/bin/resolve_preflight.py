#!/usr/bin/env python
"""resolve_preflight.py — preflight checks for /oss:resolve Step 1.

Verifies tool availability (codex optional, gh required), authentication,
and remote state. Pulls latest if remote is ahead. Caches positive
results under ``.claude/state/preflight/`` with a 4-hour TTL so repeat
invocations short-circuit.

Output:
    files — writes CODEX_AVAILABLE and GH_OK to ${TMPDIR:-/tmp}/resolve-preflight-<KEY>
    stderr — human-readable status (echoed to terminal)

Exit:
    0 — all required checks passed (codex absence is non-fatal)
    1 — required check failed (gh missing, gh unauthenticated, git pull
        conflict, or other hard error)

Caller pattern:
    python resolve_preflight.py  # timeout: 15000
    CODEX_AVAILABLE=$(cat "${TMPDIR:-/tmp}/resolve-preflight-CODEX_AVAILABLE" 2>/dev/null || echo "false")
    GH_OK=$(cat "${TMPDIR:-/tmp}/resolve-preflight-GH_OK" 2>/dev/null || echo "true")
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from shutil import which

_PREFLIGHT_TTL = 14400  # 4 hours in seconds
_PREFLIGHT_DIR = Path(".claude/state/preflight")


def _preflight_ok(name: str, state_dir: Path = _PREFLIGHT_DIR) -> bool:
    """Return True if ``name`` has a valid (non-expired) preflight cache entry.

    Args:
        name: Cache key (e.g. ``"gh"``, ``"codex"``).
        state_dir: Directory containing ``<name>.ok`` timestamp files.

    Returns:
        ``True`` when the cache file exists and is within TTL.

    Examples:
        >>> _preflight_ok("nonexistent_key_xyz")
        False
    """
    cache_file = state_dir / f"{name}.ok"
    if not cache_file.is_file():
        return False
    try:
        ts = int(cache_file.read_text(encoding="utf-8").strip())
        now = int(datetime.now(tz=timezone.utc).timestamp())
        return (now - ts) < _PREFLIGHT_TTL
    except (ValueError, OSError):
        return False


def _preflight_pass(name: str, state_dir: Path = _PREFLIGHT_DIR) -> None:
    """Write a fresh preflight cache entry for ``name``.

    Args:
        name: Cache key.
        state_dir: Directory to write the ``<name>.ok`` file.

    Examples:
        No doctest — filesystem side effects; covered by pytest.
    """
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{name}.ok").write_text(str(int(datetime.now(tz=timezone.utc).timestamp())), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    """Entry point — mirrors ``resolve_preflight.sh`` behaviour.

    Args:
        argv: Unused; script takes no positional arguments.

    Returns:
        Exit code: 0 on success; 1 on required-check failure.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]

    # --- codex (optional) -------------------------------------------------------
    codex_available = False
    if _preflight_ok("codex"):
        codex_available = True
        print("codex (openai-codex): ok (cached)", file=sys.stderr)
    else:
        claude = which("claude")
        if claude:
            proc = subprocess.run(  # noqa: S603
                [claude, "plugin", "list"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if "codex@openai-codex" in proc.stdout:
                _preflight_pass("codex")
                codex_available = True
                print("codex (openai-codex): ok", file=sys.stderr)
            else:
                print(
                    "codex (openai-codex): missing — complex multi-file action items will be"
                    " skipped; simple items implemented via foundry:sw-engineer"
                    " (see Step 8 degradation)",
                    file=sys.stderr,
                )
        else:
            print(
                "codex (openai-codex): missing — complex multi-file action items will be"
                " skipped; simple items implemented via foundry:sw-engineer"
                " (see Step 8 degradation)",
                file=sys.stderr,
            )

    # --- gh (required) ----------------------------------------------------------
    gh = which("gh")
    if _preflight_ok("gh"):
        print("gh: ok (cached)", file=sys.stderr)
    elif gh:
        auth_proc = subprocess.run(  # noqa: S603
            [gh, "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if auth_proc.returncode == 0:
            _preflight_pass("gh")
            all_output = auth_proc.stdout + auth_proc.stderr
            auth_line = next((ln.strip() for ln in all_output.splitlines() if "Logged in" in ln), "")
            print(f"gh: ok ({auth_line})", file=sys.stderr)
        else:
            print(
                "Pre-flight failed: gh found but not authenticated — run: gh auth login",
                file=sys.stderr,
            )
            return 1
    else:
        print("Pre-flight failed: gh not found — install: brew install gh", file=sys.stderr)
        return 1

    # --- git state --------------------------------------------------------------
    git = which("git")
    if git:
        remote_proc = subprocess.run(  # noqa: S603
            [git, "remote", "-v"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if remote_proc.stdout:
            print(remote_proc.stdout, file=sys.stderr, end="")

        # Always fetch all remotes so origin/$BASE_REF is current before Step 5 merges it.
        # Conditional fetch (gated on current branch having @{u}) left origin/$BASE_REF stale
        # when invoked from a branch with no upstream tracking ref.
        subprocess.run(  # noqa: S603
            [git, "fetch", "origin"],
            capture_output=True,
            check=False,
            timeout=30,
        )

        upstream_proc = subprocess.run(  # noqa: S603
            [git, "rev-parse", "--abbrev-ref", "@{u}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if upstream_proc.returncode == 0 and upstream_proc.stdout.strip():
            log_proc = subprocess.run(  # noqa: S603
                [git, "log", "HEAD..@{u}", "--oneline"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            remote_ahead = len([ln for ln in log_proc.stdout.splitlines() if ln.strip()])
            if remote_ahead > 0:
                print(f"Remote is {remote_ahead} commit(s) ahead — running git pull...", file=sys.stderr)
                pull_proc = subprocess.run(  # noqa: S603
                    [git, "pull"],
                    check=False,
                    timeout=60,
                )
                if pull_proc.returncode == 0:
                    print("✓ git pull: merged", file=sys.stderr)
                else:
                    print(
                        "Pre-flight failed: git pull had conflicts — resolve manually before running /resolve",
                        file=sys.stderr,
                    )
                    return 1
            else:
                print("✓ git: up to date", file=sys.stderr)
        else:
            print("✓ git: fetched origin (no upstream tracking on current branch — pull skipped)", file=sys.stderr)

    # --- write vars to TMPDIR files for safe cross-block consumption ------------
    tmpdir = Path(os.environ.get("TMPDIR", "/tmp"))
    (tmpdir / "resolve-preflight-CODEX_AVAILABLE").write_text(str(codex_available).lower())
    (tmpdir / "resolve-preflight-GH_OK").write_text("true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
