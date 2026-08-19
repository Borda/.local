"""Acceptance checks for the bridge's shipped contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
RULES_ROOT = PLUGIN_ROOT / "rules"
SCHEMAS_ROOT = PLUGIN_ROOT / "schemas"

CORE_SCHEMA_PATH = SCHEMAS_ROOT / "envelope.schema.json"
HARNESS_SCHEMA_PATH = SCHEMAS_ROOT / "harness-envelope.schema.json"
MCP_SCHEMA_PATH = SCHEMAS_ROOT / "mcp-tools.schema.json"
MCP_CONFIG_PATH = PLUGIN_ROOT / ".mcp.json"

CORE_FIELDS = {"status", "verdict", "findings", "files_touched", "remaining", "blockers"}
PEER_FIELDS = CORE_FIELDS | {"details"}
HARNESS_ONLY_FIELDS = {
    "model",
    "effort",
    "effort_substituted",
    "cost",
    "tokens",
    "duration_seconds",
    "depth",
    "run_id",
    "incident",
    "session_id",
    "transcript_path",
    "verb",
    "direction",
}


def _read_json(path: Path) -> dict[str, object]:
    """Read one JSON contract object with an exact top-level object assertion."""
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict), f"{path} must contain a JSON object"
    return parsed


def _assert_value_matches_contract(schema: Mapping[str, object], value: object) -> None:
    """Validate fixtures against every JSON-Schema keyword used by bridge contracts."""
    allowed_types = schema.get("type")
    if isinstance(allowed_types, str):
        allowed_types = [allowed_types]
    if allowed_types is not None:
        assert isinstance(allowed_types, list)
        type_matches = {
            "array": isinstance(value, list),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "null": value is None,
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "object": isinstance(value, dict),
            "string": isinstance(value, str),
        }
        assert any(type_matches.get(item, False) for item in allowed_types)

    if "enum" in schema:
        assert value in schema["enum"]
    if "minLength" in schema:
        assert isinstance(value, str)
        assert len(value) >= schema["minLength"]
    if "minimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        assert value >= schema["minimum"]
    if "exclusiveMinimum" in schema and isinstance(value, (int, float)) and not isinstance(value, bool):
        assert value > schema["exclusiveMinimum"]

    if isinstance(value, list):
        if "minItems" in schema:
            assert len(value) >= schema["minItems"]
        if "items" in schema:
            assert isinstance(schema["items"], Mapping)
            for item in value:
                _assert_value_matches_contract(schema["items"], item)

    if not isinstance(value, dict):
        return

    required = schema.get("required", [])
    assert isinstance(required, list)
    assert set(required).issubset(value)
    properties = schema.get("properties", {})
    assert isinstance(properties, Mapping)
    if schema.get("additionalProperties") is False:
        assert set(value).issubset(properties)
    for key, item in value.items():
        if key in properties:
            assert isinstance(properties[key], Mapping)
            _assert_value_matches_contract(properties[key], item)
        elif isinstance(schema.get("additionalProperties"), Mapping):
            _assert_value_matches_contract(schema["additionalProperties"], item)


@pytest.mark.parametrize(
    "relative_path",
    (
        "rules/escalation-policy.md",
        "rules/self-healing.md",
        "rules/envelope.md",
        "rules/recursion-guard.md",
        "rules/prompting.md",
        "schemas/envelope.schema.json",
        "schemas/harness-envelope.schema.json",
        "schemas/mcp-tools.schema.json",
    ),
)
def test_contract_artifacts_exist(relative_path: str) -> None:
    """Prevent runtime dispatch without every declared source-of-truth contract."""
    assert (PLUGIN_ROOT / relative_path).is_file(), relative_path


def test_model_core_schema_accepts_only_model_authored_result() -> None:
    """Prevent model output from claiming harness-observed lifecycle metadata."""
    schema = _read_json(CORE_SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == PEER_FIELDS
    assert set(schema["properties"]) == PEER_FIELDS
    assert schema["properties"]["status"]["enum"] == ["complete", "partial", "blocked"]
    assert PEER_FIELDS.isdisjoint(HARNESS_ONLY_FIELDS)
    assert schema["properties"]["verdict"]["maxLength"] == 500
    for field in ("findings", "files_touched", "remaining", "blockers"):
        assert schema["properties"][field]["maxItems"] == 8
        assert schema["properties"][field]["items"]["maxLength"] == 500
    assert schema["properties"]["details"]["maxItems"] == 32
    assert schema["properties"]["details"]["items"]["maxLength"] == 2000

    _assert_value_matches_contract(
        schema,
        {
            "status": "partial",
            "verdict": "The bounded result is usable.",
            "findings": ["one finding"],
            "files_touched": [],
            "remaining": ["one follow-up"],
            "blockers": [],
            "details": ["one transcript-only detail"],
        },
    )

    with pytest.raises(AssertionError):
        _assert_value_matches_contract(
            schema,
            {
                "status": "timeout",
                "verdict": "wrong layer",
                "findings": [],
                "files_touched": [],
                "remaining": [],
                "blockers": [],
                "details": [],
            },
        )
    with pytest.raises(AssertionError):
        _assert_value_matches_contract(
            schema,
            {
                "status": "complete",
                "verdict": "wrong layer",
                "findings": [],
                "files_touched": [],
                "remaining": [],
                "blockers": [],
                "details": [],
                "cost": 1.0,
            },
        )


def test_harness_schema_adds_observed_metadata_and_terminal_statuses() -> None:
    """Prevent timeout/refusal and telemetry from leaking into the model-core schema."""
    schema = _read_json(HARNESS_SCHEMA_PATH)

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == CORE_FIELDS | HARNESS_ONLY_FIELDS
    assert set(schema["properties"]) == CORE_FIELDS | HARNESS_ONLY_FIELDS
    assert schema["properties"]["status"]["enum"] == ["complete", "partial", "blocked", "timeout", "refused"]

    _assert_value_matches_contract(
        schema,
        {
            "status": "refused",
            "verdict": "Recursion was refused.",
            "findings": [],
            "files_touched": [],
            "remaining": [],
            "blockers": ["recursion-depth"],
            "model": "test-model",
            "effort": "low",
            "effort_substituted": None,
            "cost": None,
            "tokens": {"input": 0, "output": 0},
            "duration_seconds": 0.0,
            "depth": 1,
            "run_id": "run-123",
            "incident": None,
            "session_id": None,
            "transcript_path": ".temp/bridge/raw.txt",
            "verb": "advise",
            "direction": "codex_to_claude",
        },
    )

    with pytest.raises(AssertionError):
        _assert_value_matches_contract(
            schema,
            {
                "status": "complete",
                "verdict": "wrong token count",
                "findings": [],
                "files_touched": [],
                "remaining": [],
                "blockers": [],
                "model": "test-model",
                "effort": "low",
                "effort_substituted": None,
                "cost": 0.0,
                "tokens": {"input": -1},
                "duration_seconds": 0.0,
                "depth": 0,
                "run_id": "run-123",
                "incident": None,
                "session_id": None,
                "transcript_path": ".temp/bridge/raw.txt",
                "verb": "advise",
                "direction": "claude_to_codex",
            },
        )


def test_mcp_input_contract_rejects_unknown_or_incomplete_request_fields() -> None:
    """Prevent an MCP tool from receiving a request the bridge cannot safely route."""
    schema = _read_json(MCP_SCHEMA_PATH)
    definitions = schema["$defs"]
    assert set(definitions) == {"bridge_implement", "bridge_advise", "bridge_review"}
    request = definitions["bridge_advise"]
    assert isinstance(request, Mapping)
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {"task"}
    for definition in definitions.values():
        assert "workspace" not in definition["properties"]
        assert "background" not in definition["properties"]
        assert "session_id" not in definition["properties"]
        assert definition["properties"]["task"]["pattern"] == "\\S"
        assert {"trivial", "none"}.issubset(definition["properties"]["effort"]["enum"])

    _assert_value_matches_contract(
        request,
        {
            "task": "Summarize the local diff.",
            "model": "test-model",
            "effort": "low",
            "depth": 0,
            "run_id": "run-123",
            "timeout_seconds": 120,
            "supported_efforts": ["low", "medium"],
        },
    )
    _assert_value_matches_contract(request, {"task": "Use bridge-owned defaults."})
    _assert_value_matches_contract(request, {"task": "Normalize a documented alias.", "effort": "none"})
    with pytest.raises(AssertionError):
        _assert_value_matches_contract(
            request,
            {
                "task": "unknown field",
                "model": "test-model",
                "effort": "low",
                "depth": 0,
                "run_id": "run-123",
                "surprise": True,
            },
        )


def test_reverse_timeout_limit_leaves_a_response_margin_before_the_mcp_deadline() -> None:
    """Prevent the complete retry policy from outliving the MCP host that returns the envelope."""
    schema = _read_json(MCP_SCHEMA_PATH)
    config = _read_json(MCP_CONFIG_PATH)
    definitions = schema["$defs"]
    timeout_limits = {
        name: definition["properties"]["timeout_seconds"]["maximum"] for name, definition in definitions.items()
    }
    maximum_attempts = {"bridge_implement": 1, "bridge_advise": 2, "bridge_review": 2}

    assert timeout_limits == {
        "bridge_implement": 700,
        "bridge_advise": 350,
        "bridge_review": 350,
    }
    for name, timeout_seconds in timeout_limits.items():
        worst_case = maximum_attempts[name] * (timeout_seconds * 1.2 + 9)
        assert worst_case + 30 < config["mcpServers"]["bridge"]["tool_timeout_sec"]


def test_mcp_python_constants_match_the_shipped_transport_config() -> None:
    """Prevent the server's deadline model from drifting away from the declared MCP config."""
    import sys

    bin_root = PLUGIN_ROOT / "bin"
    if str(bin_root) not in sys.path:
        sys.path.insert(0, str(bin_root))
    import bridge_mcp

    config = _read_json(MCP_CONFIG_PATH)
    schema = _read_json(MCP_SCHEMA_PATH)

    assert bridge_mcp.MCP_HOST_DEADLINE_SECONDS == config["mcpServers"]["bridge"]["tool_timeout_sec"]
    for name, verb in bridge_mcp.TOOL_NAMES.items():
        schema_maximum = schema["$defs"][name]["properties"]["timeout_seconds"]["maximum"]
        assert bridge_mcp.MAX_MCP_TIMEOUT_SECONDS_BY_VERB[verb] == schema_maximum


