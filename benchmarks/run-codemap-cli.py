#!/usr/bin/env python3
"""Codemap scan-query benchmark — measures accuracy, latency, and coverage of the scan-query binary.

## Motivation

The `codemap` plugin scans a Python codebase once (`ast.parse`) into a structural JSON index; agents answer
structural questions (rdeps, deps, centrality, import paths) with one `scan-query` call instead of many Glob/Grep
passes. This script benchmarks the `scan-query` binary directly against cold grep baselines — it does NOT invoke the
Claude API, spawn agents, or record live tool-call counts.

## Goal

Quantify codemap's benefit across four dimensions:

Frozen task set: benchmarks/suites/tasks-code.json — 15 tasks grouped by skill:
  B-01–B-05  bug/fix scenarios    (blast radius before touching faulty code)
  F-01–F-05  feature scenarios    (coupling risk before hooking in)
  R-01–R-05  refactor scenarios   (full structural picture before restructuring)

Suite C — Coverage gap: structural completeness of cold grep vs codemap.

  Code  Name                     What it measures                            Pass threshold
  ----  -----------------------  ------------------------------------------  ---------------
  C1    coverage-gap             codemap finds >=10% more importers          gap >= 10%
  C2    infeasible-path-fraction >=50% of 2+ hop paths not grep-             fraction >= 50%
                                 discoverable in 1 call
  C3    leverage-ratio           structural context / cold exploration       ratio >= 2.0x
                                 call ratio across all 15 tasks

Suite A — Accuracy: AST-verified rdeps precision + boundary-grep recall floor.

  Code  Name         What it measures                                   Pass threshold
  ----  -----------  -------------------------------------------------  ---------------
  A1    rdeps-high   AST precision + grep recall floor, high-risk tasks precision >= 0.90
                     (B-01,B-03,B-05,F-02,F-05,R-01,R-02)              recall    >= 0.85
  A2    rdeps-low    AST precision for low-risk tasks (B-04, R-05)      precision = 1.00
  A3    fp-rate      overall AST false-positive rate across all tasks   FP rate < 5%

Suite L — Latency: wall-clock cost of codemap queries vs cold grep pipelines.

  Code  Name         What it measures                                   Pass threshold
  ----  -----------  -------------------------------------------------  ---------------
  L1    central      median of 5 runs of scan-query central --top 5     median < 200 ms
  L2    rdeps        median of 5 runs of scan-query rdeps across 3      median < 100 ms
                     high-risk task modules
  L3    index-build  one scan-index run amortized over 10 invocations   amortized < 500 ms
                     (total build time / 10)
  L4    speedup      codemap (L1+L2) vs cold grep baseline               >= 2x faster

Suite Q — Query shape: validates the OUTPUT SHAPE of the scan-query commands a skill would inject. It
does NOT invoke the skill, exercise the SKILL.md injection block, or prove the context is wired into a
prompt. (plugins/codemap/bin/check_injection.py separately audits SKILL.md/agent files for injection
MARKERS — also not a runtime context-block test.)

  Code        Skill queries       What is validated              Pass threshold
  ---------   ------------------  -----------------------------  ---------------
  Q_fix       develop:fix         per-task queries (5 tasks)     JSON valid
  Q_feature   develop:feature     per-task queries (5 tasks)     JSON valid
  Q_refactor  develop:refactor    per-task queries + rdeps/deps  all present,
                                  (5 tasks)                      rdeps+deps valid

Suites S, H, X are SELF-CONSISTENCY / DETERMINISM checks, not independent-correctness checks: their
ground truth in tasks-bench.json is derived from scan-query's own output, so a pass confirms
determinism / index-version stability against a frozen snapshot, not independent correctness. They
run on a separate self-consistency track EXCLUDED from the primary verdict (see below). All three
pass on an exact/tolerant match against that frozen snapshot:
  Suite S — Symbol lookup (SE-01..SE-05): scan-query symbol start_line within ±3 of gt; S2 = all pass.
  Suite H — Health (CQ-01..CQ-05): undocumented/uncovered total == gt.count; H1/H2 = all pass.
  Suite X — Xrefs broken (CQ-04): xrefs --broken count + target set == gt; X1 = all pass.

Index path resolution: .cache/codemap/ is checked before .cache/scan/ (scan-index --root default).

## Requirements

  - Python 3.8+ (stdlib for C/A/L/Q/X; pandas+rich for reporting); git on PATH
  - A pytorch-lightning clone plus a pre-built codemap index for it:
      python3 plugins/codemap/bin/scan-index --root ./pytorch-lightning-master
  - scan-query on PATH or at plugins/codemap/bin/scan-query (found automatically)
  - benchmarks/suites/tasks-bench.json present for S/H/X (auto-skipped if absent)

## Quick start

    # Full benchmark with markdown report (suites C/A/L/Q always run; S/H/X when tasks-bench.json present)
    python benchmarks/run-codemap-cli.py \\
        --repo-path ./pytorch-lightning-master \\
        --report

    # Verify task modules exist in the index before running
    python benchmarks/run-codemap-cli.py --verify-tasks --repo-path ./pytorch-lightning-master

    # Non-default index path: add --index-path /path/to/index.json  (see main() docstring for more)

## Where the benchmark fits in the full flow

  A develop/oss skill's codemap soft-check injects a structural-context block (scan-query rdeps/deps)
  or skips it when the index/plugin is absent. This script starts AFTER that: Suite Q checks the query
  output shape; C/A/L compare the WITH-codemap path against a WITHOUT-codemap cold Glob/Grep/Read
  baseline. It does NOT measure whether the agent actually USED the injected context (needs live
  Claude API runs with tool-use recording — out of scope).

## How each suite computes its metrics

  Each suite's exact formula lives in its function docstring (the authoritative source), and the
  per-scenario pass thresholds are the tables above plus the THRESHOLDS dict:
    Suite C — run_measure_calls / _measure_coverage_gap (AST-verified importer gap) /
      _measure_infeasible_paths (direct-edge grep test).
    Suite A — score_rdeps_accuracy: precision judged against an INDEPENDENT AST import-resolver (not
      raw grep, so aliased / relative / re-export importers are not penalised) and recall as a FLOOR
      against a boundary-anchored grep set; a scan-query failure FAILS the scenario (never scored as
      an empty result with precision 1.0).
    Suite L — run_measure_latency: L3 amortizes the one-time build over _QUERIES_PER_SESSION (an
      explicit stated assumption, not telemetry; L3 is expected to fail on large repos and the verdict
      owns it); L4 reports both the warm-only (gate) and the build-inclusive speedup.
    Suite Q — run_measure_query_shape: validates scan-query output SHAPE only; it does NOT invoke the
      skill or exercise the SKILL.md injection block.

## Output

  Default mode: stdout carries the human verdict + self-consistency lines, the summary envelope
  (JSON), and the report path (with --report); stderr carries progress narration; the markdown report
  is written to benchmarks/results/code-YYYY-MM-DD.md with --report.

  --json-only mode (machine consumption): stdout carries ONLY one compact JSON object per scenario
  (JSONL) followed by the summary envelope; human logs, the progress bar, and the report are suppressed.

## JSON output schema (per-scenario lines + summary envelope)

  Each scenario line mirrors the ScenarioResult dataclass fields exactly (see :func:`emit`):
  scenario (e.g. "C1"|"A1"|"Q_fix"|"S2"), name, suite ("calls"|"accuracy"|"latency"|"query-shape"|
  "symbol"|"health"|"xrefs"), passed, result (suite-specific measurement dict), threshold, notes.

  Final summary envelope (last stdout line): verdict (PRIMARY correctness), scenarios_passed/total
  (all scenarios), primary {passed,total} (the verdict basis), self_consistency
  {verdict ∈ CONSISTENT|PARTIAL|INCONSISTENT|SKIPPED, passed, total} (S/H/X determinism track, NOT in
  the verdict), suites {<suite>: {passed,total}} for calls/accuracy/latency/query-shape/symbol/health/
  xrefs, and date/repo/index.

## Verdict thresholds (single source of truth — compute_verdict in source)

  SCENARIO-based, computed ONLY from the four PRIMARY suites checked against an independent oracle:
  calls (C), accuracy (A), latency (L), query-shape (Q). The self-consistency suites (symbol/health/
  xrefs) validate against frozen scan-query-derived GT and are reported on a separate self_consistency
  track that NEVER contributes — circular passes cannot float the verdict up. With P/T = primary
  passed/total: PASS = P == T; PARTIAL = P/T >= 0.50; FAIL = P/T < 0.50 or T == 0. FAIL headroom is
  real: A uses an AST oracle (codemap can be wrong) and L3 fails on large repos under an honest divisor.

Full scenario definitions and pass criteria: .plans/blueprint/2026-04-15-codemap-benchmark-spec.md
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import fire
import pandas as pd

try:
    from rich.console import Console
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    _console: Console | None = Console()
    _IS_RICH_AVAILABLE = True
except ImportError:
    _console = None
    _IS_RICH_AVAILABLE = False

# ---- TYPES ----


@dataclass
class Query:
    """A single scan-query invocation specification."""

    cmd: str  # "rdeps", "deps", "central", "coupled", "path"
    args: list[str]  # positional args after the command


@dataclass
class Task:
    """A benchmark task loaded from tasks-code.json."""

    id: str  # "B-01", "F-03", "R-05"
    skill: str  # "fix", "feature", "refactor"
    prompt: str  # developer-facing scenario description
    primary_module: str  # dotted module name
    risk_tier: str  # "high", "moderate", "low", "very-high", etc.
    queries: list[Query]  # ordered scan-query calls for this task
    ground_truth_keys: list[str]  # expected JSON keys in query results

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        """Construct a Task from a raw JSON dict."""
        return cls(
            id=d["id"],
            skill=d["skill"],
            prompt=d["prompt"],
            primary_module=d["primary_module"],
            risk_tier=d["risk_tier"],
            queries=[Query(**q) for q in d["queries"]],
            ground_truth_keys=d["ground_truth_keys"],
        )


@dataclass
class ScenarioResult:
    """Result of a single benchmark scenario evaluation."""

    scenario: str  # "C1", "A1", "L2", "Q_fix", etc.
    name: str  # human label e.g. "coverage-gap"
    suite: str  # "calls", "accuracy", "latency", "query-shape", "symbol", "health", "xrefs"
    passed: bool
    result: dict  # suite-specific measurement values
    threshold: dict  # the threshold values applied
    notes: str = ""


@dataclass
class TimingStats:
    """Timing measurement results from repeated command runs."""

    min_ms: float
    median_ms: float
    max_ms: float
    n: int


@dataclass
class AccuracyStats:
    """Per-task precision/recall results for rdeps accuracy."""

    precision: float
    recall: float
    tp: int
    fp: int
    fn: int
    fp_modules: list[str]
    fn_modules: list[str]


@dataclass
class SuiteStats:
    """Aggregate pass/fail counters for a single benchmark suite."""

    total: int = 0
    passed: int = 0
    failed: int = 0


@dataclass
class ValidationResult:
    """Outcome of a structural JSON validation check."""

    ok: bool
    reason: str  # empty string if ok; error description if not


@dataclass
class ScanResult:
    """Outcome of a scan-query invocation: parsed data or a distinct error reason.

    Separates a genuine empty/negative result (``data`` present, ``error`` is
    ``None``) from a tool failure — non-zero exit, timeout, or undecodable output
    (``data`` is ``None``, ``error`` set).  Callers use this to avoid scoring a
    crashed or absent-module query as a passing empty result.

    Examples:
        >>> ScanResult(data={"imported_by": []}, error=None).ok
        True
        >>> ScanResult(data=None, error="timeout after 30s").ok
        False
    """

    data: dict | None
    error: str | None  # None on success; short failure reason otherwise

    @property
    def ok(self) -> bool:
        """Return ``True`` when the query succeeded and ``data`` is available."""
        return self.error is None


# ---- CONFIG ----

TASKS_FILE = Path(__file__).parent / "suites" / "tasks-code.json"
OSS_TASKS_FILE = Path(__file__).parent / "suites" / "tasks-bench.json"

THRESHOLDS = {
    # Coverage gap suite (C): structural completeness of cold grep vs codemap
    "C1": {"coverage_gap_min": 0.10},  # codemap finds >=10% more importers than grep
    "C2": {"infeasible_path_fraction_min": 0.50},  # >=50% of 2+ hop paths not grep-discoverable in 1 call
    "C3": {"leverage_ratio_min": 2.0},  # structural context tokens / cold exploration tokens >= 2x
    # Accuracy suite (A): rdeps precision/recall vs grep ground truth
    "A1": {"precision_min": 0.90, "recall_min": 0.85},  # high-risk tasks (B-01,B-03,B-05,F-02,F-05,R-01,R-02)
    "A2": {"precision_min": 1.00},  # low-risk tasks (B-04, R-05)
    "A3": {"fp_rate_max": 0.05},  # overall across all 15 tasks
    # Query-shape suite (Q): scan-query output shape is valid for each skill group (NOT the injection path)
    "Q_fix": {"block_present": True, "json_valid": True},
    "Q_feature": {"block_present": True, "json_valid": True},
    "Q_refactor": {"block_present": True, "json_valid": True, "has_rdeps": True, "has_deps": True},
    # Latency suite (L): unchanged
    "L1": {"median_ms_max": 200},
    "L2": {"median_ms_max": 100},
    "L3": {"amortized_ms_max": 500},
    "L4": {"speedup_min": 2.0},
    # Symbol suite (S): symbol command returns correct line range
    "S1": {"symbol_found": True, "start_line_ok": True},
    "S2": {"symbol_found": True},
    # Health suite (H): undocumented / uncovered counts match tasks-bench.json ground truth
    "H1": {"count_match": True},  # undocumented tasks
    "H2": {"count_match": True},  # uncovered tasks
    # Xrefs suite (X): xrefs --broken count matches tasks-bench.json ground truth
    "X1": {"count_match": True},
}


def load_tasks(skill_filter: str | None = None) -> list[Task]:
    """Load benchmark tasks from tasks-code.json, optionally filtered by skill.

    Args:
        skill_filter: When given, return only tasks whose ``skill`` field equals
            this value (e.g. ``"fix"``, ``"feature"``, ``"refactor"``).

    Returns:
        List of :class:`Task` objects in the order they appear in the file.

    Examples:
        >>> tasks = load_tasks()
        >>> all(isinstance(t, Task) for t in tasks)
        True
        >>> fix_tasks = load_tasks(skill_filter="fix")
        >>> all(t.skill == "fix" for t in fix_tasks)
        True
    """
    with TASKS_FILE.open() as f:
        raw = json.load(f)
    tasks = [Task.from_dict(t) for t in raw]
    if skill_filter:
        tasks = [t for t in tasks if t.skill == skill_filter]
    return tasks


def load_oss_tasks(type_filter: str | None = None) -> list[dict]:
    """Load OSS benchmark tasks from tasks-bench.json, optionally filtered by type.

    Args:
        type_filter: When given, return only tasks with ``type == type_filter``.

    Returns:
        List of raw task dicts (structure as defined in tasks-bench.json).
    """
    if not OSS_TASKS_FILE.exists():
        return []
    with OSS_TASKS_FILE.open() as f:
        parsed = json.load(f)
    raw: list[dict] = parsed["tasks"] if isinstance(parsed, dict) else parsed
    if type_filter:
        raw = [t for t in raw if t.get("type") == type_filter]
    return raw


# ---- HELPERS ----


def path_to_module(path: str, repo_root: str) -> str | None:
    """Convert a filesystem path to a dotted module name relative to the repo root.

    Strips a leading ``src/`` layout prefix if present, converts path separators
    to dots, drops the ``.py`` suffix, and collapses ``__init__`` to its package.

    Args:
        path: Absolute or relative path to a ``.py`` file.
        repo_root: Absolute path to the repository root used as the base for
            ``os.path.relpath``.

    Returns:
        Dotted module name (e.g. ``"lightning.pytorch.trainer.trainer"``), or
        ``None`` if ``path`` does not end with ``.py``.

    Examples:
        >>> path_to_module("/repo/src/pkg/mod.py", "/repo")
        'pkg.mod'
        >>> path_to_module("/repo/pkg/__init__.py", "/repo")
        'pkg'
        >>> path_to_module("/repo/README.md", "/repo") is None
        True
    """
    rel = os.path.relpath(path, repo_root)
    if rel.startswith("src/"):
        rel = rel[4:]
    if not rel.endswith(".py"):
        return None
    mod = rel[:-3].replace("/", ".")
    if mod.endswith(".__init__"):
        mod = mod[:-9]
    return mod


def module_to_grep_pattern(module: str) -> str:
    """Build a grep alternation pattern that matches direct imports of a module.

    The returned pattern matches both ``from <module> import ...`` and
    ``import <module>`` forms and is suitable for ``grep -rn <pattern>``.

    Args:
        module: Dotted module name (e.g. ``"lightning.pytorch.trainer.trainer"``).

    Returns:
        A grep alternation string using ``\\|`` as the separator.

    Examples:
        >>> module_to_grep_pattern("foo.bar")
        'from foo.bar import\\\\|import foo.bar'
    """
    # For grep: match "from <module> import" or "import <module>"
    return rf"from {module} import\|import {module}"


def module_to_package(module: str) -> str | None:
    """Return the parent package of a dotted module name, or None for top-level modules.

    Args:
        module: Dotted module name (e.g. ``"lightning.pytorch.trainer.trainer"``).

    Returns:
        The parent package (everything before the last dot), or ``None`` when
        ``module`` has no dot (i.e. is already a top-level module).

    Examples:
        >>> module_to_package("foo.bar.baz")
        'foo.bar'
        >>> module_to_package("foo") is None
        True
    """
    parts = module.rsplit(".", 1)
    return parts[0] if len(parts) > 1 else None


# ---- COLD BASELINE ----


def _run(cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command with standard benchmark defaults (capture, text, 30s timeout)."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)


class CallCounter:
    def __init__(self) -> None:
        self.count = 0

    def run(self, cmd: list[str], *, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        self.count += 1
        return _run(cmd, cwd=cwd)


def cold_greps(repo_path: Path, *cmds: list[str]) -> int:
    """Execute each command via :class:`CallCounter` and return the total invocation count.

    All commands are run with ``cwd=repo_path`` and their output is discarded.
    The function is used only for counting — it measures how many subprocess
    calls a cold grep baseline requires, not what the commands return.

    Args:
        repo_path: Working directory passed to each subprocess call.
        *cmds: Variable number of command lists, each formatted as a list of
            strings suitable for :func:`subprocess.run`.

    Returns:
        Total number of commands executed (always ``len(cmds)``).

    Examples:
        >>> cold_greps(Path("/tmp"), ["echo", "a"], ["echo", "b"])
        2
    """
    counter = CallCounter()
    for cmd in cmds:
        counter.run(cmd, cwd=str(repo_path))
    return counter.count


def count_cold_calls_centrality(repo_path: Path) -> int:
    """Return the number of grep/find calls needed to compute centrality without the index.

    Simulates the three-step cold grep pipeline: (1) enumerate all ``.py`` files,
    (2) extract import lines, (3) extract module names from import statements.

    Args:
        repo_path: Root of the repository to search.

    Returns:
        Number of subprocess invocations executed (always 3 for this query type).
    """
    repo = str(repo_path)
    return cold_greps(
        repo_path,
        ["find", repo, "-name", "*.py", "-not", "-path", "*/.git/*", "-not", "-path", "*/__pycache__/*"],
        ["grep", "-rn", r"^from \|^import ", repo, "--include=*.py", "-l"],
        ["grep", "-roh", r"from \([a-z_][a-z_.]*\) import\|^import \([a-z_][a-z_.]*\)", repo, "--include=*.py"],
    )


def count_cold_calls_rdeps(repo_path: Path, module: str) -> int:
    """Return the number of grep calls needed to find reverse-dependencies without the index.

    Simulates a two-pass cold grep: one for direct dotted-name imports and one
    for ``from <parent-package> import`` style imports.

    Args:
        repo_path: Root of the repository to search.
        module: Dotted module name whose importers are to be found.

    Returns:
        Number of subprocess invocations executed (always 2 for this query type).
    """
    repo = str(repo_path)
    pattern = module_to_grep_pattern(module)
    pkg = module_to_package(module)
    second_pattern = f"from {pkg} import" if pkg else f"import {module}"
    return cold_greps(
        repo_path,
        ["grep", "-rn", pattern, repo, "--include=*.py"],
        ["grep", "-rn", second_pattern, repo, "--include=*.py"],
    )


def count_cold_calls_deps(repo_path: Path, module: str) -> int:
    """Return the number of grep calls needed to find a module's direct imports without the index.

    Locates the module source file (checking ``src/`` layout and ``__init__.py``
    variants) and greps its import block.  Returns 1 even when the file is not
    found, because a real agent would still attempt the grep.

    Args:
        repo_path: Root of the repository to search.
        module: Dotted module name whose import block is to be inspected.

    Returns:
        Number of subprocess invocations executed (always 1 for this query type).
    """
    parts = module.replace(".", "/")
    candidates = [
        repo_path / "src" / (parts + ".py"),
        repo_path / (parts + ".py"),
        repo_path / "src" / parts / "__init__.py",
        repo_path / parts / "__init__.py",
    ]
    target = next((c for c in candidates if c.exists()), None)
    if target is None:
        return 1  # would still attempt one grep
    return cold_greps(repo_path, ["grep", "-n", r"^from \|^import ", str(target)])


def count_cold_calls_path(repo_path: Path, frm: str, to: str) -> int:
    """Return the number of grep calls needed to discover a 2-hop import path without the index.

    Assumes a 2-hop path (A → intermediate → B) requiring three grep passes:
    grep for ``frm``, grep for ``frm``'s parent package, and grep for ``to``.

    Args:
        repo_path: Root of the repository to search.
        frm: Dotted module name of the path source.
        to: Dotted module name of the path destination.

    Returns:
        Number of subprocess invocations executed (always 3 for this query type).
    """
    # BFS via grep: N+1 calls for N-hop path; use 2-hop assumption = 3 calls
    repo = str(repo_path)
    return cold_greps(
        repo_path,
        ["grep", "-rn", f"import {frm}", repo, "--include=*.py"],
        ["grep", "-rn", f"import {frm.rsplit('.', 1)[0]}", repo, "--include=*.py"],
        ["grep", "-rn", f"import {to}", repo, "--include=*.py"],
    )


# ---- WARM QUERIES ----


def find_codemap_bin(name: str, plugin_root: Path | None = None) -> Path | None:
    """Locate a codemap CLI binary (scan-query or scan-index) on PATH or in the plugin directory.

    Checks ``PATH`` first via :func:`shutil.which`.  Falls back to
    ``<plugin_root>/plugins/codemap/bin/<name>`` when ``plugin_root`` is given.

    Args:
        name: Binary name to locate (e.g. ``"scan-query"`` or ``"scan-index"``).
        plugin_root: Root of the plugin repository.  When provided and the binary
            is not on ``PATH``, the function checks the local plugin ``bin/``
            directory.

    Returns:
        Resolved :class:`~pathlib.Path` to the binary, or ``None`` when not found.
    """
    which = shutil.which(name)
    if which:
        return Path(which)
    if plugin_root:
        candidate = plugin_root / "plugins" / "codemap" / "bin" / name
        if candidate.exists():
            return candidate
    return None


def run_scan_query_result(scan_query_bin: Path, args: list[str], index_path: Path, repo_path: Path) -> ScanResult:
    """Run scan-query and return a :class:`ScanResult` distinguishing success from failure.

    Always passes ``--index <index_path>`` explicitly so scan-query uses the
    correct index regardless of ``cwd`` or git availability.  On failure the
    ``error`` field carries a short reason (a trailing stderr line when
    available) so a crashed / timed-out / absent-module query is never confused
    with a genuine empty result.

    Args:
        scan_query_bin: Path to the scan-query Python script.
        args: Subcommand and its arguments (e.g. ``["rdeps", "foo.bar"]``).
        index_path: Path to the pre-built codemap JSON index.
        repo_path: Working directory for the subprocess (the repository root).

    Returns:
        :class:`ScanResult` with ``data`` set and ``error=None`` on success, or
        ``data=None`` and a non-empty ``error`` reason on any failure.
    """
    # Pass --index explicitly so scan-query uses the correct index regardless of cwd / git availability.
    cmd = ["python3", str(scan_query_bin.resolve()), "--index", str(index_path.resolve())] + args
    try:
        result = _run(cmd, cwd=str(repo_path))
    except subprocess.TimeoutExpired:
        return ScanResult(data=None, error="timeout after 30s")
    except OSError as exc:
        return ScanResult(data=None, error=f"os error: {exc}")
    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        detail = stderr_lines[-1][:200] if stderr_lines else f"exit {result.returncode}"
        return ScanResult(data=None, error=f"exit {result.returncode}: {detail}")
    try:
        return ScanResult(data=json.loads(result.stdout), error=None)
    except json.JSONDecodeError as exc:
        return ScanResult(data=None, error=f"invalid JSON: {exc}")


def run_scan_query(scan_query_bin: Path, args: list[str], index_path: Path, repo_path: Path) -> dict | None:
    """Run scan-query with the given subcommand arguments and return parsed JSON output.

    Thin wrapper over :func:`run_scan_query_result` that discards the error
    reason.  Retained for call sites that only need the parsed data and treat
    any failure as ``None``.

    Args:
        scan_query_bin: Path to the scan-query Python script.
        args: Subcommand and its arguments (e.g. ``["rdeps", "foo.bar"]``).
        index_path: Path to the pre-built codemap JSON index.
        repo_path: Working directory for the subprocess (the repository root).

    Returns:
        Parsed JSON dict from scan-query stdout, or ``None`` on non-zero exit
        code, timeout, JSON decode error, or OS error.
    """
    return run_scan_query_result(scan_query_bin, args, index_path, repo_path).data


# ---- ACCURACY ----


def codemap_rdeps_result(
    scan_query_bin: Path, index_path: Path, repo_path: Path, module: str
) -> tuple[set[str], str | None]:
    """Retrieve a module's reverse-dependencies from the index, surfacing tool errors.

    Args:
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.
        repo_path: Working directory for the subprocess (the repository root).
        module: Dotted module name whose importers are to be retrieved.

    Returns:
        Tuple ``(importers, error)``.  ``error`` is ``None`` on success — even
        when the importer set is legitimately empty — and a short reason string
        when scan-query failed.  When ``error`` is set the returned set is empty
        and must NOT be scored as a passing result.
    """
    res = run_scan_query_result(scan_query_bin, ["rdeps", module], index_path, repo_path)
    if not res.ok:
        return set(), res.error
    return set((res.data or {}).get("imported_by", [])), None


# ---- COVERAGE GAP (real importer-set comparison) ----


def grep_importers_boundary(repo_path: Path, module: str) -> set[str]:
    """Find importers of ``module`` with a boundary-anchored, import-statement grep.

    Unlike a naive dotted-name grep, the pattern is anchored to the start of the line
    (allowing leading whitespace) and requires ``module`` to be followed by
    whitespace, a dot, or end-of-line.  This avoids substring false matches such
    as ``import pkg.target_helper`` matching a search for ``pkg.target``.  It
    still misses relative (``from . import x``) and aliased-package imports that
    do not spell the dotted name literally — those are recovered by
    :func:`verify_importer` during coverage-gap analysis.

    Args:
        repo_path: Root of the repository to search.
        module: Dotted module name whose importers are to be found.

    Returns:
        Set of dotted module names that textually import ``module``.  Excludes
        ``module`` itself.  Returns an empty set on timeout or no matches.
    """
    escaped = re.escape(module)
    # ^<ws>(from|import)<ws><module>(<ws> | . | EOL) — POSIX ERE for portability (BSD/GNU grep).
    pattern = rf"^[[:space:]]*(from|import)[[:space:]]+{escaped}([[:space:].]|$)"
    try:
        result = _run(
            [
                "grep",
                "-rlE",
                pattern,
                str(repo_path),
                "--include=*.py",
                "--exclude-dir=.git",
                "--exclude-dir=__pycache__",
            ]
        )
    except subprocess.TimeoutExpired:
        return set()

    modules: set[str] = set()
    repo_root = str(repo_path)
    for line in result.stdout.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        mod = path_to_module(stripped, repo_root)
        if mod and mod != module:
            modules.add(mod)
    return modules


def module_to_source_file(module: str, repo_root: Path) -> Path | None:
    """Resolve a dotted module name to its source ``.py`` file on disk.

    Checks ``src/`` layout and ``__init__.py`` package variants, mirroring the
    candidate order used by :func:`count_cold_calls_deps`.

    Args:
        module: Dotted module name (e.g. ``"pkg.sub.mod"``).
        repo_root: Repository root to resolve the module against.

    Returns:
        The first existing candidate path, or ``None`` when no source file is
        found.

    Examples:
        >>> module_to_source_file("nope.not.here", Path("/tmp")) is None
        True
    """
    parts = module.replace(".", "/")
    candidates = [
        repo_root / "src" / f"{parts}.py",
        repo_root / f"{parts}.py",
        repo_root / "src" / parts / "__init__.py",
        repo_root / parts / "__init__.py",
    ]
    return next((c for c in candidates if c.exists()), None)


def _file_base_package(file_path: Path, repo_root: Path) -> str:
    """Return the dotted package that contains ``file_path`` (for relative-import resolution).

    Args:
        file_path: Path to a ``.py`` source file.
        repo_root: Repository root used as the relative base.

    Returns:
        Dotted name of the directory containing the file (empty string when the
        file sits at the repository root or under a bare ``src/`` layout root).
    """
    rel = os.path.relpath(str(file_path), str(repo_root))
    if rel.startswith("src/"):
        rel = rel[4:]
    directory = os.path.dirname(rel)
    return directory.replace("/", ".").strip(".")


def _resolve_relative(base_package: str, level: int, module: str | None) -> str:
    """Resolve a relative import target to its absolute dotted module base.

    Args:
        base_package: Dotted package containing the importing file (``level`` 1
            resolves against this package).
        level: Relative-import level (number of leading dots).
        module: The dotted suffix after the dots, or ``None`` for ``from . import x``.

    Returns:
        Absolute dotted base for the import (may be an empty string when the
        relative reference escapes the resolvable root).

    Examples:
        >>> _resolve_relative("pkg.rel", 2, "target")
        'pkg.target'
        >>> _resolve_relative("pkg.rel", 1, None)
        'pkg.rel'
    """
    parts = base_package.split(".") if base_package else []
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    base = ".".join(parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _imported_names_from_source(source: str, base_package: str) -> set[str]:
    """Collect every absolute dotted name referenced by the import statements in ``source``.

    Handles ``import a.b``, ``import a.b as c``, ``from a.b import c`` (recording
    both ``a.b`` and ``a.b.c``), and relative imports resolved against
    ``base_package``.

    Args:
        source: Python source text to parse.
        base_package: Dotted package of the source file, for relative imports.

    Returns:
        Set of absolute dotted names introduced by import statements.

    Raises:
        SyntaxError: If ``source`` cannot be parsed.
    """
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_relative(base_package, node.level, node.module) if node.level else (node.module or "")
            if base:
                names.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                names.add(f"{base}.{alias.name}" if base else alias.name)
    return names


def file_imports_module(file_path: Path, target_module: str, repo_root: Path) -> bool:
    """Verify by AST that ``file_path`` truly imports ``target_module``.

    A file imports the target when any import statement resolves to the target
    module itself or to a descendant of it (importing ``a.b.c`` imports the
    package ``a.b``).  Relative and aliased imports are resolved correctly.

    Args:
        file_path: Path to the importing source file.
        target_module: Dotted module name whose import is being verified.
        repo_root: Repository root, used to resolve relative imports.

    Returns:
        ``True`` when the file imports the target module; ``False`` on read
        error, syntax error, or when no matching import is found.
    """
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    try:
        names = _imported_names_from_source(source, _file_base_package(file_path, repo_root))
    except SyntaxError:
        return False
    prefix = f"{target_module}."
    return any(name == target_module or name.startswith(prefix) for name in names)


def verify_importer(candidate_module: str, target_module: str, repo_root: Path) -> bool:
    """Confirm that ``candidate_module``'s source file actually imports ``target_module``.

    Resolves the candidate to a source file and delegates to
    :func:`file_imports_module`.  Used to filter grep-missed extras down to true
    importers when computing the coverage gap.

    Args:
        candidate_module: Dotted module claimed (by the index) to import the target.
        target_module: Dotted module whose import is being verified.
        repo_root: Repository root for file resolution.

    Returns:
        ``True`` only when the candidate resolves to a file that genuinely
        imports the target module.
    """
    source_file = module_to_source_file(candidate_module, repo_root)
    if source_file is None:
        return False
    return file_imports_module(source_file, target_module, repo_root)


def compute_precision_recall(codemap_set: set[str], grep_set: set[str]) -> AccuracyStats:
    """Compute precision and recall of codemap rdeps relative to a grep baseline.

    Uses grep as the reference set (not ground truth — grep can miss aliased or
    conditional imports).  Precision measures how much of what codemap returns
    is confirmed by grep; recall measures how much of what grep finds codemap
    also returns.

    Args:
        codemap_set: Set of module names returned by scan-query rdeps.
        grep_set: Set of module names found by the grep baseline.

    Returns:
        :class:`AccuracyStats` with precision, recall, TP/FP/FN counts, and the
        sorted lists of false-positive and false-negative module names.
        Precision defaults to ``1.0`` when ``codemap_set`` is empty; recall
        defaults to ``1.0`` when ``grep_set`` is empty.
    """
    tp_set = codemap_set & grep_set
    fp_set = codemap_set - grep_set
    fn_set = grep_set - codemap_set
    precision = len(tp_set) / len(codemap_set) if codemap_set else 1.0
    recall = len(tp_set) / len(grep_set) if grep_set else 1.0
    return AccuracyStats(
        precision=round(precision, 4),
        recall=round(recall, 4),
        tp=len(tp_set),
        fp=len(fp_set),
        fn=len(fn_set),
        fp_modules=sorted(fp_set),
        fn_modules=sorted(fn_set),
    )


def score_rdeps_accuracy(
    codemap_set: set[str], grep_floor: set[str], target_module: str, repo_root: Path
) -> AccuracyStats:
    """Score codemap rdeps with an AST-verified precision oracle and a grep recall floor.

    Precision is judged against an independent AST import-resolver: every module
    codemap returns is confirmed (or refuted) by parsing its source
    (:func:`verify_importer`), so codemap is never penalised for surfacing
    aliased, relative, or ``__init__`` re-export importers that a literal grep
    cannot see.  Recall is a *floor* — the fraction of the conservative
    boundary-anchored grep importer set that codemap also returns; because
    boundary-grep matches are genuine importers, codemap should contain them all.

    Args:
        codemap_set: Set of module names returned by scan-query rdeps.
        grep_floor: Boundary-anchored grep importer set used as the recall floor.
        target_module: Module whose importers are under test (for AST verification).
        repo_root: Repository root used to resolve candidate source files.

    Returns:
        :class:`AccuracyStats` where ``precision`` is AST-verified precision,
        ``recall`` is grep-floor coverage, ``fp``/``fp_modules`` are codemap
        members the AST oracle rejects (genuine false positives), ``fn``/
        ``fn_modules`` are grep-floor importers codemap missed, and ``tp`` is the
        codemap∩grep_floor overlap (the recall numerator).
    """
    verified = {m for m in codemap_set if verify_importer(m, target_module, repo_root)}
    ast_false_positives = codemap_set - verified
    floor_hits = codemap_set & grep_floor
    missed_floor = grep_floor - codemap_set
    precision = len(verified) / len(codemap_set) if codemap_set else 1.0
    recall = len(floor_hits) / len(grep_floor) if grep_floor else 1.0
    return AccuracyStats(
        precision=round(precision, 4),
        recall=round(recall, 4),
        tp=len(floor_hits),
        fp=len(ast_false_positives),
        fn=len(missed_floor),
        fp_modules=sorted(ast_false_positives),
        fn_modules=sorted(missed_floor),
    )


# ---- LATENCY ----


def time_command(cmd: list[str], n: int = 5, cwd: str | None = None) -> TimingStats:
    """Time a single command over ``n`` repeated runs and return sorted wall-clock statistics.

    Timings are sorted before computing the median to eliminate cold-start
    outliers.  Timed-out runs are recorded as 30,000 ms (the subprocess timeout).

    Args:
        cmd: Command to run, formatted as a list of strings for
            :func:`subprocess.run`.
        n: Number of repetitions.  Default is 5.
        cwd: Working directory for the subprocess.  ``None`` inherits the current
            process directory.

    Returns:
        :class:`TimingStats` with ``min_ms``, ``median_ms``, ``max_ms`` (all in
        milliseconds, rounded to 2 decimal places), and ``n`` (run count).
    """
    timings: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        try:
            _run(cmd, cwd=cwd)
        except subprocess.TimeoutExpired:
            timings.append(30_000.0)
            continue
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return TimingStats(
        min_ms=round(timings[0], 2), median_ms=round(statistics.median(timings), 2), max_ms=round(timings[-1], 2), n=n
    )


def time_commands(cmds: list[list[str]], n: int = 3, cwd: str | None = None) -> TimingStats:
    """Time a sequence of commands as one logical operation (e.g. a cold grep session).

    Runs all commands in ``cmds`` back-to-back per repetition, measuring total
    elapsed wall-clock time for the whole sequence.  Timed-out individual
    commands are skipped but their wall-clock contribution is still counted.
    Timings are sorted before computing the median to eliminate cold-start
    outliers.

    Args:
        cmds: Sequence of commands to run in order; each command is a list of
            strings suitable for :func:`subprocess.run`.
        n: Number of full repetitions of the command sequence.  Default is 3.
        cwd: Working directory for every subprocess call.  ``None`` inherits
            the current process directory.

    Returns:
        :class:`TimingStats` with ``min_ms``, ``median_ms``, ``max_ms`` (all
        in milliseconds, rounded to 2 decimal places), and ``n`` (repetition
        count).

    Examples:
        >>> import subprocess
        >>> stats = time_commands([["echo", "a"], ["echo", "b"]], n=3)
        >>> stats.n
        3
        >>> stats.median_ms >= 0
        True
    """
    timings: list[float] = []
    for _ in range(n):
        start = time.perf_counter()
        for cmd in cmds:
            try:
                _run(cmd, cwd=cwd)
            except subprocess.TimeoutExpired:
                pass
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    return TimingStats(
        min_ms=round(timings[0], 2), median_ms=round(statistics.median(timings), 2), max_ms=round(timings[-1], 2), n=n
    )


# ---- QUERY SHAPE ----


def validate_central_json(data: dict) -> ValidationResult:
    """Validate that a scan-query ``central`` response has the required structure.

    Checks that ``data`` contains a non-empty ``central`` list and that every
    item in the list has a ``rdep_count`` field.

    Args:
        data: Parsed JSON dict from a ``scan-query central`` call.

    Returns:
        :class:`ValidationResult` with ``ok=True`` on success, or ``ok=False``
        and a reason string describing the first structural violation found.
    """
    if "central" not in data:
        return ValidationResult(ok=False, reason="missing 'central' key")
    central = data["central"]
    if not isinstance(central, list) or len(central) == 0:
        return ValidationResult(ok=False, reason="'central' is empty or not a list")
    for item in central:
        if "rdep_count" not in item:
            return ValidationResult(ok=False, reason="central item missing 'rdep_count'")
    return ValidationResult(ok=True, reason="")


def validate_rdeps_json(data: dict) -> ValidationResult:
    """Validate that a scan-query ``rdeps`` response has the required structure.

    Checks that ``data`` contains both ``imported_by`` and ``module`` keys.

    Args:
        data: Parsed JSON dict from a ``scan-query rdeps`` call.

    Returns:
        :class:`ValidationResult` with ``ok=True`` on success, or ``ok=False``
        and a reason string describing the missing key.
    """
    if "imported_by" not in data:
        return ValidationResult(ok=False, reason="missing 'imported_by' key")
    if "module" not in data:
        return ValidationResult(ok=False, reason="missing 'module' key")
    return ValidationResult(ok=True, reason="")


def validate_deps_json(data: dict) -> ValidationResult:
    """Validate that a scan-query ``deps`` response has the required structure.

    Checks that ``data`` contains both ``direct_imports`` and ``module`` keys.

    Args:
        data: Parsed JSON dict from a ``scan-query deps`` call.

    Returns:
        :class:`ValidationResult` with ``ok=True`` on success, or ``ok=False``
        and a reason string describing the missing key.
    """
    if "direct_imports" not in data:
        return ValidationResult(ok=False, reason="missing 'direct_imports' key")
    if "module" not in data:
        return ValidationResult(ok=False, reason="missing 'module' key")
    return ValidationResult(ok=True, reason="")


_QUERY_SHAPE_VALIDATORS = {"central": validate_central_json, "rdeps": validate_rdeps_json, "deps": validate_deps_json}


def run_query_shape_query(
    scan_query_bin: Path, index_path: Path, repo_path: Path, query: Query
) -> tuple[bool, bool, dict | None, str | None]:
    """Run one skill query and validate its output SHAPE (not the injection path).

    Executes ``scan-query <query.cmd> <query.args>`` via
    :func:`run_scan_query_result` and validates the returned JSON using the
    registered validator for the command type (``central``, ``rdeps``, or
    ``deps``).  Commands without a registered validator (``path``, ``coupled``)
    are considered automatically valid when they return a non-null result.  A
    scan-query failure is reported as ``present=False`` with a non-empty error
    reason so the caller can surface it rather than treat it as a bad shape.

    Args:
        scan_query_bin: Path to the ``scan-query`` executable.
        index_path: Path to the pre-built codemap index JSON file.
        repo_path: Root directory of the repository under test.
        query: :class:`Query` specifying the command and its positional arguments.

    Returns:
        A 4-tuple ``(present, valid, data, error)`` where:

        - ``present`` (``bool``): ``True`` when scan-query returned a non-null result.
        - ``valid`` (``bool``): ``True`` when the result passes the structural
          JSON validator for ``query.cmd``, or when no validator is registered.
        - ``data`` (``dict | None``): The raw parsed JSON dict, or ``None`` on failure.
        - ``error`` (``str | None``): Short scan-query failure reason, or ``None``
          on success.
    """
    res = run_scan_query_result(scan_query_bin, [query.cmd] + query.args, index_path, repo_path)
    if not res.ok:
        return False, False, None, res.error
    data = res.data
    validator = _QUERY_SHAPE_VALIDATORS.get(query.cmd)
    if validator is None:
        return True, True, data, None  # path/coupled — no structural validator needed
    v = validator(data)
    return True, v.ok, data, None


# ---- REPORT ----


def render_report(
    results: list[ScenarioResult],
    repo_path: Path,
    index_path: Path,
    report_path: Path,
) -> None:
    """Render a markdown benchmark report with numeric values and relative margins.

    Args:
        results: Evaluated scenario results from all suites.
        repo_path: Path to the repository under test.
        index_path: Path to the codemap JSON index.
        report_path: Destination path for the markdown report.
    """
    lines: list[str] = []
    today = date.today().isoformat()

    # --- Gather repo info ---
    git_sha = "unknown"
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_path),
        )
        if r.returncode == 0:
            git_sha = r.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass

    # --- Count modules in index ---
    mod_count = 0
    degraded_count = 0
    if index_path.exists():
        try:
            with index_path.open() as f:
                idx = json.load(f)
            mods = idx.get("modules", [])
            mod_count = len(mods)
            degraded_count = sum(1 for m in mods if m.get("status") == "degraded")
        except (json.JSONDecodeError, OSError):
            pass

    # --- Compute suite verdicts ---
    suite_results: dict[str, SuiteStats] = {}
    for r_item in results:
        s = suite_results.setdefault(r_item.suite, SuiteStats())
        s.total += 1
        if r_item.passed:
            s.passed += 1
        else:
            s.failed += 1

    verdict = compute_verdict(results)
    primary_passed, primary_total = _tally(results, _PRIMARY_SUITES)
    self_consistency = compute_self_consistency(results)

    # --- Header ---
    lines.append(f"# Codemap Benchmark Report -- {today}")
    lines.append("")
    pass_pct = primary_passed / primary_total if primary_total else 0
    lines.append(
        f"**Verdict** (primary correctness): {verdict} — {primary_passed}/{primary_total} "
        f"primary scenarios ({pass_pct:.0%})"
    )
    lines.append(
        f"**Self-consistency** (determinism track, excluded from verdict): "
        f"{self_consistency['verdict']} — {self_consistency['passed']}/{self_consistency['total']}"
    )
    lines.append(f"**pytorch-lightning**: commit {git_sha}")
    lines.append(f"**Index**: {index_path} ({mod_count} modules, {degraded_count} degraded)")
    lines.append("")

    # --- Summary table (primary suites decide the verdict) ---
    lines.append("## Summary Table — primary suites")
    lines.append("")
    suite_display = {
        "calls": "Call Savings",
        "accuracy": "Accuracy",
        "latency": "Latency",
        "query-shape": "Query Shape",
    }
    suite_rows: list[dict] = []
    for key, label in suite_display.items():
        if key in suite_results:
            s = suite_results[key]
            rate = s.passed / s.total if s.total else 0
            if s.failed == 0:
                status = "\u2713"
            elif s.passed > 0:
                status = "~"
            else:
                status = "\u2717"
            suite_rows.append(
                {
                    "Suite": label,
                    "Scenarios": s.total,
                    "Pass Rate": f"{s.passed}/{s.total} ({rate:.0%})",
                    "Status": status,
                }
            )
    lines.append(pd.DataFrame(suite_rows).to_markdown(index=False))
    lines.append("")

    # --- Self-consistency (determinism) table — NOT counted in the verdict ---
    sc_display = {"symbol": "Symbol (S)", "health": "Health (H)", "xrefs": "Xrefs (X)"}
    sc_rows: list[dict] = []
    for key, label in sc_display.items():
        if key not in suite_results:
            continue
        s = suite_results[key]
        rate = s.passed / s.total if s.total else 0
        status = "✓" if s.failed == 0 else ("~" if s.passed > 0 else "✗")
        sc_rows.append(
            {"Suite": label, "Scenarios": s.total, "Pass Rate": f"{s.passed}/{s.total} ({rate:.0%})", "Status": status}
        )
    if sc_rows:
        lines.append("## Self-Consistency (determinism) Checks — NOT in the verdict")
        lines.append("")
        lines.append(
            "> Ground truth here is derived from scan-query's own output (frozen in tasks-bench.json), "
            "so a pass confirms determinism / index-version stability, not independent correctness."
        )
        lines.append("")
        lines.append(pd.DataFrame(sc_rows).to_markdown(index=False))
        lines.append("")

    # --- Call Savings table ---
    calls_items = [r for r in results if r.suite == "calls"]
    if calls_items:
        calls_rows: list[dict] = []
        for r_item in calls_items:
            res = r_item.result
            scen = r_item.scenario
            if scen == "C1":
                val = res.get("coverage_gap", 0)
                calls_rows.append(
                    {
                        "Scenario": f"{scen} {r_item.name}",
                        "Value": f"{val:.1%}",
                        "Notes": f"{res.get('verified_extras_total', '?')} verified extras / {res.get('codemap_set_total', '?')} importers",
                    }
                )
            elif scen == "C2":
                val = res.get("fraction", 0)
                calls_rows.append(
                    {
                        "Scenario": f"{scen} {r_item.name}",
                        "Value": f"{val:.1%}",
                        "Notes": f"{res.get('infeasible_count', '?')}/{res.get('total_path_queries', '?')} paths need >1 grep",
                    }
                )
            elif scen == "C3":
                val = res.get("leverage_ratio", 0)
                calls_rows.append(
                    {
                        "Scenario": f"{scen} {r_item.name}",
                        "Value": f"{val:.1f}×",
                        "Notes": f"{res.get('total_cold_calls', '?')} cold / {res.get('total_warm_calls', '?')} warm",
                    }
                )
        lines.append("## Call Savings\n")
        lines.append(pd.DataFrame(calls_rows).to_markdown(index=False))
        lines.append("")

    # --- Accuracy table (unified A1 + A2 with Suite column; A3 as summary line) ---
    acc_items = [r for r in results if r.suite == "accuracy"]
    if acc_items:
        a1 = next((r for r in acc_items if r.scenario == "A1"), None)
        a2 = next((r for r in acc_items if r.scenario == "A2"), None)
        a3 = next((r for r in acc_items if r.scenario == "A3"), None)

        acc_rows: list[dict] = []
        for suite_label, item in [("A1", a1), ("A2", a2)]:
            if item and "per_module" in item.result:
                for pm in item.result["per_module"]:
                    acc_rows.append(
                        {
                            "Suite": suite_label,
                            "Module": pm["module"],
                            "Recall": f"{pm['recall']:.2f}",
                            "Precision": f"{pm['precision']:.2f}",
                            "Codemap": pm["codemap_count"],
                            "Grep": pm["grep_count"],
                            "TP": pm["tp"],
                            "FP": pm["fp"],
                            "FN": pm["fn"],
                        }
                    )

        summary_parts = []
        if a1 and "avg_precision" in a1.result:
            summary_parts.append(
                f"A1 avg precision={a1.result['avg_precision']:.2f}  recall={a1.result.get('avg_recall', 0):.2f}"
            )
        if a2 and "min_precision" in a2.result:
            summary_parts.append(f"A2 min precision={a2.result['min_precision']:.2f}")
        if a3:
            fp_rate = a3.result.get("fp_rate", 0)
            total_cm = a3.result.get("total_codemap_results", "?")
            total_fp = a3.result.get("total_false_positives", "?")
            summary_parts.append(f"A3 FP rate={fp_rate:.2%} ({total_fp} FP / {total_cm} total)")

        lines.append("## Accuracy\n")
        if summary_parts:
            lines.append("> " + "  |  ".join(summary_parts))
            lines.append("")
        if acc_rows:
            lines.append(pd.DataFrame(acc_rows).to_markdown(index=False))
        lines.append("")

    # --- Latency table ---
    lat_items = [r for r in results if r.suite == "latency"]
    if lat_items:
        lat_rows: list[dict] = []
        for r_item in lat_items:
            res = r_item.result
            scen = r_item.scenario
            if scen == "L4":
                speedup = res.get("speedup", 0)
                lat_rows.append(
                    {
                        "Scenario": f"{scen} {r_item.name}",
                        "Measured": f"{speedup:.1f}×",
                        "Notes": f"cold {res.get('cold_total_median_ms', 0):.0f} ms  codemap {res.get('warm_total_ms', 0):.0f} ms",
                    }
                )
            else:
                median_ms = res.get("median_ms", 0)
                lat_rows.append(
                    {
                        "Scenario": f"{scen} {r_item.name}",
                        "Measured": f"{median_ms:.1f} ms",
                        "Notes": f"min {res.get('min_ms', 0):.1f}  max {res.get('max_ms', 0):.1f}",
                    }
                )
        lines.append("## Latency\n")
        lines.append(pd.DataFrame(lat_rows).to_markdown(index=False))
        lines.append("")

    # --- Query-shape table ---
    inj_items = [r for r in results if r.suite == "query-shape"]
    if inj_items:
        inj_rows: list[dict] = []
        for r_item in inj_items:
            res = r_item.result
            per_task = res.get("per_task", [])
            total = res.get("task_count", len(per_task))
            ok_count = sum(
                1 for d in per_task if all(v for k, v in d.items() if k.endswith("_present") or k.endswith("_valid"))
            )
            coverage = f"{ok_count / total:.0%}" if total else "N/A"
            inj_rows.append(
                {
                    "Scenario": r_item.scenario,
                    "Skill": r_item.name,
                    "Tasks OK": f"{ok_count}/{total}",
                    "Coverage": coverage,
                    "has_rdeps": "Yes" if res.get("has_rdeps") else "No",
                    "has_deps": "Yes" if res.get("has_deps") else "No",
                }
            )
        lines.append("## Query-Shape Validation (scan-query output shape only — not the injection path)\n")
        lines.append(pd.DataFrame(inj_rows).to_markdown(index=False))
        lines.append("")

    # --- False positive analysis (unchanged) ---
    fp_modules: list[dict] = []
    for r_item in results:
        if r_item.suite == "accuracy":
            res = r_item.result
            if "per_module" in res:
                fp_modules.extend(pm for pm in res["per_module"] if pm.get("fp_list"))
            elif res.get("fp_list"):
                fp_modules.append(res)
    if fp_modules:
        lines.append("## False Positive Analysis")
        lines.append("")
        for pm in fp_modules:
            mod_name = pm.get("module", "unknown")
            for fp_item in pm["fp_list"]:
                lines.append(
                    f"- **{mod_name}**: false positive `{fp_item}`"
                    " -- likely conditional/dynamic import"
                    " or re-export via __init__.py"
                )
        lines.append("")

    # --- Limitations (unchanged) ---
    lines.append("## Limitations")
    lines.append("")
    lines.append("- Cold call simulation is a lower bound -- real agents may issue more exploratory calls")
    lines.append("- Accuracy tested at one point in time against one version of pytorch-lightning")
    lines.append("- Latency results are hardware-dependent; thresholds calibrated for modern laptop (M1/M2)")
    lines.append("- Query-shape (Q) suite validates scan-query output structure only, NOT the skill injection path")
    lines.append("- Symbol/health/xrefs (S/H/X) are self-consistency/determinism checks, excluded from the verdict")
    lines.append("- Index staleness detection is not tested")
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# Suites that check codemap against an INDEPENDENT oracle — these alone decide the primary verdict.
_PRIMARY_SUITES = frozenset({"calls", "accuracy", "latency", "query-shape"})
# Suites validated against frozen scan-query-derived ground truth — determinism/regression only.
_SELF_CONSISTENCY_SUITES = frozenset({"symbol", "health", "xrefs"})


def _tally(results: list[ScenarioResult], suites: frozenset[str]) -> tuple[int, int]:
    """Return ``(passed, total)`` for the scenarios whose suite is in ``suites``.

    Args:
        results: All scenario results produced by the benchmark run.
        suites: Set of suite names to count.

    Returns:
        Tuple of passed-scenario count and total-scenario count for that subset.

    Examples:
        >>> a = ScenarioResult("C1", "x", "calls", True, {}, {})
        >>> b = ScenarioResult("S2", "x", "symbol", False, {}, {})
        >>> _tally([a, b], _PRIMARY_SUITES)
        (1, 1)
    """
    subset = [r for r in results if r.suite in suites]
    return sum(1 for r in subset if r.passed), len(subset)


def compute_verdict(results: list[ScenarioResult]) -> str:
    """Compute the PRIMARY correctness verdict (scenario-based, independent-oracle suites only).

    Only the primary suites (calls, accuracy, latency, query-shape) count — the
    self-consistency suites (symbol, health, xrefs), whose ground truth is
    scan-query-derived, are excluded so a block of near-guaranteed circular passes
    cannot float the verdict up.

    Args:
        results: All :class:`ScenarioResult` objects produced by the benchmark run.

    Returns:
        ``"PASS"`` when every primary scenario passed, ``"PARTIAL"`` when at least
        half passed, ``"FAIL"`` when fewer than half passed or there are no
        primary scenarios.
    """
    passed, total = _tally(results, _PRIMARY_SUITES)
    if total == 0:
        return "FAIL"
    if passed == total:
        return "PASS"
    if passed / total >= 0.5:
        return "PARTIAL"
    return "FAIL"


def compute_self_consistency(results: list[ScenarioResult]) -> dict:
    """Summarize the self-consistency / determinism track (symbol, health, xrefs).

    This track never contributes to :func:`compute_verdict`; it reports whether
    scan-query output is stable against its own frozen ground truth.

    Args:
        results: All scenario results produced by the benchmark run.

    Returns:
        Dict ``{"verdict", "passed", "total"}`` where verdict is ``"CONSISTENT"``
        (all passed), ``"PARTIAL"`` (≥50%), ``"INCONSISTENT"`` (<50%), or
        ``"SKIPPED"`` (no self-consistency scenarios ran).
    """
    passed, total = _tally(results, _SELF_CONSISTENCY_SUITES)
    if total == 0:
        verdict = "SKIPPED"
    elif passed == total:
        verdict = "CONSISTENT"
    elif passed / total >= 0.5:
        verdict = "PARTIAL"
    else:
        verdict = "INCONSISTENT"
    return {"verdict": verdict, "passed": passed, "total": total}


# ---- OUTPUT HELPERS ----


class _OutputState:
    """Module-level output-verbosity flag (mirrors the module-level ``_console``).

    ``quiet`` is set to ``True`` by :func:`main` in ``--json-only`` mode so that
    human progress narration via :func:`log` is suppressed and stdout carries
    only the scenario JSONL and the final summary envelope.
    """

    quiet: bool = False


_OUT = _OutputState()


def emit(result: ScenarioResult) -> None:
    """Print one compact JSON line describing a single scenario result to stdout.

    Emits the dataclass fields directly: ``scenario``, ``name``, ``suite``,
    ``passed``, ``result``, ``threshold``, and ``notes``.  Intended for machine
    consumption in ``--json-only`` mode (one JSON object per line).

    Args:
        result: The :class:`ScenarioResult` to serialize.

    Examples:
        >>> import io, json, contextlib
        >>> r = ScenarioResult("C1", "coverage-gap", "calls", True, {"coverage_gap": 0.5}, {})
        >>> buf = io.StringIO()
        >>> with contextlib.redirect_stdout(buf):
        ...     emit(r)
        >>> json.loads(buf.getvalue())["scenario"]
        'C1'
    """
    line = {
        "scenario": result.scenario,
        "name": result.name,
        "suite": result.suite,
        "passed": result.passed,
        "result": result.result,
        "threshold": result.threshold,
        "notes": result.notes,
    }
    print(json.dumps(line, separators=(",", ":"), default=str))


def build_summary_envelope(results: list[ScenarioResult], repo_path: Path, index_path: Path, verdict: str) -> dict:
    """Build the final one-line summary envelope for machine consumption.

    Aggregates per-suite pass/total counts keyed by the scenario ``suite`` field
    (``calls``, ``accuracy``, ``latency``, ``query-shape``, ``symbol``,
    ``health``, ``xrefs``), the PRIMARY-suite pass/total that the verdict is
    computed from, and the separate self-consistency track, plus scenario totals,
    date, repo, and index path.

    Args:
        results: All scenario results produced by the benchmark run.
        repo_path: Path to the repository under test.
        index_path: Path to the codemap index used.
        verdict: Primary correctness verdict (``PASS`` / ``PARTIAL`` / ``FAIL``).

    Returns:
        A JSON-serializable summary envelope dict.

    Examples:
        >>> r = ScenarioResult("C1", "x", "calls", True, {}, {})
        >>> env = build_summary_envelope([r], Path("/repo"), Path("/i.json"), "PASS")
        >>> env["primary"], env["suites"]["calls"]
        ({'passed': 1, 'total': 1}, {'passed': 1, 'total': 1})
    """
    suites: dict[str, dict[str, int]] = {}
    for r in results:
        bucket = suites.setdefault(r.suite, {"passed": 0, "total": 0})
        bucket["total"] += 1
        if r.passed:
            bucket["passed"] += 1
    primary_passed, primary_total = _tally(results, _PRIMARY_SUITES)
    return {
        "verdict": verdict,
        "scenarios_passed": sum(1 for r in results if r.passed),
        "scenarios_total": len(results),
        "primary": {"passed": primary_passed, "total": primary_total},
        "self_consistency": compute_self_consistency(results),
        "suites": suites,
        "date": date.today().isoformat(),
        "repo": str(repo_path),
        "index": str(index_path),
    }


def write_report_file(results: list[ScenarioResult], repo_path: Path, index_path: Path) -> str:
    """Resolve the report path once, render the report to it, and return that path.

    Resolving the destination a single time (rather than calling
    :func:`resolve_report_path` again after the file already exists) guarantees
    the returned path is exactly the file that was written — not a ``-2`` sibling
    that does not exist.

    Args:
        results: Scenario results to render.
        repo_path: Path to the repository under test.
        index_path: Path to the codemap index used.

    Returns:
        String path of the markdown report actually written.
    """
    report_path = resolve_report_path()
    render_report(results, repo_path, index_path, report_path)
    return str(report_path)


def log(msg: str) -> None:
    """Print a progress message to the rich console or stderr.

    Suppressed entirely when :data:`_OUT` is in quiet (``--json-only``) mode so
    that stdout is not polluted for machine consumers.

    Args:
        msg: Message string to display.
    """
    if _OUT.quiet:
        return
    if _IS_RICH_AVAILABLE and _console is not None:
        _console.print(msg)
    else:
        print(msg, file=sys.stderr)


# ---- SUITE: CALLS ----

_HIGH_RISK_TIERS = {"high", "very-high", "moderate-high"}


def _measure_coverage_gap(
    tasks: list[Task], repo_path: Path, scan_query_bin: Path, index_path: Path
) -> tuple[float, int, int, list[dict], list[str]]:
    """Measure the real importer coverage gap of codemap over boundary-anchored grep.

    For each high-risk task the codemap ``rdeps`` importer set is compared with a
    boundary-anchored grep importer set.  Every extra importer that codemap found
    but grep missed is AST-verified (:func:`verify_importer`) to confirm it is a
    genuine importer — resolving aliased, relative, and ``__init__`` re-export
    forms that grep's literal pattern cannot see.  The gap is the total verified
    extras divided by the total codemap importer count, aggregated across tasks.

    Args:
        tasks: All benchmark tasks (only high-risk tiers with an rdeps query count).
        repo_path: Root of the repository under test.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap index.

    Returns:
        Tuple ``(coverage_gap, verified_extras_total, codemap_set_total, per_task, errors)``
        where ``per_task`` is a JSON-serializable list of per-task breakdowns and
        ``errors`` lists ``"<task-id>: <reason>"`` for any task whose rdeps query
        failed (those tasks are excluded from the totals, never scored as empty).
    """
    per_task: list[dict] = []
    errors: list[str] = []
    verified_extras_total = 0
    codemap_set_total = 0
    for task in tasks:
        if task.risk_tier not in _HIGH_RISK_TIERS:
            continue
        rdeps_q = next((q for q in task.queries if q.cmd == "rdeps" and q.args), None)
        if rdeps_q is None:
            continue
        module = rdeps_q.args[0]
        cm_set, err = codemap_rdeps_result(scan_query_bin, index_path, repo_path, module)
        if err is not None:
            errors.append(f"{task.id}: {err}")
            per_task.append({"task_id": task.id, "module": module, "errored": True, "error": err})
            continue
        grep_set = grep_importers_boundary(repo_path, module)
        extras = cm_set - grep_set
        verified = sorted(e for e in extras if verify_importer(e, module, repo_path))
        verified_extras_total += len(verified)
        codemap_set_total += len(cm_set)
        per_task.append(
            {
                "task_id": task.id,
                "module": module,
                "codemap_count": len(cm_set),
                "grep_count": len(grep_set),
                "extras": sorted(extras),
                "verified_extras": verified,
                "verified_count": len(verified),
            }
        )
    coverage_gap = verified_extras_total / max(codemap_set_total, 1)
    return coverage_gap, verified_extras_total, codemap_set_total, per_task, errors


def _measure_infeasible_paths(tasks: list[Task], repo_path: Path) -> tuple[float, int, int, list[dict]]:
    """Measure the fraction of import paths that are not discoverable in a single grep.

    A path query ``A -> B`` is *1-grep-feasible* only when ``A`` is a direct
    importer of ``B`` — i.e. a single boundary-anchored grep for importers of
    ``B`` surfaces ``A`` directly (a direct edge).  When ``A`` is absent from
    ``B``'s direct importers the path requires at least one intermediate hop and
    is counted as infeasible.  The fraction is infeasible paths over all path
    queries.

    Args:
        tasks: All benchmark tasks (only those carrying ``path`` queries contribute).
        repo_path: Root of the repository under test.

    Returns:
        Tuple ``(fraction, infeasible_count, total_path_queries, per_path)`` where
        ``per_path`` is a JSON-serializable list of per-query direct-edge results.
    """
    per_path: list[dict] = []
    infeasible_count = 0
    total_path_queries = 0
    for task in tasks:
        for q in task.queries:
            if q.cmd != "path" or len(q.args) < 2:
                continue
            total_path_queries += 1
            frm, to = q.args[0], q.args[1]
            direct_edge = frm in grep_importers_boundary(repo_path, to)
            if not direct_edge:
                infeasible_count += 1
            per_path.append({"from": frm, "to": to, "direct_edge": direct_edge})
    fraction = infeasible_count / max(total_path_queries, 1)
    return fraction, infeasible_count, total_path_queries, per_path


def run_measure_calls(repo_path: Path, scan_query_bin: Path, index_path: Path) -> list[ScenarioResult]:
    """Run Suite C — coverage gap, infeasible-path fraction, and leverage ratio.

    Evaluates three scenarios: C1 (real importer coverage gap of codemap vs a
    boundary-anchored grep, AST-verified), C2 (fraction of import paths that need
    more than one grep hop), and C3 (leverage ratio of cold vs warm call counts).

    Args:
        repo_path: Root of the pytorch-lightning repository to search.
        scan_query_bin: Path to the scan-query executable (used for C1 rdeps).
        index_path: Path to the pre-built codemap index (used for C1 rdeps).

    Returns:
        List of three :class:`ScenarioResult` objects (C1, C2, C3).
    """
    results: list[ScenarioResult] = []
    tasks = load_tasks()
    log("[calls] Starting call-savings measurement...")

    # C1: coverage gap — verified importers codemap finds that a boundary grep misses
    log("[calls] C1: coverage-gap")
    coverage_gap, verified_extras_total, codemap_set_total, cov_per_task, cov_errors = _measure_coverage_gap(
        tasks, repo_path, scan_query_bin, index_path
    )
    # A scan-query failure must not pass silently as a zero-gap empty result — fail C1 when any task errored.
    passed = coverage_gap >= THRESHOLDS["C1"]["coverage_gap_min"] and not cov_errors
    err_note = f"; {len(cov_errors)} errored: {'; '.join(cov_errors)}" if cov_errors else ""
    r = ScenarioResult(
        scenario="C1",
        name="coverage-gap",
        suite="calls",
        passed=passed,
        result={
            "coverage_gap": round(coverage_gap, 4),
            "verified_extras_total": verified_extras_total,
            "codemap_set_total": codemap_set_total,
            "errored": cov_errors,
            "per_task": cov_per_task,
        },
        threshold=THRESHOLDS["C1"],
        notes=(
            f"{verified_extras_total} verified extras / {codemap_set_total} codemap importers; "
            f"gap={coverage_gap:.2%}{err_note}"
        ),
    )
    results.append(r)

    # C2: infeasible path fraction — paths where the source is not a direct importer of the target
    log("[calls] C2: infeasible-path-fraction")
    fraction, infeasible_count, total_path_queries, path_detail = _measure_infeasible_paths(tasks, repo_path)
    passed = fraction >= THRESHOLDS["C2"]["infeasible_path_fraction_min"]
    r = ScenarioResult(
        scenario="C2",
        name="infeasible-path-fraction",
        suite="calls",
        passed=passed,
        result={
            "total_path_queries": total_path_queries,
            "infeasible_count": infeasible_count,
            "fraction": round(fraction, 4),
            "per_path": path_detail,
        },
        threshold=THRESHOLDS["C2"],
        notes=f"{infeasible_count}/{total_path_queries} paths need >1 grep hop",
    )
    results.append(r)

    # C3: leverage ratio — structural context tokens / cold exploration tokens
    log("[calls] C3: leverage-ratio")
    total_cold = 0
    total_warm = 0
    for task in tasks:
        mod = task.primary_module
        total_cold += count_cold_calls_rdeps(repo_path, mod) + count_cold_calls_deps(repo_path, mod)
        total_warm += max(sum(1 for q in task.queries if q.cmd in ("rdeps", "deps")), 1)
    leverage_ratio = total_cold / max(total_warm, 1)
    passed = leverage_ratio >= THRESHOLDS["C3"]["leverage_ratio_min"]
    r = ScenarioResult(
        scenario="C3",
        name="leverage-ratio",
        suite="calls",
        passed=passed,
        result={
            "total_cold_calls": total_cold,
            "total_warm_calls": total_warm,
            "leverage_ratio": round(leverage_ratio, 2),
            "task_count": len(tasks),
        },
        threshold=THRESHOLDS["C3"],
        notes=f"cold={total_cold} calls; warm={total_warm}; ratio={leverage_ratio:.1f}x",
    )
    results.append(r)

    return results


# ---- SUITE: ACCURACY ----


_A1_TIERS = _HIGH_RISK_TIERS  # high-risk accuracy group (high / very-high / moderate-high)
_A2_TIERS = {"low"}  # low-risk accuracy group


def _errored_accuracy_row(task: Task, module: str, error: str) -> dict:
    """Build a zeroed, error-flagged accuracy row that is excluded from scoring.

    Args:
        task: The benchmark task whose rdeps query failed.
        module: The rdeps module argument that was queried.
        error: Short scan-query failure reason from :func:`codemap_rdeps_result`.

    Returns:
        A per-module dict with ``errored=True`` and zeroed metrics so the row is
        never scored as a passing empty result.
    """
    return {
        "module": module,
        "task_id": task.id,
        "risk_tier": task.risk_tier,
        "errored": True,
        "error": error,
        "codemap_count": 0,
        "grep_count": 0,
        "tp": 0,
        "fp": 0,
        "fn": 0,
        "precision": 0.0,
        "recall": 0.0,
        "fp_list": [],
        "fn_list": [],
    }


def _score_accuracy_tasks(tasks: list[Task], scan_query_bin: Path, index_path: Path, repo_path: Path) -> list[dict]:
    """Score every rdeps task with AST-verified precision and a grep recall floor.

    A scan-query failure is recorded as an errored row (via
    :func:`_errored_accuracy_row`) rather than a silent empty result, so a
    crashed or absent-module query can never score precision 1.0.

    Args:
        tasks: All benchmark tasks (those without an rdeps query are skipped).
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap index.
        repo_path: Root of the repository under test.

    Returns:
        List of per-module result dicts, one per task carrying an rdeps query.
    """
    scored: list[dict] = []
    for task in tasks:
        log(f"[accuracy] {task.id}: {task.primary_module} ({task.risk_tier})")
        rdeps_queries = [q for q in task.queries if q.cmd == "rdeps"]
        if not rdeps_queries:
            continue
        rdeps_mod = rdeps_queries[0].args[0]
        cm_set, err = codemap_rdeps_result(scan_query_bin, index_path, repo_path, rdeps_mod)
        if err is not None:
            scored.append(_errored_accuracy_row(task, rdeps_mod, err))
            continue
        grep_floor = grep_importers_boundary(repo_path, rdeps_mod)
        stats = score_rdeps_accuracy(cm_set, grep_floor, rdeps_mod, repo_path)
        scored.append(
            {
                "module": rdeps_mod,
                "task_id": task.id,
                "risk_tier": task.risk_tier,
                "errored": False,
                "codemap_count": len(cm_set),
                "grep_count": stats.tp + stats.fn,
                "tp": stats.tp,
                "fp": stats.fp,
                "fn": stats.fn,
                "precision": stats.precision,
                "recall": stats.recall,
                "fp_list": stats.fp_modules,
                "fn_list": stats.fn_modules,
            }
        )
    return scored


def _a1_scenario(rows: list[dict]) -> ScenarioResult:
    """Build the A1 result: AST-verified precision + grep recall floor for high-risk tasks."""
    thr = THRESHOLDS["A1"]
    group = [m for m in rows if m["risk_tier"] in _A1_TIERS]
    scored = [m for m in group if not m["errored"]]
    errored = [m for m in group if m["errored"]]
    if not scored:
        return ScenarioResult(
            "A1",
            "rdeps-accuracy-high",
            "accuracy",
            False,
            {"error": "no scored high-risk tasks", "errored": [m["module"] for m in errored], "per_module": group},
            thr,
            notes="no high-risk tasks scored",
        )
    avg_precision = statistics.mean(m["precision"] for m in scored)
    avg_recall = statistics.mean(m["recall"] for m in scored)
    for pm in scored:
        pm["pass"] = pm["precision"] >= thr["precision_min"] and pm["recall"] >= thr["recall_min"]
    passed = avg_precision >= thr["precision_min"] and avg_recall >= thr["recall_min"] and not errored
    err_note = f"; {len(errored)} errored" if errored else ""
    return ScenarioResult(
        "A1",
        "rdeps-accuracy-high",
        "accuracy",
        passed,
        {
            "avg_precision": round(avg_precision, 4),
            "avg_recall": round(avg_recall, 4),
            "errored": [m["module"] for m in errored],
            "per_module": group,
        },
        thr,
        notes=f"scored {len(scored)} high-risk tasks (AST precision, grep recall floor){err_note}",
    )


def _a2_scenario(rows: list[dict]) -> ScenarioResult:
    """Build the A2 result: AST-verified precision must be perfect for low-risk tasks.

    A2 is precision-only (no recall gate), so a non-errored EMPTY codemap result would score
    precision 1.0 vacuously — an empty non-answer is not a correct precise answer. Such modules are
    treated as N/A (excluded from the perfection check), never a free pass; if every low-risk module
    is empty or errored the scenario FAILS.
    """
    thr = THRESHOLDS["A2"]
    group = [m for m in rows if m["risk_tier"] in _A2_TIERS]
    errored = [m for m in group if m["errored"]]
    scored = [m for m in group if not m["errored"] and m["codemap_count"] > 0]
    vacuous = [m for m in group if not m["errored"] and m["codemap_count"] == 0]
    if not scored:
        return ScenarioResult(
            "A2",
            "rdeps-accuracy-low",
            "accuracy",
            False,
            {
                "error": "no low-risk tasks with a non-empty codemap result",
                "vacuous": [m["module"] for m in vacuous],
                "errored": [m["module"] for m in errored],
                "per_module": group,
            },
            thr,
            notes="no low-risk tasks scored (all empty or errored)",
        )
    min_precision = min(m["precision"] for m in scored)
    all_perfect = all(m["precision"] >= thr["precision_min"] for m in scored)
    for pm in scored:
        pm["pass"] = pm["precision"] >= thr["precision_min"]
    passed = all_perfect and not errored
    tail = f"; {len(vacuous)} N/A (empty)" if vacuous else ""
    tail += f"; {len(errored)} errored" if errored else ""
    return ScenarioResult(
        "A2",
        "rdeps-accuracy-low",
        "accuracy",
        passed,
        {
            "min_precision": min_precision,
            "all_perfect": all_perfect,
            "vacuous": [m["module"] for m in vacuous],
            "errored": [m["module"] for m in errored],
            "per_module": group,
        },
        thr,
        notes=f"scored {len(scored)} low-risk tasks; min AST precision = {min_precision}{tail}",
    )


def _a3_scenario(rows: list[dict]) -> ScenarioResult:
    """Build the A3 result: overall AST false-positive rate across all scored tasks."""
    thr = THRESHOLDS["A3"]
    scored = [m for m in rows if not m["errored"]]
    errored = [m for m in rows if m["errored"]]
    total_codemap = sum(m["codemap_count"] for m in scored)
    total_fp = sum(m["fp"] for m in scored)
    fp_rate = total_fp / total_codemap if total_codemap > 0 else 0.0
    passed = fp_rate <= thr["fp_rate_max"] and not errored
    err_note = f"; {len(errored)} errored" if errored else ""
    return ScenarioResult(
        "A3",
        "rdeps-fp-analysis",
        "accuracy",
        passed,
        {
            "total_codemap_results": total_codemap,
            "total_false_positives": total_fp,
            "fp_rate": round(fp_rate, 4),
            "errored": [m["module"] for m in errored],
            "fp_details": [{"module": m["module"], "fp_list": m["fp_list"]} for m in scored if m["fp_list"]],
        },
        thr,
        notes=f"AST false-positive rate: {fp_rate:.2%} across {len(scored)} scored tasks{err_note}",
    )


def run_measure_accuracy(repo_path: Path, scan_query_bin: Path, index_path: Path) -> list[ScenarioResult]:
    """Run Suite A — score scan-query rdeps with an AST oracle and a grep recall floor.

    For each task module, precision is judged against an independent AST
    import-resolver (the authoritative oracle — codemap is not penalised for
    surfacing aliased / relative / re-export importers grep cannot see) and
    recall is a floor against a boundary-anchored grep importer set.  A
    scan-query failure fails the scenario rather than scoring a false precision
    of 1.0.  Evaluates A1 (high-risk accuracy), A2 (low-risk precision), and A3
    (overall AST false-positive rate).

    Args:
        repo_path: Root of the pytorch-lightning repository.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.

    Returns:
        List of three :class:`ScenarioResult` objects (A1, A2, A3).
    """
    log("[accuracy] Starting accuracy measurement...")
    rows = _score_accuracy_tasks(load_tasks(), scan_query_bin, index_path, repo_path)
    return [_a1_scenario(rows), _a2_scenario(rows), _a3_scenario(rows)]


# ---- SUITE: LATENCY ----

# Assumed number of structural queries a skill session issues before the index goes stale.
# This is an explicit stated assumption, NOT telemetry: it is the divisor used to amortize the
# one-time scan-index build cost over a session (L3) and to fold the build into the honest
# build-inclusive speedup (L4). A conservative value; on a large repo the real build cost dominates
# and L3 is expected to fail under it — that failure is owned by the primary verdict, not hidden.
_QUERIES_PER_SESSION = 10


def run_measure_latency(
    repo_path: Path, scan_query_bin: Path, index_path: Path, scan_index_bin: Path | None
) -> list[ScenarioResult]:
    """Run Suite L — measure wall-clock latency of scan-query commands vs cold grep pipelines.

    Evaluates four scenarios: L1 (central query latency), L2 (rdeps query
    latency across 3 high-risk modules), L3 (amortized scan-index build time),
    and L4 (speedup of codemap vs equivalent cold grep baseline).

    Args:
        repo_path: Root of the pytorch-lightning repository.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.
        scan_index_bin: Path to the scan-index executable, or ``None`` when not
            found.  L3 is recorded as failed when this is ``None``.

    Returns:
        List of four :class:`ScenarioResult` objects (L1, L2, L3, L4).
    """
    results: list[ScenarioResult] = []
    cwd = str(repo_path)
    sq = str(scan_query_bin)
    log("[latency] Starting latency measurement...")

    # L1: central query latency
    log("[latency] L1: scan-query central --top 5")
    l1_timing = time_command(["python3", sq, "central", "--top", "5"], n=5, cwd=cwd)
    passed = l1_timing.median_ms <= THRESHOLDS["L1"]["median_ms_max"]
    r = ScenarioResult(
        scenario="L1",
        name="latency-central",
        suite="latency",
        passed=passed,
        result={
            "min_ms": l1_timing.min_ms,
            "median_ms": l1_timing.median_ms,
            "max_ms": l1_timing.max_ms,
            "runs": l1_timing.n,
        },
        threshold=THRESHOLDS["L1"],
        notes=f"5 runs; median={l1_timing.median_ms:.1f}ms",
    )
    results.append(r)

    # L2: rdeps query latency (sample 3 high-risk modules, 5 runs each)
    log("[latency] L2: scan-query rdeps (3 modules)")
    tasks = load_tasks()
    high_risk_mods = [t.primary_module for t in tasks if t.risk_tier in ("high", "very-high")][:3]
    module_medians: list[float] = []
    all_timings: dict[str, TimingStats] = {}
    for mod in high_risk_mods:
        mod_timing = time_command(["python3", sq, "rdeps", mod], n=5, cwd=cwd)
        module_medians.append(mod_timing.median_ms)
        all_timings[mod] = mod_timing

    overall_median = statistics.median(module_medians) if module_medians else 0
    passed = overall_median <= THRESHOLDS["L2"]["median_ms_max"]
    r = ScenarioResult(
        scenario="L2",
        name="latency-rdeps",
        suite="latency",
        passed=passed,
        result={
            "median_ms": round(overall_median, 2),
            "min_ms": round(min(module_medians), 2) if module_medians else 0,
            "max_ms": round(max(module_medians), 2) if module_medians else 0,
            "per_module": {
                m: {"min_ms": ts.min_ms, "median_ms": ts.median_ms, "max_ms": ts.max_ms, "runs": ts.n}
                for m, ts in all_timings.items()
            },
            "runs": 5,
        },
        threshold=THRESHOLDS["L2"],
        notes=f"median across {len(high_risk_mods)} modules = {overall_median:.1f}ms",
    )
    results.append(r)

    # L3: index build time (amortized over 10)
    log("[latency] L3: scan-index build time")
    if scan_index_bin:
        si = str(scan_index_bin)
        start = time.perf_counter()
        try:
            subprocess.run(["python3", si, "--root", str(repo_path)], capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            log("[latency] L3: scan-index timed out at 120s")
        build_ms = (time.perf_counter() - start) * 1000
        amortized_ms = build_ms / _QUERIES_PER_SESSION
        passed = amortized_ms <= THRESHOLDS["L3"]["amortized_ms_max"]
        r = ScenarioResult(
            scenario="L3",
            name="latency-index-build",
            suite="latency",
            passed=passed,
            result={
                "build_ms": round(build_ms, 2),
                "amortized_ms": round(amortized_ms, 2),
                "amortization_factor": _QUERIES_PER_SESSION,
                "median_ms": round(amortized_ms, 2),
                "min_ms": round(amortized_ms, 2),
                "max_ms": round(build_ms, 2),
            },
            threshold=THRESHOLDS["L3"],
            notes=(
                f"build={build_ms:.0f}ms; amortized over {_QUERIES_PER_SESSION} queries/session "
                f"= {amortized_ms:.0f}ms (assumption, not telemetry)"
            ),
        )
    else:
        r = ScenarioResult(
            scenario="L3",
            name="latency-index-build",
            suite="latency",
            passed=False,
            result={"error": "scan-index binary not found", "median_ms": 0, "min_ms": 0, "max_ms": 0},
            threshold=THRESHOLDS["L3"],
            notes="scan-index binary not found; cannot measure build time",
        )
    results.append(r)

    # L4: cold grep baseline vs codemap
    log("[latency] L4: cold grep baseline vs codemap")
    repo = str(repo_path)
    test_mod = high_risk_mods[0] if high_risk_mods else tasks[0].primary_module
    pattern = module_to_grep_pattern(test_mod)
    pkg = module_to_package(test_mod) or test_mod

    cold_central = time_commands(
        [
            ["find", repo, "-name", "*.py", "-not", "-path", "*/.git/*", "-not", "-path", "*/__pycache__/*"],
            ["grep", "-rn", r"^from \|^import ", repo, "--include=*.py", "-l"],
            ["grep", "-roh", r"from \([a-z_][a-z_.]*\) import\|^import \([a-z_][a-z_.]*\)", repo, "--include=*.py"],
        ]
    )
    cold_rdeps = time_commands(
        [
            ["grep", "-rn", pattern, repo, "--include=*.py"],
            ["grep", "-rn", f"from {pkg} import", repo, "--include=*.py"],
        ]
    )
    cold_total_median = cold_central.median_ms + cold_rdeps.median_ms
    warm_central_median = results[0].result["median_ms"]  # L1
    warm_rdeps_median = results[1].result["median_ms"]  # L2
    warm_total = warm_central_median + warm_rdeps_median
    speedup = cold_total_median / warm_total if warm_total > 0 else 0
    # Build-inclusive variant: fold the amortized one-time index build (from L3) into the warm side so
    # the showcase figure is honest. The pass gate stays on the warm-only (steady-state) speedup.
    build_ms = results[2].result.get("build_ms", 0)  # L3
    amortized_build_ms = build_ms / _QUERIES_PER_SESSION
    warm_total_build_inclusive = warm_total + amortized_build_ms
    speedup_build_inclusive = cold_total_median / warm_total_build_inclusive if warm_total_build_inclusive > 0 else 0
    passed = speedup >= THRESHOLDS["L4"]["speedup_min"]
    r = ScenarioResult(
        scenario="L4",
        name="latency-cold-grep-baseline",
        suite="latency",
        passed=passed,
        result={
            "cold_central_median_ms": cold_central.median_ms,
            "cold_rdeps_median_ms": cold_rdeps.median_ms,
            "cold_total_median_ms": round(cold_total_median, 2),
            "warm_total_ms": round(warm_total, 2),
            "speedup": round(speedup, 2),
            "amortized_build_ms": round(amortized_build_ms, 2),
            "warm_total_build_inclusive_ms": round(warm_total_build_inclusive, 2),
            "speedup_build_inclusive": round(speedup_build_inclusive, 2),
            "queries_per_session": _QUERIES_PER_SESSION,
            "median_ms": round(cold_total_median, 2),
            "min_ms": round(cold_central.min_ms + cold_rdeps.min_ms, 2),
            "max_ms": round(cold_central.max_ms + cold_rdeps.max_ms, 2),
        },
        threshold=THRESHOLDS["L4"],
        notes=(
            f"cold grep = {cold_total_median:.0f}ms; codemap warm = {warm_total:.0f}ms; "
            f"warm-only speedup = {speedup:.1f}x (gate); build-inclusive = {speedup_build_inclusive:.1f}x"
        ),
    )
    results.append(r)

    return results


# ---- SUITE: QUERY SHAPE ----


def _validate_skill_group(
    skill: str, tasks_for_skill: list[Task], scan_query_bin: Path, index_path: Path, repo_path: Path, threshold_key: str
) -> ScenarioResult:
    """Validate the scan-query output SHAPE for a skill group of tasks.

    For each task in ``tasks_for_skill``, runs every query defined on the task
    via :func:`run_query_shape_query` and checks that the result is both present
    (non-null) and structurally valid.  This checks output shape only — it does
    NOT invoke the skill or exercise its SKILL.md injection block.  Aggregates
    per-query pass/fail (and any scan-query errors) into a single
    :class:`ScenarioResult` for the whole skill group.

    Args:
        skill: Skill name, e.g. ``"fix"``, ``"feature"``, or ``"refactor"``.
            Used only for display labels and log messages.
        tasks_for_skill: Tasks to validate, filtered to this skill group.
        scan_query_bin: Path to the ``scan-query`` executable.
        index_path: Path to the pre-built codemap index JSON file.
        repo_path: Root directory of the repository under test.
        threshold_key: Key into :data:`THRESHOLDS` for this group (e.g.
            ``"Q_fix"``, ``"Q_feature"``, ``"Q_refactor"``).

    Returns:
        :class:`ScenarioResult` whose ``passed`` field is ``True`` only when
        every query across all tasks in the group is present and valid, and
        (for ``threshold_key="Q_refactor"``) at least one rdeps and one deps
        result was returned.
    """
    log(f"[query-shape] {threshold_key}: develop:{skill} ({len(tasks_for_skill)} tasks)")

    per_task_details: list[dict] = []
    errors: list[str] = []
    all_ok = True

    for task in tasks_for_skill:
        task_detail: dict = {"task_id": task.id, "module": task.primary_module}

        for q in task.queries:
            bp, jv, data, err = run_query_shape_query(scan_query_bin, index_path, repo_path, q)
            if err is not None:
                errors.append(f"{task.id} {q.cmd}: {err}")
            if q.cmd in ("central", "coupled"):
                task_detail[f"{q.cmd}_present"] = bp
                task_detail[f"{q.cmd}_valid"] = jv
                if not (bp and jv):
                    all_ok = False
            elif q.cmd == "rdeps":
                task_detail["rdeps_present"] = bp
                task_detail["rdeps_valid"] = jv
                task_detail["rdeps_count"] = len(data.get("imported_by", [])) if data else 0
                if not (bp and jv):
                    all_ok = False
            elif q.cmd == "deps":
                task_detail["deps_present"] = bp
                task_detail["deps_valid"] = jv
                task_detail["deps_count"] = len(data.get("direct_imports", [])) if data else 0
                if not (bp and jv):
                    all_ok = False
            elif q.cmd == "path":
                task_detail["path_present"] = bp
                if not bp:
                    all_ok = False

        per_task_details.append(task_detail)

    threshold = THRESHOLDS[threshold_key]
    has_rdeps = any(d.get("rdeps_present", False) for d in per_task_details)
    has_deps = any(d.get("deps_present", False) for d in per_task_details)

    passed = all_ok
    if threshold.get("has_rdeps"):
        passed = passed and has_rdeps
    if threshold.get("has_deps"):
        passed = passed and has_deps

    err_note = f"; {len(errors)} scan-query errors: {'; '.join(errors)}" if errors else ""
    return ScenarioResult(
        scenario=threshold_key,
        name=f"develop:{skill}",
        suite="query-shape",
        passed=passed,
        result={
            "block_present": all_ok,
            "json_valid": all_ok,
            "has_rdeps": has_rdeps,
            "has_deps": has_deps,
            "errors": errors,
            "task_count": len(tasks_for_skill),
            "per_task": per_task_details,
        },
        threshold=threshold,
        notes=f"validated {len(tasks_for_skill)} {skill} tasks (shape only, not the injection path){err_note}",
    )


def run_measure_query_shape(
    plugin_root: Path, repo_path: Path, scan_query_bin: Path, index_path: Path
) -> list[ScenarioResult]:
    """Run Suite Q — verify each skill group's scan-query output SHAPE is valid.

    Runs the same scan-query commands that develop:fix, develop:feature, and
    develop:refactor would issue, then validates the output structure.  The skill
    is NOT invoked and its SKILL.md injection block is NOT exercised; only the
    binary output shape is checked — a pass proves the queries return
    well-formed JSON, not that injection wiring is present or active.

    Args:
        plugin_root: Root of the plugin repository (used as ``cwd`` fallback).
        repo_path: Root of the pytorch-lightning repository.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.

    Returns:
        List of three :class:`ScenarioResult` objects (Q_fix, Q_feature, Q_refactor).
    """
    results: list[ScenarioResult] = []
    log("[query-shape] Starting query-shape validation...")

    for skill, key in [("fix", "Q_fix"), ("feature", "Q_feature"), ("refactor", "Q_refactor")]:
        r = _validate_skill_group(skill, load_tasks(skill_filter=skill), scan_query_bin, index_path, repo_path, key)
        results.append(r)

    return results


# ---- VERIFY TASKS ----


def run_verify_tasks(scan_query_bin: Path, index_path: Path, repo_path: Path) -> None:
    """Verify that all task primary_modules exist in the index with status 'ok'."""
    log("[verify] Checking task modules against index...")
    tasks = load_tasks()

    if not index_path.exists():
        log(f"[verify] ERROR: index not found at {index_path}")
        return

    try:
        with index_path.open() as f:
            idx = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log(f"[verify] ERROR: cannot read index: {exc}")
        return

    module_map = {m["name"]: m for m in idx.get("modules", [])}

    central_data = run_scan_query(scan_query_bin, ["central", "--top", "15"], index_path, repo_path)
    top_names: list[str] = (
        [c["name"] for c in central_data["central"]] if central_data and "central" in central_data else []
    )

    task_modules = {t.primary_module for t in tasks}
    missing: list[str] = []

    for task in tasks:
        entry = module_map.get(task.primary_module)
        if entry is None:
            log(f"[verify] WARN: {task.id} {task.primary_module} -- NOT FOUND in index")
            missing.append(task.primary_module)
        elif entry.get("status") != "ok":
            log(f"[verify] WARN: {task.id} {task.primary_module} -- status={entry.get('status')} (not 'ok')")
        else:
            log(f"[verify] OK: {task.id} {task.primary_module} -- rdep_count={entry.get('rdep_count', 0)}, status=ok")

    if missing:
        candidates = [n for n in top_names if n not in task_modules]
        if candidates:
            log(f"[verify] Suggested substitutes from central --top 15: {candidates[: len(missing)]}")
        else:
            log("[verify] No substitute candidates available from central --top 15")


# ---- REPORT PATH ----


def resolve_report_path() -> Path:
    """Return a non-conflicting path for the benchmark markdown report.

    Creates ``benchmarks/results/`` if it does not exist.  Returns
    ``benchmarks/results/code-<YYYY-MM-DD>.md`` for the first call on a given
    day; appends ``-2``, ``-3``, etc. on subsequent calls to avoid overwriting
    earlier runs.

    Returns:
        :class:`~pathlib.Path` to a file that does not yet exist.
    """
    today = date.today().isoformat()
    base_dir = Path("benchmarks") / "results"
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = base_dir / f"code-{today}.md"
    if not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = base_dir / f"code-{today}-{counter}.md"
        if not candidate.exists():
            return candidate
        counter += 1


# ---- MAIN ----


def resolve_repo_path(arg: str | None) -> Path | None:
    """Resolve the path to the pytorch-lightning clone to benchmark.

    Resolution order:
    1. ``arg`` when provided and is an existing directory.
    2. ``$PYTORCH_LIGHTNING_PATH`` environment variable.
    3. ``./pytorch-lightning`` relative to the current working directory.

    Args:
        arg: Value of the ``--repo-path`` CLI flag, or ``None``.

    Returns:
        Resolved :class:`~pathlib.Path` to the repository root, or ``None``
        when no valid directory is found (error logged to stderr).
    """
    if arg:
        p = Path(arg)
        if p.is_dir():
            return p
        log(f"ERROR: --repo-path {arg} is not a directory")
        return None
    env_path = os.environ.get("PYTORCH_LIGHTNING_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_dir():
            return p
        log(f"WARN: $PYTORCH_LIGHTNING_PATH={env_path} is not a directory")
    local = Path("pytorch-lightning")
    if local.is_dir():
        return local
    log("ERROR: cannot find pytorch-lightning repo. Provide --repo-path or set $PYTORCH_LIGHTNING_PATH")
    return None


def resolve_index_path(arg: str | None, repo_path: Path) -> Path:
    """Resolve the path to the pre-built codemap JSON index.

    When ``arg`` is given it is used directly.  Otherwise searches
    ``<repo_path>/.cache/codemap/`` then ``<repo_path>/.cache/scan/`` for a
    JSON file whose stem matches the repository directory name (with ``-master``
    and ``-main`` suffixes stripped).  Falls back to the first ``.json`` found
    in the directory, then to the canonical default path
    ``<repo_path>/.cache/codemap/<bare-name>.json``.

    Args:
        arg: Value of the ``--index-path`` CLI flag, or ``None``.
        repo_path: Resolved path to the pytorch-lightning repository root.

    Returns:
        :class:`~pathlib.Path` to the index file.  The path may not exist yet
        when the index has not been built; callers must check with
        :meth:`~pathlib.Path.exists`.
    """
    if arg:
        return Path(arg)
    stems = [repo_path.name, repo_path.name.replace("-master", ""), repo_path.name.replace("-main", "")]
    # Check both canonical locations: new (.cache/codemap/) then legacy (.cache/scan/)
    for cache_subdir in (".cache/codemap", ".cache/scan"):
        d = repo_path / cache_subdir
        for stem in stems:
            p = d / f"{stem}.json"
            if p.exists():
                return p
        if d.exists():
            jsons = sorted(d.glob("*.json"))
            if jsons:
                return jsons[0]
    bare = repo_path.name.replace("-master", "").replace("-main", "")
    return repo_path / ".cache" / "codemap" / f"{bare}.json"


# ---- SUITE S — SYMBOL LOOKUP ----


def run_suite_symbol(
    scan_query_bin: Path,
    index_path: Path,
    repo_path: Path,
) -> list[ScenarioResult]:
    """Suite S: symbol line-range self-consistency / determinism check.

    Runs the ``symbol`` command for each S-task in tasks-bench.json and compares
    ``start_line`` / ``end_line`` against ground truth (±3 lines tolerance for
    disambiguating decorator vs def line).  The ground-truth line numbers are
    derived from scan-query's own output, so this validates determinism and
    index-version stability, not independent correctness — it is reported on the
    self-consistency track and EXCLUDED from the primary verdict.

    Args:
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap index.
        repo_path: Root of the pytorch-lightning repository.

    Returns:
        List of ScenarioResult — one per S-task, plus an aggregate S2 (all-pass rate).
    """
    tasks = load_oss_tasks(type_filter="symbol_extraction")
    if not tasks:
        log("[suite-S] tasks-bench.json not found or no symbol_extraction tasks — skipping")
        return []

    results: list[ScenarioResult] = []
    passed_count = 0

    for task in tasks:
        task_id = task["id"]
        gt = task.get("ground_truth", {})
        qname = gt.get("qualified_name", "")
        module = gt.get("module", "")
        expected_start = gt.get("start_line", 0)
        expected_end = gt.get("end_line", 0)

        sq = run_scan_query_result(scan_query_bin, ["symbol", qname], index_path, repo_path)
        if not sq.ok:
            results.append(
                ScenarioResult(
                    scenario=f"S_{task_id}",
                    name=f"symbol-{task_id}",
                    suite="symbol",
                    passed=False,
                    result={"error": sq.error},
                    threshold=THRESHOLDS["S1"],
                    notes=f"qname={qname}: {sq.error}",
                )
            )
            continue
        data = sq.data

        symbols = data.get("symbols", [])
        match = next(
            (s for s in symbols if s.get("qualified_name") == qname and s.get("module") == module),
            None,
        ) or next((s for s in symbols if s.get("qualified_name") == qname), None)

        symbol_found = match is not None
        start_ok = symbol_found and abs(match.get("start_line", 0) - expected_start) <= 3
        end_ok = symbol_found and abs(match.get("end_line", 0) - expected_end) <= 3
        passed = symbol_found and start_ok

        if passed:
            passed_count += 1

        results.append(
            ScenarioResult(
                scenario=f"S_{task_id}",
                name=f"symbol-{task_id}",
                suite="symbol",
                passed=passed,
                result={
                    "symbol_found": symbol_found,
                    "start_line_ok": start_ok,
                    "end_line_ok": end_ok,
                    "got_start": match.get("start_line") if match else None,
                    "got_end": match.get("end_line") if match else None,
                    "expected_start": expected_start,
                    "expected_end": expected_end,
                    "count_returned": len(symbols),
                },
                threshold=THRESHOLDS["S1"],
                notes=f"qname={qname} module={module}",
            )
        )

    # Aggregate: S2 = all symbol tasks passed
    total = len(tasks)
    all_pass_rate = passed_count / total if total else 0.0
    results.append(
        ScenarioResult(
            scenario="S2",
            name="symbol-all-pass-rate",
            suite="symbol",
            passed=passed_count == total,
            result={"passed": passed_count, "total": total, "pass_rate": round(all_pass_rate, 3)},
            threshold=THRESHOLDS["S2"],
            notes=f"{passed_count}/{total} symbol tasks passed",
        )
    )
    return results


# ---- SUITE H — HEALTH (undocumented / uncovered) ----


def run_suite_health(
    scan_query_bin: Path,
    index_path: Path,
    repo_path: Path,
) -> list[ScenarioResult]:
    """Suite H: undocumented/uncovered count self-consistency / determinism check.

    Runs each code_quality task that uses ``undocumented`` or ``uncovered`` commands and checks
    whether the returned ``total`` matches the ground truth count (exact match).  The counts in
    tasks-bench.json are frozen scan-query-derived (uncovered) or bench-generator-derived
    ground truth, so this is a regression/determinism check — reported on the self-consistency
    track and EXCLUDED from the primary verdict, not an independent-correctness measurement.

    Args:
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap index.
        repo_path: Root of the pytorch-lightning repository.

    Returns:
        List of ScenarioResult — one per relevant CQ-task (code_quality task prefix) plus H1/H2 aggregates.
    """
    tasks = load_oss_tasks(type_filter="code_quality")
    if not tasks:
        log("[suite-H] tasks-bench.json not found or no code_quality tasks — skipping")
        return []

    results: list[ScenarioResult] = []
    undoc_tasks_passed = undoc_tasks_total = 0
    uncov_tasks_passed = uncov_tasks_total = 0

    for task in tasks:
        task_id = task["id"]
        gt = task.get("ground_truth", {})
        check = gt.get("check", "")
        expected_queries = task.get("expected_queries", [])

        for q in expected_queries:
            cmd = q.get("cmd", "")
            if cmd not in ("undocumented", "uncovered"):
                continue

            args = [cmd] + q.get("args", [])
            sq = run_scan_query_result(scan_query_bin, args, index_path, repo_path)

            if cmd == "undocumented":
                expected_count = gt.get("undocumented_count", gt.get("count", 0))
                suite_key = "H1"
                undoc_tasks_total += 1
            else:
                expected_count = gt.get("uncovered_count", gt.get("count", 0))
                suite_key = "H2"
                uncov_tasks_total += 1

            if not sq.ok:
                passed = False
                got_count = None
            else:
                got_count = (sq.data or {}).get("total", None)
                passed = got_count == expected_count

            if passed:
                if cmd == "undocumented":
                    undoc_tasks_passed += 1
                else:
                    uncov_tasks_passed += 1

            results.append(
                ScenarioResult(
                    scenario=f"H_{task_id}_{cmd}",
                    name=f"health-{task_id}-{cmd}",
                    suite="health",
                    passed=passed,
                    result={
                        "count_match": passed,
                        "expected": expected_count,
                        "got": got_count,
                        "check": check,
                    },
                    threshold=THRESHOLDS[suite_key],
                    notes=f"task={task_id} cmd={cmd} args={q.get('args', [])}",
                )
            )

    # Aggregates
    if undoc_tasks_total:
        results.append(
            ScenarioResult(
                scenario="H1",
                name="health-undocumented",
                suite="health",
                passed=undoc_tasks_passed == undoc_tasks_total,
                result={
                    "count_match": undoc_tasks_passed == undoc_tasks_total,
                    "passed": undoc_tasks_passed,
                    "total": undoc_tasks_total,
                },
                threshold=THRESHOLDS["H1"],
                notes=f"{undoc_tasks_passed}/{undoc_tasks_total} undocumented tasks matched",
            )
        )
    if uncov_tasks_total:
        results.append(
            ScenarioResult(
                scenario="H2",
                name="health-uncovered",
                suite="health",
                passed=uncov_tasks_passed == uncov_tasks_total,
                result={
                    "count_match": uncov_tasks_passed == uncov_tasks_total,
                    "passed": uncov_tasks_passed,
                    "total": uncov_tasks_total,
                },
                threshold=THRESHOLDS["H2"],
                notes=f"{uncov_tasks_passed}/{uncov_tasks_total} uncovered tasks matched",
            )
        )
    return results


# ---- SUITE X — XREFS BROKEN ----


def run_suite_xrefs(
    scan_query_bin: Path,
    index_path: Path,
    repo_path: Path,
) -> list[ScenarioResult]:
    """Suite X: xrefs --broken self-consistency / determinism check.

    Runs ``xrefs --broken`` for each OSS task with ``check == "xrefs_broken"`` and
    confirms both the broken count and the set of broken target/line pairs.  The
    ground truth in tasks-bench.json is frozen scan-query-derived output, so this
    validates determinism rather than independent correctness — reported on the
    self-consistency track and EXCLUDED from the primary verdict.

    Args:
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap index.
        repo_path: Root of the pytorch-lightning repository.

    Returns:
        List of ScenarioResult — one per xrefs_broken task plus X1 aggregate.
    """
    tasks = [
        t
        for t in load_oss_tasks(type_filter="code_quality")
        if t.get("ground_truth", {}).get("check") == "xrefs_broken"
    ]
    if not tasks:
        log("[suite-X] no xrefs_broken tasks in tasks-bench.json — skipping")
        return []

    results: list[ScenarioResult] = []
    x_passed = x_total = 0

    for task in tasks:
        task_id = task["id"]
        gt = task.get("ground_truth", {})
        expected_count = gt.get("broken_count", 0)
        expected_targets = {(t["target"], t["line"]) for t in gt.get("broken_targets", [])}
        expected_queries = task.get("expected_queries", [])

        q = next((q for q in expected_queries if q.get("cmd") == "xrefs"), None)
        if q is None:
            continue

        args = ["xrefs"] + q.get("args", [])
        sq = run_scan_query_result(scan_query_bin, args, index_path, repo_path)
        x_total += 1

        if not sq.ok:
            results.append(
                ScenarioResult(
                    scenario=f"X_{task_id}",
                    name=f"xrefs-broken-{task_id}",
                    suite="xrefs",
                    passed=False,
                    result={"error": sq.error, "count_match": False},
                    threshold=THRESHOLDS["X1"],
                    notes=f"task={task_id}: {sq.error}",
                )
            )
            continue

        data = sq.data
        broken = data.get("broken", [])
        got_count = data.get("count", len(broken))
        got_targets = {(b.get("target", ""), b.get("line", 0)) for b in broken}

        count_match = got_count == expected_count
        targets_match = got_targets == expected_targets
        passed = count_match and targets_match

        if passed:
            x_passed += 1

        results.append(
            ScenarioResult(
                scenario=f"X_{task_id}",
                name=f"xrefs-broken-{task_id}",
                suite="xrefs",
                passed=passed,
                result={
                    "count_match": count_match,
                    "targets_match": targets_match,
                    "expected_count": expected_count,
                    "got_count": got_count,
                    "missing_targets": sorted(expected_targets - got_targets),
                    "extra_targets": sorted(got_targets - expected_targets),
                },
                threshold=THRESHOLDS["X1"],
                notes=f"task={task_id} args={q.get('args', [])}",
            )
        )

    if x_total:
        results.append(
            ScenarioResult(
                scenario="X1",
                name="xrefs-broken-all",
                suite="xrefs",
                passed=x_passed == x_total,
                result={"count_match": x_passed == x_total, "passed": x_passed, "total": x_total},
                threshold=THRESHOLDS["X1"],
                notes=f"{x_passed}/{x_total} xrefs_broken tasks matched",
            )
        )
    return results


def _resolve_plugin_root() -> Path | None:
    """Return the git top-level directory as the plugin root, or None when unavailable."""
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def _ensure_index(index_path: Path, repo_path: Path, scan_index_bin: Path | None) -> Path:
    """Return an existing index path, building it once via scan-index when missing.

    Exits the process with a clear message when the index cannot be located or
    built (scan-index absent, build failure, or still-missing index after build).

    Args:
        index_path: Resolved (possibly non-existent) candidate index path.
        repo_path: Repository root passed to scan-index --root.
        scan_index_bin: Path to scan-index, or None when it could not be found.

    Returns:
        Path to an index file that exists on disk.
    """
    if index_path.exists():
        return index_path
    log(f"[index] not found at {index_path}")
    if scan_index_bin is None:
        log("ERROR: scan-index not found — cannot auto-build the index.")
        log(f"Run manually:  python3 plugins/codemap/bin/scan-index --root {repo_path}")
        log("Then retry, or pass --index-path <path-to-index.json>.")
        sys.exit(1)
    log(f"[index] building now via {scan_index_bin} --root {repo_path} ...")
    result = subprocess.run(
        [sys.executable, str(scan_index_bin), "--root", str(repo_path)], capture_output=True, text=True, timeout=360
    )
    if result.returncode != 0:
        log(f"ERROR: scan-index failed:\n{result.stderr}")
        sys.exit(1)
    log(result.stdout.strip())
    rebuilt = resolve_index_path(None, repo_path)
    if not rebuilt.exists():
        log(f"ERROR: index still not found at {rebuilt} after build.")
        log("Try: --index-path <path-to-index.json>")
        sys.exit(1)
    return rebuilt


def _run_all_suites(suites: list[tuple[str, object]], use_progress: bool) -> list[ScenarioResult]:
    """Run every suite callable, optionally under a rich progress bar.

    Args:
        suites: List of ``(label, zero-arg callable returning list[ScenarioResult])``.
        use_progress: When True and rich is available, render a progress bar.

    Returns:
        Flattened list of all scenario results across every suite.
    """
    all_results: list[ScenarioResult] = []
    if use_progress and _IS_RICH_AVAILABLE and _console is not None:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=_console,
        ) as progress:
            bar = progress.add_task("Benchmark", total=len(suites))
            for label, run_fn in suites:
                progress.update(bar, description=label)
                all_results.extend(run_fn())  # type: ignore[operator]
                progress.advance(bar)
    else:
        for _label, run_fn in suites:
            all_results.extend(run_fn())  # type: ignore[operator]
    return all_results


def main(
    repo_path: str = None,
    index_path: str = None,
    report: bool = False,
    json_only: bool = False,
    verify_tasks: bool = False,
) -> None:
    """Run the codemap scan-query benchmark suite against a pytorch-lightning clone.

    Executes primary suites C (coverage gap), A (accuracy), L (latency), and Q
    (query shape), plus the self-consistency suites S (symbol), H (health), and X
    (xrefs) in order.  Prints the primary correctness verdict and the separate
    self-consistency line to stdout; optionally writes a markdown report.

    Exposed via ``python benchmarks/run-codemap-cli.py`` using
    :func:`fire.Fire`.  CLI flags match parameter names with ``_`` replaced by
    ``-`` (e.g. ``--repo-path``, ``--json-only``, ``--verify-tasks``).

    Args:
        repo_path: Path to the pytorch-lightning repository clone.  When omitted,
            falls back to ``$PYTORCH_LIGHTNING_PATH`` then ``./pytorch-lightning``.
        index_path: Path to the pre-built codemap JSON index.  When omitted,
            resolved automatically from the repository directory.
        report: Write a markdown report to ``benchmarks/results/code-<date>.md``.
            Ignored when ``json_only`` is ``True``.
        json_only: Suppress the markdown report; print only the verdict line.
        verify_tasks: Before running suites, check that each task's
            ``primary_module`` exists in the index with status ``ok``.

    Examples:
        # Full benchmark with markdown report
        python benchmarks/run-codemap-cli.py \\
            --repo-path ./pytorch-lightning-master \\
            --report

        # Verify task modules exist before running suites
        python benchmarks/run-codemap-cli.py \\
            --repo-path ./pytorch-lightning-master \\
            --verify-tasks

        # Use a custom index path
        python benchmarks/run-codemap-cli.py \\
            --repo-path ./pytorch-lightning \\
            --index-path /tmp/my-index.json \\
            --report
    """
    write_report = report and not json_only
    _OUT.quiet = json_only  # suppress human progress narration for machine consumers

    plugin_root = _resolve_plugin_root()
    repo_path = resolve_repo_path(repo_path)
    if repo_path is None:
        sys.exit(1)

    scan_query_bin = find_codemap_bin("scan-query", plugin_root)
    scan_index_bin = find_codemap_bin("scan-index", plugin_root)
    if scan_query_bin is None:
        log("ERROR: scan-query not found in PATH or plugin directory")
        sys.exit(1)

    index_path = _ensure_index(resolve_index_path(index_path, repo_path), repo_path, scan_index_bin)

    # Verify tasks if requested (runs before suites, does not skip them)
    if verify_tasks:
        run_verify_tasks(scan_query_bin, index_path, repo_path)

    suites: list[tuple[str, object]] = [
        ("C — Coverage gap", lambda: run_measure_calls(repo_path, scan_query_bin, index_path)),
        ("A — Accuracy", lambda: run_measure_accuracy(repo_path, scan_query_bin, index_path)),
        ("L — Latency", lambda: run_measure_latency(repo_path, scan_query_bin, index_path, scan_index_bin)),
        (
            "Q — Query shape",
            lambda: run_measure_query_shape(plugin_root or Path.cwd(), repo_path, scan_query_bin, index_path),
        ),
        ("S — Symbol lookup", lambda: run_suite_symbol(scan_query_bin, index_path, repo_path)),
        ("H — Health (doc/cov)", lambda: run_suite_health(scan_query_bin, index_path, repo_path)),
        ("X — Xrefs broken", lambda: run_suite_xrefs(scan_query_bin, index_path, repo_path)),
    ]

    all_results = _run_all_suites(suites, use_progress=not json_only)
    verdict = compute_verdict(all_results)
    envelope = build_summary_envelope(all_results, repo_path, index_path, verdict)

    # --json-only: emit scenario JSONL + summary envelope on stdout, nothing else.
    if json_only:
        for r in all_results:
            emit(r)
        print(json.dumps(envelope, separators=(",", ":"), default=str))
        return

    # Default mode: human verdict line, summary envelope, optional markdown report.
    report_path_str: str | None = None
    if write_report and all_results:
        report_path_str = write_report_file(all_results, repo_path, index_path)

    sc = envelope["self_consistency"]
    print(f"\n{verdict}  {envelope['primary']['passed']}/{envelope['primary']['total']} primary scenarios passed")
    print(f"self-consistency: {sc['verdict']}  {sc['passed']}/{sc['total']} (determinism track, not in verdict)")
    print(json.dumps(envelope, separators=(",", ":"), default=str))
    if report_path_str:
        print(f"→ {report_path_str}")


if __name__ == "__main__":
    fire.Fire(main)
