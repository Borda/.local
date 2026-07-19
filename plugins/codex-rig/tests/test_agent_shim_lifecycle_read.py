"""Acceptance checks for the inert shim lifecycle parsing kernel."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
LIFECYCLE_PATH = PLUGIN_ROOT / "scripts" / "_agent_shim_lifecycle.py"
GENERATOR_PATH = PLUGIN_ROOT / "scripts" / "generate_roles.py"
INSTALL_ID = "123e4567-e89b-42d3-a456-426614174000"
DIGEST = "a" * 64


def load_module(path: Path, name: str) -> ModuleType:
    """Load one installed script module without package assumptions."""
    if path == LIFECYCLE_PATH and "generate_roles" not in sys.modules:
        load_module(GENERATOR_PATH, "generate_roles")
    specification = importlib.util.spec_from_file_location(name, path)
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[name] = module
    specification.loader.exec_module(module)
    return module


def role_ids() -> tuple[str, ...]:
    """Read the canonical roster from the generator implementation."""
    return load_module(GENERATOR_PATH, "codex_rig_generator_roster").ROLE_IDS


def marker_line(role_id: str, *, file_digest: str = DIGEST) -> bytes:
    """Build one exact marker fixture."""
    return (
        "# codex-rig-shim schema=1 plugin=codex-rig "
        f"install_id={INSTALL_ID} role_id={role_id} package_hash=sha256:{DIGEST} "
        f"role_hash=sha256:{file_digest} bootstrap=1 generator=1"
    ).encode()


def root(path: str) -> dict[str, object]:
    """Build one exact persisted root identity."""
    return {"canonical_path": path, "device": 1, "inode": 2, "owner": 3, "group": 4, "mode": "0700"}


def state_payload(*, status: str = "current") -> dict[str, object]:
    """Build one complete valid lifecycle state fixture."""
    roles = role_ids()
    return {
        "schema": 1,
        "plugin": "codex-rig",
        "scope": "user",
        "install_id": INSTALL_ID,
        "plugin_version": "0.2.0",
        "package_hash": DIGEST,
        "codex_home_identity": root("/codex"),
        "plugin_root_identity": root("/plugin"),
        "state_root_identity": root("/codex/codex-rig/shims"),
        "target_root_identity": root("/codex/agents"),
        "roster_hash": DIGEST,
        "bootstrap": {"protocol": 1, "helper_path": "scripts/verify_role_link.py", "helper_hash": DIGEST},
        "generator_version": 1,
        "roles": [
            {
                "role_id": role_id,
                "target_name": f"codex-rig-{role_id}.toml",
                "card_path": f"roles/{role_id}/ROLE.md",
                "role_hash": DIGEST,
                "file_hash": DIGEST,
            }
            for role_id in roles
        ],
        "transaction_status": status,
    }


def encode(value: object) -> bytes:
    """Encode one compact JSON fixture."""
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"value":NaN}',
        b"\xef\xbb\xbf{}",
        b"\xff",
        b"[]",
        b"{} trailing",
    ],
    ids=["duplicate", "nonfinite", "bom", "utf8", "nonobject", "trailing"],
)
def test_strict_json_rejects_hostile_inputs(payload: bytes) -> None:
    """Prevent ambiguous or unbounded JSON from reaching lifecycle authority."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_json")

    with pytest.raises(module.LifecycleDataError):
        module.parse_json_object(payload, maximum=32)