@pytest.mark.parametrize(
    ("filename", "required_paragraphs"),
    (
        (
            "escalation-policy.md",
            (
                "A caller-supplied unknown level is rejected before spawning a child.",
                "Soft budgets are advise 120 seconds, review 300 seconds, and implement 600 seconds.",
                "Implement never retries automatically because edits may have landed.",
            ),
        ),
        (
            "self-healing.md",
            (
                "A bridge call performs at most one remedy.",
                "Timeout retry is limited to read-only verbs; implement is reported with its partial transcript and workspace delta.",
            ),
        ),
        (
            "envelope.md",
            (
                "The bridge has two validation boundaries.",
                "The public envelope status may additionally be `timeout` or `refused`.",
            ),
        ),
        (
            "recursion-guard.md",
            (
                "A caller may report a greater depth but cannot lower the inherited value, and negative depth is rejected.",
                "A host receiving trusted depth one or greater returns `refused: recursion-depth` without dispatching a peer.",
            ),
        ),
        (
            "prompting.md",
            (
                "Every dispatched task starts with its soft budget, the current depth, and the run identifier.",
                "report inaccessible resources or approvals in `blockers` instead of waiting.",
            ),
        ),
    ),
)
def test_contract_rules_keep_each_behavioral_invariant(filename: str, required_paragraphs: tuple[str, ...]) -> None:
    """Prevent prose contracts from dropping a complete dispatch-safety invariant."""
    text = (RULES_ROOT / filename).read_text(encoding="utf-8")
    for paragraph in required_paragraphs:
        assert paragraph in text, f"{filename}: missing invariant {paragraph!r}"
