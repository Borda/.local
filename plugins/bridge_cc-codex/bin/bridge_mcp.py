"""Expose reverse bridge calls through a portable stdio MCP server.

Purpose: Let a Codex-installed bridge hand work to a locally authenticated Claude
CLI without invoking that CLI from the model sandbox. Scope: The module speaks
the small JSON-RPC subset needed by stdio MCP clients: initialize, the
initialized notification, tools/list, and tools/call. It defines implement,
advise, and review tools, validates request arguments at the transport edge,
and calls the shared Python supervisor for execution and artifact handling.
Usage: Start ``bridge_mcp.py --stdio`` from the installed plugin's MCP config.
The process reads one JSON-RPC object per stdin line and emits one response line
per request that has an id. Outputs: A successful tool call returns one compact
public bridge envelope in a text content item; protocol errors are JSON-RPC
errors and never corrupt stdout with diagnostics. Failure: Invalid messages,
unknown tools, malformed request values, and child failures are returned as
structured protocol or envelope errors. Used by: Codex-facing implement, advise,
and review skills through the bridge plugin's stdio MCP declaration. This server
uses only Python's standard library and imports bridge_call from its own bin
directory, so it remains valid after the plugin is installed outside this repo.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import uuid
from typing import Any

# Keep sibling imports valid when repository-wide doctest collection imports this
# file without launching it as a script from its installed ``bin`` directory.
_BIN_DIRECTORY = str(Path(__file__).resolve().parent)
if _BIN_DIRECTORY not in sys.path:
    sys.path.insert(0, _BIN_DIRECTORY)

from bridge_call import (  # noqa: E402
    CHILD_TIMEOUT_MULTIPLIER,
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUTS,
    Request,
    run_request,
)


MCP_HOST_DEADLINE_SECONDS = 900.0
MCP_RESPONSE_MARGIN_SECONDS = 30.0
# Worst-case per-attempt supervision overhead beyond the hard cutoff: the 2 s
# SIGTERM grace in _terminate_process_group plus the 5 s + 2 s bounded drain.
TERMINATION_DRAIN_SECONDS = 9.0
MAX_MCP_TIMEOUT_SECONDS_BY_VERB = {
    "implement": 700.0,
    "advise": 350.0,
    "review": 350.0,
}
_MAX_ATTEMPTS_BY_VERB = {"implement": 1, "advise": 2, "review": 2}
for _verb, _cap in MAX_MCP_TIMEOUT_SECONDS_BY_VERB.items():
    _attempts = _MAX_ATTEMPTS_BY_VERB[_verb]
    _worst_case = _attempts * (_cap * CHILD_TIMEOUT_MULTIPLIER + TERMINATION_DRAIN_SECONDS)
    if _worst_case + MCP_RESPONSE_MARGIN_SECONDS > MCP_HOST_DEADLINE_SECONDS:
        raise ValueError(f"MCP timeout cap for {_verb} cannot fit inside the host deadline")
TOOL_NAMES = {
    "bridge_implement": "implement",
    "bridge_advise": "advise",
    "bridge_review": "review",
}


def tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool definitions with one explicit schema per bridge verb."""
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "mcp-tools.schema.json"
    definitions = json.loads(schema_path.read_text(encoding="utf-8"))["$defs"]
    return [
        {
            "name": name,
            "description": f"Run a bounded {verb} bridge request through Claude.",
            "inputSchema": definitions[name],
        }
        for name, verb in TOOL_NAMES.items()
    ]


def handle_message(message: dict[str, Any], *, trusted_workspace: Path | None = None) -> dict[str, Any] | None:
    """Handle one JSON-RPC request or notification and return its response."""
    # JSON-RPC 2.0 forbids responding to a notification, so id-lessness must
    # short-circuit before any validation can produce an error response.
    notification = "id" not in message
    if message.get("jsonrpc") != "2.0":
        return None if notification else _error(None, -32600, "invalid request: jsonrpc must be 2.0")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        return None if notification else _error(None, -32600, "invalid request: method must be a non-empty string")
    if "params" in message and not isinstance(message["params"], (dict, list)):
        return None if notification else _error(None, -32600, "invalid request: params must be an object or array")
    if notification:
        return None
    request_id = message["id"]
    if (
        isinstance(request_id, bool)
        or not isinstance(request_id, (str, int, float, type(None)))
        or isinstance(request_id, float)
        and not math.isfinite(request_id)
    ):
        return _error(None, -32600, "invalid request: id must be a string, number, or null")
    if method == "notifications/initialized":
        # A conforming client sends this without an id; acknowledge a
        # malformed id-bearing variant instead of leaving the request hanging.
        return _result(request_id, {})
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bridge", "version": "0.2.1"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": tool_definitions()})
    if method == "tools/call":
        return _call_tool(request_id, message.get("params"), trusted_workspace or Path.cwd())
    return _error(request_id, -32601, f"method not found: {method}")


