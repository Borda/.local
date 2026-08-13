#!/usr/bin/env python
"""integration.py — ``codemap-py integrate`` cross-runtime integration engine (plan §8.3).

Adapter-free engine behind ``/codemap-py:integration`` and ``$codemap-py:integration``:
either host runtime can target Claude Code, Codex, or both; this module never invokes
the other model and never imports Codex Rig or any ``cc_*`` consumer package (plan §8.5
symmetric optionality gate).

Modes (pinned CLI surface, delivery-plan.md "Pinned CLI surface"):

- ``check``  — read-only audit: installed/active versions, roots, protocol compatibility,
  Codex-Rig-owned global-instruction status from verifiable bytes, shared-index identity,
  runtime-log isolation.
- ``plan``   — persists one JSON artifact: ordered ``source_write`` ops (managed-block edits
  to allowlisted consumer source files) and ``runtime_sync`` ops (native plugin-manager argv),
  each with before-state hashes, desired state, rollback identity, and expected post-state,
  bound together by ``plan_sha256``.
- ``apply``  — executes only a plan's ``source_write`` ops against a verified source checkout.
- ``sync``   — executes only a plan's ``runtime_sync`` ops (native CLI only); never touches
  consumer source or global instructions.
- ``demo``   — disposable ``check`` plus one representative structural-context query.

The closed integration/reinstall set is fixed at the module level (plan §8.3 "closed
integration/reinstall set"): Claude consumers ``foundry``, ``oss``, ``develop``, ``research``;
Codex consumer ``codex-rig``; provider ``codemap-py``. This is an explicit mapping, never a
discovery registry — an unknown consumer name is refused, not looked up.

Every mutation is dry-run-first (``plan``), hash-approved (``--approve <plan_sha256>``),
journaled per target under a task-specific ``.reports/integrate/<ts>/`` directory (never a
plugin cache), and followed by a post-state hash/version verification before the engine
claims success. :func:`run` is the sole CLI boundary: argparse usage errors surface as exit
``2``; every other failure is caught and turned into one bounded JSON stderr line — never a
bare traceback (plan §7.5).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from pathlib import Path

from codemap_py import __version__, index_paths, query, runtime_log, rwgate

PROTOCOL_VERSION = "codemap-py.integration.v1"
SCHEMA_VERSION = 1
PROVIDER_NAME = "codemap-py"
MARKETPLACE_NAME = "borda-ai-rig"
MARKETPLACE_REMOTE = "https://github.com/Borda/AI-Rig.git"

_EXIT_OK = 0
_EXIT_RUNTIME = 1
_EXIT_USAGE = 2

_NATIVE_TIMEOUT_S = 30
_GIT_TIMEOUT_S = 5
_MAX_JSON_BYTES = 1_048_576
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_BATCH_METACHARACTERS = frozenset('&|<>^()%!"')

# In-file managed-block scheme for `apply`'s source_write ops (canonical marker shape).
# `apply` never owns a whole file — it replaces only the sentinel-bounded region inside an
# existing, consumer-owned source file; everything outside the sentinels is preserved
# byte-for-byte. BLOCK_SCHEMA_VERSION is embedded in the begin marker so a future body-shape
# change is distinguishable from today's; the full sha256 of the enclosed body is the
# drift/foreign-tamper signal, independent of that version tag.
BLOCK_SCHEMA_VERSION = 1
_MANAGED_BEGIN_RE = re.compile(r"<!-- codemap-py:integration:begin v(\d+) sha256=([0-9a-f]{64}) -->\n")
_MANAGED_END = "<!-- codemap-py:integration:end -->\n"

# Finalized Phase 5 consumer target map. Each entry is an explicit, allowlisted
# source-owned integration site; no runtime discovery or installed-cache mutation occurs.
CONSUMER_MANAGED_FILE: dict[str, str] = {
    "foundry": "skills/_shared/codemap-context.md",
    "oss": "skills/_shared/codemap-gates.md",
    "develop": "skills/_shared/codemap-context.md",
    "research": "skills/_shared/codemap-context.md",
    "codex-rig": "shared/codemap-py-integration.md",
}

# Read-only inspection contract for Codex Rig's own authenticated global-instructions block
# (plugins/codex-rig/scripts/install_global_agents.py BEGIN_PREFIX/END_MARKER). Never imported
# from codex-rig (plan §8.5 gate) — the byte format is treated as a stable, independently
# verifiable contract, not a Python API.
_CODEX_RIG_AGENTS_BEGIN_RE = re.compile(rb"<!-- codex-rig:global-agents begin sha256=([0-9a-f]{64}) -->\n")
_CODEX_RIG_AGENTS_END = b"<!-- codex-rig:global-agents end -->\n"


class IntegrationError(Exception):
    """Bounded, structured integration failure (plan §7.5 — never a bare traceback).

    Attributes:
        code: Stable machine-readable error slug.
        exit_code: Process exit code this error maps to.
        detail: Structured supporting fields (argv, journal path, ...); never secrets.
    """

    def __init__(self, code: str, message: str, *, exit_code: int = _EXIT_RUNTIME, detail: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.exit_code = exit_code
        self.detail = detail or {}


class RefusalError(IntegrationError):
    """A safety invariant refused a mutation before touching anything (exit ``1``)."""

    def __init__(self, code: str, message: str, *, detail: dict | None = None) -> None:
        super().__init__(code, message, exit_code=_EXIT_RUNTIME, detail=detail)


class ApprovalError(IntegrationError):
    """``--approve`` does not authorize the requested mutation (exit ``2``)."""

    def __init__(self, code: str, message: str, *, detail: dict | None = None) -> None:
        super().__init__(code, message, exit_code=_EXIT_USAGE, detail=detail)


class Runtime(str, Enum):
    """Host runtime a target belongs to, plus the ``BOTH`` selector.

    Inherits ``str`` (not ``enum.StrEnum`` — ``requires-python`` is ``>=3.10``) so members
    serialise into plan/report JSON as plain strings. ``BOTH`` is a CLI selector only: it
    never appears on a :class:`ConsumerTarget`, and :func:`_runtimes_of` expands it.
    """

    CLAUDE = "claude"
    CODEX = "codex"
    BOTH = "both"


class Source(str, Enum):
    """Which marketplace source a ``sync`` refreshes from (plan §8.3 two source modes)."""

    LOCAL_CANDIDATE = "local-candidate"
    RELEASE = "release"


@dataclass(frozen=True)
class ConsumerTarget:
    """One closed-set integration target (plan §8.3 "closed integration/reinstall set").

    Attributes:
        runtime: ``Runtime.CLAUDE`` or ``Runtime.CODEX`` — never ``Runtime.BOTH``.
        consumer: Installed plugin name — must equal that plugin's own manifest ``name``.
        plugin_dir: Repo-relative directory holding the consumer's source checkout.
    """

    runtime: Runtime
    consumer: str
    plugin_dir: str


CLAUDE_TARGETS: tuple[ConsumerTarget, ...] = (
    ConsumerTarget(Runtime.CLAUDE, "foundry", "plugins/cc_foundry"),
    ConsumerTarget(Runtime.CLAUDE, "oss", "plugins/cc_oss"),
    ConsumerTarget(Runtime.CLAUDE, "develop", "plugins/cc_develop"),
    ConsumerTarget(Runtime.CLAUDE, "research", "plugins/cc_research"),
)
CODEX_TARGETS: tuple[ConsumerTarget, ...] = (ConsumerTarget(Runtime.CODEX, "codex-rig", "plugins/codex-rig"),)
ALL_TARGETS: tuple[ConsumerTarget, ...] = CLAUDE_TARGETS + CODEX_TARGETS
PROVIDER_DIR = "plugins/codemap-py"

# Selectors that include each concrete runtime — `BOTH` is a member of both sets.
_CLAUDE_SELECTORS: tuple[Runtime, ...] = (Runtime.CLAUDE, Runtime.BOTH)
_CODEX_SELECTORS: tuple[Runtime, ...] = (Runtime.CODEX, Runtime.BOTH)


def _cli_for(runtime: Runtime | str) -> str:
    """Return the native plugin-manager executable name for *runtime*.

    Accepts a plain string too: ``runtime`` is read straight off a persisted plan op in
    the apply/sync paths, where it arrives as JSON text rather than a member.
    """
    return Runtime.CLAUDE.value if runtime == Runtime.CLAUDE else Runtime.CODEX.value


def _targets_for_runtime(runtime: Runtime) -> tuple[ConsumerTarget, ...]:
    """Return the closed-set targets for one runtime selector."""
    if runtime == Runtime.CLAUDE:
        return CLAUDE_TARGETS
    if runtime == Runtime.CODEX:
        return CODEX_TARGETS
    return ALL_TARGETS


def _runtimes_of(runtime: Runtime) -> tuple[Runtime, ...]:
    """Return the concrete runtimes a selector expands to (``BOTH`` fans out, others pass through)."""
    return (Runtime.CLAUDE, Runtime.CODEX) if runtime == Runtime.BOTH else (runtime,)


def resolve_targets(runtime: Runtime | str, consumers: Sequence[str] | None) -> list[ConsumerTarget]:
    """Return the closed-set targets selected by *runtime*, filtered by optional *consumers*.

    Args:
        runtime: A :class:`Runtime` member, or its plain value from the CLI.
        consumers: Explicit consumer-name subset, or ``None`` for every target in *runtime*.

    Returns:
        Targets in *consumers* order when given, else the registry's declared order.

    Raises:
        IntegrationError: an entry in *consumers* is outside the closed set for *runtime*
            (``unknown_target``, exit ``2`` — this is never a discovery registry).

    Examples:
        >>> [t.consumer for t in resolve_targets("codex", None)]
        ['codex-rig']
        >>> [t.consumer for t in resolve_targets("claude", ["oss"])]
        ['oss']
    """
    runtime = Runtime(runtime)
    pool = _targets_for_runtime(runtime)
    if consumers is None:
        return list(pool)
    by_name = {t.consumer: t for t in pool}
    unknown = [name for name in consumers if name not in by_name]
    if unknown:
        raise IntegrationError(
            "unknown_target",
            f"not in the closed target set for runtime={runtime.value!r}: {unknown}",
            exit_code=_EXIT_USAGE,
            detail={"unknown": unknown, "runtime": runtime.value},
        )
    return [by_name[name] for name in consumers]


def _find_target(runtime: Runtime | str, consumer: str) -> ConsumerTarget:
    """Return the registered :class:`ConsumerTarget` for *runtime*/*consumer*, or refuse it."""
    for target in ALL_TARGETS:
        if target.runtime == runtime and target.consumer == consumer:
            return target
    raise IntegrationError(
        "unknown_target", f"{consumer!r} ({runtime}) is not in the closed target set", exit_code=_EXIT_USAGE
    )


# --------------------------------------------------------------------------------------
# Small pure helpers — hashing, canonical JSON, timestamps, report directory.
# --------------------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str | None:
    """Return the sha256 of *path*, or ``None`` when it is absent (first-install case)."""
    if not path.is_file() or path.is_symlink():
        return None
    return _sha256_bytes(path.read_bytes())


def _canonical_json(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_plan_sha256(plan: dict) -> str:
    """Return the plan's binding SHA-256, computed over every field except the digest itself.

    Examples:
        >>> p = {"a": 1, "plan_sha256": "stale"}
        >>> compute_plan_sha256(p) == compute_plan_sha256({"a": 1})
        True
    """
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    return _sha256_bytes(_canonical_json(body))


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())


def _report_dir(root: Path) -> Path:
    """Return (and create) a fresh task-specific integration report directory.

    Never inside a plugin cache (plan §8.3: "journal and before-images ... never written
    inside a plugin cache").
    """
    path = root / ".reports" / "integrate" / _utc_stamp()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_file(path: Path) -> dict | None:
    """Return the JSON object at *path*, or ``None`` if absent, symlinked, or unparsable."""
    if path.is_symlink() or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _manifest_for(target: ConsumerTarget, root: Path) -> dict | None:
    """Return *target*'s own plugin manifest (``.claude-plugin`` or ``.codex-plugin``)."""
    dirname = ".claude-plugin" if target.runtime == "claude" else ".codex-plugin"
    return _read_json_file(root / target.plugin_dir / dirname / "plugin.json")


# --------------------------------------------------------------------------------------
# Native command execution — Windows-safe argv quoting (plan §8.3 "win_quoting").
# --------------------------------------------------------------------------------------


def _unsafe_windows_batch_argv(executable: str, arguments: Sequence[str]) -> bool:
    """Return True when *arguments* could smuggle shell syntax into a Windows ``.bat``/``.cmd``."""
    if any(character in '\r\n"%!' for character in executable):
        return True
    return any(
        not argument or any(ch.isspace() or ch in _WINDOWS_BATCH_METACHARACTERS for ch in argument)
        for argument in arguments
    )


def _resolve_native_command(command: Sequence[str], *, windows: bool) -> tuple[list[str] | str, bool]:
    """Resolve one argv to its executable; return a batch-safe shell line on Windows when needed.

    Examples:
        >>> _resolve_native_command(["definitely-not-a-real-binary-xyz"], windows=False)
        Traceback (most recent call last):
            ...
        codemap_py.integration.IntegrationError: command unavailable: definitely-not-a-real-binary-xyz
    """
    executable = shutil.which(command[0])
    if executable is None:
        raise IntegrationError(
            "native_command_missing", f"command unavailable: {command[0]}", detail={"argv": list(command)}
        )
    resolved = [executable, *command[1:]]
    if windows and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        if _unsafe_windows_batch_argv(executable, command[1:]):
            raise IntegrationError(
                "unsafe_windows_argv", "argv is unsafe for a Windows batch launcher", detail={"argv": list(command)}
            )
        line = f'"{executable}"'
        if command[1:]:
            line = f"{line} {' '.join(command[1:])}"
        return line, True
    return resolved, False


def _run_native(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run one resolved native command (argv-only; Windows batch launchers quoted safely)."""
    resolved, shell = _resolve_native_command(argv, windows=os.name == "nt")
    try:
        return subprocess.run(
            resolved,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_NATIVE_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise IntegrationError(
            "native_command_failed", f"{argv[0]} failed to start: {exc}", detail={"argv": list(argv)}
        ) from exc


def _run_native_required(argv: Sequence[str]) -> None:
    """Run one native command; raise a bounded :class:`IntegrationError` on non-zero exit."""
    completed = _run_native(argv)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "command failed").strip()[:512]
        raise IntegrationError(
            "native_command_failed",
            f"{argv[0]} failed ({completed.returncode}): {detail}",
            detail={"argv": list(argv)},
        )


def _native_json_probe(argv: Sequence[str]) -> object | None:
    """Best-effort JSON probe: ``None`` on any failure — absence is a valid, non-fatal state."""
    try:
        resolved, shell = _resolve_native_command(argv, windows=os.name == "nt")
    except IntegrationError:
        return None
    try:
        completed = subprocess.run(
            resolved,
            shell=shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_NATIVE_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    if len(completed.stdout.encode("utf-8")) > _MAX_JSON_BYTES:
        return None
    try:
        return json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError):
        return None


def _claude_installed_version(consumer: str, installed: object) -> str | None:
    """Return *consumer*'s enabled version from a ``claude plugin list --json`` payload."""
    if not isinstance(installed, list):
        return None
    prefix = f"{consumer}@"
    matches = [
        item["version"]
        for item in installed
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"].startswith(prefix)
        and item.get("enabled") is True
        and isinstance(item.get("version"), str)
    ]
    return matches[0] if len(matches) == 1 else None


def _codex_installed_version(consumer: str, payload: object) -> str | None:
    """Return *consumer*'s enabled version from a ``codex plugin list --json`` payload."""
    installed = payload.get("installed") if isinstance(payload, dict) else None
    if not isinstance(installed, list):
        return None
    matches = [
        item["version"]
        for item in installed
        if isinstance(item, dict)
        and item.get("name") == consumer
        and item.get("enabled") is True
        and isinstance(item.get("version"), str)
    ]
    return matches[0] if len(matches) == 1 else None


def _installed_version_lookup(runtime: Runtime | str) -> Callable[[str, object], str | None]:
    return _claude_installed_version if runtime == Runtime.CLAUDE else _codex_installed_version


def _marketplace_entry(runtime: Runtime | str) -> dict | None:
    """Return the configured ``borda-ai-rig`` marketplace entry for *runtime*, or ``None``."""
    if runtime == Runtime.CLAUDE:
        payload = _native_json_probe(["claude", "plugin", "marketplace", "list", "--json"])
        entries = payload if isinstance(payload, list) else None
    else:
        payload = _native_json_probe(["codex", "plugin", "marketplace", "list", "--json"])
        entries = payload.get("marketplaces") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return None
    matches = [e for e in entries if isinstance(e, dict) and e.get("name") == MARKETPLACE_NAME]
    return matches[0] if len(matches) == 1 else None


# --------------------------------------------------------------------------------------
# Codex-Rig global-instructions status — read-only bytes, never an import (plan §8.5).
# --------------------------------------------------------------------------------------


def _codex_home(environ: Mapping[str, str]) -> Path:
    configured = environ.get("CODEX_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".codex"


def codex_rig_global_status(environ: Mapping[str, str] | None = None) -> str:
    """Return ``absent`` | ``present`` | ``authenticated`` for ``${CODEX_HOME}/AGENTS.md``.

    Read-only inspection of Codex Rig's own authenticated-marker byte format; never invokes
    ``install_global_agents.py`` and never writes the file. ``stale`` is reportable only
    through a versioned, Codex-Rig-owned read-only status contract — which does not exist yet
    — so staleness is always ``unavailable`` to callers of this function, never guessed from
    these bytes alone (plan §8.3).

    Args:
        environ: Environment mapping to resolve ``CODEX_HOME`` from (defaults to
            :data:`os.environ`).

    Examples:
        >>> codex_rig_global_status({"CODEX_HOME": "/nonexistent-codemap-py-doctest-home"})
        'absent'
    """
    target = _codex_home(environ if environ is not None else os.environ) / "AGENTS.md"
    if not target.is_file() or target.is_symlink():
        return "absent"
    try:
        content = target.read_bytes()
    except OSError:
        return "absent"
    match = _CODEX_RIG_AGENTS_BEGIN_RE.search(content)
    if match is None:
        return "absent"
    end_index = content.find(_CODEX_RIG_AGENTS_END, match.end())
    if end_index == -1:
        return "present"
    body = content[match.end() : end_index]
    return "authenticated" if _sha256_bytes(body) == match.group(1).decode("ascii") else "present"


# --------------------------------------------------------------------------------------
# Managed-block scheme for `apply`'s source_write targets.
# --------------------------------------------------------------------------------------


def _render_managed_block(body: str) -> str:
    """Wrap *body* in an authenticated, version-stamped, sha256-stamped managed block.

    Canonical shape (plan §8.3 apply contract, in-file managed-block model):
    ``<!-- codemap-py:integration:begin v<schema> sha256=<64hex> -->`` ... enclosed body ...
    ``<!-- codemap-py:integration:end -->``.

    Examples:
        >>> block = _render_managed_block("hello\\n")
        >>> _managed_block_status(block)
        'authenticated'
    """
    digest = _sha256_bytes(body.encode("utf-8"))
    return f"<!-- codemap-py:integration:begin v{BLOCK_SCHEMA_VERSION} sha256={digest} -->\n{body}{_MANAGED_END}"


def _managed_block_status(content: str) -> str:
    """Return ``absent`` | ``authenticated`` | ``foreign_or_modified`` for enclosing-file *content*.

    Structural, tamper-evident check on whatever managed block currently exists in *content* —
    independent of any plan's before/after-state bookkeeping (see :func:`_classify_mutation`
    for the drift/idempotency layer built on top of this).

    Examples:
        >>> _managed_block_status("")
        'absent'
        >>> _managed_block_status("not a managed block")
        'absent'
    """
    matches = list(_MANAGED_BEGIN_RE.finditer(content))
    if not matches:
        return "absent"
    if len(matches) > 1 or content.count(_MANAGED_END) != 1:
        return "foreign_or_modified"
    match = matches[0]
    end_index = content.find(_MANAGED_END, match.end())
    if end_index == -1:
        return "foreign_or_modified"
    body = content[match.end() : end_index]
    return "authenticated" if _sha256_bytes(body.encode("utf-8")) == match.group(2) else "foreign_or_modified"


def _managed_block_body(runtime: str, consumer: str, version: str | None) -> str:
    """Return the contract-bound managed body for one provider/consumer wiring."""
    return (
        f"Provider: {PROVIDER_NAME} {__version__}\n"
        f"Runtime: {runtime}\n"
        f"Consumer: {consumer} {version or 'unknown'}\n"
        f"Protocol: {PROTOCOL_VERSION}\n"
        "Contract: shared/integration-contract.md\n"
        f"Updated: {_utc_now_iso()}\n"
    )


def _replace_managed_region(content: str, new_block: str) -> str:
    """Swap only the sentinel-bounded region in *content* for *new_block*; preserve the rest.

    Examples:
        >>> old = "before\\n" + _render_managed_block("ALPHA\\n") + "after\\n"
        >>> new = _replace_managed_region(old, _render_managed_block("BETA\\n"))
        >>> new.startswith("before\\n") and new.endswith("after\\n") and "BETA" in new and "ALPHA" not in new
        True
    """
    match = _MANAGED_BEGIN_RE.search(content)
    if match is None:
        return content  # caller already gated "replace" on sentinel presence; unreachable in practice
    end_index = content.find(_MANAGED_END, match.end())
    if end_index == -1:
        return content
    region_end = end_index + len(_MANAGED_END)
    return content[: match.start()] + new_block + content[region_end:]


def _mutate_content(original_text: str, new_block: str, action: str) -> str:
    """Return *original_text* with *new_block* either inserted (new file/EOF-appended) or swapped in.

    ``"insert"`` appends at EOF preceded by one blank line (or writes just the block for an
    absent/empty file); ``"replace"`` swaps only the existing sentinel-bounded region, leaving
    everything outside it byte-for-byte unchanged.

    Examples:
        >>> _mutate_content("", "BLOCK\\n", "insert")
        'BLOCK\\n'
        >>> _mutate_content("existing\\n", "BLOCK\\n", "insert")
        'existing\\n\\nBLOCK\\n'
    """
    if action == "insert":
        if not original_text:
            return new_block
        body = original_text if original_text.endswith("\n") else original_text + "\n"
        return f"{body}\n{new_block}"
    return _replace_managed_region(original_text, new_block)


# --------------------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------------------


def _consumer_check(target: ConsumerTarget, root: Path, installed: object) -> dict:
    manifest = _manifest_for(target, root)
    lookup = _installed_version_lookup(target.runtime)
    return {
        "manifest_present": manifest is not None,
        "name_matches": isinstance(manifest, dict) and manifest.get("name") == target.consumer,
        "source_version": manifest.get("version") if isinstance(manifest, dict) else None,
        "installed_version": lookup(target.consumer, installed),
    }


def _runtime_check(targets: tuple[ConsumerTarget, ...], root: Path, runtime: Runtime) -> dict:
    cli = _cli_for(runtime)
    installed = _native_json_probe([cli, "plugin", "list", "--json"])
    provider_target = ConsumerTarget(runtime, PROVIDER_NAME, PROVIDER_DIR)
    consumers = {t.consumer: _consumer_check(t, root, installed) for t in targets}
    return {
        "available": installed is not None,
        "provider": _consumer_check(provider_target, root, installed),
        "consumers": consumers,
    }


def build_check_report(runtime: Runtime | str, plugin_root: Path) -> dict:
    """Assemble the non-mutating ``check`` report (plan §8.3 "check" contract).

    Args:
        runtime: A :class:`Runtime` member, or its plain value from the CLI.
        plugin_root: codemap-py's own resolved plugin root.

    Examples:
        >>> report = build_check_report("both", Path("/nonexistent-plugin-root"))
        >>> report["protocol"]
        'codemap-py.integration.v1'
        >>> sorted(report["runtime_log_isolation"])
        ['claude', 'codex', 'direct']
    """
    runtime = Runtime(runtime)
    root = index_paths.canonical_root()
    identity = index_paths.resolve_index(root=root)
    return {
        "protocol": PROTOCOL_VERSION,
        "provider": {"name": PROVIDER_NAME, "version": __version__, "root": str(plugin_root)},
        "shared_index": {
            "project": identity.project,
            "root": str(identity.root),
            "root_key": identity.root_key,
            "index_path": str(identity.index_path),
            "override": identity.override,
        },
        "runtime_log_isolation": {
            name: str(runtime_log.log_dir_for(name, root=root)) for name in runtime_log.RUNTIME_ALLOWLIST
        },
        "claude": _runtime_check(CLAUDE_TARGETS, root, Runtime.CLAUDE) if runtime in _CLAUDE_SELECTORS else None,
        "codex": _runtime_check(CODEX_TARGETS, root, Runtime.CODEX) if runtime in _CODEX_SELECTORS else None,
        "codex_rig_global_instructions": codex_rig_global_status() if runtime in _CODEX_SELECTORS else None,
    }


def _print_check_text(report: dict) -> None:
    print(f"protocol: {report['protocol']}")
    print(f"provider: {report['provider']['name']} {report['provider']['version']}")
    print(f"shared_index: {report['shared_index']['index_path']}")
    for runtime_name in (Runtime.CLAUDE.value, Runtime.CODEX.value):
        block = report.get(runtime_name)
        if block is None:
            continue
        print(f"{runtime_name}: available={block['available']}")
        for name, status in sorted(block["consumers"].items()):
            print(
                f"  {name}: source={status['source_version']} installed={status['installed_version']} "
                f"name_matches={status['name_matches']}"
            )
    if report.get("codex_rig_global_instructions") is not None:
        print(f"codex_rig_global_instructions: {report['codex_rig_global_instructions']}")


def cmd_check(ns: argparse.Namespace, plugin_root: Path) -> int:
    """Run ``integrate check``; return exit ``0`` (report always succeeds — probes are best-effort)."""
    report = build_check_report(ns.runtime, plugin_root)
    if ns.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_check_text(report)
    return _EXIT_OK


# --------------------------------------------------------------------------------------
# plan
# --------------------------------------------------------------------------------------


def _source_write_op(index: int, target: ConsumerTarget, root: Path) -> dict:
    """Build one in-file managed-block ``source_write`` op for *target*.

    The target file is an allowlisted, existing-or-creatable path from
    :data:`CONSUMER_MANAGED_FILE`. Whether this op inserts
    (no sentinel present, including an absent file) or replaces (sentinel already present) is
    decided here, at plan time, from the file's current content — :func:`_classify_mutation`
    re-derives the same decision at apply time and refuses on any disagreement (drift).
    """
    rel_path = f"{target.plugin_dir}/{CONSUMER_MANAGED_FILE[target.consumer]}"
    abs_path = root / rel_path
    before_hash = _sha256_file(abs_path)
    original_text = abs_path.read_text(encoding="utf-8") if abs_path.is_file() else ""
    first_time = _managed_block_status(original_text) == "absent"
    manifest = _manifest_for(target, root)
    version = manifest.get("version") if isinstance(manifest, dict) else None
    new_block = _render_managed_block(_managed_block_body(target.runtime, target.consumer, version))
    mutated = _mutate_content(original_text, new_block, "insert" if first_time else "replace")
    return {
        "index": index,
        "kind": "source_write",
        "runtime": target.runtime,
        "consumer": target.consumer,
        "path": rel_path,
        "first_time": first_time,
        "before_hash": before_hash,
        "desired": {"version": version, "ref": None, "pkg_hash": None},
        "new_block": new_block,
        "argv": [],
        "rollback": {"kind": "restore_file", "identity": before_hash or "absent"},
        "expected_post_state": {"hash": _sha256_bytes(mutated.encode("utf-8"))},
    }


def _marketplace_source(source: Source, root: Path) -> str:
    """Return the marketplace ``add`` source string for *source* (plan §8.3 two source modes)."""
    return str(root) if source == Source.LOCAL_CANDIDATE else MARKETPLACE_REMOTE


def _marketplace_sync_op(index: int, runtime: Runtime, source: Source, root: Path) -> dict:
    entry = _marketplace_entry(runtime)
    cli = _cli_for(runtime)
    if entry is None:
        argv = [cli, "plugin", "marketplace", "add", _marketplace_source(source, root)]
    else:
        refresh_verb = "update" if runtime == Runtime.CLAUDE else "upgrade"
        argv = [cli, "plugin", "marketplace", refresh_verb, MARKETPLACE_NAME]
    return {
        "index": index,
        "kind": "runtime_sync",
        "role": "marketplace",
        "runtime": runtime.value,
        "consumer": None,
        "before_hash": None,
        "desired": {"version": None, "ref": source.value, "pkg_hash": None},
        "argv": [argv],
        "rollback": {"kind": "none", "identity": "marketplace refresh is not rolled back independently"},
        "expected_post_state": {"registered": True},
    }


def _plugin_sync_op(index: int, runtime: Runtime, name: str, installed_state: object) -> dict:
    cli = _cli_for(runtime)
    current_version = _installed_version_lookup(runtime)(name, installed_state)
    if runtime == Runtime.CLAUDE:
        argv = (
            [cli, "plugin", "update", name]
            if current_version is not None
            else [cli, "plugin", "install", f"{name}@{MARKETPLACE_NAME}", "--scope", "user"]
        )
    else:
        # No `codex plugin update` verb is assumed unless a tested CLI actually exposes one
        # (plan §8.3); `add` is idempotent add-or-refresh for the currently probed codex-cli.
        argv = [cli, "plugin", "add", f"{name}@{MARKETPLACE_NAME}"]
    rollback = (
        {"kind": "reinstall_previous", "identity": current_version}
        if current_version is not None
        else {"kind": "remove_first_install", "identity": "absent"}
    )
    return {
        "index": index,
        "kind": "runtime_sync",
        "role": "plugin",
        "runtime": runtime.value,
        "consumer": name,
        "before_hash": current_version,
        "desired": {"version": None, "ref": None, "pkg_hash": None},
        "argv": [argv],
        "rollback": rollback,
        "expected_post_state": {"installed": True},
    }


def _runtime_sync_ops(
    start_index: int, runtime: Runtime, source: Source, targets: Sequence[ConsumerTarget], root: Path
) -> list[dict]:
    """Return ops for one runtime: one marketplace refresh, then provider-then-consumer installs."""
    ops = [_marketplace_sync_op(start_index, runtime, source, root)]
    cli = _cli_for(runtime)
    installed_state = _native_json_probe([cli, "plugin", "list", "--json"])
    names = [PROVIDER_NAME, *(t.consumer for t in targets)]
    ops.extend(_plugin_sync_op(start_index + 1 + i, runtime, name, installed_state) for i, name in enumerate(names))
    return ops


def build_plan(
    runtime: Runtime | str, consumers: Sequence[str] | None, source: Source | str | None, plugin_root: Path
) -> dict:
    """Build the unsigned integration plan for *runtime* (plan §8.3 "plan" contract).

    When *source* is given, the plan also carries ``runtime_sync`` ops (native plugin-manager
    argv, provider-then-consumer order per runtime); omitting it produces a source-only plan
    consumable only by ``apply``, never ``sync``.

    Args:
        runtime: A :class:`Runtime` member, or its plain value from the CLI.
        consumers: Explicit consumer-name subset, or ``None`` for every target in *runtime*.
        source: A :class:`Source` member, its plain value, or ``None`` for a source-only plan.
        plugin_root: codemap-py's own resolved plugin root (recorded, not mutated).

    Raises:
        IntegrationError: an entry in *consumers* is outside the closed target set (exit ``2``).
    """
    runtime = Runtime(runtime)
    source = Source(source) if source is not None else None
    root = index_paths.canonical_root()
    targets = resolve_targets(runtime, consumers)
    ops: list[dict] = [_source_write_op(i, target, root) for i, target in enumerate(targets)]
    if source is not None:
        for one_runtime in _runtimes_of(runtime):
            selected = [t for t in targets if t.runtime == one_runtime]
            ops.extend(_runtime_sync_ops(len(ops), one_runtime, source, selected, root))
    plan = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_VERSION,
        "op_id": uuid.uuid4().hex,
        "created_at": _utc_now_iso(),
        "runtime": runtime.value,
        "consumers": [t.consumer for t in targets],
        "source": source.value if source is not None else None,
        "provider": {"name": PROVIDER_NAME, "version": __version__, "root": str(plugin_root)},
        "ops": ops,
    }
    plan["plan_sha256"] = compute_plan_sha256(plan)
    return plan


def cmd_plan(ns: argparse.Namespace, plugin_root: Path) -> int:
    """Run ``integrate plan``; write the artifact and print its path + SHA-256."""
    plan = build_plan(ns.runtime, ns.consumers, ns.source, plugin_root)
    root = index_paths.canonical_root()
    out_path = Path(ns.out).expanduser() if ns.out else _report_dir(root) / "plan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"plan": str(out_path), "plan_sha256": plan["plan_sha256"], "ops": len(plan["ops"])}, indent=2))
    return _EXIT_OK


# --------------------------------------------------------------------------------------
# Journal — append-only per-run record + before-images (plan §8.3 state machine).
# --------------------------------------------------------------------------------------


class Journal:
    """Append-only per-run journal and before-image store.

    Lives under a task-specific ``.reports/integrate/<ts>/`` directory — never inside a
    plugin cache — and is the durable record consulted when a mutation stops partway
    (state ``recovery-required``).
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self._path = directory / "journal.jsonl"

    def record(self, state: str, *, index: int | None = None, detail: dict | None = None) -> None:
        """Append one journal entry (``planned``/``approved``/``applying``/.../``complete``)."""
        entry = {"ts": _utc_now_iso(), "state": state, "index": index, "detail": detail or {}}
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, separators=(",", ":")) + "\n")

    def save_before_image(self, index: int, data: bytes) -> Path:
        """Persist *data* as the pre-mutation image for op *index*; return its path."""
        before_dir = self.directory / "before"
        before_dir.mkdir(parents=True, exist_ok=True)
        path = before_dir / f"{index}.bak"
        path.write_bytes(data)
        return path


def load_plan(path: Path) -> dict:
    """Load and structurally validate a saved plan artifact.

    Raises:
        IntegrationError: the file is missing, unreadable, or missing required keys (exit ``1``).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IntegrationError("plan_unreadable", f"cannot read plan artifact: {exc}") from exc
    required = {"schema_version", "op_id", "ops", "plan_sha256"}
    if not isinstance(data, dict) or not required.issubset(data):
        raise IntegrationError("plan_malformed", "plan artifact is missing required fields")
    return data


def verify_approval(plan: dict, approve: str) -> None:
    """Bind ``--approve`` to the plan's own recomputed SHA-256.

    Raises:
        ApprovalError: *approve* is not 64 lowercase hex characters, or does not match the
            plan's recomputed digest (exit ``2``).
    """
    if not _SHA256_RE.match(approve):
        raise ApprovalError("approve_malformed", "--approve must be a 64-hex sha256")
    if compute_plan_sha256(plan) != approve:
        raise ApprovalError("approve_mismatch", "--approve does not match this plan's SHA-256")


# --------------------------------------------------------------------------------------
# apply — source_write ops only (refusal matrix, plan §8.3 "apply" contract).
# --------------------------------------------------------------------------------------


def _is_contained(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _is_installed_cache_path(path: Path) -> bool:
    """Return True when *path* resolves under any ``.../plugins/cache/...`` tree."""
    parts = path.parts
    return any(parts[i] == "plugins" and parts[i + 1] == "cache" for i in range(len(parts) - 1))


def _git_dirty(root: Path, rel_path: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", rel_path],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_GIT_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return bool(result.stdout.strip())


def _refuse_if(condition: bool, code: str, message: str) -> None:
    if condition:
        raise RefusalError(code, message)


def _refuse_unverified_identity(target: ConsumerTarget, root: Path) -> None:
    manifest = _manifest_for(target, root)
    _refuse_if(
        not isinstance(manifest, dict) or manifest.get("name") != target.consumer,
        "unverified_product_identity",
        "consumer manifest name does not match the plan's target",
    )


def _classify_mutation(op: dict, target_path: Path) -> str:
    """Decide ``"insert"`` | ``"replace"`` | ``"noop"`` for one op's enclosing file, right now.

    Runs the structural foreign/modified check on whatever managed block currently exists
    (independent of the plan's own bookkeeping), then layers idempotency and drift on top:
    a file already matching the plan's ``expected_post_state`` hash is a safe no-op re-apply,
    not drift; anything matching neither the plan's ``before_hash`` nor its post-state hash is
    drift, as is a first_time/update expectation that no longer matches reality.

    Raises:
        RefusalError: ``foreign_or_modified_marker`` or ``drift``.
    """
    current_bytes = target_path.read_bytes() if target_path.is_file() else None
    current_text = current_bytes.decode("utf-8") if current_bytes is not None else ""
    status = _managed_block_status(current_text)
    _refuse_if(
        status == "foreign_or_modified", "foreign_or_modified_marker", "existing managed block failed integrity check"
    )
    current_hash = _sha256_bytes(current_bytes) if current_bytes is not None else None
    if current_hash == op["expected_post_state"]["hash"]:
        return "noop"
    _refuse_if(
        current_hash != op["before_hash"], "drift", "target changed since the plan was made; approval invalidated"
    )
    action = "insert" if op["first_time"] else "replace"
    _refuse_if(
        action == "replace" and status == "absent",
        "drift",
        "expected an existing managed block; sentinel is now missing",
    )
    _refuse_if(action == "insert" and status != "absent", "drift", "expected no managed block yet; one now exists")
    return action


def _validate_source_write(op: dict, root: Path) -> tuple[Path, str]:
    """Revalidate one ``source_write`` op immediately before mutating.

    Returns:
        ``(resolved_path, action)`` — *action* is ``"insert"``, ``"replace"``, or ``"noop"``
        (see :func:`_classify_mutation`).

    Raises:
        RefusalError: path escape, symlink, installed-cache root, dirty overlap, unverified
            product identity, a foreign/modified existing managed block, or drift.
    """
    target = _find_target(op["runtime"], op["consumer"])
    plugin_dir = (root / target.plugin_dir).resolve()
    target_path = (root / op["path"]).resolve()
    _refuse_if(_is_installed_cache_path(target_path), "installed_cache_root", "target resolves under a plugin cache")
    _refuse_if(not _is_contained(target_path, plugin_dir), "path_escape", "target escapes its consumer directory")
    _refuse_if(
        (root / op["path"]).is_symlink() or plugin_dir.is_symlink(), "symlink_target", "target path traverses a symlink"
    )
    _refuse_if(_git_dirty(root, op["path"]), "dirty_overlap", "target has uncommitted changes; refusing to overlay")
    _refuse_unverified_identity(target, root)
    return target_path, _classify_mutation(op, target_path)


def _atomic_write(path: Path, content: str | bytes) -> None:
    # Write raw bytes in binary mode: the managed block is self-authenticating (its embedded
    # sha256 stamps its exact body), so the on-disk bytes must equal ``content`` UTF-8-encoded
    # with LF line endings on every OS. Text mode translates ``\n`` to ``\r\n`` on Windows,
    # which would break the post-write hash check and corrupt the marker's integrity stamp.
    data = content if isinstance(content, bytes) else content.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _apply_one(op: dict, root: Path, journal: Journal) -> None:
    target_path, action = _validate_source_write(op, root)
    journal.record("applying", index=op["index"])
    if action == "noop":
        journal.record("verified", index=op["index"], detail={"noop": True})
        return
    original_text = ""
    if target_path.is_file():
        original_bytes = target_path.read_bytes()
        journal.save_before_image(op["index"], original_bytes)
        original_text = original_bytes.decode("utf-8")
    _atomic_write(target_path, _mutate_content(original_text, op["new_block"], action))
    actual_hash = _sha256_file(target_path)
    if actual_hash != op["expected_post_state"]["hash"]:
        raise IntegrationError("post_state_mismatch", "write completed but the post-write hash does not match the plan")
    journal.record("verified", index=op["index"])


def _rollback_source_writes(applied: list[dict], root: Path, journal: Journal) -> str:
    ok = True
    for op in reversed(applied):
        before_path = journal.directory / "before" / f"{op['index']}.bak"
        target_path = root / op["path"]
        try:
            if before_path.is_file():
                _atomic_write(target_path, before_path.read_bytes())
            else:
                target_path.unlink(missing_ok=True)
            if _sha256_file(target_path) != op["before_hash"]:
                ok = False
        except OSError:
            ok = False
    return "rollback-succeeded" if ok else "rollback-failed"


def _recovery_commands_source(applied: list[dict], journal: Journal) -> list[str]:
    commands = []
    for op in applied:
        before = journal.directory / "before" / f"{op['index']}.bak"
        commands.append(f"cp {before} {op['path']}")
    return commands


def _handle_apply_failure(op: dict, applied: list[dict], root: Path, journal: Journal, exc: IntegrationError) -> None:
    """Stop, roll back any already-applied targets, and re-raise a bounded error. Never returns."""
    journal.record("stopped", index=op["index"], detail={"code": exc.code, "message": str(exc)})
    if not applied:
        raise exc
    journal.record("rollback-started")
    state = _rollback_source_writes(applied, root, journal)
    journal.record(state)
    detail = {
        "state": state,
        "failed_index": op["index"],
        "applied": [a["index"] for a in applied],
        "journal": str(journal.directory),
    }
    if state == "rollback-failed":
        detail["recovery_commands"] = _recovery_commands_source(applied, journal)
        raise IntegrationError("recovery_required", "rollback failed; manual recovery required", detail=detail)
    raise IntegrationError(exc.code, f"{exc}; rolled back {len(applied)} prior target(s)", detail=detail)


def apply_plan(plan: dict, approve: str, plugin_root: Path, journal_dir: Path | None = None) -> dict:
    """Execute every ``source_write`` op in *plan* (plan §8.3 "apply" contract).

    Args:
        plan: A plan artifact as returned by :func:`load_plan` / :func:`build_plan`.
        approve: The plan's own SHA-256, as shown to the user.
        plugin_root: codemap-py's own resolved plugin root (unused by mutation, kept for
            call-site symmetry with the other ``cmd_*`` entry points).
        journal_dir: Explicit journal directory (tests only); defaults to a fresh
            ``.reports/integrate/<ts>/``.

    Returns:
        ``{"state": "complete", "applied": [...], "journal": "..."}`` on success.

    Raises:
        ApprovalError: bad or mismatched ``--approve`` (exit ``2``).
        IntegrationError: any refusal, drift, or unrecoverable failure (exit ``1``).
    """
    del plugin_root  # kept for signature symmetry with cmd_sync/cmd_demo; mutation is source-relative
    verify_approval(plan, approve)
    root = index_paths.canonical_root()
    ops = [op for op in plan["ops"] if op["kind"] == "source_write"]
    journal = Journal(journal_dir or _report_dir(root))
    journal.record("approved", detail={"op_id": plan["op_id"]})
    applied: list[dict] = []
    for op in ops:
        try:
            _apply_one(op, root, journal)
        except IntegrationError as exc:
            _handle_apply_failure(op, applied, root, journal, exc)
        applied.append(op)
    journal.record("complete")
    return {"state": "complete", "applied": [op["index"] for op in applied], "journal": str(journal.directory)}


def cmd_apply(ns: argparse.Namespace, plugin_root: Path) -> int:
    """Run ``integrate apply``; return exit ``0`` (failures raise and are caught by :func:`run`)."""
    plan = load_plan(Path(ns.plan).expanduser())
    result = apply_plan(plan, ns.approve, plugin_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return _EXIT_OK


# --------------------------------------------------------------------------------------
# sync — runtime_sync ops only; native CLI only, never consumer source (plan §8.3 "sync").
# --------------------------------------------------------------------------------------


def _validate_runtime_sync(op: dict) -> None:
    """Revalidate one ``runtime_sync`` op's before-state immediately before executing it."""
    if op["role"] == "marketplace":
        return  # a marketplace refresh has no single before-hash worth redrift-checking
    cli = _cli_for(op["runtime"])
    installed_state = _native_json_probe([cli, "plugin", "list", "--json"])
    current = _installed_version_lookup(op["runtime"])(op["consumer"], installed_state)
    _refuse_if(current != op["before_hash"], "drift", "installed state changed since the plan was made")


def _verify_plugin_installed(op: dict) -> None:
    cli = _cli_for(op["runtime"])
    installed_state = _native_json_probe([cli, "plugin", "list", "--json"])
    if _installed_version_lookup(op["runtime"])(op["consumer"], installed_state) is None:
        raise IntegrationError("post_state_mismatch", f"{op['consumer']} is not enabled after sync")


def _sync_one(op: dict, journal: Journal) -> None:
    _validate_runtime_sync(op)
    journal.record("applying", index=op["index"])
    for argv in op["argv"]:
        _run_native_required(argv)
    if op["role"] == "plugin":
        _verify_plugin_installed(op)
    journal.record("verified", index=op["index"])


def _rollback_runtime_sync(applied: list[dict], journal: Journal) -> str:
    del journal  # native rollback has no before-image to restore from; kept for signature symmetry
    ok = True
    for op in reversed(applied):
        if op["role"] != "plugin" or op["rollback"]["kind"] != "reinstall_previous":
            continue  # marketplace refreshes and first-installs are not reverted automatically
        cli = _cli_for(op["runtime"])
        verb = "install" if cli == "claude" else "add"
        argv = [cli, "plugin", verb, f"{op['consumer']}@{MARKETPLACE_NAME}"]
        try:
            completed = _run_native(argv)
            ok = ok and completed.returncode == 0
        except IntegrationError:
            ok = False
    return "rollback-succeeded" if ok else "rollback-failed"


def _recovery_commands_sync(applied: list[dict]) -> list[str]:
    return [
        f"manually verify/reinstall: {op['consumer'] or 'marketplace'} ({op['rollback']['kind']})" for op in applied
    ]


def _handle_sync_failure(op: dict, applied: list[dict], journal: Journal, exc: IntegrationError) -> None:
    """Stop, best-effort roll back already-synced targets, and re-raise. Never returns."""
    journal.record("stopped", index=op["index"], detail={"code": exc.code, "message": str(exc)})
    if not applied:
        raise exc
    journal.record("rollback-started")
    state = _rollback_runtime_sync(applied, journal)
    journal.record(state)
    detail = {
        "state": state,
        "failed_index": op["index"],
        "applied": [a["index"] for a in applied],
        "journal": str(journal.directory),
    }
    if state == "rollback-failed":
        detail["recovery_commands"] = _recovery_commands_sync(applied)
        raise IntegrationError("recovery_required", "rollback failed; manual recovery required", detail=detail)
    raise IntegrationError(exc.code, f"{exc}; rolled back {len(applied)} prior target(s)", detail=detail)


def sync_plan(plan: dict, approve: str, source: str, plugin_root: Path, journal_dir: Path | None = None) -> dict:
    """Execute every ``runtime_sync`` op in *plan* (plan §8.3 "sync" contract).

    Never mutates consumer source or global instructions — only the ordered native
    plugin-manager argv the plan already recorded.

    Args:
        plan: A plan artifact as returned by :func:`load_plan` / :func:`build_plan`.
        approve: The plan's own SHA-256, as shown to the user.
        source: ``"local-candidate"`` or ``"release"``; must match the plan's recorded source.
        plugin_root: codemap-py's own resolved plugin root (kept for call-site symmetry).
        journal_dir: Explicit journal directory (tests only).

    Raises:
        ApprovalError: bad ``--approve``, or *source* does not match the plan (exit ``2``).
        IntegrationError: any drift, native-command failure, or unrecoverable failure (exit ``1``).
    """
    del plugin_root
    verify_approval(plan, approve)
    if plan.get("source") != source:
        raise ApprovalError("source_mismatch", "--source does not match the plan's recorded source")
    root = index_paths.canonical_root()
    ops = [op for op in plan["ops"] if op["kind"] == "runtime_sync"]
    journal = Journal(journal_dir or _report_dir(root))
    journal.record("approved", detail={"op_id": plan["op_id"]})
    applied: list[dict] = []
    for op in ops:
        try:
            _sync_one(op, journal)
        except IntegrationError as exc:
            _handle_sync_failure(op, applied, journal, exc)
        applied.append(op)
    journal.record("complete")
    return {"state": "complete", "applied": [op["index"] for op in applied], "journal": str(journal.directory)}


def cmd_sync(ns: argparse.Namespace, plugin_root: Path) -> int:
    """Run ``integrate sync``; return exit ``0`` (failures raise and are caught by :func:`run`)."""
    plan = load_plan(Path(ns.plan).expanduser())
    result = sync_plan(plan, ns.approve, ns.source, plugin_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return _EXIT_OK


# --------------------------------------------------------------------------------------
# demo — disposable check + one representative structural-context query.
# --------------------------------------------------------------------------------------


def _demo_query(identity: index_paths.IndexIdentity) -> dict:
    if not identity.index_path.is_file():
        return {"ran": False, "reason": "no index built yet"}
    capture = StringIO()
    try:
        # No lease here: query.main takes its own read lease around the load
        # (codemap_py.query._load_index_leased). Wrapping it in a second one would
        # parse the whole index twice per demo and re-introduce the caller-side
        # leasing the gate's module docstring forbids.
        with contextlib.redirect_stdout(capture):
            query.main(["central", "--top", "3", "--root", str(identity.root)])
        return {"ran": True, "output": capture.getvalue()[:2048]}
    except (rwgate.IndexBusy, rwgate.CoordinationUnavailable) as exc:
        return {"ran": False, "reason": str(exc)}
    except SystemExit as exc:
        return {"ran": False, "reason": f"query exited with {exc.code}"}


def run_demo(runtime: Runtime | str, plugin_root: Path) -> dict:
    """Run ``check`` plus one representative structural-context query (plan §8.3 "demo").

    Disposable evidence only — writes its JSON result under a fresh
    ``.reports/integrate/<ts>/`` directory and never mutates plan/approval state.
    """
    root = index_paths.canonical_root()
    identity = index_paths.resolve_index(root=root)
    demo = {
        "protocol": PROTOCOL_VERSION,
        "check": build_check_report(runtime, plugin_root),
        "query_evidence": _demo_query(identity),
    }
    demo_dir = _report_dir(root)
    (demo_dir / "demo.json").write_text(json.dumps(demo, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    demo["report_path"] = str(demo_dir / "demo.json")
    return demo


def cmd_demo(ns: argparse.Namespace, plugin_root: Path) -> int:
    """Run ``integrate demo``; return ``0`` on a completed run, ``1`` when the query itself failed."""
    demo = run_demo(ns.runtime, plugin_root)
    print(json.dumps(demo, indent=2, sort_keys=True))
    if demo["query_evidence"]["ran"] is False and demo["query_evidence"]["reason"] != "no index built yet":
        return _EXIT_RUNTIME
    return _EXIT_OK


# --------------------------------------------------------------------------------------
# CLI boundary — argparse dispatch, exit codes per plan §7.5.
# --------------------------------------------------------------------------------------


def _add_runtime_flag(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--runtime", choices=[r.value for r in Runtime], default=Runtime.BOTH.value)


def _split_csv(value: str) -> list[str]:
    return [item for item in value.split(",") if item]


def _add_check_parser(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser("check")
    _add_runtime_flag(sub)
    sub.add_argument("--json", action="store_true")


def _add_plan_parser(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser("plan")
    _add_runtime_flag(sub)
    sub.add_argument("--consumers", type=_split_csv, default=None)
    sub.add_argument("--source", choices=[x.value for x in Source], default=None)
    sub.add_argument("--out", default=None)


def _add_apply_parser(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser("apply")
    sub.add_argument("--plan", required=True)
    sub.add_argument("--approve", required=True)


def _add_sync_parser(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser("sync")
    sub.add_argument("--source", choices=[x.value for x in Source], required=True)
    sub.add_argument("--plan", required=True)
    sub.add_argument("--approve", required=True)
    _add_runtime_flag(sub)


def _add_demo_parser(subparsers: argparse._SubParsersAction) -> None:
    sub = subparsers.add_parser("demo")
    _add_runtime_flag(sub)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codemap-py integrate", description="Manage codemap-py's cross-runtime integration state (plan §8.3)."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    _add_check_parser(subparsers)
    _add_plan_parser(subparsers)
    _add_apply_parser(subparsers)
    _add_sync_parser(subparsers)
    _add_demo_parser(subparsers)
    return parser


_COMMANDS: dict[str, Callable[[argparse.Namespace, Path], int]] = {
    "check": cmd_check,
    "plan": cmd_plan,
    "apply": cmd_apply,
    "sync": cmd_sync,
    "demo": cmd_demo,
}


def _emit_bounded_error(exc: IntegrationError) -> int:
    payload: dict[str, object] = {"error": exc.code, "detail": str(exc)}
    if exc.detail:
        payload["context"] = exc.detail
    sys.stderr.write(json.dumps(payload, sort_keys=True) + "\n")
    return exc.exit_code


def run(argv: Sequence[str], plugin_root: Path) -> int:
    """Dispatch ``codemap-py integrate <mode>`` (plan §8.3; exit codes per plan §7.5).

    Sole CLI boundary for the integration engine: argparse usage errors already exit ``2``
    with their own bounded stderr message; every other failure is caught here and turned
    into one bounded JSON stderr line — never a bare traceback.

    Args:
        argv: Arguments after ``integrate`` (e.g. ``["check", "--json"]``).
        plugin_root: codemap-py's own resolved plugin root, passed through unchanged from
            :func:`codemap_py.cli.main`.

    Returns:
        Process exit code: ``0`` success, ``1`` runtime/domain/refusal failure, ``2`` bad
        syntax or a failed/invalid approval.
    """
    try:
        namespace = _build_parser().parse_args(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else _EXIT_USAGE
    try:
        return _COMMANDS[namespace.mode](namespace, plugin_root)
    except IntegrationError as exc:
        return _emit_bounded_error(exc)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: bounded error, never a traceback
        return _emit_bounded_error(IntegrationError("internal_error", f"{type(exc).__name__}: {exc}"))


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[2:], Path(__file__).resolve().parents[2]))
