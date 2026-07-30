#!/usr/bin/env python3
"""Codex-only runner for the structural provider-parity benchmark.

``structural`` is the clearer name for the former `bench`/real-codebase category;
it is not a third benchmark type. The two model-driven categories are:

  structural — constrained questions from ``tasks-bench.json`` about symbols,
               callers, dependencies, debugging, and change impact
  agentic    — open-ended exploration tasks from ``tasks-agentic.json``

This runner is structural-only. It does not load the agentic suite. Codex
agentic support needs a separate runner after its evaluator and ground-truth
transport contract are defined.

## What this measures

The same locked structural task, target repository, prompt, evaluator, and
600-second wall-clock budget are used for three within-Codex arms. The
experiment asks whether Codemap availability reduces model input and elapsed
time without lowering task quality:

  A_plain    — Codemap absent; the locked index is inaccessible
  B_auto     — Codemap available; the model chooses whether to use it
  C_required — Codemap available and must be called at least once

The task series are identical to ``run-claude-structural.py``:

  SE — symbol extraction          FN — function call graph
  RV — review assistance          CQ — code quality
  BR — development blast radius   DG — debug from trace
  FT — feature scaffolding        RI — real issue
  DI — diff impact                GR — graph reasoning
  MB — module blast radius

This module owns only Codex-native process handling, isolated homes, permission
profiles, JSONL event normalization, and per-cell persistence. Task identity,
arm contracts, and scoring remain in ``provider_parity_contracts.py`` and the
shared Claude structural evaluator registry.

## Arms

Every arm receives the canonical task prompt unchanged plus a separately
fingerprinted arm envelope:

  A_plain
    Uses ``provider-parity-plain``. It has no Codemap plugin or writable path,
    and cannot read the locked index or copied authentication file.

  B_auto
    Uses ``provider-parity-codemap``. The Codemap plugin and locked index are
    available, but using them is optional.

  C_required
    Uses the same treatment profile as B. It must call
    ``$codemap-py:query-code`` at least once; compliance and correctness are
    recorded separately.

Both permission profiles extend ``:read-only``, disable network, and inherit no
shell environment. B/C may write only the index-local ``.index-rw`` coordination
directory. The model command cannot read the disposable home's ``auth.json``.

## Metrics

Each task × repetition × arm cell records:

  Headline inputs:
    provider, repetition, elapsed_s, input_tokens, cached_input_tokens, output_tokens,
    reasoning_output_tokens, quality_score, and correct

  Diagnostics:
    command_calls, Codemap calls/successes/errors, fallback calls, required-arm
    compliance, extraction failure, contamination, retry count, native item
    counts, raw Codex events, and provider error classification

The runner writes raw cells; it does not declare an advantage. The manifest
analysis compares paired log input-token ratios and quality deltas, then applies
failure, adoption, and compliance guardrails.

## What is NOT measured

  - Agentic exploration from ``tasks-agentic.json``
  - Index construction cost; the locked index is prepared before model timing
  - A general Codemap advantage from one smoke task
  - Cross-provider raw token equality or pooled Claude/Codex results

## Quick start

First run the no-model preflight. It validates the target/index identities,
permission profiles, authentication isolation, plugin isolation, and the
deterministic cell plan:

  python benchmarks/run-codex-structural.py \\
      --repo-path /path/to/pytorch-lightning \\
      --tasks-path benchmarks/suites/tasks-bench.json \\
      --index-path /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \\
      --marketplace-root . \\
      --auth-source /path/to/codex/auth.json \\
      --model gpt-5.6-luna \\
      --task-id FN-02 \\
      --dry-run

After manifest and spend approval, omit ``--dry-run`` and provide a new output
path. This invokes the model and creates the JSONL file exclusively:

  python benchmarks/run-codex-structural.py \\
      --repo-path /path/to/pytorch-lightning \\
      --tasks-path benchmarks/suites/tasks-bench.json \\
      --index-path /path/to/pytorch-lightning/.cache/codemap/pytorch-lightning.json \\
      --marketplace-root . \\
      --auth-source /path/to/codex/auth.json \\
      --model gpt-5.6-luna \\
      --task-id FN-02 \\
      --arm all \\
      --output-path benchmarks/results/codex-fn02-r6.jsonl

Use ``--arm A_plain``, ``--arm B_auto``, or ``--arm C_required`` for a single
arm. ``--arm all`` uses the manifest's deterministic arm ordering.
``--repetitions N`` executes repetitions 1 through N and records the repetition
on every JSONL row. Repeat ``--task-id`` to select the immutable pilot subset.

## Requirements

  - Python 3.10+ and the benchmark dependency group
  - Codex CLI >=0.138.0; r6 permission profiles were validated with 0.145.0
  - A clean target at PyTorch Lightning tag ``2.6.5`` and its locked index
  - The local plugin marketplace root for B/C
  - For authenticated execution, a user-owned regular ``auth.json`` with mode
    0600; symlinks and group/other-readable files are rejected

## Failure conditions

The run fails closed before a model call when the manifest, target, task,
prompt, index, plugin, provided authentication, or permission-profile contract
differs from r6. It also rejects dirty targets, symlinked or hard-linked
protected paths, credential/index exposure to A, missing index access for B/C,
or a broad coordination write surface.

During execution, timeouts, non-zero Codex exits, malformed/incomplete native
events, extraction failures, and target/index/coordination mutations remain
visible in the result. Only zero-token retryable transport failures may retry,
at most twice. A C no-call is recorded as ``compliance=false`` rather than
rewritten as an incorrect task answer.

## Output

``--dry-run`` invokes no model and prints one ``PROBE`` line per selected arm
followed by deterministic task/repetition/arm ``PLAN`` lines. A paid run appends
one normalized JSON object per completed cell to ``--output-path`` and prints a
``RESULT`` line.
The file is created before the first cell so an existing result cannot be
overwritten, and each completed cell survives a later failure.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import inspect
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from provider_parity_contracts import (  # noqa: E402
    ARM_CONTRACTS,
    EvaluationResult,
    PARITY_TIMEOUT_SECONDS,
    TaskPolicy,
    capability_strata,
    canonical_task_hash,
    deterministic_arm_order,
    load_task_policies,
    load_task_suite,
    prompt_hash,
    semantic_suite_hash,
)


PARITY_MANIFEST_PATH = Path(__file__).parent / "results" / "manifests" / "provider-parity-v1.json"
PARITY_EXPERIMENT_REVISION = "codemap-provider-parity-v1-b0-r7"
ARMS = tuple(ARM_CONTRACTS)
PARITY_CODEX_MODEL = "gpt-5.6-luna"
PARITY_CODEX_REASONING_EFFORT = "high"
_CODEX_BIN = "codex"
_PROVENANCE_KEY = "_codex_provenance"
_PLAIN_PERMISSION_PROFILE = "provider-parity-plain"
_CODEMAP_PERMISSION_PROFILE = "provider-parity-codemap"
_MIN_PERMISSION_PROFILE_VERSION = (0, 138, 0)
_COORDINATION_NAME = ".index-rw"
_REGISTRY_NAME = "registry.lock"
_READERS_NAME = "readers"


def _raw_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical task object without adapter-added provenance."""
    raw = dict(task)
    raw.pop(_PROVENANCE_KEY, None)
    return raw


def _raw_task_hash(task: Mapping[str, Any]) -> str:
    """Hash raw task bytes, never a provider projection."""
    return canonical_task_hash(_raw_task(task))