def test_strict_json_converts_bounded_huge_integer_failure() -> None:
    """Keep interpreter integer limits inside the lifecycle error contract."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_huge_integer")
    payload = b'{"value":' + b"9" * 5000 + b"}"

    with pytest.raises(module.LifecycleDataError):
        module.parse_json_object(payload, maximum=len(payload))


def test_strict_json_converts_decoder_recursion_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep decoder recursion failures inside the lifecycle error contract."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_deep_json")

    def raise_recursion(*args: object, **kwargs: object) -> object:
        """Model decoder recursion failure without interpreter-specific depth assumptions."""
        raise RecursionError("fixture recursion limit")

    monkeypatch.setattr(module.json, "loads", raise_recursion)

    with pytest.raises(module.LifecycleDataError) as caught:
        module.parse_json_object(b"{}", maximum=2)

    assert isinstance(caught.value.__cause__, RecursionError)


def test_marker_parser_accepts_current_and_historical_role_ids() -> None:
    """Accept strict role grammar without coupling old ownership to the active roster."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_marker")

    marker = module.parse_marker(marker_line("challenger"))
    historical = module.parse_marker(marker_line("retired-specialist"))

    assert marker == module.Marker(INSTALL_ID, "challenger", DIGEST, DIGEST)
    assert historical.role_id == "retired-specialist"
    for payload in (
        marker_line("challenger") + b"\n",
        marker_line("1unknown"),
        b" " + marker_line("challenger"),
    ):
        with pytest.raises(module.LifecycleDataError):
            module.parse_marker(payload)


def test_state_parser_accepts_complete_current_and_removed_state() -> None:
    """Require exact schema and canonical roster ordering for both statuses."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_state")

    assert module.parse_state(encode(state_payload()))["transaction_status"] == "current"
    assert module.parse_state(encode(state_payload(status="removed")))["transaction_status"] == "removed"
    historical = state_payload()
    historical["roles"] = historical["roles"][:-1]
    assert len(module.parse_state(encode(historical))["roles"]) == len(role_ids()) - 1


@pytest.mark.parametrize(
    "mutation",
    [
        "future",
        "boolean-schema",
        "invalid-version",
        "extra",
        "reordered",
        "bad-root",
        "aliased-root",
        "double-root",
        "control-root",
        "boolean-root",
    ],
)
def test_state_parser_rejects_incompatible_or_partial_state(mutation: str) -> None:
    """Prevent malformed ownership state from authorizing target changes."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_bad_state")
    value = state_payload()
    if mutation == "future":
        value["schema"] = 2
    elif mutation == "boolean-schema":
        value["schema"] = True
    elif mutation == "invalid-version":
        value["plugin_version"] = "02.0"
    elif mutation == "extra":
        value["unexpected"] = True
    elif mutation == "reordered":
        value["roles"][0], value["roles"][1] = value["roles"][1], value["roles"][0]
    elif mutation == "bad-root":
        value["target_root_identity"]["mode"] = "0999"
    elif mutation == "aliased-root":
        value["target_root_identity"]["canonical_path"] = "/codex/../tmp"
    elif mutation == "double-root":
        value["target_root_identity"]["canonical_path"] = "//remote/path"
    elif mutation == "control-root":
        value["target_root_identity"]["canonical_path"] = "/codex/agents\nforeign"
    else:
        value["target_root_identity"]["device"] = True

    with pytest.raises(module.LifecycleDataError):
        module.parse_state(encode(value))


def observations(module: ModuleType, state: dict[str, object] | None, kind: str) -> dict[str, object]:
    """Build one complete target observation roster."""
    result = {}
    for role_id in role_ids():
        name = f"codex-rig-{role_id}.toml"
        marker = module.parse_marker(marker_line(role_id)) if kind == "regular" else None
        result[name] = module.TargetObservation(kind, DIGEST if kind == "regular" else None, marker)
    return result