def _call_tool(request_id: Any, params: Any, trusted_workspace: Path) -> dict[str, Any]:
    """Validate tool arguments and execute a reverse bridge request."""
    if not isinstance(params, dict):
        return _error(request_id, -32602, "tools/call params must be an object")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str) or not name:
        return _error(request_id, -32602, "bridge tool name must be a non-empty string")
    if name not in TOOL_NAMES:
        return _error(request_id, -32602, f"unknown bridge tool: {name}")
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "tool arguments must be an object")
    try:
        request = _request_from_arguments(TOOL_NAMES[name], arguments, trusted_workspace)
    except ValueError as error:
        return _error(request_id, -32602, str(error))
    try:
        envelope = run_request(request, host="claude")
    except (OSError, ValueError):
        return _error(request_id, -32603, "bridge execution failed")
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(envelope, sort_keys=True)}],
            "isError": envelope["status"] in {"blocked", "timeout", "refused"},
        },
    )


def _request_from_arguments(verb: str, arguments: dict[str, Any], trusted_workspace: Path) -> Request:
    """Create a reverse-direction request from MCP tool arguments."""
    allowed = {"task", "model", "effort", "timeout_seconds", "depth", "run_id", "supported_efforts"}
    extra = set(arguments) - allowed
    if extra:
        raise ValueError(f"unsupported tool arguments: {', '.join(sorted(extra))}")
    task = arguments.get("task")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task must be a non-empty string")
    depth = arguments.get("depth", 0)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
        raise ValueError("depth must be a non-negative integer")
    timeout = arguments.get("timeout_seconds", DEFAULT_TIMEOUTS[verb])
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_seconds must be a finite positive number")
    maximum_timeout = MAX_MCP_TIMEOUT_SECONDS_BY_VERB[verb]
    if timeout > maximum_timeout:
        raise ValueError(f"timeout_seconds must not exceed {maximum_timeout:g} seconds for {verb}")
    for name in ("model", "effort", "run_id"):
        value = arguments.get(name)
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f"{name} must be a non-empty string")
    supported = arguments.get("supported_efforts", [])
    if not isinstance(supported, list) or not all(isinstance(item, str) and item for item in supported):
        raise ValueError("supported_efforts must be an array of non-empty strings")
    if "supported_efforts" in arguments and not supported:
        raise ValueError("supported_efforts must not be empty when supplied")
    workspace = trusted_workspace.resolve()
    if verb == "implement" and workspace in _refused_write_roots(workspace):
        raise ValueError(
            "write-capable bridge calls need a project workspace; the MCP host launched this server "
            "from the user home or a filesystem root"
        )
    return Request(
        verb,
        task,
        arguments.get("model", DEFAULT_MODEL),
        arguments.get("effort", DEFAULT_EFFORT),
        float(timeout),
        depth,
        arguments.get("run_id", str(uuid.uuid4())),
        workspace,
        "codex_to_claude",
        False,
        None,
        None,
        tuple(supported),
    )


def _refused_write_roots(workspace: Path) -> set[Path]:
    """Return the launch directories too broad to root an acceptEdits run.

    ``Path.home`` can raise on hosts with no home resolution (minimal
    containers); an unknown home must not crash the server, only narrow the
    refusal set to the filesystem root.
    """
    roots = {Path(workspace.anchor)}
    try:
        roots.add(Path.home().resolve())
    except (OSError, RuntimeError):
        pass
    return roots


def _result(request_id: Any, value: dict[str, Any]) -> dict[str, Any]:
    """Build one JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """Build one JSON-RPC error response without leaking traceback details."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve() -> int:
    """Serve newline-delimited JSON-RPC over standard input and output."""
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            response = _error(None, -32700, f"parse error: {error.msg}")
        else:
            response = (
                handle_message(message)
                if isinstance(message, dict)
                else _error(None, -32600, "invalid request: request must be an object")
            )
        if response is not None:
            sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
            sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the MCP server only when the explicit stdio mode is selected."""
    parser = argparse.ArgumentParser(description="Run the bridge stdio MCP server.")
    parser.add_argument("--stdio", action="store_true", required=True)
    parser.parse_args(argv)
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
