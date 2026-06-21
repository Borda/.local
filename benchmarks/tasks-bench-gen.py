#!/usr/bin/env python3
"""Ground truth generator and validator for benchmarks/tasks-bench.json.

Runs the scan-query commands implied by each task and validates (or refreshes)
the ground_truth dict stored in the task file.

Usage:
    # Validate all tasks against live index
    python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir>

    # Validate a single task
    python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir> --task SE-01

    # Refresh ground truth from live scan-query output
    python benchmarks/tasks-bench-gen.py --repo-path ./<repo-dir> --update

Requirements:
    - repo clone with a pre-built codemap index (see tasks-bench.json "repo.default_path")
    - scan-query on PATH or at plugins/codemap/bin/scan-query
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

TASKS_FILE = Path(__file__).parent / "tasks-bench.json"


# ---- BINARY RESOLUTION ----


def find_codemap_bin(name: str, plugin_root: Path | None = None) -> Path | None:
    """Locate a codemap CLI binary by PATH lookup or plugin directory fallback.

    Args:
        name: Binary name to find (e.g. "scan-query").
        plugin_root: Optional project root containing plugins/codemap/bin/.

    Returns:
        Resolved path or None if not found.
    """
    which = shutil.which(name)
    if which:
        return Path(which)
    if plugin_root:
        candidate = plugin_root / "plugins" / "codemap" / "bin" / name
        if candidate.exists():
            return candidate
    return None


def resolve_index_path(arg: str | None, repo_path: Path) -> Path:
    """Resolve the codemap index path, checking both .cache/codemap/ and .cache/scan/.

    Args:
        arg: Explicit --index-path argument; if given, returned as-is.
        repo_path: Root of the repository being indexed.

    Returns:
        Path to the index JSON (may not exist yet).
    """
    if arg:
        return Path(arg)
    repo_name = repo_path.name
    stems = [repo_name, repo_name.replace("-master", ""), repo_name.replace("-main", "")]
    for stem in stems:
        for cache_dir in (".cache/codemap", ".cache/scan"):
            p = repo_path / cache_dir / f"{stem}.json"
            if p.exists():
                return p
    for cache_dir in (".cache/codemap", ".cache/scan"):
        d = repo_path / cache_dir
        if d.exists():
            jsons = sorted(d.glob("*.json"))
            if jsons:
                return jsons[0]
    bare = repo_name.replace("-master", "").replace("-main", "")
    return repo_path / ".cache" / "codemap" / f"{bare}.json"


# ---- SCAN-QUERY RUNNER ----


def run_scan_query(sq: Path, args: list[str], index_path: Path, repo_path: Path) -> dict | None:
    """Run scan-query with given args and return parsed JSON output.

    Args:
        sq: Path to the scan-query script.
        args: Subcommand + positional/flag args (e.g. ["fn-rdeps", "mod::fn", "--exclude-tests"]).
        index_path: Path to the codemap index JSON.
        repo_path: Working directory for the subprocess.

    Returns:
        Parsed dict from stdout, or None on error.
    """
    cmd = ["python3", str(sq.resolve()), "--index", str(index_path.resolve())] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(repo_path))
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


# ---- PER-TYPE VALIDATORS ----


def _validate_symbol(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate symbol_extraction task ground truth.

    Args:
        task: Task dict from tasks-bench.json.
        sq: Path to scan-query.
        index: Path to codemap index.
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason)
    """
    gt = task["ground_truth"]
    module = gt["module"]
    qname = gt["qualified_name"]

    # Run `symbol <qname>` — scan-query matches on name or qualified_name
    data = run_scan_query(sq, ["symbol", qname], index, repo)
    if data is None:
        return False, None, "scan-query symbol returned None"

    symbols = data.get("symbols", [])
    match = next((s for s in symbols if s.get("module") == module and s.get("qualified_name") == qname), None)
    if match is None:
        # Widen to any symbol with the right qname
        match = next((s for s in symbols if s.get("qualified_name") == qname), None)
    if match is None:
        names_found = [(s.get("module"), s.get("qualified_name")) for s in symbols[:5]]
        return False, None, f"symbol {module}::{qname} not found; first 5: {names_found}"

    live_gt: dict[str, Any] = {
        "module": match.get("module", module),
        "qualified_name": match.get("qualified_name", qname),
        "start_line": match.get("start_line", 0),
        "end_line": match.get("end_line", 0),
    }

    problems: list[str] = []
    for field in ("module", "qualified_name", "start_line", "end_line"):
        if live_gt[field] != gt[field]:
            problems.append(f"{field}: expected {gt[field]!r}, got {live_gt[field]!r}")

    return (not problems), live_gt, "; ".join(problems)