def test_target_classification_preserves_foreign_modified_and_unsafe() -> None:
    """Separate absent, current, modified, foreign, and unsafe rosters."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_targets")
    parsed = module.parse_state(encode(state_payload()))

    assert module.classify_targets(None, observations(module, None, "absent")) == "absent"
    assert module.classify_targets(None, observations(module, None, "regular")) == "foreign"
    assert module.classify_targets(parsed, observations(module, parsed, "regular")) == "current"
    modified = observations(module, parsed, "regular")
    modified["codex-rig-challenger.toml"] = module.TargetObservation("regular", "b" * 64, None)
    assert module.classify_targets(parsed, modified) == "modified"
    assert module.classify_targets(parsed, observations(module, parsed, "unsafe")) == "unsafe"


def test_target_classification_handles_missing_and_removed_tombstones() -> None:
    """Distinguish repairable absence from removed-state conflicts."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_removed")
    current = module.parse_state(encode(state_payload()))
    removed = module.parse_state(encode(state_payload(status="removed")))
    missing = observations(module, current, "regular")
    missing["codex-rig-challenger.toml"] = module.TargetObservation("absent")

    assert module.classify_targets(current, missing) == "repairable-missing"
    assert module.classify_targets(removed, observations(module, removed, "absent")) == "removed"
    assert module.classify_targets(removed, missing) == "removed-conflict"


def test_recovery_classification_is_single_exact_and_fail_closed() -> None:
    """Reject unknown or competing recovery authority."""
    module = load_module(LIFECYCLE_PATH, "codex_rig_lifecycle_recovery")

    assert module.classify_recovery(()) == "none"
    assert module.classify_recovery((module.RecoveryObservation("journal", True),)) == "journal"
    assert module.classify_recovery((module.RecoveryObservation("probe-receipt", True),)) == "probe-receipt"
    assert module.classify_recovery((module.RecoveryObservation("empty-probe", True, True),)) == "empty-probe"
    assert module.classify_recovery((module.RecoveryObservation("unknown", False),)) == "blocked-unknown"
    assert module.classify_recovery((module.RecoveryObservation("journal", "yes"),)) == "blocked-unknown"
    assert (
        module.classify_recovery(
            (module.RecoveryObservation("journal", True), module.RecoveryObservation("probe-receipt", True))
        )
        == "blocked-multiple"
    )


