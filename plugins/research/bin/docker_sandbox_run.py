#!/usr/bin/env python3
"""Run a command inside a sandboxed ``python:3.11-slim`` Docker container.

Two modes:
    ``--mode explore`` — read-only project mount; runs an exploratory script by path.
    ``--mode verify``  — read-only project mount + read-write ``.experiments`` mount; runs an
        arbitrary metric command.

Network defaults to ``none``; override via ``SANDBOX_NETWORK`` environment variable.

Usage:
    docker_sandbox_run.py --mode explore <script-path>
    docker_sandbox_run.py --mode verify  <metric-cmd>

Exit codes:
    Forwarded from ``docker run``; ``2`` = bad CLI args.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IMAGE = "python:3.11-slim"
TMPFS_SIZE = "256m"
TMPFS_MOUNT = f"/tmp:rw,size={TMPFS_SIZE}"
DEFAULT_NETWORK = "none"


def build_explore_command(arg: str, network: str, workdir: str) -> list[str]:
    """Build the ``docker run`` argv for explore mode.

    The script path may be given with a leading ``./``; it's stripped before being
    appended to the container's ``/workspace/`` prefix to match the bash version.

    Args:
        arg: Workspace-relative path to the exploratory script.
        network: Docker network mode (e.g. ``"none"``).
        workdir: Host directory mounted at ``/workspace`` (read-only).

    Returns:
        Argument list ready for ``subprocess.run`` (no shell).

    Examples:
        >>> build_explore_command("scripts/explore.py", "none", "/proj")[:3]
        ['docker', 'run', '--rm']
        >>> build_explore_command("./scripts/x.py", "none", "/proj")[-1]
        '/workspace/scripts/x.py'
        >>> "--network" in build_explore_command("a.py", "none", "/proj")
        True
    """
    script = arg[2:] if arg.startswith("./") else arg
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "-v",
        f"{workdir}:/workspace:ro",
        "--tmpfs",
        TMPFS_MOUNT,
        "-w",
        "/workspace",
        IMAGE,
        "python",
        f"/workspace/{script}",
    ]


def build_verify_command(arg: str, network: str, workdir: str) -> list[str]:
    """Build the ``docker run`` argv for verify mode.

    The ``.experiments`` subdir of ``workdir`` is mounted read-write so metric runs may
    log into it. The supplied metric command is passed to ``sh -c`` inside the container.

    Args:
        arg: Shell string executed inside the container as ``sh -c <arg>``.
        network: Docker network mode (e.g. ``"none"``).
        workdir: Host directory mounted at ``/workspace`` (read-only); its
            ``.experiments`` subdir is mounted read-write.

    Returns:
        Argument list ready for ``subprocess.run`` (no shell).

    Examples:
        >>> cmd = build_verify_command("pytest -q", "bridge", "/proj")
        >>> cmd[-3:]
        ['sh', '-c', 'pytest -q']
        >>> any("experiments:rw" in c for c in cmd)
        True
    """
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "-v",
        f"{workdir}:/workspace:ro",
        "-v",
        f"{workdir}/.experiments:/workspace/.experiments:rw",
        "--tmpfs",
        TMPFS_MOUNT,
        "-w",
        "/workspace",
        IMAGE,
        "sh",
        "-c",
        arg,
    ]


def _parse_args(argv: list[str]) -> tuple[str, str]:
    """Parse ``--mode`` and the single positional argument; mirrors the bash interface.

    Bash accepts ``--mode X`` and ``--mode=X``; the final non-flag token becomes ``ARG``.
    Unrecognised flags are not supported — we mirror bash's catch-all positional capture.

    Args:
        argv: Raw argv tokens (without program name).

    Returns:
        ``(mode, arg)`` tuple; empty strings when absent.
    """
    mode = ""
    arg = ""
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--mode":
            mode = argv[i + 1] if i + 1 < len(argv) else ""
            i += 2
            continue
        if tok.startswith("--mode="):
            mode = tok[len("--mode=") :]
            i += 1
            continue
        # Bash assigns ARG=$1 for every non-mode token, so the *last* one wins.
        arg = tok
        i += 1
    return mode, arg


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, cwd: str | None = None) -> int:
    """Entry point — mirrors ``docker-sandbox-run.sh`` behaviour exactly.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
        env: Optional environment mapping (defaults to ``os.environ``).
        cwd: Optional working directory used as host mount (defaults to ``os.getcwd()``).

    Returns:
        Exit code forwarded from ``docker run``; ``2`` on bad CLI args.
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    workdir = str(Path(cwd).resolve()) if cwd else os.getcwd()

    mode, arg = _parse_args(raw_argv)

    if not mode or not arg:
        print(
            "usage: docker_sandbox_run.py --mode <explore|verify> <script-path-or-metric-cmd>",
            file=sys.stderr,
        )
        return 2

    network = env.get("SANDBOX_NETWORK") or DEFAULT_NETWORK

    if mode == "explore":
        cmd = build_explore_command(arg, network, workdir)
    elif mode == "verify":
        cmd = build_verify_command(arg, network, workdir)
    else:
        # argparse choices should have rejected, but guard anyway.
        print(f"unknown mode: {mode} (expected: explore|verify)", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(cmd, check=False)  # noqa: S603 — fixed binary, argv-controlled args.
    except FileNotFoundError:
        print("docker_sandbox_run.py: 'docker' binary not found in PATH", file=sys.stderr)
        return 127
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