class _CallFinder(ast.NodeVisitor):
    """AST visitor that records the enclosing scope of each matching call site.

    Args:
        simple_name: Simple call name to match (e.g. ``"method"``).
        rel_module: Dotted module path of the file being walked (e.g. ``"pkg.mod"``).
        callers: Mutable set to accumulate ``"<module>::<scope>"`` caller strings.
    """

    def __init__(self, simple_name: str, rel_module: str, callers: set[str]) -> None:
        self._simple_name = simple_name
        self._rel_module = rel_module
        self._callers = callers
        self._scope_stack: list[str] = []

    def _scope(self) -> str:
        return ".".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        matched = (isinstance(node.func, ast.Name) and node.func.id == self._simple_name) or (
            isinstance(node.func, ast.Attribute) and node.func.attr == self._simple_name
        )
        if matched and self._scope_stack:
            self._callers.add(f"{self._rel_module}::{self._scope()}")
        self.generic_visit(node)


def _callers_via_ast(primary_fn: str, repo) -> tuple[set[str], str | None]:
    """Walk repo Python AST to find callers of ``primary_fn`` independent of scan-query.

    Args:
        primary_fn: Qualified name like ``"mod::Class.method"`` or ``"mod::func"``.
        repo: Repository root directory.

    Returns:
        (caller_set, error_reason) — caller_set contains ``"<module>::<scope>"`` strings
        for each enclosing function/method that contains a call matching the target's simple
        name. error_reason is None on success, a short message on failure.

    Notes:
        Approximate oracle: matches by simple name of target, so over-approximates when
        same-named functions exist in unrelated classes, and under-approximates for
        aliased calls. Use to detect *divergence* from scan-query, not as standalone GT.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text("def caller():\n    target()\n")
        ...     callers, err = _callers_via_ast("m::target", repo)
        >>> sorted(callers), err
        (['m::caller'], None)
    """
    tail = primary_fn.split("::")[-1]
    simple_name = tail.split(".")[-1]

    callers: set[str] = set()
    error: str | None = None

    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            try:
                source = fpath.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(source, filename=str(fpath))
            except SyntaxError:
                continue
            rel = str(fpath.relative_to(repo)).replace(os.sep, "/").replace(".py", "").replace("/", ".")
            _CallFinder(simple_name, rel, callers).visit(tree)

    return callers, error


