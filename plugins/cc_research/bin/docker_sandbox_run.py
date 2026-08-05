#!/usr/bin/env python3
"""Run a command inside a sandboxed ``python:3.11-slim`` Docker container.

Two modes:
    ``--mode explore`` — read-only project mount; runs an exploratory script by path.
    ``--mode verify``  — read-only project mount + read-write ``.experiments`` mount; runs a
        metric command. The command is rejected if it contains shell metacharacters or
        destructive binaries (``rm``, ``dd``, ``truncate`` …) that could wipe the
        read-write ``.experiments`` mount — run non-trivial logic via a script entry point.

Limitation (H1): that destructive-binary rejection is a defense-in-depth speed bump against
*accidental* wipes, not a security boundary — a deliberate payload routed through a sanctioned
interpreter (``python -c "...rmtree(...)"``) passes it; containment is the Docker isolation flags.

Network defaults to ``none``; override via ``SANDBOX_NETWORK`` environment variable.
Each ``docker run`` is capped at ``SANDBOX_TIMEOUT_SEC`` seconds (default 600) as a host-side
backstop; on expiry the container is killed via its ``--cidfile`` id and ``124`` is returned.

Usage:
    docker_sandbox_run.py --mode explore <script-path>
    docker_sandbox_run.py --mode verify  <metric-cmd>

Exit codes:
    Forwarded from ``docker run``; ``2`` = bad CLI args; ``124`` = timeout; ``127`` = no docker.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

IMAGE = "python:3.11-slim"
TMPFS_SIZE = "256m"
TMPFS_MOUNT = f"/tmp:rw,size={TMPFS_SIZE}"
DEFAULT_NETWORK = "none"
# Wall-clock cap for one ``docker run``; override via ``SANDBOX_TIMEOUT_SEC``.  The container
# gets no CPU/memory limits of its own, so a hanging metric command would otherwise pin the
# host-side client forever.  Callers with their own shorter cap hit theirs first.
DEFAULT_TIMEOUT_SEC = 600
# Cap for the post-timeout ``docker kill`` itself — a wedged daemon must not re-hang the exit path.
_KILL_TIMEOUT_SEC = 15
# Docker network modes that preserve sandbox isolation.  ``host`` is excluded by
# policy: it removes network namespace isolation and would allow exfiltration
# from inside the verify-mode container (SEC-R-2).
_ALLOWED_NETWORK_MODES: frozenset[str] = frozenset({"none", "bridge", "internal"})
# Shell metacharacters forbidden in verify-mode command strings.  These reach
# ``sh -c`` inside the container; ``SANDBOX_NETWORK=host`` would otherwise allow
# network exfiltration via embedded ``$(...)``, backticks, redirection, etc.
_VERIFY_FORBIDDEN_CHARS = frozenset(";&|$`<>\n\r\\")
# Destructive binaries forbidden as bare command tokens in verify mode.  The
# ``.experiments`` host dir is the one read-write mount (L143); the metachar filter
# above blocks command *chaining* but not a single space-separated destructive
# invocation (e.g. ``rm -rf /workspace/.experiments/state``), which would silently
# wipe prior-iteration state that retro/significance analysis depends on (H1).
# Defense-in-depth: reject these as whole-word tokens.  Legitimate metric commands
# (``pytest``, ``python``, ``echo`` …) are unaffected.
# Limitation (H1): a speed bump against *accidental* destruction, not a security boundary — it
# cannot stop deliberate destruction expressed as an interpreter payload (``python -c
# "__import__('shutil').rmtree(...)"`` token-splits to nothing here).  Containment is the Docker
# isolation flags in the argv builders below, not this blocklist.
_VERIFY_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {"rm", "rmdir", "unlink", "shred", "truncate", "dd", "mv", "mkfs", "find", "chmod", "chown"}
)


def find_destructive_tokens(arg: str) -> list[str]:
    """Return sorted destructive command tokens found in a verify-mode command string.

    Splits on whitespace-equivalent word boundaries and matches whole tokens against
    :data:`_VERIFY_FORBIDDEN_TOKENS`. Substrings never match (``pytest_rm`` is safe;
    ``rm`` is not).

    Args:
        arg: The verify-mode command string destined for ``sh -c``.

    Returns:
        Sorted list of forbidden tokens present in ``arg`` (empty when none).

    Examples:
        >>> find_destructive_tokens("pytest -q metric.py")
        []
        >>> find_destructive_tokens("rm -rf /workspace/.experiments/state")
        ['rm']
        >>> find_destructive_tokens("truncate -s 0 log && dd of=x")
        ['dd', 'truncate']
        >>> find_destructive_tokens("python -c 'import armor'")
        []
    """
    tokens = set(re.split(r"[^A-Za-z0-9_]+", arg))
    return sorted(tokens & _VERIFY_FORBIDDEN_TOKENS)


def _verify_rejection_reason(arg: str) -> str | None:
    """Return why a verify-mode command must be rejected, or ``None`` when it may run.

    Metacharacters are checked before destructive binaries and the first failure wins, so a
    command failing both is reported by its more fundamental problem (SEC-R-1 before H1).

    Args:
        arg: The verify-mode command string destined for ``sh -c``.

    Returns:
        Rejection message (without the program-name prefix), or ``None`` when both filters pass.

    Examples:
        >>> _verify_rejection_reason("pytest -q metric.py") is None
        True
        >>> "metacharacters" in _verify_rejection_reason("echo a; echo b")
        True
        >>> "destructive binaries" in _verify_rejection_reason("rm -rf /workspace")
        True
    """
    unsafe = sorted({ch for ch in arg if ch in _VERIFY_FORBIDDEN_CHARS})
    if unsafe:
        return (
            f"verify-mode command contains shell metacharacters {unsafe!r}; "
            "use a script entry point instead of inline shell composition"
        )
    destructive = find_destructive_tokens(arg)
    if destructive:
        return (
            f"verify-mode command uses destructive binaries {destructive!r} "
            "that could wipe the read-write .experiments mount; run the metric via a script entry point"
        )
    return None


def build_explore_command(arg: str, network: str, workdir: str, cidfile: str | None = None) -> list[str]:
    """Build the ``docker run`` argv for explore mode.

    The script path may be given with a leading ``./``; it's stripped before being
    appended to the container's ``/workspace/`` prefix to match the bash version.

    Args:
        arg: Workspace-relative path to the exploratory script.
        network: Docker network mode (e.g. ``"none"``).
        workdir: Host directory mounted at ``/workspace`` (read-only).
        cidfile: Path docker writes the container id to. Omitted from the argv when ``None``;
            :func:`main` always supplies one so the timeout path has a kill handle.

    Returns:
        Argument list ready for ``subprocess.run`` (no shell).

    Raises:
        ValueError: if the script path contains ``..`` components (path traversal)
            or resolves to an absolute path (SEC-M14).

    Examples:
        >>> build_explore_command("scripts/explore.py", "none", "/proj")[:3]
        ['docker', 'run', '--rm']
        >>> build_explore_command("./scripts/x.py", "none", "/proj")[-1]
        '/workspace/scripts/x.py'
        >>> "--network" in build_explore_command("a.py", "none", "/proj")
        True
        >>> build_explore_command("a.py", "none", "/proj", cidfile="/c.cid")[3:5]
        ['--cidfile', '/c.cid']
        >>> build_explore_command("../etc/passwd", "none", "/proj")
        Traceback (most recent call last):
            ...
        ValueError: Path traversal not allowed in script path: '../etc/passwd'
        >>> build_explore_command("./scripts/../../etc/passwd", "none", "/proj")
        Traceback (most recent call last):
            ...
        ValueError: Path traversal not allowed in script path: './scripts/../../etc/passwd'
        >>> build_explore_command("/etc/passwd", "none", "/proj")
        Traceback (most recent call last):
            ...
        ValueError: Absolute script path not allowed: '/etc/passwd'
    """
    script_raw = arg[2:] if arg.startswith("./") else arg
    script_path = Path(script_raw)
    # On Windows Path("/etc/passwd").is_absolute() is False (no drive); check posix form too.
    if script_path.is_absolute() or script_path.as_posix().startswith("/"):
        raise ValueError(f"Absolute script path not allowed: {arg!r}")
    if any(part == ".." for part in script_path.parts):
        raise ValueError(f"Path traversal not allowed in script path: {arg!r}")
    script = script_raw
    return [
        "docker",
        "run",
        "--rm",
        *(("--cidfile", cidfile) if cidfile else ()),
        "--network",
        network,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
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


def build_verify_command(arg: str, network: str, workdir: str, cidfile: str | None = None) -> list[str]:
    """Build the ``docker run`` argv for verify mode.

    The ``.experiments`` subdir of ``workdir`` is mounted read-write so metric runs may
    log into it. The supplied metric command is passed to ``sh -c`` inside the container.

    Args:
        arg: Shell string executed inside the container as ``sh -c <arg>``.
        network: Docker network mode (e.g. ``"none"``).
        workdir: Host directory mounted at ``/workspace`` (read-only); its
            ``.experiments`` subdir is mounted read-write.
        cidfile: Path docker writes the container id to. Omitted from the argv when ``None``;
            :func:`main` always supplies one so the timeout path has a kill handle.

    Returns:
        Argument list ready for ``subprocess.run`` (no shell).

    Examples:
        >>> cmd = build_verify_command("pytest -q", "bridge", "/proj")
        >>> cmd[-3:]
        ['sh', '-c', 'pytest -q']
        >>> any("experiments:rw" in c for c in cmd)
        True
        >>> build_verify_command("pytest -q", "none", "/proj", cidfile="/c.cid")[3:5]
        ['--cidfile', '/c.cid']
    """
    # arg in verify mode is treated as shell string — Docker container is primary isolation boundary
    return [
        "docker",
        "run",
        "--rm",
        *(("--cidfile", cidfile) if cidfile else ()),
        "--network",
        network,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
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


def _resolve_timeout(raw: str | int) -> float:
    """Coerce a ``SANDBOX_TIMEOUT_SEC`` value into a positive number of seconds.

    A malformed or non-positive override falls back to :data:`DEFAULT_TIMEOUT_SEC` rather than
    raising: this is a backstop against a hung container, so it must never end up disabled.

    Args:
        raw: Raw env value, or :data:`DEFAULT_TIMEOUT_SEC` when the variable is unset.

    Returns:
        Timeout in seconds, always ``> 0``.

    Examples:
        >>> _resolve_timeout(600)
        600.0
        >>> _resolve_timeout("30")
        30.0
        >>> _resolve_timeout("not-a-number")
        600.0
        >>> _resolve_timeout("0")
        600.0
        >>> _resolve_timeout("-5")
        600.0
    """
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return float(DEFAULT_TIMEOUT_SEC)
    return seconds if seconds > 0 else float(DEFAULT_TIMEOUT_SEC)


def _kill_container(cidfile: str) -> None:
    """Best-effort ``docker kill`` of the container id recorded in ``cidfile``.

    Only called after a timeout, once ``subprocess.run`` has killed the docker *client*: the
    container itself survives that and would keep running unsupervised. Every failure here is
    swallowed — the caller is already returning a timeout exit code and has no better recourse.

    Args:
        cidfile: Path docker wrote the container id to; may be missing or empty.
    """
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        cid = Path(cidfile).read_text(encoding="utf-8").strip()
        if cid:
            subprocess.run(  # noqa: S603 — fixed binary; cid read from our own cidfile.
                ["docker", "kill", cid], check=False, timeout=_KILL_TIMEOUT_SEC, capture_output=True
            )


def _run_docker(cmd: list[str], timeout: float, cidfile: str) -> int:
    """Run a ``docker run`` argv under a wall-clock cap, killing the container on expiry.

    Args:
        cmd: Full ``docker run`` argv, containing ``--cidfile <cidfile>``.
        timeout: Wall-clock cap in seconds.
        cidfile: Path docker writes the container id to; removed before returning.

    Returns:
        Exit code from ``docker run``; ``124`` on timeout, ``127`` when docker is not installed.
    """
    try:
        result = subprocess.run(cmd, check=False, timeout=timeout)  # noqa: S603 — fixed binary, argv-controlled args.
        return result.returncode
    except FileNotFoundError:
        print("docker_sandbox_run.py: 'docker' binary not found in PATH", file=sys.stderr)
        return 127
    except subprocess.TimeoutExpired:
        print(f"docker_sandbox_run.py: sandbox exceeded {timeout:g}s timeout; killing container", file=sys.stderr)
        _kill_container(cidfile)
        return 124
    finally:
        # Suppressed: a failed cleanup must not replace the exit code we are about to return.
        with contextlib.suppress(OSError):
            Path(cidfile).unlink(missing_ok=True)


def main(argv: list[str] | None = None, env: dict[str, str] | None = None, cwd: str | None = None) -> int:
    """Entry point — mirrors ``docker-sandbox-run.sh`` behaviour exactly.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).
        env: Optional environment mapping (defaults to ``os.environ``).
        cwd: Optional working directory used as host mount (defaults to ``os.getcwd()``).

    Returns:
        Exit code forwarded from ``docker run``; ``2`` on bad CLI args, ``124`` on timeout.
    """
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if env is None else env
    workdir = Path(cwd).as_posix() if cwd else Path(os.getcwd()).as_posix()

    # Honour only -h/--help via argparse; every other token flows through the manual
    # _parse_args below, which mirrors the bash interface (last non-flag token wins,
    # --mode=X form, bad mode/arg → exit 2). argparse's own positional/choices errors
    # would change the exit-2 message and the last-token-wins capture — keep the
    # manual parser as the sole argv authority so the observable contract is unchanged.
    if raw_argv in (["-h"], ["--help"]):
        argparse.ArgumentParser(
            prog="docker_sandbox_run.py",
            description="Run a command inside a sandboxed python:3.11-slim Docker container.",
        ).parse_args(["-h"])

    mode, arg = _parse_args(raw_argv)

    if not mode or not arg:
        print(
            "usage: docker_sandbox_run.py --mode <explore|verify> <script-path-or-metric-cmd>",
            file=sys.stderr,
        )
        return 2

    network = env.get("SANDBOX_NETWORK") or DEFAULT_NETWORK
    timeout = _resolve_timeout(env.get("SANDBOX_TIMEOUT_SEC") or DEFAULT_TIMEOUT_SEC)
    if network not in _ALLOWED_NETWORK_MODES:
        # ``host`` is explicitly rejected — it removes network-namespace isolation.
        print(
            f"docker_sandbox_run.py: Disallowed SANDBOX_NETWORK: {network!r} "
            f"(allowed: {sorted(_ALLOWED_NETWORK_MODES)})",
            file=sys.stderr,
        )
        return 2

    # Container-id handle for the post-timeout kill: unique per invocation so concurrent sandbox
    # runs never share one, and never pre-created here — docker writes the file itself.
    cidfile = str(Path(tempfile.gettempdir()) / f"docker-sandbox-{uuid.uuid4().hex}.cid")

    if mode == "explore":
        try:
            cmd = build_explore_command(arg, network, workdir, cidfile=cidfile)
        except ValueError as exc:
            print(f"docker_sandbox_run.py: {exc}", file=sys.stderr)
            return 2
    elif mode == "verify":
        # Verify mode forwards ``arg`` to ``sh -c`` inside the container: metacharacters can
        # chain arbitrary commands even on non-host networks (SEC-R-1), and a bare destructive
        # binary needs no metacharacter to wipe the read-write ``.experiments`` mount (H1).
        reason = _verify_rejection_reason(arg)
        if reason:
            print(f"docker_sandbox_run.py: {reason}", file=sys.stderr)
            return 2
        cmd = build_verify_command(arg, network, workdir, cidfile=cidfile)
    else:
        # argparse choices should have rejected, but guard anyway.
        print(f"unknown mode: {mode} (expected: explore|verify)", file=sys.stderr)
        return 2

    return _run_docker(cmd, timeout, cidfile)


if __name__ == "__main__":
    sys.exit(main())