def _repo_sha(repo_path: Path) -> str:
    """Return repository HEAD or ``unknown`` when the fixture has no Git metadata."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else "unknown"


def _index_sha(index_path: Path | None) -> str:
    """Fingerprint an index file when one is configured."""
    if index_path is None or not index_path.is_file():
        return "unknown"
    try:
        return hashlib.sha256(index_path.read_bytes()).hexdigest()
    except OSError:
        return "unknown"


def _validate_locked_runtime(repo_path: Path, index_path: Path | None, arm: str) -> None:
    """Fail closed unless the target repository and index match the frozen manifest."""
    try:
        manifest = json.loads(PARITY_MANIFEST_PATH.read_text(encoding="utf-8"))
        expected_repo = manifest["target_source"]["commit"]
        expected_index = manifest["index"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity manifest is unavailable or malformed") from exc
    if _repo_sha(repo_path) != expected_repo:
        raise ValueError(f"canonical Codex run requires target commit {expected_repo}")
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("canonical Codex run could not verify worktree cleanliness") from exc
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("canonical Codex run requires a clean target worktree")
    if index_path is None or not index_path.is_file():
        raise ValueError("canonical Codex arm requires the locked index")
    if not index_path.is_relative_to(repo_path):
        raise ValueError("canonical Codemap index must be readable inside the target sandbox")
    expected_index_path = repo_path / ".cache" / "codemap" / f"{repo_path.name}.json"
    if index_path != expected_index_path:
        raise ValueError(f"canonical Codemap index must use the product resolver path {expected_index_path}")
    if hashlib.sha256(index_path.read_bytes()).hexdigest() != expected_index["raw_sha256"]:
        raise ValueError("canonical Codex run requires the locked index bytes")
    metadata = json.loads(index_path.read_text(encoding="utf-8"))
    if (
        metadata.get("git_sha") != expected_index["git_sha"]
        or metadata.get("scan_version") != expected_index["scan_version"]
    ):
        raise ValueError("canonical Codex index metadata does not match the locked manifest")


def build_codex_command(
    repo_path: Path | str,
    model: str,
    prompt: str,
    *,
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
    codex_bin: str = _CODEX_BIN,
) -> list[str]:
    """Build an ephemeral, JSONL Codex command preserving *prompt* as-is.

    The isolated ``CODEX_HOME`` supplied by :class:`CodexRunner` prevents a
    user's global config from changing an arm's tool surface.
    """
    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    if not isinstance(model, str) or not model:
        raise ValueError("model must be a non-empty string")
    if not isinstance(reasoning_effort, str) or not reasoning_effort:
        raise ValueError("reasoning_effort must be a non-empty string")
    path = str(Path(repo_path).resolve())
    return [
        codex_bin,
        "exec",
        "--json",
        "--ephemeral",
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--strict-config",
        "--cd",
        path,
        "--model",
        model,
        prompt,
    ]


def _validate_codex_stratum(model: str, reasoning_effort: str) -> None:
    """Reject benchmark execution outside the preregistered Luna/high stratum."""
    if model != PARITY_CODEX_MODEL:
        raise ValueError(f"Codex provider parity currently permits only {PARITY_CODEX_MODEL}")
    if reasoning_effort != PARITY_CODEX_REASONING_EFFORT:
        raise ValueError(f"Codex provider-parity reasoning effort must be {PARITY_CODEX_REASONING_EFFORT}")


def _validate_execution_manifest(manifest_path: Path = PARITY_MANIFEST_PATH) -> None:
    """Require a reviewed manifest for the exact implementation revision."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        revision = manifest["experiment_revision"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity execution manifest is unavailable or malformed") from exc
    if revision != PARITY_EXPERIMENT_REVISION:
        raise ValueError(
            f"paid execution requires a reviewed {PARITY_EXPERIMENT_REVISION} manifest; found {revision!r}"
        )


@dataclass
class CodexParseResult:
    """Normalized Codex stream telemetry plus lossless parsed event records."""

    thread_id: str = ""
    output_text: str = ""
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    command_calls: int = 0
    codemap_calls: int = 0
    codemap_successful_calls: int = 0
    codemap_errors: int = 0
    fallback_calls: int = 0
    completed: bool = False
    incomplete: bool = False
    error: str = ""
    error_type: str = ""
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    malformed_lines: int = 0
    raw_usage: dict[str, Any] = field(default_factory=dict)
    item_counts: dict[str, int] = field(default_factory=dict)
    tool_elapsed_s: float | None = None
    tool_result_tokens: int | None = None
    retryable: bool = False

    @property
    def success(self) -> bool:
        """Return whether the stream reached a successful terminal event."""
        return self.completed and not self.incomplete and not self.error


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _item_text(item: Mapping[str, Any]) -> str:
    for key in ("text", "content", "message"):
        value = item.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            chunks = [part.get("text", "") for part in value if isinstance(part, Mapping)]
            if chunks:
                return "".join(str(part) for part in chunks)
    return ""


def _command_text(item: Mapping[str, Any]) -> str:
    values = [item.get(key, "") for key in ("command", "cmd", "name", "arguments", "input")]
    return " ".join(value if isinstance(value, str) else json.dumps(value, sort_keys=True) for value in values)


def _is_codemap_command(command: str) -> bool:
    lowered = command.lower()
    return any(
        token in lowered for token in ("/bin/scan-query", "/bin/codemap-py", "$codemap-py:", "codemap:query-code")
    ) or bool(re.search(r"(?:^|[;&|]\s*)(?:scan-query|codemap-py)(?:\s|$)", lowered))


def _shell_reported_exit_code(command: str, item: Mapping[str, Any]) -> int | None:
    """Recover an embedded exit status from the launcher's ``; echo $?`` probe."""
    if "echo $?" not in command:
        return None
    output = str(item.get("aggregated_output", item.get("output", ""))).strip()
    last_line = output.splitlines()[-1] if output else ""
    return int(last_line) if last_line.isdigit() else None


def _iter_lines(stream: str | bytes | Iterable[str | bytes]) -> Iterable[str]:
    if isinstance(stream, bytes):
        stream = stream.decode("utf-8", errors="replace")
    if isinstance(stream, str):
        yield from stream.splitlines()
        return
    for line in stream:
        if isinstance(line, bytes):
            yield line.decode("utf-8", errors="replace")
        else:
            yield line