def _validate_fn(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate fn_call_graph task ground truth.

    Args:
        task: Task dict from tasks-bench.json.
        sq: Path to scan-query.
        index: Path to codemap index.
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason)
    """
    gt = task["ground_truth"]
    primary_fn = task["primary_fn"]

    args = ["fn-rdeps", primary_fn]
    if gt.get("exclude_tests"):
        args.append("--exclude-tests")

    data = run_scan_query(sq, args, index, repo)
    if data is None:
        return False, None, "scan-query fn-rdeps returned None"

    called_by = data.get("called_by", [])
    raw_count = data.get("count", len(called_by))
    # caller field already contains "module::QualifiedName" — use directly; dedup first
    callers = sorted(set(e["caller"] for e in called_by))
    unique_count = len(callers)

    # Independent AST oracle — over-approximates but catches scan-query blind spots
    ast_callers, _ast_err = _callers_via_ast(primary_fn, repo)

    live_gt: dict[str, Any] = {
        "fn_callers": callers,
        "unique_caller_count": unique_count,
        "raw_caller_count": raw_count,
        "exclude_tests": gt.get("exclude_tests", False),
        "note": gt.get("note", "static edges only (import/local/self-resolved); dynamic dispatch excluded by design"),
        "fn_callers_ast": sorted(ast_callers),
        "ast_divergence": {
            "ast_only": sorted(ast_callers - set(callers)),
            "sq_only": sorted(set(callers) - ast_callers),
            "ast_caller_count": len(ast_callers),
        },
    }

    problems: list[str] = []
    if unique_count != gt["unique_caller_count"]:
        problems.append(f"unique_caller_count: expected {gt['unique_caller_count']}, got {unique_count}")
    if raw_count != gt["raw_caller_count"]:
        problems.append(f"raw_caller_count: expected {gt['raw_caller_count']}, got {raw_count}")

    expected_set = set(gt["fn_callers"])
    live_set = set(callers)
    extra = sorted(live_set - expected_set)
    missing = sorted(expected_set - live_set)
    if extra:
        problems.append(f"extra callers ({len(extra)}): {extra[:5]}{'...' if len(extra) > 5 else ''}")
    if missing:
        problems.append(f"missing callers ({len(missing)}): {missing[:5]}{'...' if len(missing) > 5 else ''}")

    return (not problems), live_gt, "; ".join(problems)


def _extract_rv_value(cmd: str, data: dict, match_type: str, count_hint: int = 0) -> Any:
    """Extract the answer value from scan-query output for a review_assistance sub-question.

    Args:
        cmd: Scan-query subcommand name (e.g. "rdeps", "fn-rdeps", "undocumented").
        data: Parsed scan-query output dict.
        match_type: "integer_extract" or "symbol_name_set".
        count_hint: For symbol_name_set, how many names to return (0 = all).

    Returns:
        int for integer_extract; list[str] of qualified_names for symbol_name_set.
    """
    if match_type == "integer_extract":
        if cmd == "rdeps":
            return len(data.get("imported_by", []))
        if cmd == "fn-rdeps":
            return data.get("count", len(data.get("called_by", [])))
        if cmd == "undocumented":
            return data.get("total", 0)
        if cmd == "uncovered":
            return data.get("total", 0)
        return 0
    # symbol_name_set
    if cmd == "undocumented":
        entries = data.get("undocumented", [])
    elif cmd == "uncovered":
        entries = data.get("uncovered", [])
    else:
        return []
    names = [e.get("qualified_name", e.get("name", "")) for e in entries]
    return names[:count_hint] if count_hint else names


def _validate_rv(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate review_assistance task ground truth.

    Args:
        task: Task dict from tasks-bench.json.
        sq: Path to scan-query.
        index: Path to codemap index.
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason)
    """
    expected_queries = task.get("expected_queries", [])
    sub_questions = task.get("sub_questions", [])

    if not expected_queries:
        return False, None, "no expected_queries defined"

    # Run the first expected_query (one scan-query call covers all sub-questions for RV tasks)
    q = expected_queries[0]
    cmd = q["cmd"]
    data = run_scan_query(sq, [cmd] + q.get("args", []), index, repo)
    if data is None:
        return False, None, f"scan-query {cmd} returned None"

    live_gt: dict[str, Any] = {}
    problems: list[str] = []

    for sq_item in sub_questions:
        sq_id = sq_item["id"]
        match_type = sq_item["match"]
        expected_gt = sq_item["ground_truth"]

        if match_type == "integer_extract":
            live_val = _extract_rv_value(cmd, data, "integer_extract")
            expected_val = expected_gt.get("count", 0)
            live_gt[sq_id] = {"count": live_val}
            if live_val != expected_val:
                problems.append(f"{sq_id}: expected count={expected_val}, got {live_val}")

        elif match_type == "symbol_name_set":
            expected_symbols = expected_gt.get("symbols", [])
            n = len(expected_symbols)
            live_names = _extract_rv_value(cmd, data, "symbol_name_set", count_hint=n)
            live_gt[sq_id] = {"symbols": live_names}
            expected_set = set(expected_symbols)
            live_set = set(live_names)
            extra = sorted(live_set - expected_set)
            missing = sorted(expected_set - live_set)
            if extra or missing:
                parts = []
                if missing:
                    parts.append(f"missing: {missing[:3]}")
                if extra:
                    parts.append(f"extra: {extra[:3]}")
                problems.append(f"{sq_id} symbol_name_set: {', '.join(parts)}")

    return (not problems), live_gt, "; ".join(problems)


