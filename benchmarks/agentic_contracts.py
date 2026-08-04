"""Score labelled agentic answers against an independent AST oracle.

The module deliberately contains the provider-neutral answer contract only.
Provider runners own transport, JSON extraction, and legacy result rendering;
they pass an already parsed answer mapping to :func:`score_answer`.
"""

from __future__ import annotations

import ast
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

try:
    from provider_parity_contracts import materialize_task_prompt
except ModuleNotFoundError:
    from benchmarks.provider_parity_contracts import materialize_task_prompt


AGENTIC_ARMS = ("A_plain", "B_auto", "C_required")
DEFAULT_REPETITIONS = 1

_ANSWER_FIELDS = frozenset(
    {
        "production_importers",
        "rdep_counts",
        "ranking",
        "buckets",
        "overlap_importers",
        "overlap_count",
        "cross_namespace_importers",
        "dependency_chain",
        "affected_module_count",
        "production_importer_count",
        "excluded_test_importer_count",
        "test_importer_count",
        "isolation_verdict",
        "risk_tier",
        "high_centrality",
    }
)
_PARAMETERIZED_FIELDS = frozenset(
    {
        "ranking",
        "buckets",
        "overlap_importers",
        "overlap_count",
        "cross_namespace_importers",
        "dependency_chain",
        "affected_module_count",
        "high_centrality",
    }
)
_CANDIDATE_SETS = frozenset({"production_importers", "non_migrated_importers", "helper_dependent_importers"})


@dataclass(frozen=True)
class _SourceModule:
    """One successfully parsed local module used by the independent oracle."""

    name: str
    path: Path
    is_test: bool
    is_package: bool
    imports: frozenset[str]
    names: frozenset[str]


@dataclass(frozen=True)
class AgenticOracle:
    """Independent expected values for one task's declared answer fields."""

    task_id: str
    fields: tuple[str, ...]
    expected: Mapping[str, Any]


@dataclass(frozen=True)
class AnswerScore:
    """Deterministic component and aggregate score for one labelled answer."""

    scored: bool
    quality_score: float
    correct: bool
    components: Mapping[str, float]
    erec: float
    rrec: float
    deff: float