def parse_codex_jsonl(stream: str | bytes | Iterable[str | bytes]) -> CodexParseResult:
    """Parse Codex ``exec --json`` events into provider-neutral telemetry.

    Codex has used both ``item.completed`` events and Claude-compatible
    assistant blocks across CLI versions.  This parser accepts both shapes,
    deduplicates lifecycle events by item ID, and retains every valid parsed
    event in ``raw_events`` for audit/debugging.
    """
    result = CodexParseResult()
    seen_items: set[str] = set()
    pending_items: set[str] = set()
    saw_terminal = False
    for raw_line in _iter_lines(stream):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            result.malformed_lines += 1
            continue
        if not isinstance(event, dict):
            result.malformed_lines += 1
            continue
        result.raw_events.append(event)
        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            result.thread_id = str(event.get("thread_id", ""))

        usage = event.get("usage")
        if isinstance(usage, Mapping):
            result.raw_usage.update(dict(usage))
            result.input_tokens = max(result.input_tokens, _as_int(usage.get("input_tokens")))
            result.cached_input_tokens = max(
                result.cached_input_tokens,
                _as_int(usage.get("cached_input_tokens", usage.get("cache_read_input_tokens"))),
            )
            result.output_tokens = max(result.output_tokens, _as_int(usage.get("output_tokens")))
            result.reasoning_output_tokens = max(
                result.reasoning_output_tokens,
                _as_int(usage.get("reasoning_output_tokens")),
            )

        item = event.get("item")
        if isinstance(item, Mapping):
            item_id = str(item.get("id", ""))
            item_type = str(item.get("type", ""))
            command = _command_text(item)
            if event_type == "item.completed" and item_type:
                result.item_counts[item_type] = result.item_counts.get(item_type, 0) + 1
            if item_type == "agent_message" and event_type in {"", "item.completed"}:
                result.output_text += _item_text(item)
            if item_type in {"command_execution", "shell_command", "command"}:
                if event_type == "item.started" and item_id:
                    pending_items.add(item_id)
                if event_type == "item.completed" and item_id not in seen_items:
                    seen_items.add(item_id)
                    pending_items.discard(item_id)
                    result.command_calls += 1
                    duration_ms = item.get("duration_ms", item.get("elapsed_ms"))
                    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
                        elapsed = max(float(duration_ms), 0.0) / 1000.0
                        result.tool_elapsed_s = (result.tool_elapsed_s or 0.0) + elapsed
                    if _is_codemap_command(command):
                        result.codemap_calls += 1
                        status = str(item.get("status", "")).lower()
                        exit_code = item.get("exit_code")
                        reported_exit_code = _shell_reported_exit_code(command, item)
                        if (
                            status in {"failed", "error", "cancelled", "canceled"}
                            or (isinstance(exit_code, int) and exit_code != 0)
                            or (reported_exit_code is not None and reported_exit_code != 0)
                        ):
                            result.codemap_errors += 1
                        else:
                            result.codemap_successful_calls += 1
                    elif result.codemap_errors:
                        result.fallback_calls += 1

        # Compatibility with older/fixture streams that use assistant blocks.
        message = event.get("message")
        if isinstance(message, Mapping):
            for block in message.get("content", []):
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "text":
                    result.output_text += str(block.get("text", ""))
                if block.get("type") == "tool_use":
                    name = str(block.get("name", ""))
                    command = _command_text(block)
                    if name.lower() in {"bash", "shell", "command_execution"}:
                        result.command_calls += 1
                    if _is_codemap_command(name + " " + command):
                        result.codemap_calls += 1

        if event_type in {"turn.completed", "result", "response.completed"}:
            saw_terminal = True
            status = str(event.get("status", event.get("subtype", "completed"))).lower()
            if status in {"completed", "success", "succeeded", ""}:
                result.completed = True
            else:
                result.incomplete = True
                result.error = result.error or status
                result.error_type = result.error_type or "turn_incomplete"
        if event_type in {"error", "turn.failed", "response.failed"}:
            saw_terminal = True
            result.retryable = True
            result.incomplete = True
            error = event.get("error") or event.get("message") or event.get("detail")
            result.error = str(error) if error else event_type
            native_error_type = event.get("error_type")
            if isinstance(native_error_type, str) and native_error_type:
                result.error_type = native_error_type
            elif event_type == "turn.failed":
                result.error_type = "turn_failed"
            elif event_type == "response.failed":
                result.error_type = "response_failed"
            else:
                result.error_type = "transport_error"
    if not saw_terminal and not result.error:
        result.incomplete = True
        result.error = "missing terminal event"
        result.error_type = "missing_terminal"
        result.retryable = not result.raw_events
    if pending_items:
        result.completed = False
        result.incomplete = True
        result.error = result.error or "terminal event left command items incomplete"
        result.error_type = result.error_type or "pending_item"
    if result.malformed_lines:
        result.completed = False
        result.incomplete = True
        result.error = result.error or f"malformed JSONL ({result.malformed_lines} line(s))"
        result.error_type = result.error_type or "malformed_stream"
    return result


@dataclass
class ArmHome:
    """Disposable Codex home and environment for one canonical arm."""

    arm: str
    path: Path
    env: dict[str, str]
    codemap_available: bool
    codemap_verified: bool = False
    auth_provisioned: bool = False
    authenticated: bool = False
    permission_profile: str = ""
    coordination_path: Path | None = None
    codemap_launcher_path: Path | None = None
    codemap_launcher_sha256: str = ""

    def cleanup(self) -> None:
        """Remove the disposable home after a run."""
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self) -> "ArmHome":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cleanup()


def _copy_auth_source(auth_source: Path, home: Path) -> None:
    """Copy one private regular credential file into a disposable Codex home."""
    source = Path(auth_source)
    try:
        source_lstat = source.lstat()
    except OSError as exc:
        raise ValueError("auth source is unavailable") from exc
    if stat.S_ISLNK(source_lstat.st_mode):
        raise ValueError("auth source must not be a symlink")

    source_fd: int | None = None
    target_fd: int | None = None
    target = home / "auth.json"
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        source_fd = os.open(source, flags)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise ValueError("auth source must be a regular file")
        if hasattr(os, "getuid") and source_stat.st_uid != os.getuid():
            raise ValueError("auth source must be owned by the current user")
        if stat.S_IMODE(source_stat.st_mode) & 0o077:
            raise ValueError("auth source permissions must deny group and other access")
        if (source_stat.st_dev, source_stat.st_ino) != (source_lstat.st_dev, source_lstat.st_ino):
            raise ValueError("auth source changed while being opened")

        target_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(source_fd, "rb") as source_handle:
            source_fd = None
            with os.fdopen(target_fd, "wb") as target_handle:
                target_fd = None
                shutil.copyfileobj(source_handle, target_handle)
        target.chmod(0o600)
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ValueError("auth source could not be copied securely") from exc
    finally:
        if source_fd is not None:
            os.close(source_fd)
        if target_fd is not None:
            os.close(target_fd)