def test_kernel_has_no_filesystem_mutation_surface() -> None:
    """Keep the parsing kernel structurally incapable of lifecycle writes."""
    source = LIFECYCLE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        ("import", alias.name, alias.asname)
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    imports.extend(
        ("from", node.module, alias.name, alias.asname)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    )
    called_names = {
        node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attributes = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    attribute_names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    loaded_names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    assigned_names = sorted(
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
    )
    definitions = [
        (type(node).__name__, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    argument_names = sorted(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
    exception_bindings = sorted(
        node.name for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler) and node.name is not None
    )

    assert imports == [
        ("import", "json", None),
        ("import", "posixpath", None),
        ("import", "re", None),
        ("import", "uuid", None),
        ("from", "__future__", "annotations", None),
        ("from", "dataclasses", "dataclass", None),
        ("from", "typing", "Any", None),
        ("from", "typing", "NoReturn", None),
        ("from", "generate_roles", "ROLE_IDS", None),
    ]
    assert called_names == {
        "LifecycleDataError",
        "Marker",
        "_digest",
        "_root",
        "_uuid",
        "all",
        "any",
        "dataclass",
        "isinstance",
        "len",
        "ord",
        "parse_json_object",
        "set",
        "str",
        "tuple",
        "type",
        "sorted",
    }
    assert called_attributes == {
        "UUID",
        "append",
        "compile",
        "decode",
        "dumps",
        "fullmatch",
        "get",
        "groups",
        "items",
        "loads",
        "normpath",
        "startswith",
        "values",
    }
    assert attribute_names == {
        "RFC_4122",
        "UUID",
        "append",
        "compile",
        "decode",
        "dumps",
        "empty",
        "exact",
        "file_hash",
        "fullmatch",
        "get",
        "groups",
        "install_id",
        "items",
        "kind",
        "loads",
        "marker",
        "normpath",
        "package_hash",
        "role_hash",
        "role_id",
        "startswith",
        "values",
        "variant",
    }
    assert loaded_names == {
        "Any",
        "BOOTSTRAP_FIELDS",
        "DIGEST",
        "LifecycleDataError",
        "MARKER",
        "MARKER_BYTES",
        "MAX_STATE_ROLES",
        "Marker",
        "NoReturn",
        "ROLE_FIELDS",
        "ROLE_ID",
        "ROLE_IDS",
        "ROOT_FIELDS",
        "RecoveryObservation",
        "RecursionError",
        "SEMVER",
        "STATE_BYTES",
        "STATE_FIELDS",
        "TargetObservation",
        "UnicodeDecodeError",
        "UnicodeError",
        "ValueError",
        "_digest",
        "_reject_constant",
        "_root",
        "_unique_object",
        "_uuid",
        "absent",
        "all",
        "any",
        "bool",
        "bootstrap",
        "bytes",
        "canonical",
        "character",
        "current_names",
        "dataclass",
        "decoded",
        "dict",
        "error",
        "exact",
        "expected_names",
        "field",
        "install_id",
        "int",
        "isinstance",
        "item",
        "json",
        "key",
        "label",
        "len",
        "line",
        "list",
        "marker",
        "match",
        "maximum",
        "name",
        "object",
        "observation",
        "observations",
        "ord",
        "package_hash",
        "pairs",
        "parse_json_object",
        "parsed",
        "path",
        "payload",
        "posixpath",
        "previous",
        "re",
        "record",
        "records",
        "result",
        "role",
        "role_hash",
        "role_id",
        "roles",
        "set",
        "sorted",
        "state",
        "str",
        "targets",
        "text",
        "tuple",
        "type",
        "uuid",
        "value",
    }
    assert assigned_names == [
        "BOOTSTRAP_FIELDS",
        "DIGEST",
        "MARKER",
        "MARKER_BYTES",
        "MAX_STATE_ROLES",
        "ROLE_FIELDS",
        "ROLE_ID",
        "ROOT_FIELDS",
        "SEMVER",
        "STATE_BYTES",
        "STATE_FIELDS",
        "absent",
        "bootstrap",
        "canonical",
        "character",
        "current_names",
        "decoded",
        "empty",
        "exact",
        "exact",
        "expected_names",
        "field",
        "file_hash",
        "install_id",
        "install_id",
        "item",
        "item",
        "item",
        "item",
        "item",
        "key",
        "key",
        "kind",
        "kind",
        "marker",
        "marker",
        "match",
        "name",
        "observation",
        "package_hash",
        "package_hash",
        "parsed",
        "path",
        "previous",
        "previous",
        "record",
        "records",
        "result",
        "role",
        "role_hash",
        "role_hash",
        "role_id",
        "role_id",
        "role_id",
        "role_id",
        "roles",
        "state",
        "text",
        "value",
        "value",
    ]
    assert {"json", "posixpath", "re", "uuid", "dataclass", "Any", "NoReturn", "ROLE_IDS"}.isdisjoint(assigned_names)
    assert definitions == [
        ("ClassDef", "LifecycleDataError"),
        ("ClassDef", "Marker"),
        ("ClassDef", "TargetObservation"),
        ("ClassDef", "RecoveryObservation"),
        ("FunctionDef", "_reject_constant"),
        ("FunctionDef", "_unique_object"),
        ("FunctionDef", "parse_json_object"),
        ("FunctionDef", "_uuid"),
        ("FunctionDef", "_digest"),
        ("FunctionDef", "parse_marker"),
        ("FunctionDef", "_root"),
        ("FunctionDef", "parse_state"),
        ("FunctionDef", "classify_targets"),
        ("FunctionDef", "classify_recovery"),
    ]
    assert argument_names == [
        "label",
        "label",
        "label",
        "line",
        "maximum",
        "observations",
        "pairs",
        "payload",
        "payload",
        "state",
        "targets",
        "value",
        "value",
        "value",
        "value",
    ]
    assert exception_bindings == ["error", "error", "error"]
    assert not any(isinstance(node, ast.Delete) for node in ast.walk(tree))