def validate_answer_contract(task: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and return the closed answer contract embedded in one task.

    The suite controls only a bounded list of output fields and their small
    fixed parameter shapes. Unknown fields or knobs fail before a provider can
    execute a differently scored experiment.
    """
    contract = task.get("answer_contract")
    if not isinstance(contract, Mapping):
        raise ValueError("task answer_contract must be an object")
    fields = contract.get("fields")
    params = contract.get("params", {})
    if not isinstance(fields, list) or not fields or any(not isinstance(field, str) for field in fields):
        raise ValueError("answer_contract fields must be a non-empty string list")
    if len(set(fields)) != len(fields) or any(field not in _ANSWER_FIELDS for field in fields):
        raise ValueError("answer_contract fields contain an unknown or duplicate field")
    if not isinstance(params, Mapping) or any(not isinstance(field, str) for field in params):
        raise ValueError("answer_contract params must be an object")
    if any(field not in fields or field not in _PARAMETERIZED_FIELDS for field in params):
        raise ValueError("answer_contract params are only allowed for declared parameterized fields")
    for field in fields:
        if field in _PARAMETERIZED_FIELDS and field not in params:
            raise ValueError(f"answer_contract field {field!r} requires params")
    for field, value in params.items():
        _validate_field_params(field, value)
    return MappingProxyType({"fields": tuple(fields), "params": MappingProxyType(dict(params))})


def answer_format_instruction(task: Mapping[str, Any]) -> str:
    """Return the exact labelled JSON envelope required for one task response."""
    contract = validate_answer_contract(task)
    labels = ", ".join(contract["fields"])
    return (
        "Return one JSON object containing exactly these labels: "
        f"{labels}. Put it between literal lines BEGIN_ANSWER_JSON and END_ANSWER_JSON."
    )


def materialize_agentic_prompt(task: Mapping[str, Any]) -> str:
    """Return shared task bytes plus the scored labelled-answer instruction."""
    prompt = materialize_task_prompt(task)
    if "answer_contract" not in task:
        return prompt
    return f"{prompt}\n\n{answer_format_instruction(task)}"


def parse_labeled_answer(task: Mapping[str, Any], text: str) -> dict[str, Any]:
    """Parse the one exact labelled JSON answer required by a task contract.

    The ``EMPTY`` marker is accepted only for collection fields and converted
    to the corresponding explicit JSON collection. Missing or additional
    labels fail closed, so a runner never scores partial prose as an answer.
    """
    contract = validate_answer_contract(task)
    if not isinstance(text, str):
        raise TypeError("labelled answer text must be a string")
    start = "BEGIN_ANSWER_JSON"
    end = "END_ANSWER_JSON"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("answer requires exactly one BEGIN_ANSWER_JSON and END_ANSWER_JSON envelope")
    before, payload = text.split(start, maxsplit=1)
    payload, after = payload.split(end, maxsplit=1)
    if start in payload or end in payload or not payload.strip():
        raise ValueError("answer JSON envelope is malformed")
    try:
        answer = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"answer JSON is invalid: {exc.msg}") from exc
    if not isinstance(answer, dict):
        raise ValueError("answer JSON must be an object")
    fields = set(contract["fields"])
    if set(answer) != fields:
        missing = sorted(fields - set(answer))
        extra = sorted(set(answer) - fields)
        raise ValueError(f"answer labels differ from contract; missing={missing}, extra={extra}")
    for field, value in tuple(answer.items()):
        if value == "EMPTY":
            if field in {
                "production_importers",
                "overlap_importers",
                "cross_namespace_importers",
                "high_centrality",
                "ranking",
                "dependency_chain",
            }:
                answer[field] = []
            elif field in {"rdep_counts", "buckets"}:
                answer[field] = {}
            else:
                raise ValueError(f"answer field {field!r} does not accept EMPTY")
    return answer


def build_oracle(task: Mapping[str, Any], source_root: Path) -> AgenticOracle:
    """Build expected answer values from a source-only, provider-independent AST scan.

    Parse failures and dynamic imports never enter the graph. Production direct
    importers exclude test modules and the target module itself, while test
    importers remain available for explicitly requested count fields.
    """
    contract = validate_answer_contract(task)
    task_id = task.get("id")
    primary_module = task.get("primary_module")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("task id must be a non-empty string")
    if not isinstance(primary_module, str) or not primary_module:
        raise ValueError("task primary_module must be a non-empty string")
    modules = _scan_modules(Path(source_root))
    reverse_imports = _reverse_imports(modules)
    production = tuple(
        sorted(
            name
            for name in reverse_imports.get(primary_module, set())
            if not modules[name].is_test and name != primary_module
        )
    )
    tests = tuple(
        sorted(
            name
            for name in reverse_imports.get(primary_module, set())
            if modules[name].is_test and name != primary_module
        )
    )
    production_rdeps = {
        name: len(
            [
                importer
                for importer in reverse_imports.get(name, set())
                if not modules[importer].is_test and importer != name
            ]
        )
        for name in production
    }
    expected = _expected_values(
        task,
        contract,
        modules,
        reverse_imports,
        production,
        tests,
        production_rdeps,
    )
    return AgenticOracle(task_id=task_id, fields=contract["fields"], expected=MappingProxyType(expected))


def score_answer(
    oracle: AgenticOracle,
    answer: Mapping[str, Any],
    *,
    exposure_text: str = "",
    report_text: str = "",
    tool_calls: int = 0,
) -> AnswerScore:
    """Score a parsed labelled answer with fixed component and tie rules.

    Set fields use recall, mappings use correct-pair fraction, rankings use
    position fraction, and scalar/path fields require exact equality. Empty
    expected collections receive credit only from an explicit empty collection.
    """
    if not isinstance(answer, Mapping):
        raise TypeError("answer must be a mapping parsed from the labelled JSON envelope")
    components: dict[str, float] = {}
    for field in oracle.fields:
        expected = oracle.expected[field]
        actual = answer.get(field)
        if field in {"production_importers", "overlap_importers", "cross_namespace_importers", "high_centrality"}:
            components[field] = _set_recall(expected, actual)
        elif field in {"rdep_counts", "buckets"}:
            components[field] = _mapping_fraction(expected, actual)
        elif field == "ranking":
            components[field] = _ranking_fraction(expected, actual)
        else:
            components[field] = 1.0 if _same_value(expected, actual) else 0.0
    if not isinstance(exposure_text, str) or not isinstance(report_text, str):
        raise TypeError("exposure_text and report_text must be strings")
    if isinstance(tool_calls, bool) or not isinstance(tool_calls, int) or tool_calls < 0:
        raise ValueError("tool_calls must be a non-negative integer")
    expected_importers = oracle.expected.get("production_importers", ())
    expected_count = max(len(expected_importers), 1)
    exposure_hits = sum(name in exposure_text for name in expected_importers)
    report_hits = sum(name in report_text for name in expected_importers)
    quality_score = sum(components.values()) / len(components)
    return AnswerScore(
        scored=True,
        quality_score=quality_score,
        correct=all(component == 1.0 for component in components.values()),
        components=MappingProxyType(components),
        erec=exposure_hits / expected_count,
        rrec=report_hits / expected_count,
        deff=exposure_hits / max(tool_calls, 1),
    )


def _validate_field_params(field: str, params: Any) -> None:
    """Reject parameter shapes outside the reviewed closed answer schema."""
    if not isinstance(params, Mapping):
        raise ValueError(f"answer_contract {field} params must be an object")
    keys = set(params)
    if field == "ranking":
        permitted = {"candidate_set", "top_k"}
        if (
            keys - {"candidate_set", "top_k", "exclude_overlap_targets", "min_rdep_count"}
            or not permitted <= keys
            or params["candidate_set"] not in _CANDIDATE_SETS
        ):
            raise ValueError("ranking params require a supported candidate_set and top_k")
        if isinstance(params["top_k"], bool) or not isinstance(params["top_k"], int) or params["top_k"] < 1:
            raise ValueError("ranking top_k must be a positive integer")
        targets = params.get("exclude_overlap_targets")
        if targets is not None and (
            params["candidate_set"] != "non_migrated_importers"
            or not isinstance(targets, list)
            or not targets
            or not all(isinstance(target, str) and target for target in targets)
        ):
            raise ValueError("ranking exclude_overlap_targets is only valid for non_migrated_importers")
        minimum = params.get("min_rdep_count")
        if minimum is not None and (isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0):
            raise ValueError("ranking min_rdep_count must be a non-negative integer")
        return
    if field == "buckets":
        labels = params.get("labels")
        if (
            keys != {"labels"}
            or not isinstance(labels, list)
            or not labels
            or not all(isinstance(label, str) and label for label in labels)
        ):
            raise ValueError("buckets params require non-empty labels")
        return
    if field in {"overlap_importers", "overlap_count", "cross_namespace_importers"}:
        if keys == {"prefix"} and isinstance(params["prefix"], str) and params["prefix"]:
            return
        if (
            field in {"overlap_importers", "overlap_count"}
            and keys == {"targets"}
            and isinstance(params["targets"], list)
            and all(isinstance(target, str) and target for target in params["targets"])
        ):
            return
        raise ValueError(f"{field} params require one non-empty prefix or targets list")
    if field == "dependency_chain":
        if keys == {"source", "target"} and all(isinstance(params[key], str) and params[key] for key in keys):
            return
        raise ValueError("dependency_chain params require source and target")
    if field in {"affected_module_count", "high_centrality"}:
        minimum = params.get("min_rdep_count")
        if keys == {"min_rdep_count"} and not isinstance(minimum, bool) and isinstance(minimum, int) and minimum >= 0:
            return
        raise ValueError(f"{field} params require non-negative min_rdep_count")
    raise ValueError(f"unsupported answer_contract parameterized field {field!r}")


def _scan_modules(source_root: Path) -> dict[str, _SourceModule]:
    """Parse local Python files once, retaining only statically resolved imports."""
    paths = sorted(
        path
        for path in source_root.rglob("*.py")
        if not any(part.startswith(".") for part in path.relative_to(source_root).parts)
    )
    names_by_path = {path: _module_name(path, source_root) for path in paths}
    names_by_path = {path: name for path, name in names_by_path.items() if name}
    all_names = set(names_by_path.values())
    modules: dict[str, _SourceModule] = {}
    for path, name in names_by_path.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        imports = _import_targets(tree, name, path.name == "__init__.py", all_names)
        parts = path.relative_to(source_root).parts
        modules[name] = _SourceModule(
            name=name,
            path=path,
            is_test=any(_is_test_path_part(part) for part in parts),
            is_package=path.name == "__init__.py",
            imports=frozenset(imports - {name}),
            names=frozenset(
                [node.id for node in ast.walk(tree) if isinstance(node, ast.Name)]
                + [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
                + [
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                ]
            ),
        )
    return modules


def _module_name(path: Path, source_root: Path) -> str:
    """Return the source-root-relative dotted module name for one Python file."""
    parts = list(path.relative_to(source_root).with_suffix("").parts)
    if parts[:1] == ["src"]:
        parts.pop(0)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_test_path_part(part: str) -> bool:
    """Return whether one source path component belongs to an explicit test root."""
    stem = Path(part).stem
    return stem in {"test", "tests"} or stem.startswith(("test_", "tests_"))


def _import_targets(tree: ast.Module, module: str, is_package: bool, all_names: set[str]) -> set[str]:
    """Resolve static import statements to known local module names only."""
    package = module if is_package else module.rpartition(".")[0]
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names if alias.name in all_names)
        elif isinstance(node, ast.ImportFrom):
            base = _relative_import_base(node, package)
            if not base:
                continue
            concrete_targets = set()
            for alias in node.names:
                candidate = f"{base}.{alias.name}"
                if candidate in all_names:
                    concrete_targets.add(candidate)
            if concrete_targets:
                targets.update(concrete_targets)
            elif base in all_names:
                targets.add(base)
    return targets


def _relative_import_base(node: ast.ImportFrom, package: str) -> str:
    """Resolve an ``ImportFrom`` base without guessing dynamic package state."""
    if node.level == 0:
        return node.module or ""
    package_parts = package.split(".") if package else []
    if node.level > len(package_parts) + 1:
        return ""
    prefix = package_parts[: len(package_parts) - (node.level - 1)]
    if node.module:
        prefix.extend(node.module.split("."))
    return ".".join(prefix)


def _reverse_imports(modules: Mapping[str, _SourceModule]) -> dict[str, set[str]]:
    """Invert statically parsed module imports into a reverse graph."""
    reverse: dict[str, set[str]] = defaultdict(set)
    for module in modules.values():
        for imported in module.imports:
            reverse[imported].add(module.name)
    return reverse


def _expected_values(
    task: Mapping[str, Any],
    contract: Mapping[str, Any],
    modules: Mapping[str, _SourceModule],
    reverse_imports: Mapping[str, set[str]],
    production: tuple[str, ...],
    tests: tuple[str, ...],
    production_rdeps: Mapping[str, int],
) -> dict[str, Any]:
    """Materialize each declared field from one fixed AST graph and contract."""
    params = contract["params"]
    expected: dict[str, Any] = {}
    for field in contract["fields"]:
        if field == "production_importers":
            expected[field] = production
        elif field == "test_importer_count":
            expected[field] = len(tests)
        elif field == "excluded_test_importer_count":
            expected[field] = len(tests)
        elif field == "production_importer_count":
            expected[field] = len(production)
        elif field == "rdep_counts":
            expected[field] = dict(production_rdeps)
        elif field == "ranking":
            candidate_set = _candidate_set(params[field], production, modules, production_rdeps)
            minimum = params[field].get("min_rdep_count", 0)
            ranked = (name for name in candidate_set if production_rdeps.get(name, 0) >= minimum)
            expected[field] = tuple(
                sorted(ranked, key=lambda name: (-production_rdeps.get(name, 0), name))[: params[field]["top_k"]]
            )
        elif field == "buckets":
            expected[field] = _bucket_values(params[field]["labels"], production, modules)
        elif field == "overlap_importers":
            expected[field] = _overlap_importers(production, modules, task["primary_module"], params[field])
        elif field == "overlap_count":
            expected[field] = len(_overlap_importers(production, modules, task["primary_module"], params[field]))
        elif field == "cross_namespace_importers":
            prefix = params[field]["prefix"]
            expected[field] = tuple(name for name in production if name.startswith(prefix))
        elif field == "dependency_chain":
            expected[field] = _shortest_chain(modules, params[field]["source"], params[field]["target"])
        elif field == "affected_module_count":
            minimum = params[field]["min_rdep_count"]
            affected = set(production)
            for importer in production:
                if production_rdeps[importer] >= minimum:
                    affected.update(name for name in reverse_imports.get(importer, set()) if not modules[name].is_test)
            expected[field] = len(affected)
        elif field == "high_centrality":
            minimum = params[field]["min_rdep_count"]
            expected[field] = tuple(
                name
                for name in sorted(production, key=lambda name: (-production_rdeps[name], name))
                if production_rdeps[name] >= minimum
            )
        elif field == "isolation_verdict":
            expected[field] = (
                "isolated" if all(count <= 5 for count in production_rdeps.values()) else "widely-imported"
            )
        elif field == "risk_tier":
            audited = task.get("audited_risk_tier")
            if audited not in {"low", "medium", "high", "critical"}:
                raise ValueError("risk_tier requires an audited_risk_tier task value")
            expected[field] = audited
        else:
            raise ValueError(f"unsupported answer_contract field {field!r}")
    return expected


def _candidate_set(
    params: Mapping[str, Any],
    production: tuple[str, ...],
    modules: Mapping[str, _SourceModule],
    production_rdeps: Mapping[str, int],
) -> tuple[str, ...]:
    """Return one reviewed named ranking candidate set."""
    name = params["candidate_set"]
    if name == "production_importers":
        return production
    if name == "helper_dependent_importers":
        return tuple(module for module in production if "_lr_find" in modules[module].names)
    if name == "non_migrated_importers":
        migrated_targets = set(params["exclude_overlap_targets"])
        return tuple(module for module in production if not (modules[module].imports & migrated_targets))
    raise ValueError(f"unsupported ranking candidate_set {name!r}")


def _bucket_values(
    labels: list[str], production: tuple[str, ...], modules: Mapping[str, _SourceModule]
) -> dict[str, tuple[str, ...]]:
    """Classify only the task labels explicitly admitted by the suite schema."""
    buckets: dict[str, tuple[str, ...]] = {}
    for label in labels:
        if label == "trainer-core":
            values = tuple(name for name in production if name.startswith("lightning.pytorch.trainer"))
        elif label == "callbacks":
            values = tuple(name for name in production if name.startswith("lightning.pytorch.callbacks"))
        elif label == "everything-else":
            values = tuple(
                name
                for name in production
                if not name.startswith(("lightning.pytorch.trainer", "lightning.pytorch.callbacks"))
            )
        elif label == "public":
            values = tuple(name for name in production if modules[name].is_package)
        elif label == "internal":
            values = tuple(name for name in production if not modules[name].is_package)
        elif label == "helper-dependent":
            values = tuple(name for name in production if "_lr_find" in modules[name].names)
        elif label == "class-only":
            values = tuple(name for name in production if "_lr_find" not in modules[name].names)
        else:
            raise ValueError(f"unsupported bucket label {label!r}")
        buckets[label] = values
    return buckets


def _overlap_importers(
    production: tuple[str, ...],
    modules: Mapping[str, _SourceModule],
    primary_module: str,
    params: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return production importers that also statically import the requested target family."""
    if "targets" in params:
        targets = set(params["targets"])
        return tuple(name for name in production if modules[name].imports & targets)
    prefix = params["prefix"]
    return tuple(
        name
        for name in production
        if any(imported != primary_module and imported.startswith(prefix) for imported in modules[name].imports)
    )


def _shortest_chain(modules: Mapping[str, _SourceModule], source: str, target: str) -> tuple[str, ...]:
    """Return the lexically tie-broken shortest static dependency path, or empty."""
    if source not in modules or target not in modules:
        return ()
    queue: deque[tuple[str, ...]] = deque([(source,)])
    visited = {source}
    while queue:
        path = queue.popleft()
        current = path[-1]
        if current == target:
            return path
        for dependency in sorted(modules[current].imports):
            if dependency not in visited:
                visited.add(dependency)
                queue.append((*path, dependency))
    return ()


def _set_recall(expected: Any, actual: Any) -> float:
    """Score an explicit list as set F1, including the empty-set contract."""
    if not isinstance(actual, list) or not all(isinstance(item, str) for item in actual):
        return 0.0
    expected_set = set(expected)
    if not expected_set:
        return 1.0 if actual == [] else 0.0
    actual_set = set(actual)
    true_positive = len(expected_set & actual_set)
    return 2 * true_positive / (len(expected_set) + len(actual_set))


def _mapping_fraction(expected: Any, actual: Any) -> float:
    """Score exact key/value pairs with F1 and explicit empty-object handling."""
    if not isinstance(actual, Mapping):
        return 0.0
    if not expected:
        return 1.0 if dict(actual) == {} else 0.0
    true_positive = sum(1 for key, value in expected.items() if key in actual and _same_value(value, actual[key]))
    return 2 * true_positive / (len(expected) + len(actual))


def _ranking_fraction(expected: Any, actual: Any) -> float:
    """Score each ranking slot against the deterministic no-expansion ordering."""
    if not isinstance(actual, list) or not all(isinstance(item, str) for item in actual):
        return 0.0
    if not expected:
        return 1.0 if actual == [] else 0.0
    return sum(index < len(actual) and actual[index] == value for index, value in enumerate(expected)) / len(expected)


def _same_value(expected: Any, actual: Any) -> bool:
    """Compare scalar or path values without accepting bool-as-int aliases."""
    if isinstance(expected, tuple):
        return isinstance(actual, list) and tuple(actual) == expected
    return type(actual) is type(expected) and actual == expected