def _assert_safe_path_components(path: Path) -> None:
    """Reject symlink components in an existing absolute filesystem path."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"permission path contains a symlink: {current}")


def _canonical_index_path(index_path: Path) -> Path:
    """Return one regular, single-link index path with no symlink components."""
    absolute = Path(os.path.abspath(index_path))
    _assert_safe_path_components(absolute)
    try:
        metadata = absolute.lstat()
    except OSError as exc:
        raise ValueError("canonical Codemap index is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("canonical Codemap index must be a regular file")
    if metadata.st_nlink != 1:
        raise ValueError("canonical Codemap index must not be hard-linked")
    return absolute.resolve(strict=True)


def _validate_coordination_root(coordination_root: Path) -> None:
    """Fail unless the coordination root is the clean canonical rwgate skeleton."""
    _assert_safe_path_components(coordination_root)
    try:
        root_metadata = coordination_root.lstat()
    except OSError as exc:
        raise ValueError("Codemap coordination root is unavailable") from exc
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("Codemap coordination root must be a directory")

    allowed = {_READERS_NAME, _REGISTRY_NAME}
    entries = {entry.name for entry in coordination_root.iterdir()}
    if entries != allowed:
        raise ValueError(f"Codemap coordination root has unexpected or live entries: {sorted(entries - allowed)}")

    readers = coordination_root / _READERS_NAME
    registry = coordination_root / _REGISTRY_NAME
    readers_metadata = readers.lstat()
    registry_metadata = registry.lstat()
    if not stat.S_ISDIR(readers_metadata.st_mode) or readers.is_symlink():
        raise ValueError("Codemap readers path must be a real directory")
    if any(readers.iterdir()):
        raise ValueError("Codemap coordination root has live reader tokens")
    if not stat.S_ISREG(registry_metadata.st_mode) or registry.is_symlink():
        raise ValueError("Codemap registry must be a regular file")
    if registry_metadata.st_nlink != 1 or registry.read_bytes() != b"L":
        raise ValueError("Codemap registry identity is invalid")


def _prepare_coordination_root(index_path: Path) -> Path:
    """Create a clean index-local rwgate skeleton before sandboxed execution."""
    canonical_index = _canonical_index_path(index_path)
    coordination_root = canonical_index.parent / _COORDINATION_NAME
    if coordination_root.exists() or coordination_root.is_symlink():
        _validate_coordination_root(coordination_root)
        return coordination_root

    try:
        coordination_root.mkdir(mode=0o700)
        readers = coordination_root / _READERS_NAME
        readers.mkdir(mode=0o700)
        registry = coordination_root / _REGISTRY_NAME
        fd = os.open(
            registry,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(fd, b"L")
        finally:
            os.close(fd)
    except OSError as exc:
        raise ValueError("Codemap coordination root could not be created safely") from exc
    _validate_coordination_root(coordination_root)
    return coordination_root


def _cleanup_coordination_root(coordination_root: Path) -> None:
    """Remove only a validated, idle rwgate skeleton."""
    _validate_coordination_root(coordination_root)
    try:
        (coordination_root / _REGISTRY_NAME).unlink()
        (coordination_root / _READERS_NAME).rmdir()
        coordination_root.rmdir()
    except OSError as exc:
        raise ValueError("Codemap coordination root cleanup failed") from exc


def _shell_environment(home: ArmHome) -> dict[str, str]:
    """Return the explicit non-secret environment allowed in model commands."""
    allowed = {
        "PATH": home.env.get("PATH", os.defpath),
        "HOME": str(home.path),
        "CODEX_HOME": str(home.path),
    }
    for name in (
        "CODEMAP_BIN",
        "CODEMAP_PYTHON",
        "SCAN_NO_AUTOBUILD",
        "CODEMAP_LOGGING",
        "CODEX_CODEMAP_AVAILABLE",
    ):
        value = home.env.get(name)
        if value is not None:
            allowed[name] = value
    return allowed


def _write_permission_config(home: ArmHome, arm: str, index_path: Path | None) -> Path:
    """Write the exact r6 permission profile into one disposable Codex home."""
    if arm not in ARM_CONTRACTS:
        raise ValueError(f"unknown benchmark arm {arm!r}")
    profile = _PLAIN_PERMISSION_PROFILE if arm == "A_plain" else _CODEMAP_PERMISSION_PROFILE
    auth_path = (home.path / "auth.json").resolve()
    filesystem_rules = [f'{json.dumps(str(auth_path))} = "deny"']
    if index_path is None:
        raise ValueError(f"{arm} permission profile requires the locked index")
    canonical_index = _canonical_index_path(index_path)
    coordination_root: Path | None = None
    if arm == "A_plain":
        filesystem_rules.append(f'{json.dumps(str(canonical_index.parent))} = "deny"')
    else:
        coordination_root = canonical_index.parent / _COORDINATION_NAME
        if coordination_root.is_symlink():
            raise ValueError("Codemap coordination root must not be a symlink")
        filesystem_rules.append(f'{json.dumps(str(coordination_root))} = "write"')

    explicit_environment = ", ".join(
        f"{name} = {json.dumps(value)}" for name, value in sorted(_shell_environment(home).items())
    )
    config_text = "\n".join(
        [
            f'default_permissions = "{profile}"',
            "",
            "[shell_environment_policy]",
            'inherit = "none"',
            "ignore_default_excludes = false",
            f"set = {{ {explicit_environment} }}",
            "",
            f"[permissions.{profile}]",
            'description = "Read-only provider parity with isolated Codemap coordination."',
            'extends = ":read-only"',
            "",
            f"[permissions.{profile}.filesystem]",
            *filesystem_rules,
            "",
            f"[permissions.{profile}.network]",
            "enabled = false",
            "",
        ]
    )
    config_path = home.path / "config.toml"
    config_path.write_text(config_text, encoding="utf-8")
    config_path.chmod(0o600)
    home.permission_profile = profile
    home.coordination_path = coordination_root
    return config_path


def prepare_arm_home(
    arm: str,
    *,
    root: Path | None = None,
    auth_source: Path | None = None,
    plugin_installer: Callable[[Path], bool | None] | None = None,
) -> ArmHome:
    """Create an isolated ``CODEX_HOME`` implementing A/B/C availability."""
    if arm not in ARM_CONTRACTS:
        raise ValueError(f"unknown benchmark arm {arm!r}")
    home = Path(tempfile.mkdtemp(prefix=f"codex-{arm}-", dir=str(root) if root else None))
    try:
        home.chmod(0o700)
        config = home / "config.toml"
        config.touch(mode=0o600)
        config.chmod(0o600)
        if auth_source is not None:
            _copy_auth_source(auth_source, home)
        verified = False
        if arm in {"B_auto", "C_required"} and plugin_installer is not None:
            verified = bool(plugin_installer(home))
        env = os.environ.copy()
        env["CODEX_HOME"] = str(home)
        env["CODEX_BENCHMARK_ARM"] = arm
        env["CODEX_CODEMAP_AVAILABLE"] = "1" if verified else "0"
        return ArmHome(
            arm,
            home,
            env,
            verified,
            verified,
            auth_provisioned=auth_source is not None,
        )
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        raise


def probe_arm_home(home: ArmHome | Path, arm: str | None = None) -> dict[str, Any]:
    """Return deterministic isolation evidence, raising on cross-arm mismatch."""
    path = home.path if isinstance(home, ArmHome) else Path(home)
    expected = arm or (home.arm if isinstance(home, ArmHome) else None)
    config = path / "config.toml"
    available = home.codemap_available if isinstance(home, ArmHome) else False
    if expected == "A_plain" and available:
        raise ValueError("A_plain Codex home unexpectedly contains Codemap")
    if expected in {"B_auto", "C_required"} and not (
        isinstance(home, ArmHome) and home.codemap_available and home.codemap_verified
    ):
        raise ValueError(f"{expected} Codex home requires a verified plugin probe")
    return {
        "home": str(path),
        "config": str(config),
        "arm": expected,
        "codemap_available": available,
        "codemap_verified": isinstance(home, ArmHome) and home.codemap_verified,
        "auth_provisioned": isinstance(home, ArmHome) and home.auth_provisioned,
        "authenticated": isinstance(home, ArmHome) and home.authenticated,
        "permission_profile": home.permission_profile if isinstance(home, ArmHome) else "",
        "coordination_write_enabled": bool(isinstance(home, ArmHome) and home.coordination_path is not None),
        "codemap_python": (
            home.env.get("CODEMAP_PYTHON")
            if isinstance(home, ArmHome) and expected in {"B_auto", "C_required"}
            else None
        ),
        "codemap_launcher_path": (
            str(home.codemap_launcher_path)
            if isinstance(home, ArmHome) and expected in {"B_auto", "C_required"} and home.codemap_launcher_path
            else None
        ),
        "codemap_launcher_sha256": (
            home.codemap_launcher_sha256 if isinstance(home, ArmHome) and expected in {"B_auto", "C_required"} else ""
        ),
        "network_access": False,
        "config_mode": stat.S_IMODE(config.stat().st_mode),
    }


def _invoke_plugin_command(
    command: list[str],
    env: Mapping[str, str],
    command_runner: Callable[..., Any] | None = None,
) -> tuple[int, str, str]:
    """Run a no-model Codex plugin command through an injectable seam."""
    runner = command_runner or subprocess.run
    try:
        completed = runner(command, env=dict(env), capture_output=True, text=True, check=False)
    except TypeError:
        completed = runner(command, dict(env))
    if isinstance(completed, tuple):
        code, stdout, stderr = (list(completed) + ["", ""])[:3]
        return int(code), str(stdout), str(stderr)
    return (
        int(getattr(completed, "returncode", 1)),
        str(getattr(completed, "stdout", "") or ""),
        str(getattr(completed, "stderr", "") or ""),
    )


def _verify_locked_codemap_python(
    *,
    manifest_path: Path = PARITY_MANIFEST_PATH,
    command_runner: Callable[..., Any] | None = None,
) -> str:
    """Validate and return the manifest-locked treatment Python executable."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        runtime = manifest["codex_permission_profiles"]["treatment_runtime"]
        python_path = runtime["environment"]["CODEMAP_PYTHON"]
        required_major_minor = tuple(runtime["required_major_minor"])
        scope = runtime["scope"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("provider-parity treatment runtime is unavailable or malformed") from exc
    if (
        not isinstance(python_path, str)
        or not Path(python_path).is_absolute()
        or not Path(python_path).is_file()
        or not os.access(python_path, os.X_OK)
    ):
        raise ValueError("locked CODEMAP_PYTHON must be an executable absolute file")
    if required_major_minor != (3, 11) or scope != ["B_auto", "C_required"]:
        raise ValueError("provider-parity treatment runtime contract does not match r6")

    code, stdout, stderr = _invoke_plugin_command(
        [python_path, "--version"],
        {},
        command_runner=command_runner,
    )
    version_match = re.search(r"(\d+)\.(\d+)(?:\.\d+)?", f"{stdout}\n{stderr}")
    found_major_minor = tuple(int(part) for part in version_match.groups()) if version_match else ()
    if code != 0 or found_major_minor != required_major_minor:
        required = ".".join(str(part) for part in required_major_minor)
        raise ValueError(f"locked CODEMAP_PYTHON must report Python {required}")
    return python_path


def _verify_permission_profile(
    home: ArmHome,
    repo_path: Path,
    index_path: Path | None = None,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove the selected profile denies secrets/source and permits only coordination."""
    code, stdout, stderr = _invoke_plugin_command(
        [_CODEX_BIN, "--version"],
        home.env,
        command_runner=command_runner,
    )
    version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", f"{stdout}\n{stderr}")
    if code != 0 or version_match is None:
        raise ValueError("Codex permission-profile version probe failed")
    version = tuple(int(part) for part in version_match.groups())
    if version < _MIN_PERMISSION_PROFILE_VERSION:
        raise ValueError(f"Codex permission profiles require >= {'.'.join(map(str, _MIN_PERMISSION_PROFILE_VERSION))}")

    profile = home.permission_profile or (
        _PLAIN_PERMISSION_PROFILE if home.arm == "A_plain" else _CODEMAP_PERMISSION_PROFILE
    )
    sandbox_prefix = [
        _CODEX_BIN,
        "sandbox",
        "-P",
        profile,
        "--include-managed-config",
        "-C",
        str(repo_path),
        "--",
        sys.executable,
        "-c",
    ]
    code, _stdout, error = _invoke_plugin_command(
        [*sandbox_prefix, "pass"],
        home.env,
        command_runner=command_runner,
    )
    if code != 0:
        raise ValueError(f"Codex permission profile is unsupported or rejected: {error[:200]}")

    source_probe = repo_path / f".codex-r6-deny-{uuid4().hex}"
    write_script = "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'probe')"
    code, _stdout, _stderr = _invoke_plugin_command(
        [*sandbox_prefix, write_script, str(source_probe)],
        home.env,
        command_runner=command_runner,
    )
    if code == 0 or source_probe.exists():
        source_probe.unlink(missing_ok=True)
        raise ValueError("Codex permission profile allowed a source-tree write")

    read_script = "from pathlib import Path; import sys; Path(sys.argv[1]).read_bytes()"
    auth_path = home.path / "auth.json"
    if auth_path.exists():
        code, probe_stdout, probe_stderr = _invoke_plugin_command(
            [*sandbox_prefix, read_script, str(auth_path)],
            home.env,
            command_runner=command_runner,
        )
        if code == 0:
            raise ValueError("Codex permission profile allowed credential reads")
        auth_bytes = auth_path.read_bytes()
        combined_output = (probe_stdout + probe_stderr).encode("utf-8", errors="replace")
        if auth_bytes and auth_bytes in combined_output:
            raise ValueError("Codex permission probe disclosed credential material")

    if index_path is not None:
        code, _stdout, error = _invoke_plugin_command(
            [*sandbox_prefix, read_script, str(index_path)],
            home.env,
            command_runner=command_runner,
        )
        if home.arm == "A_plain" and code == 0:
            raise ValueError("A_plain permission profile allowed locked-index reads")
        if home.arm != "A_plain" and code != 0:
            raise ValueError(f"Codemap permission profile denied locked-index reads: {error[:200]}")

    if home.coordination_path is not None:
        coordination_probe = home.coordination_path / f".codex-r6-allow-{uuid4().hex}"
        code, _stdout, error = _invoke_plugin_command(
            [*sandbox_prefix, write_script, str(coordination_probe)],
            home.env,
            command_runner=command_runner,
        )
        if code != 0 or not coordination_probe.is_file():
            raise ValueError(f"Codex permission profile denied coordination writes: {error[:200]}")
        coordination_probe.unlink()
        _validate_coordination_root(home.coordination_path)


def _verify_authentication(
    home: ArmHome,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove the disposable home is authenticated without retaining command output."""
    returncode, _stdout, _stderr = _invoke_plugin_command(
        ["codex", "login", "status"],
        home.env,
        command_runner,
    )
    if returncode != 0:
        raise RuntimeError("disposable Codex home is not authenticated")
    home.authenticated = True


def _codemap_enabled(plugin_json: str) -> bool:
    """Return whether Codemap appears enabled in ``codex plugin list --json``."""
    try:
        payload = json.loads(plugin_json)
    except json.JSONDecodeError:
        return False
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        entries = payload.get("plugins", payload.get("installed", []))
    else:
        entries = []
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if isinstance(entry, str):
            if "codemap-py" in entry.lower():
                return True
            continue
        if not isinstance(entry, Mapping):
            continue
        name = str(entry.get("name", entry.get("id", ""))).lower()
        if "codemap-py" in name:
            return bool(entry.get("enabled", entry.get("active", True)))
    return False


def _configure_codemap_launcher(home: ArmHome, install_json: str) -> None:
    """Validate and expose the exact launcher reported by Codex plugin install."""
    try:
        payload = json.loads(install_json)
        raw_installed_path = payload["installedPath"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise RuntimeError("Codemap plugin install did not report installedPath") from exc
    if not isinstance(raw_installed_path, str) or not raw_installed_path:
        raise RuntimeError("Codemap plugin installedPath must be a non-empty string")

    installed_path = Path(os.path.abspath(raw_installed_path))
    _assert_safe_path_components(installed_path)
    try:
        installed_path = installed_path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Codemap plugin installedPath is unavailable") from exc
    home_root = home.path.resolve(strict=True)
    if not installed_path.is_relative_to(home_root):
        raise RuntimeError("Codemap plugin installedPath escaped the disposable CODEX_HOME")

    plugin_manifest = installed_path / ".codex-plugin" / "plugin.json"
    launcher = installed_path / "bin" / "codemap-py"
    _assert_safe_path_components(plugin_manifest)
    _assert_safe_path_components(launcher)
    try:
        manifest_metadata = plugin_manifest.lstat()
        launcher_metadata = launcher.lstat()
        manifest_payload = json.loads(plugin_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Codemap plugin launcher or manifest is unavailable") from exc
    if (
        not stat.S_ISREG(manifest_metadata.st_mode)
        or plugin_manifest.is_symlink()
        or manifest_metadata.st_nlink != 1
        or manifest_payload.get("name") != "codemap-py"
    ):
        raise RuntimeError("Codemap plugin manifest identity is invalid")
    if (
        not stat.S_ISREG(launcher_metadata.st_mode)
        or launcher.is_symlink()
        or launcher_metadata.st_nlink != 1
        or not os.access(launcher, os.X_OK)
    ):
        raise RuntimeError("Codemap plugin launcher must be a regular executable")

    resolved_launcher = launcher.resolve(strict=True)
    if not resolved_launcher.is_relative_to(installed_path):
        raise RuntimeError("Codemap plugin launcher escaped installedPath")
    home.env["CODEMAP_BIN"] = str(resolved_launcher)
    home.codemap_launcher_path = resolved_launcher
    home.codemap_launcher_sha256 = hashlib.sha256(resolved_launcher.read_bytes()).hexdigest()


def _install_codemap_plugin(
    home: ArmHome,
    marketplace_root: Path | None,
    *,
    codex_bin: str = _CODEX_BIN,
    command_runner: Callable[..., Any] | None = None,
) -> bool:
    """Install and verify Codemap via Codex's no-model plugin CLI."""
    if marketplace_root is None:
        return False
    marketplace_root = marketplace_root.resolve()
    marketplace_manifest = marketplace_root / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_manifest.is_file():
        raise RuntimeError(
            "Codemap plugin source must be a marketplace root containing .agents/plugins/marketplace.json"
        )
    add_marketplace = [codex_bin, "plugin", "marketplace", "add", str(marketplace_root)]
    add_plugin = [codex_bin, "plugin", "add", "codemap-py@borda-ai-rig", "--json"]
    list_plugins = [codex_bin, "plugin", "list", "--json"]
    install_json = ""
    for command in (add_marketplace, add_plugin):
        code, stdout, stderr = _invoke_plugin_command(command, home.env, command_runner)
        if code != 0:
            raise RuntimeError(f"Codemap plugin setup failed ({' '.join(command[1:4])}): {stderr[:300]}")
        if command is add_plugin:
            install_json = stdout
    _configure_codemap_launcher(home, install_json)
    code, stdout, stderr = _invoke_plugin_command(list_plugins, home.env, command_runner)
    if code != 0 or not _codemap_enabled(stdout):
        raise RuntimeError(f"Codemap plugin verification failed: {stderr[:300]}")
    return True


def _verify_plain_plugin_absent(
    home: ArmHome,
    *,
    codex_bin: str = _CODEX_BIN,
    command_runner: Callable[..., Any] | None = None,
) -> None:
    """Prove A has no Codemap plugin or Codemap binary exposed on PATH."""
    code, stdout, stderr = _invoke_plugin_command([codex_bin, "plugin", "list", "--json"], home.env, command_runner)
    if code != 0:
        raise RuntimeError(f"A_plain plugin absence probe failed: {stderr[:300]}")
    if _codemap_enabled(stdout):
        raise RuntimeError("A_plain Codemap plugin unexpectedly enabled")
    path_dirs = home.env.get("PATH", "").split(os.pathsep)
    if any(
        (Path(directory) / candidate).exists() for directory in path_dirs for candidate in ("codemap-py", "scan-query")
    ):
        raise RuntimeError("A_plain Codemap binary is exposed on PATH")


def load_tasks_with_provenance(tasks_path: Path, manifest_path: Path = PARITY_MANIFEST_PATH) -> list[dict[str, Any]]:
    """Load raw tasks and fail closed on any locked hash or ordering mismatch."""
    raw_tasks = load_task_suite(tasks_path)
    policies = load_task_policies(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_rows = {task["id"]: task for suite in manifest.get("suites", []) for task in suite.get("tasks", [])}
    task_ids = [task["id"] for task in raw_tasks]
    matching_suites = [
        suite for suite in manifest.get("suites", []) if [row.get("id") for row in suite.get("tasks", [])] == task_ids
    ]
    if len(matching_suites) != 1:
        raise ValueError("ordered task IDs do not match exactly one locked manifest suite")
    for task in raw_tasks:
        row = manifest_rows.get(task["id"])
        if row is None or task["id"] not in policies:
            raise ValueError(f"no locked task policy for {task['id']!r}")
        if canonical_task_hash(task) != row.get("canonical_task_sha256"):
            raise ValueError(f"task hash mismatch for {task['id']!r}")
        if prompt_hash(task) != row.get("prompt_sha256"):
            raise ValueError(f"prompt hash mismatch for {task['id']!r}")
    suite_hash = semantic_suite_hash(raw_tasks)
    raw_hash = hashlib.sha256(tasks_path.read_bytes()).hexdigest()
    loaded: list[dict[str, Any]] = []
    for task in raw_tasks:
        policy: TaskPolicy = policies[task["id"]]
        item = dict(task)
        item[_PROVENANCE_KEY] = {
            "experiment_revision": PARITY_EXPERIMENT_REVISION,
            "task_hash": canonical_task_hash(task),
            "prompt_hash": prompt_hash(task),
            "suite_hash": suite_hash,
            "suite_raw_hash": raw_hash,
            "oracle_class": policy.oracle_class,
            "headline_eligible_v1": policy.headline_eligible_v1,
            "scoreable": policy.scoreable,
        }
        loaded.append(item)
    return loaded


@dataclass
class CodexRun:
    """Normalized provider result carrying shared provenance and native telemetry."""

    arm: str
    task_id: str
    task_type: str
    model: str
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT
    provider: str = "codex"
    capability_strata: tuple[str, ...] = ()
    quality_components: dict[str, float] = field(default_factory=dict)
    repetition: int = 1
    success: bool = False
    experiment_revision: str = PARITY_EXPERIMENT_REVISION
    parity_arm: str = ""
    task_hash: str = ""
    prompt_hash: str = ""
    suite_hash: str = ""
    suite_raw_hash: str = ""
    evaluator_id: str = ""
    evaluator_hash: str = ""
    envelope_hash: str = ""
    arm_contract_hash: str = ""
    repo_sha: str = "unknown"
    index_sha: str = "unknown"
    oracle_class: str = "unknown"
    headline_eligible_v1: bool = False
    scoreable: bool = True
    quality_score: float | None = None
    correct: bool = False
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    command_calls: int = 0
    codemap_calls: int = 0
    codemap_successful_calls: int = 0
    codemap_errors: int = 0
    fallback_calls: int = 0
    compliance: bool | None = None
    incomplete: bool = False
    extraction_failed: bool = False
    contaminated: bool = False
    error: str = ""
    error_type: str = ""
    output_text: str = ""
    thread_id: str = ""
    raw_events: list[dict[str, Any]] = field(default_factory=list)
    native_item_counts: dict[str, int] = field(default_factory=dict)
    elapsed_s: float = 0.0
    tool_elapsed_s: float | None = None
    tool_result_tokens: int | None = None
    native_attempt_events: list[list[dict[str, Any]]] = field(default_factory=list)
    retry_count: int = 0
    turn_budget_enforced: bool = False


@lru_cache(maxsize=1)
def _reference_bench_module() -> Any:
    """Load the Claude reference module once to reuse its exact evaluator registry."""
    module_path = Path(__file__).with_name("run-claude-structural.py")
    spec = importlib.util.spec_from_file_location("_codex_shared_bench_reference", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load shared evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _default_evaluator(task: Mapping[str, Any], output_text: str) -> EvaluationResult:
    """Invoke the exact evaluator registry used by the Claude reference adapter."""
    return _reference_bench_module()._SHARED_EVALUATORS.evaluate(task, output_text)


def _evaluator_identity(task: Mapping[str, Any], evaluator: Callable[..., Any]) -> tuple[str, str]:
    """Return the shared evaluator ID/hash, or deterministic fixture provenance."""
    if evaluator is _default_evaluator:
        return _reference_bench_module()._evaluator_provenance(task)
    identifier = getattr(evaluator, "__name__", evaluator.__class__.__name__)
    try:
        source = inspect.getsource(evaluator)
    except (OSError, TypeError):
        source = identifier
    return identifier, hashlib.sha256((identifier + "\n" + source).encode("utf-8")).hexdigest()


class CodexRunner:
    """Run one canonical Codex cell with injectable process/evaluator seams."""

    def __init__(
        self,
        model: str,
        repo_path: Path,
        *,
        reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
        index_path: Path | None = None,
        timeout: float = PARITY_TIMEOUT_SECONDS,
        marketplace_root: Path | None = None,
        auth_source: Path | None = None,
        plugin_installer: Callable[[Path], bool | None] | None = None,
        plugin_probe: Callable[[Path], bool] | None = None,
        command_runner: Callable[..., Any] | None = None,
        transport: Callable[..., str | bytes | Iterable[str | bytes]] | None = None,
        evaluator: Callable[[Mapping[str, Any], str], EvaluationResult] | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.repo_path = Path(repo_path).resolve()
        self.index_path = _canonical_index_path(Path(index_path)) if index_path else None
        self.timeout = timeout
        self.marketplace_root = marketplace_root.resolve() if marketplace_root else None
        # Preserve the caller-supplied path so `_copy_auth_source` can reject a
        # symlink instead of silently dereferencing it during normalization.
        self.auth_source = Path(auth_source) if auth_source else None
        self.plugin_installer = plugin_installer
        self.plugin_probe = plugin_probe
        self.command_runner = command_runner
        self.transport = transport
        self.evaluator = evaluator or _default_evaluator

    def build_command(self, prompt: str) -> list[str]:
        """Build this runner's canonical Codex command."""
        return build_codex_command(
            self.repo_path,
            self.model,
            prompt,
            reasoning_effort=self.reasoning_effort,
        )

    def _prepare_verified_home(self, arm: str) -> ArmHome:
        """Create and verify one arm home without invoking a model."""
        _validate_locked_runtime(self.repo_path, self.index_path, arm)
        home = prepare_arm_home(
            arm,
            auth_source=self.auth_source,
            plugin_installer=self.plugin_installer,
        )
        try:
            if arm in {"B_auto", "C_required"} and self.index_path is not None:
                home.env["CODEMAP_PYTHON"] = _verify_locked_codemap_python(
                    command_runner=self.command_runner,
                )
                home.env["SCAN_NO_AUTOBUILD"] = "1"
                home.env["CODEMAP_LOGGING"] = "false"
                home.env["CODEX_CODEMAP_AVAILABLE"] = "1"
                home.coordination_path = _prepare_coordination_root(self.index_path)
            else:
                for variable in (
                    "CODEMAP_BIN",
                    "CODEMAP_INDEX",
                    "CODEMAP_INDEX_DIR",
                    "CODEMAP_PYTHON",
                    "SCAN_NO_AUTOBUILD",
                    "CODEMAP_LOGGING",
                ):
                    home.env.pop(variable, None)
            if arm != "A_plain":
                if self.plugin_probe is not None:
                    home.codemap_verified = bool(self.plugin_probe(home.path))
                elif not home.codemap_verified:
                    home.codemap_verified = _install_codemap_plugin(
                        home,
                        self.marketplace_root,
                        command_runner=self.command_runner,
                    )
            if arm in {"B_auto", "C_required"}:
                if not home.codemap_verified:
                    raise RuntimeError("Codemap plugin is not verified by codex plugin list --json")
                home.codemap_available = True
            _write_permission_config(home, arm, self.index_path)
            _verify_permission_profile(
                home,
                self.repo_path,
                self.index_path,
                command_runner=self.command_runner,
            )
            if home.auth_provisioned:
                _verify_authentication(home, command_runner=self.command_runner)
            if arm == "A_plain":
                _verify_plain_plugin_absent(home, command_runner=self.command_runner)
        except Exception:
            if home.coordination_path is not None:
                with contextlib.suppress(ValueError):
                    _cleanup_coordination_root(home.coordination_path)
            home.cleanup()
            raise
        return home

    def probe_arm(self, arm: str) -> dict[str, Any]:
        """Return no-model runtime and plugin-isolation evidence for one arm."""
        if arm not in ARM_CONTRACTS:
            raise ValueError(f"unknown benchmark arm {arm!r}")
        with self._prepare_verified_home(arm) as home:
            return probe_arm_home(home)

    def run(self, task: Mapping[str, Any], arm: str, *, repetition: int = 1) -> CodexRun:
        """Execute a task cell, or use an injected fixture transport."""
        if arm not in ARM_CONTRACTS:
            raise ValueError(f"unknown benchmark arm {arm!r}")
        if repetition < 1:
            raise ValueError("repetition must be a positive integer")
        task_id = task.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("task requires a non-empty id")
        prompt = task.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("task prompt must be a string")
        envelope = _arm_envelope(arm)
        command_prompt = envelope + "\n\n" + prompt
        metadata = task.get(_PROVENANCE_KEY, {})
        if not isinstance(metadata, Mapping):
            metadata = {}
        run = CodexRun(
            arm,
            task_id,
            str(task.get("type", "unknown")),
            self.model,
            reasoning_effort=self.reasoning_effort,
            repetition=repetition,
        )
        run.parity_arm = arm
        run.capability_strata = capability_strata(_raw_task(task))
        run.arm_contract_hash = ARM_CONTRACTS[arm]["contract_sha256"]
        raw_hash = _raw_task_hash(task)
        expected_hash = metadata.get("task_hash", task.get("task_hash"))
        raw_prompt_hash = prompt_hash(_raw_task(task))
        expected_prompt_hash = metadata.get("prompt_hash", task.get("prompt_hash"))
        if metadata and metadata.get("task_hash") != raw_hash:
            raise ValueError(f"task hash mismatch for {task_id!r}")
        if metadata and metadata.get("prompt_hash") != raw_prompt_hash:
            raise ValueError(f"prompt hash mismatch for {task_id!r}")
        # ``load_tasks_with_provenance`` already verifies these values against
        # the locked manifest.  Trusting the precomputed fields here avoids
        # hashing an enriched projection (which is not canonical task bytes).
        run.task_hash = str(expected_hash or raw_hash)
        run.prompt_hash = str(expected_prompt_hash or raw_prompt_hash)
        run.suite_hash = str(metadata.get("suite_hash", task.get("suite_hash", "")))
        run.suite_raw_hash = str(metadata.get("suite_raw_hash", task.get("suite_raw_hash", "")))
        run.experiment_revision = str(
            metadata.get("experiment_revision", task.get("experiment_revision", PARITY_EXPERIMENT_REVISION))
        )
        run.oracle_class = str(metadata.get("oracle_class", task.get("oracle_class", "unknown")))
        run.headline_eligible_v1 = bool(metadata.get("headline_eligible_v1", task.get("headline_eligible_v1", False)))
        run.repo_sha = _repo_sha(self.repo_path)
        run.index_sha = _index_sha(self.index_path)
        explicit_evaluator_id = metadata.get("evaluator_id", task.get("evaluator_id"))
        explicit_evaluator_hash = metadata.get("evaluator_hash", task.get("evaluator_hash"))
        if explicit_evaluator_id and explicit_evaluator_hash:
            run.evaluator_id = str(explicit_evaluator_id)
            run.evaluator_hash = str(explicit_evaluator_hash)
        else:
            run.evaluator_id, run.evaluator_hash = _evaluator_identity(_raw_task(task), self.evaluator)
        run.envelope_hash = hashlib.sha256(envelope.encode()).hexdigest()
        run.scoreable = metadata.get("scoreable", task.get("scoreable", True)) is not False
        home: ArmHome | None = None
        if self.transport is None:
            home = self._prepare_verified_home(arm)
        started_at = time.monotonic()
        attempt_events: list[list[dict[str, Any]]] = []
        parsed = CodexParseResult()
        postflight_error = ""
        command = self.build_command(command_prompt)
        try:
            for attempt in range(3):
                if self.transport is None:
                    assert home is not None
                    stream = self._subprocess(command, home.env)
                else:
                    stream = self.transport(command, arm=arm)
                parsed = parse_codex_jsonl(stream)
                attempt_events.append(parsed.raw_events)
                if home is not None:
                    try:
                        _validate_locked_runtime(self.repo_path, self.index_path, arm)
                        if home.coordination_path is not None:
                            _validate_coordination_root(home.coordination_path)
                    except ValueError as exc:
                        postflight_error = str(exc)
                        parsed.completed = False
                        parsed.incomplete = True
                        parsed.error = f"runtime contamination: {postflight_error}"
                        parsed.error_type = "runtime_contamination"
                        parsed.retryable = False
                        break
                zero_token_transport_failure = (
                    parsed.input_tokens == 0 and parsed.output_tokens == 0 and parsed.retryable
                )
                if not zero_token_transport_failure or attempt == 2:
                    run.retry_count = attempt
                    break
                run.retry_count = attempt + 1
        finally:
            run.elapsed_s = time.monotonic() - started_at
            if home is not None:
                if home.coordination_path is not None:
                    try:
                        _cleanup_coordination_root(home.coordination_path)
                    except ValueError as exc:
                        postflight_error = postflight_error or str(exc)
                home.cleanup()
        run.thread_id = parsed.thread_id
        run.output_text = parsed.output_text
        run.raw_events = parsed.raw_events
        run.native_attempt_events = attempt_events
        run.native_item_counts = parsed.item_counts
        run.tool_elapsed_s = parsed.tool_elapsed_s
        run.tool_result_tokens = parsed.tool_result_tokens
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "command_calls",
            "codemap_calls",
            "codemap_successful_calls",
            "codemap_errors",
            "fallback_calls",
        ):
            setattr(run, field_name, getattr(parsed, field_name))
        run.success = parsed.success
        run.incomplete = parsed.incomplete
        run.error = parsed.error
        run.error_type = parsed.error_type
        run.compliance = run.codemap_calls > 0 if arm == "C_required" else None
        run.contaminated = bool(postflight_error) or (arm == "A_plain" and run.codemap_calls > 0)
        if postflight_error:
            run.incomplete = True
            run.error = f"runtime contamination: {postflight_error}"
            run.error_type = "runtime_contamination"
            run.success = False
        if run.contaminated and not run.error:
            run.error = "contaminated"
            run.success = False
        if run.scoreable and not run.incomplete:
            evaluation = self.evaluator(_raw_task(task), run.output_text)
            run.quality_score = evaluation.quality_score
            run.quality_components = evaluation.components
            run.correct = evaluation.correct
            run.extraction_failed = not evaluation.scored
        return run

    def _subprocess(self, command: list[str], env: Mapping[str, str]) -> str:
        """Run Codex and classify timeout/non-zero output without retrying model calls."""
        try:
            completed = subprocess.run(
                command,
                cwd=self.repo_path,
                env=dict(env),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "type": "error",
                    "error": f"timeout ({self.timeout}s)",
                    "error_type": "timeout",
                }
            )
        if completed.returncode != 0:
            terminal = json.dumps(
                {
                    "type": "error",
                    "error": completed.stderr.strip()[:300] or f"non-zero exit {completed.returncode}",
                    "error_type": "non_zero_exit",
                }
            )
            return (completed.stdout + "\n" + terminal).lstrip()
        return completed.stdout


def _arm_envelope(arm: str) -> str:
    """Return arm-only tool availability instructions."""
    if arm == "A_plain":
        return "Codemap is absent and inaccessible. Use ordinary provider tools only; do not invoke Codemap."
    if arm == "B_auto":
        return "Codemap is installed and available. You may use $codemap-py:query-code; no Codemap call is required."
    return "Codemap is installed and available. You must use $codemap-py:query-code at least once for structural investigation; other tools remain allowed."


def _append_run(output_path: Path, run: CodexRun) -> None:
    """Append one completed cell so later failures cannot erase smoke evidence."""
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(run), sort_keys=True) + "\n")


def main(
    *,
    repo_path: Path,
    model: str,
    reasoning_effort: str = PARITY_CODEX_REASONING_EFFORT,
    tasks_path: Path,
    index_path: Path | None = None,
    marketplace_root: Path | None = None,
    auth_source: Path | None = None,
    output_path: Path | None = None,
    task_ids: list[str] | None = None,
    repetitions: int = 1,
    arm: str = "all",
    dry_run: bool = False,
) -> None:
    """Validate and plan canonical cells; model execution requires omitting ``dry_run``."""
    _validate_codex_stratum(model, reasoning_effort)
    if repetitions < 1:
        raise ValueError("--repetitions must be a positive integer")
    tasks = load_tasks_with_provenance(tasks_path)
    if task_ids:
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("--task-id values must be unique")
        missing = set(task_ids) - {task["id"] for task in tasks}
        if missing:
            raise ValueError(f"unknown locked task IDs: {sorted(missing)}")
        selected_ids = set(task_ids)
        tasks = [task for task in tasks if task["id"] in selected_ids]
    if not dry_run:
        if output_path is None:
            raise ValueError("non-dry Codex runs require --output-path")
        if output_path.exists():
            raise FileExistsError(output_path)
        _validate_execution_manifest()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("x", encoding="utf-8"):
            pass
    runner = CodexRunner(
        model,
        repo_path,
        reasoning_effort=reasoning_effort,
        index_path=index_path,
        marketplace_root=marketplace_root,
        auth_source=auth_source,
    )
    if dry_run:
        for selected in ARMS if arm == "all" else (arm,):
            evidence = runner.probe_arm(selected)
            runtime = evidence.get("codemap_python") or "absent"
            print(f"PROBE\t{selected}\tcodemap={str(evidence['codemap_available']).lower()}\tcodemap_python={runtime}")
    task_arms = {
        (task["id"], repetition): (
            deterministic_arm_order(
                PARITY_EXPERIMENT_REVISION,
                "codex",
                model,
                task["id"],
                repetition,
                reasoning_effort=reasoning_effort,
            )
            if arm == "all"
            else (arm,)
        )
        for task in tasks
        for repetition in range(1, repetitions + 1)
    }
    for task in tasks:
        for repetition in range(1, repetitions + 1):
            for selected in task_arms[(task["id"], repetition)]:
                print(f"PLAN\t{task['id']}\t{repetition}\t{selected}")
    if dry_run:
        return
    for task in tasks:
        for repetition in range(1, repetitions + 1):
            for selected in task_arms[(task["id"], repetition)]:
                run = runner.run(task, selected, repetition=repetition)
                _append_run(output_path, run)
                print(f"RESULT\t{task['id']}\t{repetition}\t{selected}\t{output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument(
        "--reasoning-effort",
        default=PARITY_CODEX_REASONING_EFFORT,
        choices=(PARITY_CODEX_REASONING_EFFORT,),
    )
    parser.add_argument("--tasks-path", type=Path, required=True)
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("--marketplace-root", type=Path, required=False)
    parser.add_argument("--auth-source", type=Path)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--task-id", dest="task_ids", action="append")
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--arm", default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(**vars(args))