def _validate_oss(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate code_quality task ground truth.

    Args:
        task: Task dict from tasks-bench.json.
        sq: Path to scan-query.
        index: Path to codemap index.
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason)
    """
    gt = task["ground_truth"]
    check = gt["check"]
    expected_queries = task.get("expected_queries", [])

    if not expected_queries:
        return False, None, "no expected_queries defined"

    problems: list[str] = []
    live_gt: dict[str, Any] = {"check": check}

    if check in ("undocumented", "combined_health"):
        q = next((q for q in expected_queries if q["cmd"] == "undocumented"), None)
        if q is None:
            return False, None, "no undocumented query found"
        data = run_scan_query(sq, ["undocumented"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query undocumented returned None"
        live_count = data.get("total", 0)
        live_syms = [e.get("qualified_name", "") for e in data.get("undocumented", [])]
        live_gt["undocumented_count"] = live_count
        live_gt["undocumented_symbols"] = live_syms
        if check != "combined_health":
            expected_count = gt.get("undocumented_count", 0)
            expected_syms = gt.get("undocumented_symbols", [])
            if live_count != expected_count:
                problems.append(f"undocumented_count: expected {expected_count}, got {live_count}")
            live_set = set(live_syms)
            exp_set = set(expected_syms)
            if live_set != exp_set:
                problems.append(
                    f"undocumented_symbols mismatch: missing={sorted(exp_set - live_set)[:3]}, "
                    f"extra={sorted(live_set - exp_set)[:3]}"
                )

    if check in ("uncovered", "combined_health"):
        q = next((q for q in expected_queries if q["cmd"] == "uncovered"), None)
        if q is None:
            return False, None, "no uncovered query found"
        data = run_scan_query(sq, ["uncovered"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query uncovered returned None"
        live_count = data.get("total", 0)
        live_syms = [e.get("qualified_name", "") for e in data.get("uncovered", [])]
        live_gt["uncovered_count"] = live_count
        live_gt["uncovered_symbols"] = live_syms
        if check != "combined_health":
            expected_count = gt.get("uncovered_count", 0)
            expected_syms = gt.get("uncovered_symbols", [])
            if live_count != expected_count:
                problems.append(f"uncovered_count: expected {expected_count}, got {live_count}")
            if set(live_syms) != set(expected_syms):
                exp_set = set(expected_syms)
                live_set = set(live_syms)
                problems.append(
                    f"uncovered_symbols mismatch: missing={sorted(exp_set - live_set)[:3]}, "
                    f"extra={sorted(live_set - exp_set)[:3]}"
                )

    if check == "combined_health":
        # Validate both counts and symbol sets together
        for field_prefix in ("undocumented", "uncovered"):
            expected_count = gt.get(f"{field_prefix}_count", 0)
            expected_syms = gt.get(f"{field_prefix}_symbols", [])
            live_count = live_gt.get(f"{field_prefix}_count", -1)
            live_syms = live_gt.get(f"{field_prefix}_symbols", [])
            if live_count != expected_count:
                problems.append(f"{field_prefix}_count: expected {expected_count}, got {live_count}")
            if set(live_syms) != set(expected_syms):
                exp_set = set(expected_syms)
                live_set_items = set(live_syms)
                problems.append(
                    f"{field_prefix}_symbols mismatch: "
                    f"missing={sorted(exp_set - live_set_items)[:3]}, "
                    f"extra={sorted(live_set_items - exp_set)[:3]}"
                )

    if check == "coupled":
        q = expected_queries[0]
        data = run_scan_query(sq, ["coupled"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query coupled returned None"
        coupled = data.get("coupled", [])
        if not coupled:
            return False, None, "coupled result is empty"
        top = coupled[0]
        live_gt["top_module"] = top.get("name", "")
        live_gt["top_dep_count"] = top.get("dep_count", 0)
        live_gt["top_internal_dep_count"] = top.get("internal_dep_count", 0)
        if live_gt["top_module"] != gt.get("top_module", ""):
            problems.append(f"top_module: expected {gt['top_module']!r}, got {live_gt['top_module']!r}")
        if live_gt["top_dep_count"] != gt.get("top_dep_count", 0):
            problems.append(f"top_dep_count: expected {gt['top_dep_count']}, got {live_gt['top_dep_count']}")
        if live_gt["top_internal_dep_count"] != gt.get("top_internal_dep_count", 0):
            problems.append(
                f"top_internal_dep_count: expected {gt['top_internal_dep_count']}, "
                f"got {live_gt['top_internal_dep_count']}"
            )

    if check == "xrefs_broken":
        q = expected_queries[0]
        data = run_scan_query(sq, ["xrefs"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query xrefs returned None"
        broken = data.get("broken", [])
        live_count = data.get("count", len(broken))
        live_targets = [{"target": b.get("target", ""), "line": b.get("line", 0)} for b in broken]
        live_gt["broken_count"] = live_count
        live_gt["broken_targets"] = live_targets

        expected_count = gt.get("broken_count", 0)
        if live_count != expected_count:
            problems.append(f"broken_count: expected {expected_count}, got {live_count}")

        expected_targets = {(t["target"], t["line"]) for t in gt.get("broken_targets", [])}
        live_target_set = {(t["target"], t["line"]) for t in live_targets}
        if live_target_set != expected_targets:
            problems.append(
                f"broken_targets mismatch: "
                f"missing={sorted(expected_targets - live_target_set)[:3]}, "
                f"extra={sorted(live_target_set - expected_targets)[:3]}"
            )

    return (not problems), live_gt, "; ".join(problems)


VALIDATORS = {
    "symbol_extraction": _validate_symbol,
    "fn_call_graph": _validate_fn,
    "review_assistance": _validate_rv,
    "code_quality": _validate_oss,
    "develop_blast_radius": _validate_fn,
}


# ---- GROUND TRUTH UPDATER ----


def _build_updated_ground_truth(task_type: str, live_gt: dict[str, Any], existing_gt: dict) -> dict:
    """Merge live computed values into the existing ground_truth dict.

    Args:
        task_type: One of "symbol_extraction", "fn_call_graph", "review_assistance", "code_quality".
        live_gt: Computed ground truth from scan-query output.
        existing_gt: Existing ground_truth from the task file (for fields not recomputed).

    Returns:
        Updated ground_truth dict.
    """
    if task_type == "symbol_extraction":
        return {**existing_gt, **live_gt}
    if task_type in ("fn_call_graph", "develop_blast_radius"):
        return {**existing_gt, **live_gt}
    if task_type == "review_assistance":
        # live_gt is {sq_id: {count: N} | {symbols: [...]}}
        return live_gt  # caller updates sub_questions in place
    if task_type == "code_quality":
        return {**existing_gt, **live_gt}
    return existing_gt


# ---- MAIN ----


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Validate or refresh ground truth in benchmarks/tasks-bench.json.",
    )
    parser.add_argument("--repo-path", type=str, default=None, help="Path to the target repository clone")
    parser.add_argument("--index-path", type=str, default=None, help="Path to pre-built index JSON")
    parser.add_argument("--task", type=str, default=None, help="Validate only this task ID (e.g. SE-01)")
    parser.add_argument("--update", action="store_true", help="Write refreshed ground truth back to tasks-bench.json")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print live ground truth on failure")
    return parser.parse_args()


def main() -> None:
    """Entry point: validate or update tasks-bench.json ground truth."""
    args = parse_args()

    # Resolve plugin root for binary lookup
    try:
        import subprocess as _sp

        r = _sp.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        plugin_root = Path(r.stdout.strip()) if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        plugin_root = None

    # Load tasks first — repo header provides default_path for fallback discovery
    try:
        with TASKS_FILE.open() as f:
            _raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read {TASKS_FILE}: {exc}")
        sys.exit(1)

    if isinstance(_raw, dict):
        repo_meta = _raw.get("repo", {})
        tasks: list[dict] = _raw.get("tasks", [])
        _tasks_wrapper: dict | None = _raw  # preserved for write-back
    else:
        repo_meta = {}
        tasks = _raw
        _tasks_wrapper = None

    # Resolve repo path
    if args.repo_path:
        repo_path = Path(args.repo_path)
    else:
        _default_path = repo_meta.get("default_path")
        _cands = [Path(_default_path)] if _default_path else []
        for candidate in _cands:
            if candidate.is_dir():
                repo_path = candidate
                break
        else:
            print("ERROR: cannot find repo; pass --repo-path")
            sys.exit(1)

    if not repo_path.is_dir():
        print(f"ERROR: --repo-path {repo_path} is not a directory")
        sys.exit(1)

    sq = find_codemap_bin("scan-query", plugin_root)
    if sq is None:
        print("ERROR: scan-query not found on PATH or in plugins/codemap/bin/")
        sys.exit(1)

    index_path = resolve_index_path(args.index_path, repo_path)
    if not index_path.exists():
        print(f"ERROR: index not found at {index_path}. Run scan-index first.")
        sys.exit(1)

    if args.task:
        tasks = [t for t in tasks if t.get("id") == args.task]
        if not tasks:
            print(f"ERROR: task {args.task!r} not found in {TASKS_FILE.name}")
            sys.exit(1)

    # Validate each task
    failed: list[str] = []
    updated_tasks: list[dict] = []

    for task in tasks:
        task_id = task.get("id", "?")
        task_type = task.get("type", "")
        validator = VALIDATORS.get(task_type)

        if validator is None:
            print(f"  SKIP  {task_id}: unknown type {task_type!r}")
            updated_tasks.append(task)
            continue

        ok, live_gt, reason = validator(task, sq, index_path, repo_path)

        if ok:
            print(f"  PASS  {task_id}")
            updated_tasks.append(task)
        else:
            print(f"  FAIL  {task_id}: {reason}")
            failed.append(task_id)
            if args.verbose and live_gt is not None:
                print(f"         live_gt = {json.dumps(live_gt, indent=2)}")

            if args.update and live_gt is not None:
                # Update ground_truth in the task dict
                updated_task = dict(task)
                if task_type == "review_assistance":
                    # Update per-sub_question ground_truth values
                    new_sqs = []
                    for sq_item in task.get("sub_questions", []):
                        sq_id = sq_item["id"]
                        if sq_id in live_gt:
                            new_sqs.append({**sq_item, "ground_truth": live_gt[sq_id]})
                        else:
                            new_sqs.append(sq_item)
                    updated_task["sub_questions"] = new_sqs
                else:
                    updated_task["ground_truth"] = _build_updated_ground_truth(
                        task_type, live_gt, task.get("ground_truth", {})
                    )
                updated_tasks.append(updated_task)
                print("         UPDATED")
            else:
                updated_tasks.append(task)

    if args.update:
        # Only update if the task list matches the full file (no --task filter)
        if args.task is None:
            with TASKS_FILE.open("w") as f:
                if _tasks_wrapper is not None:
                    out = {**_tasks_wrapper, "tasks": updated_tasks}
                    json.dump(out, f, indent=2, sort_keys=True)
                else:
                    json.dump(updated_tasks, f, indent=2, sort_keys=True)
                f.write("\n")
            print(f"\nWrote updated ground truth to {TASKS_FILE.name}")
        else:
            print(f"\nSingle-task mode: updated task {args.task!r} not written (omit --task to write full file)")

    total = len(tasks)
    passed = total - len(failed)
    print(f"\n{passed}/{total} passed")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        if not args.update:
            sys.exit(1)


if __name__ == "__main__":
    main()
