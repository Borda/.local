"""Shared Codex stream normalization, rendering, and paid-stage lifecycle."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any, Generic, TextIO, TypeVar
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel

from _bench_common.presentation import fmt_time, fmt_tok

_SENSITIVE_EVENT_KEYS = frozenset(
    {"access_token", "refresh_token", "id_token", "authorization", "cookie", "set-cookie"}
)
STRUCTURAL_OUTPUT_LEGEND = (
    "LEGEND\n"
    "  treatments: A_plain=no Codemap, B_direct=direct Codemap required, "
    "C_skill=Codemap Skill required\n"
    "  tasks:\n"
    "      SE: symbol extraction\n"
    "      FN: function-call graph\n"
    "      RV: review assistance\n"
    "      CQ: code quality\n"
    "      BR: blast radius\n"
    "      DG: debug from trace\n"
    "      FT: feature scaffolding\n"
    "      RI: real issue\n"
    "      DI: diff impact\n"
    "      GR: graph reasoning\n"
    "      MB: module blast radius\n"
    "  status: ✓ completed, ✗ failed\n"
    "  quality: continuous [0,1], ? unscoreable (higher is better)\n"
    "  progress: N completed cells / M planned cells\n"
    "  treatment: ✓ assigned arm followed, ✗ assigned arm not followed\n"
    "  codemap-used: ✓ Codemap call observed; ✗ no Codemap call "
    "(expected for A_plain) or required use missed (B/C)\n"
    "  query: ✓ exact expected query; ✗ mismatch; — not applicable\n"
    "  cohort: H headline; D diagnostic\n"
    "  input tokens: gross total; cached and fresh details remain in telemetry only "
    "(lower is better at equal quality)\n"
    "END LEGEND"
)


@dataclass
class CodexParseResult:
    """Normalized Codex stream telemetry plus lossless parsed event records."""

    thread_id: str = ""
    output_text: str = ""
    last_tool_text_offset: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    command_calls: int = 0
    codemap_observed_calls: int = 0
    codemap_calls: int = 0
    codemap_successful_calls: int = 0
    codemap_compact_successful_calls: int = 0
    codemap_direct_calls: int = 0
    codemap_direct_successful_calls: int = 0
    codemap_direct_compact_successful_calls: int = 0
    codemap_skill_calls: int = 0
    codemap_skill_successful_calls: int = 0
    codemap_skill_compact_successful_calls: int = 0
    successful_query_arguments: list[list[str]] = field(default_factory=list)
    skill_delivery_observed: bool = False
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


def _is_refresh_token_authentication_failure(error: str) -> bool:
    """Identify deterministic OAuth refresh failures that cannot succeed on retry."""
    normalized = error.casefold()
    return (
        "401" in normalized
        and "refresh token" in normalized
        and ("expired" in normalized or "already been used" in normalized or "already used" in normalized)
    )


def _redact_sensitive_text(value: str) -> str:
    """Remove standard credential representations from persisted provider errors."""
    value = re.sub(
        r"(?i)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]*",
        r"\1: <redacted>",
        value,
    )
    value = re.sub(r"(?i)(bearer\s+)[^\s,;\]\}]+", r"\1<redacted>", value)
    return re.sub(
        r'(?i)(["\']?(?:access_token|refresh_token|id_token|authorization|cookie|set-cookie)["\']?\s*[:=]\s*["\'])[^"\']*',
        r"\1<redacted>",
        value,
    )


def _redact_sensitive_event(value: Any) -> Any:
    """Return a telemetry-safe projection without credential-valued fields."""
    if isinstance(value, Mapping):
        return {
            str(key): "<redacted>" if str(key).casefold() in _SENSITIVE_EVENT_KEYS else _redact_sensitive_event(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_event(item) for item in value]
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _redact_provider_error(value: Any) -> str:
    """Render one provider error without persisting credential values."""
    if isinstance(value, (Mapping, list)):
        return json.dumps(_redact_sensitive_event(value), sort_keys=True, default=str)
    return _redact_sensitive_text(str(value))


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


def _unwrap_native_command(command: str) -> str | None:
    """Return a native command after at most one exact Codex zsh wrapper."""
    if not command or "\n" in command or "\r" in command:
        return None
    normalized = command.strip()
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return None
    if parts[:2] != ["/bin/zsh", "-lc"]:
        return normalized
    if len(parts) != 3 or not parts[2] or "\n" in parts[2] or "\r" in parts[2]:
        return None
    return parts[2]


def _native_item_tokens(command: str, *, preserve_quotes: bool = False) -> list[str] | None:
    """Tokenize one dedicated native command, optionally retaining quote context."""
    normalized = _unwrap_native_command(command)
    if normalized is None:
        return None
    try:
        lexer = shlex.shlex(normalized, posix=not preserve_quotes, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or any(any(character in ";&|<>()`" for character in token) for token in tokens):
        return None
    return tokens


def _has_unquoted_comment(command: str) -> bool:
    """Return whether a shell comment can hide after an otherwise valid command."""
    quote: str | None = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote is not None:
            if character == quote:
                quote = None
        elif character in {"'", '"'}:
            quote = character
        elif character == "#":
            return True
        index += 1
    return False


def _canonical_query_arguments(command: str) -> list[str] | None:
    """Return query arguments only for the dedicated canonical launcher command."""
    normalized = _unwrap_native_command(command)
    if normalized is None:
        return None
    if _has_unquoted_comment(normalized):
        return None
    tokens = _native_item_tokens(command)
    quoted_tokens = _native_item_tokens(command, preserve_quotes=True)
    if (
        tokens is None
        or quoted_tokens is None
        or len(tokens) != len(quoted_tokens)
        or len(tokens) < 4
        or tokens[0] not in {"$CODEMAP_BIN", "${CODEMAP_BIN}"}
        or tokens[1:3] != ["query", "--compact"]
        or any(
            "$" in token and not (len(token) >= 2 and token.startswith("'") and token.endswith("'"))
            for token in quoted_tokens[3:]
        )
    ):
        return None
    arguments = tokens[3:]
    if arguments[0] == "help" or arguments[0].startswith("-"):
        return None
    return arguments


def _records_compact_query_attempt(command: str) -> bool:
    """Return whether a native item records a compact-query attempt for C ordering."""
    return _canonical_query_arguments(command) is not None


def _observes_compact_codemap_query(command: str) -> bool:
    """Return whether a native item invokes Codemap's compact query surface.

    This observational signal is broader than canonical-query credit: a compound
    shell item can prove use, but cannot satisfy a treatment requirement that
    demands one standalone, exact query command.
    """
    normalized = _unwrap_native_command(command)
    if normalized is None:
        return False
    return (
        re.search(r"(?:['\"]?\$CODEMAP_BIN['\"]?|\$\{CODEMAP_BIN\})\s+query\s+--compact(?:\s|$)", normalized)
        is not None
    )


def _is_codemap_command(command: str, *, launcher_path: Path | None = None) -> bool:
    """Return whether a command satisfies the prospective canonical query form."""
    del launcher_path
    return _canonical_query_arguments(command) is not None


def _is_compact_codemap_query(command: str, *, launcher_path: Path | None = None) -> bool:
    """Return whether a command satisfies the canonical compact-query form."""
    return _is_codemap_command(command, launcher_path=launcher_path)


def _command_output(item: Mapping[str, Any]) -> str:
    """Return the captured command output used for deterministic evidence checks."""
    value = item.get("aggregated_output", item.get("output", ""))
    return value if isinstance(value, str) else ""


def _query_output_complete(item: Mapping[str, Any]) -> bool:
    """Return whether output contains JSON proving a completed locked-index query."""
    output = _command_output(item)
    decoder = json.JSONDecoder()
    for offset, character in enumerate(output):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(output[offset:])
        except json.JSONDecodeError:
            continue
        index = payload.get("index") if isinstance(payload, Mapping) else None
        if isinstance(index, Mapping) and index.get("query_complete") is True:
            return True
    return False


def _canonical_skill_read(command: str, skill_path: Path | None) -> bool:
    """Return whether a dedicated command uses the runner-owned Skill binding."""
    if skill_path is None:
        return False
    normalized = _unwrap_native_command(command)
    return normalized is not None and normalized.strip() == 'cat "$CODEMAP_SKILL_FILE"'


def _completed_with_explicit_zero_exit(item: Mapping[str, Any]) -> bool:
    """Return whether one native command item completed with explicit exit zero."""
    return item.get("status") == "completed" and type(item.get("exit_code")) is int and item["exit_code"] == 0


def _canonical_query_output(item: Mapping[str, Any]) -> bool:
    """Return whether output is one complete compact-query JSON document."""
    try:
        payload = json.loads(_command_output(item))
    except (TypeError, json.JSONDecodeError):
        return False
    index = payload.get("index") if isinstance(payload, Mapping) else None
    return isinstance(index, Mapping) and index.get("query_complete") is True and index.get("compact") is True


def _exact_skill_read_output(item: Mapping[str, Any], skill_path: Path | None, skill_sha256: str) -> bool:
    """Return whether output exactly proves the currently locked Skill bytes."""
    if skill_path is None or not skill_sha256:
        return False
    try:
        locked_skill_bytes = skill_path.read_bytes()
        output_bytes = _command_output(item).encode("utf-8")
    except (OSError, UnicodeEncodeError):
        return False
    return (
        bool(locked_skill_bytes)
        and hashlib.sha256(locked_skill_bytes).hexdigest() == skill_sha256
        and output_bytes == locked_skill_bytes
    )


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


def _append_message_text(current: str, item: Mapping[str, Any]) -> str:
    """Preserve agent-message boundaries when reconstructing one response."""
    addition = _item_text(item)
    if not addition:
        return current
    return f"{current}\n{addition}" if current else addition


def parse_codex_jsonl(
    stream: str | bytes | Iterable[str | bytes],
    *,
    launcher_path: Path | None = None,
    skill_path: Path | None = None,
    skill_sha256: str = "",
) -> CodexParseResult:
    """Parse Codex ``exec --json`` events into provider-neutral telemetry.

    Codex has used both ``item.completed`` events and Claude-compatible
    assistant blocks across CLI versions.  This parser accepts both shapes,
    deduplicates lifecycle events by item ID, and retains every valid parsed
    event in ``raw_events`` for audit/debugging.
    """
    result = CodexParseResult()
    seen_items: set[str] = set()
    pending_items: set[str] = set()
    compact_query_attempt_seen = False
    saw_terminal = False
    saw_authentication_failure = False
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
        result.raw_events.append(_redact_sensitive_event(event))
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
                result.output_text = _append_message_text(result.output_text, item)
            if item_type in {"command_execution", "shell_command", "command"}:
                if event_type == "item.started" and item_id:
                    pending_items.add(item_id)
                if event_type == "item.completed" and item_id not in seen_items:
                    seen_items.add(item_id)
                    pending_items.discard(item_id)
                    result.last_tool_text_offset = len(result.output_text)
                    result.command_calls += 1
                    duration_ms = item.get("duration_ms", item.get("elapsed_ms"))
                    if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool):
                        elapsed = max(float(duration_ms), 0.0) / 1000.0
                        result.tool_elapsed_s = (result.tool_elapsed_s or 0.0) + elapsed
                    skill_read_verified = (
                        _canonical_skill_read(command, skill_path)
                        and _completed_with_explicit_zero_exit(item)
                        and _exact_skill_read_output(item, skill_path, skill_sha256)
                    )
                    if _canonical_query_arguments(command) is not None:
                        result.codemap_calls += 1
                        # The immutable C home proves the installed-Skill treatment.
                        # A manual Skill-file read remains useful audit evidence, but
                        # requiring it would add ceremony unrelated to a query's use.
                        delivery = "skill" if skill_path is not None else "direct"
                        if delivery == "direct":
                            result.codemap_direct_calls += 1
                        else:
                            result.codemap_skill_calls += 1
                        if not _completed_with_explicit_zero_exit(item) or not _canonical_query_output(item):
                            result.codemap_errors += 1
                        else:
                            result.codemap_successful_calls += 1
                            result.codemap_compact_successful_calls += 1
                            query_arguments = _canonical_query_arguments(command)
                            if query_arguments is not None:
                                result.successful_query_arguments.append(query_arguments)
                            if delivery == "direct":
                                result.codemap_direct_successful_calls += 1
                                result.codemap_direct_compact_successful_calls += 1
                            else:
                                result.codemap_skill_successful_calls += 1
                                result.codemap_skill_compact_successful_calls += 1
                    if _observes_compact_codemap_query(command):
                        result.codemap_observed_calls += 1
                    elif result.codemap_errors:
                        result.fallback_calls += 1
                    if skill_read_verified and not compact_query_attempt_seen:
                        result.skill_delivery_observed = True
                    if _records_compact_query_attempt(command):
                        compact_query_attempt_seen = True

        # Compatibility with older/fixture streams that use assistant blocks.
        message = event.get("message")
        if isinstance(message, Mapping):
            for block in message.get("content", []):
                if not isinstance(block, Mapping):
                    continue
                if block.get("type") == "text":
                    text_item = {"text": str(block.get("text", ""))}
                    result.output_text = _append_message_text(result.output_text, text_item)
                if block.get("type") == "tool_use":
                    result.last_tool_text_offset = len(result.output_text)
                    name = str(block.get("name", ""))
                    command = _command_text(block)
                    if name.lower() in {"bash", "shell", "command_execution"}:
                        result.command_calls += 1
                    if _is_codemap_command(name + " " + command, launcher_path=launcher_path):
                        result.codemap_calls += 1
                        if result.skill_delivery_observed:
                            result.codemap_skill_calls += 1
                        else:
                            result.codemap_direct_calls += 1

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
            result.error = _redact_provider_error(error) if error else event_type
            native_error_type = event.get("error_type")
            if isinstance(native_error_type, str) and native_error_type:
                result.error_type = native_error_type
            elif event_type == "turn.failed":
                result.error_type = "turn_failed"
            elif event_type == "response.failed":
                result.error_type = "response_failed"
            else:
                result.error_type = "transport_error"
            if _is_refresh_token_authentication_failure(result.error):
                saw_authentication_failure = True
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
    if saw_authentication_failure or _is_refresh_token_authentication_failure(result.error):
        result.error_type = "authentication_failed"
        result.retryable = False
    return result


Task = TypeVar("Task")
Arm = TypeVar("Arm")


@dataclass(frozen=True)
class PaidStageCallbacks(Generic[Task, Arm]):
    """Stage-specific work and presentation hooks for one paid lifecycle.

    ``prepare_run`` creates stage-local durable inputs after the exclusive run
    directory exists. ``emit_lifecycle`` receives plain structured events that
    a stage may append to its run log and print. ``emit_row`` owns row
    formatting and may forward the rendered row to the shared terminal renderer.
    """

    run_cell: Callable[[Task, Arm], Mapping[str, Any]]
    validate_row: Callable[[Task, Arm, Mapping[str, Any]], None]
    prepare_run: Callable[[Path], None]
    persist_metadata: Callable[[Path, Mapping[str, Any]], None]
    emit_lifecycle: Callable[[str, Mapping[str, Any]], None]
    emit_row: Callable[[Mapping[str, Any], int, int, Arm], None]
    write_checksums: Callable[[Path], None]
    close_adapter: Callable[[], None]


def write_checksums(run_dir: Path) -> None:
    """Write SHA-256 digests for every retained artifact except the ledger itself."""
    ledger = run_dir / "checksums.sha256"
    files = [path for path in sorted(run_dir.rglob("*")) if path.is_file() and path != ledger]
    entries = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(run_dir).as_posix()}\n" for path in files
    )
    (run_dir / "checksums.sha256").write_text(entries, encoding="utf-8")


def print_unified_paid_command(
    *,
    repo_path: Path,
    manifest_path: Path,
    index_path: Path,
    marketplace_root: Path,
    codemap_bin: Path,
    model: str,
    selectors: Sequence[str],
    scope_sha256: str,
) -> None:
    """Print the exact shell-safe command authorized by a unified dry run."""
    quote = shlex.quote
    run_dir = Path("benchmarks") / "results" / f"codex-unified-{uuid4().hex[:12]}"
    print("PAID_COMMAND")
    print("python3 benchmarks/run-codex-structural.py \\")
    print(f"  --repo-path {quote(str(repo_path.resolve()))} \\")
    print(f"  --manifest-path {quote(str(manifest_path.resolve()))} \\")
    print(f"  --index-path {quote(str(index_path.resolve()))} \\")
    print(f"  --marketplace-root {quote(str(marketplace_root.resolve()))} \\")
    print(f"  --codemap-bin {quote(str(codemap_bin.resolve()))} \\")
    print(f"  --model {quote(model)} \\")
    if selectors:
        print(f"  --tasks {quote(','.join(selectors))} \\")
    print('  --auth-source "$HOME/.codex/auth.json" \\')
    print(f"  --run-dir {quote(str(run_dir))} \\")
    print(f"  --paid-approval {scope_sha256}")


def verify_checksums(run_dir: Path) -> None:
    """Raise when a retained artifact no longer matches the lifecycle ledger."""
    root = run_dir.resolve()
    ledger = root / "checksums.sha256"
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("lifecycle checksum ledger is unavailable") from exc
    for line in lines:
        digest, separator, relative = line.partition("  ")
        if not separator or len(digest) != 64 or not relative:
            raise ValueError("lifecycle checksum ledger contains an invalid entry")
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("lifecycle checksum ledger contains an unsafe path")
        try:
            path = (root / candidate).resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"lifecycle checksum mismatch: {relative}") from exc
        if not path.is_relative_to(root):
            raise ValueError("lifecycle checksum ledger contains an unsafe path")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"lifecycle checksum mismatch: {relative}")


def run_paid_stage(
    *,
    tasks: Sequence[Task],
    arms: Sequence[Arm],
    run_dir: Path,
    metadata: Mapping[str, Any],
    callbacks: PaidStageCallbacks[Task, Arm],
) -> Path:
    """Run, persist, and finalize one exclusive paid stage in task-by-arm order.

    Every successful cell is written and flushed before its metadata progress
    record and presentation callback. Failures retain the preceding cells,
    persist a final error status, refresh checksums, close the adapter, and
    then propagate the original exception.
    """
    run_dir = Path(run_dir)
    lifecycle_metadata = dict(metadata)
    total_cells = len(tasks) * len(arms)
    metadata_path = run_dir / "run-metadata.json"
    telemetry_path = run_dir / "telemetry.jsonl"
    directory_created = False
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
        directory_created = True
        lifecycle_metadata.update(status="running", persisted_cells=0)
        callbacks.persist_metadata(metadata_path, lifecycle_metadata)
        callbacks.prepare_run(run_dir)
        callbacks.emit_lifecycle(
            "artifacts",
            {"metadata_path": str(metadata_path), "telemetry_path": str(telemetry_path)},
        )
        with telemetry_path.open("x", encoding="utf-8") as telemetry:
            for task in tasks:
                for arm in arms:
                    row = callbacks.run_cell(task, arm)
                    callbacks.validate_row(task, arm, row)
                    telemetry.write(json.dumps(dict(row), sort_keys=True) + "\n")
                    telemetry.flush()
                    lifecycle_metadata["persisted_cells"] = int(lifecycle_metadata["persisted_cells"]) + 1
                    callbacks.persist_metadata(metadata_path, lifecycle_metadata)
                    callbacks.emit_row(row, int(lifecycle_metadata["persisted_cells"]), total_cells, arm)
        lifecycle_metadata["status"] = "completed"
        callbacks.persist_metadata(metadata_path, lifecycle_metadata)
        return run_dir
    except BaseException as exc:
        if directory_created:
            lifecycle_metadata["status"] = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
            lifecycle_metadata["error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
            callbacks.persist_metadata(metadata_path, lifecycle_metadata)
        raise
    finally:
        if directory_created:
            callbacks.emit_lifecycle(
                "summary",
                {
                    "persisted_cells": int(lifecycle_metadata.get("persisted_cells", 0)),
                    "status": lifecycle_metadata.get("status", "failed"),
                    "total_cells": total_cells,
                },
            )
            callbacks.write_checksums(run_dir)
        callbacks.close_adapter()


ARM_ROW_STYLES = {
    "A_plain": "yellow",
    "B_direct_required": "cyan",
    "C_skill_required": "magenta",
    "B_auto": "cyan",
    "C_strict": "magenta",
}
ARM_ROW_ANSI_CODES = {
    "A_plain": "33",
    "B_direct_required": "36",
    "C_skill_required": "35",
    "B_auto": "36",
    "C_strict": "35",
}
_DISPLAY_ARM_TO_CANONICAL = {
    "A_plain": "A_plain",
    "B_direct_required": "B_direct_required",
    "C_skill_required": "C_skill_required",
    "B_direct": "B_direct_required",
    "C_skill": "C_skill_required",
    "B_auto": "B_direct_required",
    "C_strict": "C_skill_required",
}
_RESULT_ARM = re.compile(
    r"^\(\d+/\d+\)\s+.*\b(A_plain|B_direct_required|C_skill_required|B_direct|C_skill|B_auto|C_strict)\b"
)
_CONSOLE = Console(highlight=False)
_PROGRESS_PREFIX = re.compile(r"^\((\d+)/(\d+)\)")
_PROGRESS_SCOPE: ContextVar[tuple[int, int] | None] = ContextVar("codex_progress_scope", default=None)
_DISPLAY_ARM_LABELS = {
    "A_plain": "A_plain",
    "B_direct_required": "B_direct",
    "C_skill_required": "C_skill",
}
_DISPLAY_ARM_COLUMN_WIDTH = max(len(label) for label in _DISPLAY_ARM_LABELS.values())


def format_plan_row(task_id: str, repetition: int, arm: str) -> str:
    """Format one deterministic structural coordinate as an aligned terminal row."""
    return f"PLAN    {task_id:<5}  rep={repetition}  {_DISPLAY_ARM_LABELS.get(arm, arm)}"


def format_structural_result_row(
    *,
    status: str,
    task_id: str,
    repetition: int,
    arm: str,
    input_tokens: int,
    cached_input_tokens: int,
    fresh_tokens: int | None,
    output_tokens: int,
    elapsed_s: float,
    quality: str,
    adherence: bool,
    codemap_used: bool,
    query_conformance: bool | None = None,
    headline_eligible: bool | None = None,
) -> str:
    """Format one structural result with stable columns and compact shared units."""
    del cached_input_tokens, fresh_tokens
    query_status = ""
    if query_conformance is not None:
        cohort = "" if headline_eligible is None else ("  cohort:H" if headline_eligible else "  cohort:D")
        query_status = f"  query:{'✓' if query_conformance else '✗'}{cohort}"
    display_arm = _DISPLAY_ARM_LABELS.get(arm, arm)
    return (
        f"{status}  {task_id:<5}  rep={repetition}  {display_arm:<{_DISPLAY_ARM_COLUMN_WIDTH}}"
        f"  in={fmt_tok(input_tokens):>6}"
        f"  out={fmt_tok(output_tokens):>5}  time={fmt_time(elapsed_s):>5}"
        f"  quality={quality:>5}  treatment:{'✓' if adherence else '✗'}  codemap-used:{'✓' if codemap_used else '✗'}"
        f"{query_status}"
    )


@contextmanager
def progress_scope(*, completed_offset: int, total_cells: int) -> Iterator[None]:
    """Map native stage counters onto one aggregate terminal counter.

    The scope changes presentation only. Stage telemetry, metadata, and plain
    run logs retain their native progress coordinates so their checksums and
    standalone interpretation remain independent.

    Args:
        completed_offset: Cells completed by earlier stages.
        total_cells: Total cells across the unified execution.

    Raises:
        ValueError: If the aggregate coordinates cannot contain another cell.
    """
    if (
        type(completed_offset) is not int
        or completed_offset < 0
        or type(total_cells) is not int
        or total_cells <= 0
        or completed_offset >= total_cells
    ):
        raise ValueError("progress scope requires 0 <= completed_offset < total_cells")
    token = _PROGRESS_SCOPE.set((completed_offset, total_cells))
    try:
        yield
    finally:
        _PROGRESS_SCOPE.reset(token)


def _map_progress_row(row: str) -> str:
    """Apply the active aggregate offset to one native terminal row."""
    scope = _PROGRESS_SCOPE.get()
    match = _PROGRESS_PREFIX.match(row)
    if scope is None or match is None:
        return row
    local_completed, local_total = (int(value) for value in match.groups())
    completed_offset, total_cells = scope
    if local_total <= 0 or not 1 <= local_completed <= local_total or completed_offset + local_total > total_cells:
        raise ValueError("native progress row is outside the active aggregate progress scope")
    return f"({completed_offset + local_completed}/{total_cells}){row[match.end() :]}"


def print_arm_row(row: str, arm: str) -> None:
    """Print an arm row with scoped progress and interactive Rich color."""
    row = _map_progress_row(row)
    if _CONSOLE.is_terminal:
        _CONSOLE.print(row, style=ARM_ROW_STYLES[arm], markup=False, soft_wrap=True)
        return
    print(row)


def _result_arm(row: str) -> str | None:
    """Return the canonical arm encoded in one human-readable result row."""
    match = _RESULT_ARM.search(row)
    return _DISPLAY_ARM_TO_CANONICAL.get(match.group(1), match.group(1)) if match else None


def render_result_rows(
    rows: Iterable[str], output: TextIO, *, force_color: bool = False, hide_plan: bool = False
) -> None:
    """Render result rows with rich terminal output and ANSI-free redirected output."""
    use_color = force_color or output.isatty()
    if not use_color:
        for row in rows:
            if not (hide_plan and row.startswith("PLAN ")):
                output.write(row)
        output.flush()
        return

    console = Console(
        file=output,
        force_terminal=use_color,
        color_system="standard" if use_color else None,
        highlight=False,
        markup=False,
        no_color=not use_color,
        legacy_windows=False if force_color else None,
    )
    legend_lines: list[str] | None = None

    def flush_legend() -> None:
        """Render one accumulated plain legend section as a titled Rich panel."""
        nonlocal legend_lines
        if legend_lines is None:
            return
        body = "\n".join(line.rstrip("\r\n") for line in legend_lines[1:-1])
        console.print(Panel(body, title="Legend", subtitle="End legend", border_style="blue"))
        legend_lines = None

    for row in rows:
        if hide_plan and row.startswith("PLAN "):
            continue
        stripped = row.rstrip("\r\n")
        if legend_lines is not None:
            legend_lines.append(row)
            if stripped == "END LEGEND":
                flush_legend()
            continue
        if stripped == "LEGEND":
            legend_lines = [row]
            continue
        arm = _result_arm(row)
        if arm is None:
            output.write(row)
            continue
        if force_color:
            colored_row = f"\x1b[{ARM_ROW_ANSI_CODES[arm]}m{stripped}\x1b[0m\n"
            if output is sys.stdout:
                output.flush()
                os.write(output.fileno(), colored_row.encode("utf-8"))
            else:
                output.write(colored_row)
            continue
        console.print(row.rstrip("\n"), style=ARM_ROW_STYLES[arm], end="\n")
    flush_legend()
    output.flush()
