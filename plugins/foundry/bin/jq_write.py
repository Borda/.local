#!/usr/bin/env python
"""jq_write.py — atomic ``jq`` edit of a JSON file via temp-file + rename.

Mirrors the original ``jq-write.sh`` interface: read ``<target>``, apply
``<jq-filter>`` with optional ``--arg <name> <value>`` pairs, write to
``<target>.tmp``, then ``shutil.move`` over ``<target>``. The atomic rename
ensures readers never see a half-written file.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/jq_write.py" <target-file> <jq-filter> [--arg <name> <value>]...

Exit codes:
    0  Success
    1  Target file missing
    2  jq subprocess error (non-zero exit or jq not on PATH)
    3  Bad args (odd number of --arg trailing tokens, or no target/filter)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


_ALLOWED_FLAGS = {"--arg", "--argjson", "--indent"}
# Hostile jq filters can exhaust CPU/memory (CWE-400); cap wall-clock at 30s.
_JQ_TIMEOUT_SECONDS = 30
# Hard virtual-memory ceiling for the jq subprocess (bytes). 256 MB is far
# beyond any realistic foundry config file (typical settings.json is < 64 KB)
# while still stopping a runaway filter that builds large in-memory data.
_JQ_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024


def _jq_preexec() -> None:  # pragma: no cover — runs in subprocess fork
    """``preexec_fn`` that caps the jq child's address space.

    Unix-only (``resource`` module unavailable on Windows); on platforms where
    ``RLIMIT_AS`` is unsupported, the import is wrapped so the failure mode is
    "no limit applied" rather than "no jq spawned at all".
    """
    try:
        import resource  # imported here so non-POSIX platforms aren't penalised at module load
    except ImportError:
        return
    try:
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        # Respect any tighter hard limit already in place.
        cap = _JQ_MEMORY_LIMIT_BYTES if hard == resource.RLIM_INFINITY else min(_JQ_MEMORY_LIMIT_BYTES, hard)
        resource.setrlimit(resource.RLIMIT_AS, (cap, hard))
    except (ValueError, OSError):
        # Setting the limit may fail on macOS for some inherited limits — fall
        # back to no cap rather than crashing the spawn.
        return


def _parse_jq_args(extras: list[str]) -> list[str] | None:
    """Validate and return passthrough jq flag tokens.

    Only flags in :data:`_ALLOWED_FLAGS` are accepted; any other ``--`` token
    is rejected (raises :class:`ValueError`). This blocks dangerous jq flags
    such as ``--slurpfile`` / ``--rawfile`` that read arbitrary filesystem
    paths.

    Args:
        extras: Tokens after ``<target> <filter>`` (e.g. ``["--arg", "k", "v"]``).

    Returns:
        The same list if every ``--arg`` is followed by two tokens, else None
        to signal malformed args.

    Raises:
        ValueError: When a disallowed ``--`` flag is encountered.
    """
    for token in extras:
        if token.startswith("--") and token.split("=", 1)[0] not in _ALLOWED_FLAGS:
            raise ValueError(f"jq_write: disallowed flag: {token!r}")
    i = 0
    while i < len(extras):
        token = extras[i]
        if token == "--arg":
            # Need exactly two more tokens: name + value.
            if i + 2 >= len(extras):
                return None
            i += 3
        else:
            i += 1
    return extras


_ALLOWED_WRITE_ROOTS_ENV_VARS = ("CLAUDE_PLUGIN_ROOT", "TMPDIR")


def _validate_target(target: Path) -> Path:
    """Resolve target and assert it lives under an allowed write root.

    Allowed roots: cwd, TMPDIR, and common config paths (.claude/, .temp/, .reports/).

    Args:
        target: User-supplied target file path.

    Returns:
        The resolved path.

    Raises:
        ValueError: If the resolved path is outside allowed roots.
    """
    import os
    import tempfile

    resolved = target.resolve()
    cwd = Path.cwd().resolve()
    tmpdir = Path(os.environ.get("TMPDIR", tempfile.gettempdir())).resolve()
    allowed = [cwd, tmpdir]
    if not any(resolved == r or r in resolved.parents for r in allowed):
        raise ValueError(
            f"jq_write: target outside allowed roots (cwd, tmpdir): {resolved}",
        )
    return resolved


def run_jq_write(target: Path, jq_filter: str, extras: list[str]) -> int:
    """Apply ``jq_filter`` to ``target`` atomically.

    Args:
        target: JSON file to rewrite in place.
        jq_filter: jq program string.
        extras: Additional jq CLI tokens (e.g. ``["--arg", "k", "v"]``).

    Returns:
        0 on success, 1 if target missing, 2 on jq subprocess error.
    """
    try:
        target = _validate_target(target)
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 1
    if not target.is_file():
        print(f"! target not found: {target}", file=sys.stderr)
        return 1

    tmp = target.with_suffix(target.suffix + ".tmp")
    # `preexec_fn` is POSIX-only and a no-op on Windows; pass it conditionally
    # so we don't crash the spawn on platforms that don't support it.
    spawn_kwargs: dict[str, object] = {}
    if sys.platform != "win32":
        spawn_kwargs["preexec_fn"] = _jq_preexec
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            completed = subprocess.run(
                ["jq", *extras, jq_filter, str(target)],
                stdout=fh,
                stderr=subprocess.PIPE,
                check=False,
                text=True,
                timeout=_JQ_TIMEOUT_SECONDS,
                **spawn_kwargs,
            )
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        print(
            f"! jq filter exceeded {_JQ_TIMEOUT_SECONDS}s timeout for {target}",
            file=sys.stderr,
        )
        return 2
    except (FileNotFoundError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        print(f"! jq invocation failed for {target}: {exc}", file=sys.stderr)
        return 2

    if completed.returncode != 0:
        tmp.unlink(missing_ok=True)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        print(f"! jq filter failed for {target}", file=sys.stderr)
        return 2

    shutil.move(str(tmp), str(target))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code.

    Hand-parses ``argv`` (no argparse): the bash original passes ``--arg name
    value`` triplets straight through to jq, which argparse would mangle.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) < 2:
        print(
            "Usage: jq_write.py <target-file> <jq-filter> [--arg <name> <value>]...",
            file=sys.stderr,
        )
        return 3

    target_str, jq_filter, *extras = args
    try:
        parsed = _parse_jq_args(extras)
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        return 3
    if parsed is None:
        print("! malformed --arg: each --arg requires <name> <value>", file=sys.stderr)
        return 3

    return run_jq_write(Path(target_str), jq_filter, parsed)


if __name__ == "__main__":
    sys.exit(main())
