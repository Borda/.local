#!/usr/bin/env python3
"""Diagnose and manage the complete Codex Rig user-agent shim roster."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NoReturn

from _agent_shim_observe import FilesystemObservation, observe_filesystem
from generate_roles import GeneratedRoster, load_generated_roster


MINIMUM_PYTHON = (3, 10)
DIAGNOSTIC_INSTALL_ID = "123e4567-e89b-42d3-a456-426614174000"
SUPPORTED_PLATFORMS = ("darwin", "linux")


class ManagerArgumentParser(argparse.ArgumentParser):
    """Emit stable usage errors without writing parser diagnostics itself."""

    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


@dataclass(frozen=True)
class CheckResult:
    """Describe one live manager prerequisite without claiming more evidence."""

    status: str
    detail: str


@dataclass(frozen=True)
class DiagnosticResult:
    """Expose one complete read-only doctor or status result."""

    action: str
    classification: str
    plugin_version: str | None
    python_version: str
    platform: str
    codex_home: str
    plugin_root: str
    checks: dict[str, CheckResult]
    state: str
    targets: str
    recovery: str
    namespace_candidates: tuple[str, ...]


def _digest_regular_executable(path: Path, label: str) -> tuple[Path, str]:
    """Resolve and hash one stable current-user executable without links."""
    try:
        canonical = path.resolve(strict=True)
        descriptor = os.open(canonical, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as error:
        raise ValueError(f"{label} is unavailable: {error}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size < 0 or before.st_size > 268_435_456:
            raise ValueError(f"{label} is not a bounded regular file")
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 65_536):
            digest.update(chunk)
        after = os.fstat(descriptor)
        stable = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in stable):
            raise ValueError(f"{label} changed during hashing")
    finally:
        os.close(descriptor)
    if not os.access(canonical, os.X_OK):
        raise ValueError(f"{label} is not executable")
    return canonical, digest.hexdigest()


def _codex_executable(explicit: Path | None) -> Path:
    """Resolve the configured or PATH-selected Codex executable name."""
    if explicit is not None:
        return explicit
    discovered = shutil.which("codex")
    if discovered is None:
        raise ValueError("Codex executable is unavailable on PATH")
    return Path(discovered)


def _active_package_check(
    plugin_root: Path,
    codex_home: Path,
    codex_binary: Path,
    codex_hash: str,
    roster: GeneratedRoster,
) -> CheckResult:
    """Run the packaged active-cache oracle for one representative role."""
    role = next((item for item in roster.roles if item.role_id == "challenger"), None)
    if role is None:
        return CheckResult("blocked", "challenger role is absent from the package roster")
    helper = plugin_root / "scripts" / "verify_role_link.py"
    command = [
        sys.executable,
        str(helper),
        "--plugin-root",
        str(plugin_root),
        "--role",
        role.role_id,
        "--role-sha256",
        role.role_hash,
        "--manifest-sha256",
        roster.package_hash,
        "--helper-sha256",
        roster.bootstrap_hash,
        "--codex-binary",
        str(codex_binary),
        "--codex-sha256",
        codex_hash,
    ]
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return CheckResult("degraded", f"active package oracle failed: {error}")
    if completed.returncode == 0:
        return CheckResult("pass", "active package, manifest, helper, and representative card match")
    detail = completed.stderr.decode("utf-8", "replace").strip() or "active package oracle refused this cache"
    return CheckResult("degraded", detail[:512])


def _classification(checks: dict[str, CheckResult], observation: FilesystemObservation) -> str:
    """Reduce exact prerequisite evidence to the stable doctor classification."""
    if observation.classification == "blocked" or any(item.status == "blocked" for item in checks.values()):
        return "blocked"
    if any(item.status != "pass" for item in checks.values()):
        return "degraded"
    return "healthy"


def diagnose(
    *,
    action: str,
    codex_home: Path,
    plugin_root: Path,
    codex_binary: Path | None = None,
    check_active_package: bool = True,
) -> DiagnosticResult:
    """Run a zero-write live doctor and optional installed-state summary."""
    if action not in {"doctor", "status"}:
        raise ValueError("diagnostic action must be doctor or status")
    home = codex_home.resolve(strict=True)
    root = plugin_root.resolve(strict=True)
    if Path(os.path.abspath(codex_home)) != home or Path(os.path.abspath(plugin_root)) != root:
        raise ValueError("Codex home and plugin root must be canonical non-symlink paths")
    checks: dict[str, CheckResult] = {}
    python_version = ".".join(str(item) for item in sys.version_info[:3])
    checks["python"] = CheckResult(
        "pass" if sys.version_info >= MINIMUM_PYTHON else "blocked",
        f"Python {python_version}; minimum is 3.10",
    )
    checks["platform"] = CheckResult(
        "pass" if sys.platform.startswith(SUPPORTED_PLATFORMS) else "blocked",
        f"platform {sys.platform}; native Windows and unknown POSIX hosts are unsupported",
    )
    observation = observe_filesystem(codex_home=home, plugin_root=root)
    checks["filesystem"] = CheckResult(
        "pass" if observation.classification != "blocked" else "blocked",
        observation.reason,
    )
    roster: GeneratedRoster | None = None
    try:
        python_path, python_hash = _digest_regular_executable(Path(sys.executable), "Python executable")
        codex_path, codex_hash = _digest_regular_executable(_codex_executable(codex_binary), "Codex executable")
        roster = load_generated_roster(
            root,
            install_id=DIAGNOSTIC_INSTALL_ID,
            python_executable=python_path,
            python_executable_hash=python_hash,
            codex_binary=codex_path,
            codex_binary_hash=codex_hash,
        )
        checks["package"] = CheckResult("pass", "package manifest, generator, verifier, and all roles match")
        checks["executables"] = CheckResult("pass", "canonical Python and Codex executables are stable")
        checks["active_package"] = (
            _active_package_check(root, home, codex_path, codex_hash, roster)
            if check_active_package
            else CheckResult("degraded", "active package oracle was explicitly skipped")
        )
    except (OSError, ValueError) as error:
        checks["package"] = CheckResult("blocked", str(error))
        checks["executables"] = CheckResult("blocked", str(error))
        checks["active_package"] = CheckResult("blocked", "package or executable validation failed first")
    candidates = tuple(item.name for item in observation.namespace_candidates)
    return DiagnosticResult(
        action,
        _classification(checks, observation),
        roster.plugin_version if roster is not None else None,
        python_version,
        sys.platform,
        str(home),
        str(root),
        checks,
        observation.state,
        observation.targets,
        observation.recovery,
        candidates,
    )


def _encode(result: DiagnosticResult) -> str:
    """Encode one deterministic machine-readable diagnostic result."""
    return json.dumps(asdict(result), ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the exact one-action public manager grammar."""
    parser = ManagerArgumentParser(prog="agent-shims", add_help=True)
    parser.add_argument("action", choices=("doctor", "status", "install", "remove"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run the public manager action with stable exit codes and JSON output."""
    try:
        arguments = parse_args(argv)
    except ValueError as error:
        print(json.dumps({"classification": "usage-error", "detail": str(error)}, sort_keys=True))
        return 2
    except SystemExit as error:
        return int(error.code)
    if arguments.action in {"install", "remove"}:
        print(
            json.dumps(
                {
                    "action": arguments.action,
                    "classification": "blocked",
                    "detail": "mutation manager is unavailable in this development build",
                },
                sort_keys=True,
            )
        )
        return 5
    home_value = os.environ.get("CODEX_HOME")
    codex_home = Path(home_value) if home_value else Path.home() / ".codex"
    plugin_root = Path(__file__).resolve().parents[1]
    try:
        result = diagnose(action=arguments.action, codex_home=codex_home, plugin_root=plugin_root)
    except (OSError, ValueError) as error:
        print(
            json.dumps({"action": arguments.action, "classification": "blocked", "detail": str(error)}, sort_keys=True)
        )
        return 5
    print(_encode(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
