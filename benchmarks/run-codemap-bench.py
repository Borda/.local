#!/usr/bin/env python3
"""Codemap real-codebase benchmark — agentic runner for SE / FN / RV / CQ / BR / DG / FT / RI task series.

## What this measures

Two arms answer the same structural questions about the target repository:

  plain    — Grep / Bash / Read / Glob only; no scan-query; no Skill tool
  codemap  — same tools plus scan-query via PATH and the Skill tool

Task types:
  SE — symbol_extraction   (locate symbol lines in source)
  FN — fn_call_graph       (caller name recall for a function)
  RV — review_assistance   (doc/coverage/rdep metrics for code review)
  CQ — code_quality        (coupled, xrefs, combined health checks)
  BR — develop_blast_radius (caller recall >=70% before modifying a function)
  DG — debug_from_trace    (root-cause function + file from a traceback)
  FT — feature_scaffolding (files to create or modify for a new feature)
  RI — real_issue          (files relevant to a real GitHub issue)

Primary metric:
  token_ratio = codemap_input_tokens / plain_input_tokens per task (lower = better for codemap)

Secondary:
  accuracy = fraction of tasks where key metric matches ground truth within tolerance

## Quick start

  # Build index once (excluded from timing)
  python plugins/codemap/bin/scan-index --root ./<repo-dir>

  # Run all tasks, both arms, haiku model
  python benchmarks/run-codemap-bench.py --repo-path ./<repo-dir> --run-all

  # Single task, codemap arm only
  python benchmarks/run-codemap-bench.py --repo-path ./<repo-dir> \\
      --tasks "['SE-01']" --arm codemap --model haiku

## Requirements

  - claude CLI on PATH
  - Pre-built codemap index in .cache/codemap/<proj>.json or .cache/scan/<proj>.json
  - pip install -r benchmarks/requirements.txt
"""

from __future__ import annotations

import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import fire
import pandas as pd
from rich.console import Console as _Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

_USE_COLOR = sys.stdout.isatty()
_GREEN = "\033[32m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_BLUE = "\033[34m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""
_console = _Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TASKS_FILE = Path(__file__).parent / "suites" / "tasks-bench.json"
PATCH_TASKS_FILE = Path(__file__).parent / "suites" / "tasks-patch.json"
RESULTS_DIR = Path("benchmarks/results")

# Synthetic task type assigned to tasks loaded via --tasks-file that carry a `skill`
# field instead of a `type` field (e.g. tasks-code.json). No evaluator is registered for
# this type; tasks of this type are forced scoreable=False and contribute token-ratio and
# tool-count data only — never accuracy.
_EXTERNAL_TASK_TYPE = "develop_skill"

MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}
_MODEL_TIMEOUT: dict[str, int] = {"haiku": 210, "sonnet": 420, "opus": 600}

ARMS = ("plain", "codemap")

_CMD = ["claude", "-p", "--verbose", "--output-format", "stream-json"]

_ARM_DISALLOWED: dict[str, list[str]] = {
    # plain: also block scan-query via Bash so the control arm can't use the index
    # Write/Edit/NotebookEdit blocked on both arms to prevent filesystem contamination during runs
    # Bash(python3:*)/Bash(python:*) blocked on both arms: prevents implement-validate spirals
    # in real_issue tasks where agents write repro scripts and edit source via heredoc.
    "plain": [
        "--disallowed-tools",
        "Skill,Write,Edit,NotebookEdit,mcp__semble__search,mcp__semble__find_related,Bash(scan-query:*),Bash(python3:*),Bash(python:*)",
    ],
    "codemap": [
        "--disallowed-tools",
        "Write,Edit,NotebookEdit,mcp__semble__search,mcp__semble__find_related,Bash(python3:*),Bash(python:*)",
    ],
}
_ARM_ALLOWED: dict[str, list[str]] = {
    "codemap": ["--allowedTools", "Bash(scan-query:*)"],
}

# ---------------------------------------------------------------------------
# Repo identity — populated from tasks-bench.json header in main()
# ---------------------------------------------------------------------------

_REPO_NAME: str = "the repository"
_REPO_NAMESPACE: list[str] = ["lightning", "examples"]
_REPO_DEFAULT_PATH: str | None = None


class SandboxError(Exception):
    """Raised when a patch sandbox cannot be set up or torn down.

    Distinct from a failing test: a SandboxError means the harness could not
    create the worktree, check out the pre-fix commit, or apply the diff — the
    pass/fail signal is unobtainable, not that the patch is semantically wrong.
    """


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BenchQuality:
    """Quality score for one benchmark run.

    Attributes:
        scored: True when evaluation ran against a matching task type.
        correct: True when the primary metric matches ground truth within tolerance.
        metric_expected: Ground-truth value of the primary metric.
        metric_got: Value extracted from model output; None when extraction failed.
        recall: Optional evaluator-specific recall metric; set by develop_br, rv (symbol tasks), debug, feature, and real_issue evaluators. None for count-based evaluators (symbol_extraction, code_quality).
        caller_count_gt: Ground-truth unique caller count; used by caller-list evaluators for both fn_call_graph and develop_blast_radius.
        evaluator_used: Name of the evaluator function that produced this score
            (diagnostic; None when no evaluator ran).
        extracted_metric: Raw value pulled from output_text before comparison — an
            integer count, a matches/recall numerator, or a found-name list depending
            on the evaluator (diagnostic; distinct from the final ``correct`` score).
        scoring_detail: Diagnostic breakdown of the comparison the evaluator computed:
            keys ``metric_expected``, ``metric_got``, ``threshold``, ``method``. Lets a
            failed run be diagnosed without re-reading output_text.
    """

    scored: bool = False
    correct: bool = False
    metric_expected: Any = None
    metric_got: Any = None
    recall: float | None = None
    caller_count_gt: int | None = None
    extraction_failed: bool = False
    evaluator_used: str | None = None
    evaluator_version: str | None = None
    extracted_metric: Any = None
    scoring_detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchRun:
    """Result of a single benchmark run (one task × arm × model).

    Attributes:
        arm: "plain" or "codemap".
        task_id: Task ID from tasks-bench.json (e.g. "SE-01").
        task_type: Task type string (e.g. "symbol_extraction").
        model: Short model tier name.
        success: True when the claude subprocess returned a successful result.
        workflow_type: Coarse workflow grouping (e.g. "query", "debug", "feature").
            Falls back to ``task_type`` when the task carries no ``workflow_type`` field.
        input_tokens: Total input token count (all cache partitions summed).
        output_tokens: Total output token count.
        elapsed_s: Wall-clock seconds.
        error: Error string on failure; empty on success.
        tool_log: Short log of tool calls in order.
        output_text: Full agent response text.
        quality: Quality evaluation result.
        skill_calls: Number of Skill tool invocations.
        grep_calls: Number of Grep tool invocations.
        bash_calls: Number of Bash tool invocations.
        patch_pass: Patch tasks only — True when the failing test passed after the
            agent's diff was applied in a sandbox; None for non-patch tasks or when
            no diff could be extracted from the agent output.
    """

    arm: str
    task_id: str
    task_type: str
    model: str
    success: bool
    workflow_type: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0
    error: str = ""
    tool_log: list[str] = field(default_factory=list)
    output_text: str = ""
    quality: BenchQuality = field(default_factory=BenchQuality)
    skill_calls: int = 0
    skill_counts: dict[str, int] = field(default_factory=dict)
    grep_calls: int = 0
    bash_calls: int = 0
    read_calls: int = 0
    scan_query_calls: int = 0
    scan_query_subcommands: dict[str, int] = field(default_factory=dict)
    turn_count: int = 0
    incomplete: bool = False  # budget exhausted before final answer; excluded from accuracy
    codemap_methods: list[str] = field(default_factory=list)
    codemap_not_covered: list[str] = field(default_factory=list)
    patch_pass: bool | None = None  # patch tasks only: True if failing test passed after applying the agent diff


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_PLAIN_SYSTEM = """You are a developer investigating the {repo_name} codebase.
Your current working directory IS the repository root ({repo_path}) — use relative paths (e.g. `find . -name "*.py"`) or absolute paths starting with {repo_path}.
Answer the question using Grep, Bash, Glob, and Read. Do NOT use the Skill tool.
Do NOT use scan-query or any codemap binary — not via bare command, not via python/python3 path.
Rely on standard filesystem and grep operations only.
Be concise and precise.

For symbol location tasks: report exactly in this format:
  file_path: <path>  start_line: <N>  end_line: <M>
For caller count tasks: report the integer count of unique production callers.
For caller list tasks: report all callers as a list of qualified names (module::function)."""

_CODEMAP_SYSTEM_TEMPLATE = """You are a developer investigating the {repo_name} codebase.
Your current working directory IS the repository root ({repo_path}) — use relative paths (e.g. `find . -name "*.py"`) or absolute paths starting with {repo_path}.
You have the scan-query structural index tool available.

For ALL structural questions (symbol lookup, call graph, coverage, coupling, xrefs),
scan-query MUST be your first tool call. Do NOT use find/grep/cat/Read for structural
questions unless scan-query reports symbol not found.
Trust scan-query output as authoritative. Do not re-verify counts or symbol lists with
grep or additional scan-query calls after receiving a result — re-verification burns tokens
and introduces errors. stale=true means source changed since scan, but counts and call
graphs are still accurate enough to answer; it does NOT mean you should re-query.

scan-query is a Python script on your PATH. Invoke it via Bash:
  scan-query --index {index_path} <subcommand> [args]

Subcommands:
  symbol <name> [--with-imports]         — get source + line range of a symbol by name
  find-symbol <pattern>                  — regex search across all symbol qualified names
  symbols <module>                       — list all symbols in a module
  fn-rdeps <qname> [--exclude-tests]    — callers of a function
  rdeps <module>                         — modules that import a module
  undocumented [module] [--all]          — symbols lacking docstrings
  uncovered [module] [--top N]           — symbols lacking test coverage
  coupled [--top N]                      — most-coupled modules
  xrefs <module> [--broken]             — Sphinx cross-references

For symbol_extraction tasks:
  Use: symbol "<name>" --with-imports, then find-symbol "<pattern>" if ambiguous.
  Report exactly: file_path: <path>  start_line: <N>  end_line: <M>

For develop_blast_radius tasks:
  Use: fn-rdeps "<qualified_name>" --exclude-tests
  Report the returned caller list directly. Do NOT grep for additional callers.

For fn_call_graph tasks:
  Use: fn-rdeps "<qualified_name>" --exclude-tests
  Report all callers as a list of qualified names; state the unique caller count.

For review_assistance tasks (PR review, blast radius, coverage metrics):
  Select the subcommand based on the task question:
  - Callers of a function    → fn-rdeps "<module>::<function>" --exclude-tests
    Note: the `count` field counts call-site EDGES, not unique callers. To report
    unique callers, count distinct `caller` values in the `called_by` list yourself.
  - Modules importing module → rdeps "<module>"
  - Symbols lacking docstrings → undocumented "<module>" [--all]
  - Symbols lacking test coverage → uncovered "<module>" [--top N]
  Run ONE scan-query call. For caller-count questions: count distinct names in
  `called_by` — do NOT use the `count` field directly. List all qualified names.
  STOP after one call.

Be concise and precise. State the exact values you found (counts, line numbers, module names)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_codemap_bin(plugin_root: Path | None) -> Path | None:
    """Locate scan-query binary.

    Args:
        plugin_root: Project root containing plugins/codemap/bin/.

    Returns:
        Path to scan-query, or None if not found.
    """
    import shutil

    which = shutil.which("scan-query")
    if which:
        return Path(which)
    if plugin_root:
        cand = plugin_root / "plugins" / "codemap" / "bin" / "scan-query"
        if cand.exists():
            return cand
    return None


def _resolve_index(repo_path: Path, explicit: Path | None = None) -> Path:
    """Resolve the codemap index path.

    Args:
        repo_path: Root of the cloned repository.
        explicit: Explicit --index-path argument; returned as-is when provided.

    Returns:
        Path to the index JSON file.

    Raises:
        FileNotFoundError: When no index can be found.
    """
    if explicit:
        resolved = explicit.resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Explicit index not found: {resolved}")
        return resolved
    for cache_dir in (".cache/codemap", ".cache/scan"):
        d = repo_path / cache_dir
        if not d.is_dir():
            continue
        candidates = [repo_path / cache_dir / f"{repo_path.name}.json"]
        for stem in (repo_path.name.replace("-master", ""), repo_path.name.replace("-main", "")):
            candidates.append(repo_path / cache_dir / f"{stem}.json")
        for c in candidates:
            if c.exists():
                return c.resolve()
        jsons = sorted(d.glob("*.json"))
        if jsons:
            return jsons[0].resolve()
    raise FileNotFoundError(
        f"No codemap index found under {repo_path}/.cache/{{codemap,scan}}/.\n"
        "Build it first:\n"
        f"  python plugins/codemap/bin/scan-index --root {repo_path}"
    )


def _normalize_external_task(task: dict) -> dict:
    """Normalize one task from a --tasks-file into the harness task schema.

    External task files use a different schema from tasks-bench.json: ``queries``
    instead of ``expected_queries``, a ``skill`` field instead of ``type``, and
    ``ground_truth_keys`` instead of materialized ``ground_truth`` values (e.g.
    tasks-code.json). Files that DO carry materialized ``ground_truth`` and an
    explicit ``scoreable: true`` (e.g. tasks-debug.json, tasks-feature.json,
    tasks-oss.json) are evaluated normally — their ``scoreable`` field is
    preserved so the registered evaluator runs.

    The original task dict is not mutated; a shallow copy is returned.

    Args:
        task: Raw task dict loaded from a --tasks-file.

    Returns:
        A new task dict with ``expected_queries``, ``type``, and ``scoreable``
        keys populated for the harness.

    Examples:
        >>> t = _normalize_external_task(
        ...     {"id": "B-01", "prompt": "p", "skill": "fix",
        ...      "queries": [{"cmd": "rdeps", "args": ["m"]}]}
        ... )
        >>> t["type"], t["scoreable"], t["expected_queries"]
        ('develop_skill', False, [{'cmd': 'rdeps', 'args': ['m']}])
        >>> "queries" in t  # original key dropped after rename
        False
        >>> scored = _normalize_external_task(
        ...     {"id": "DBG-01", "type": "debug_from_trace", "scoreable": True,
        ...      "prompt": "p", "ground_truth": {"function": "f", "file": "a.py", "start_line": 1}}
        ... )
        >>> scored["scoreable"]
        True
    """
    norm = dict(task)
    if "queries" in norm and "expected_queries" not in norm:
        norm["expected_queries"] = norm.pop("queries")
    # Harness requires a `type` for BenchRun, logging, and summary grouping.
    if not norm.get("type"):
        norm["type"] = _EXTERNAL_TASK_TYPE
    # Only force scoreable=False when no materialized ground truth present.
    # Tasks with ground_truth + explicit scoreable=True are scored via their evaluator.
    if not norm.get("ground_truth"):
        norm["scoreable"] = False
    elif "scoreable" not in norm:
        norm["scoreable"] = True
    return norm


def _load_tasks_file(path: Path) -> list[dict]:
    """Load and normalize an additional task file passed via --tasks-file.

    Accepts either a bare JSON list of tasks or a ``{"repo": ..., "tasks": [...]}``
    object (the tasks-bench.json shape). Every loaded task is run through
    :func:`_normalize_external_task`.

    Args:
        path: Path to the JSON task file.

    Returns:
        List of normalized task dicts.

    Raises:
        FileNotFoundError: When the file does not exist.
        ValueError: When the JSON is malformed or has an unexpected shape.
    """
    if not path.is_file():
        raise FileNotFoundError(f"--tasks-file not found: {path}")
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"--tasks-file {path} is not valid JSON: {exc}") from exc
    if isinstance(raw, dict):
        raw_tasks = raw.get("tasks", [])
    elif isinstance(raw, list):
        raw_tasks = raw
    else:
        raise ValueError(f"--tasks-file {path} must be a JSON list or object with a 'tasks' key")
    return [_normalize_external_task(t) for t in raw_tasks]


def _subprocess_env(index_path: Path) -> dict[str, str]:
    """Build subprocess environment with codemap bin dir and CODEMAP_INDEX set.

    Args:
        index_path: Path to the pre-built codemap index.

    Returns:
        Environment dict for subprocess.Popen.
    """
    env = os.environ.copy()
    plugin_cache = Path.home() / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap"
    bin_dirs = sorted(plugin_cache.glob("*/bin"), reverse=True)
    if bin_dirs:
        env["PATH"] = str(bin_dirs[0]) + os.pathsep + env.get("PATH", "")
    env["CODEMAP_INDEX"] = str(index_path)
    env["CODEMAP_ENABLED"] = "true"
    env["CODEMAP_LOGGING"] = "false"
    return env


# Subcommands recognised by scan-query (mirrors the _CODEMAP_SYSTEM_TEMPLATE help block).
_SCAN_QUERY_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "symbol",
        "find-symbol",
        "symbols",
        "fn-rdeps",
        "rdeps",
        "undocumented",
        "uncovered",
        "coupled",
        "xrefs",
    }
)


def _parse_scan_query_subcommand(command: str) -> Optional[str]:
    """Extract the scan-query subcommand from a Bash command line.

    The first non-flag token following ``scan-query`` (after skipping the
    ``--index <path>`` option and any other leading ``--flag``/``--flag value``
    pairs) is the subcommand. Returns None when the command is not a scan-query
    invocation or no recognised subcommand is present.

    Args:
        command: Raw Bash command string (as recorded in tool_log / tool input).

    Returns:
        The subcommand name (e.g. ``"fn-rdeps"``), or None.

    Examples:
        >>> _parse_scan_query_subcommand("scan-query --index /x.json fn-rdeps a.b --exclude-tests")
        'fn-rdeps'
        >>> _parse_scan_query_subcommand("scan-query symbol Trainer")
        'symbol'
        >>> _parse_scan_query_subcommand("grep -r foo .") is None
        True
    """
    if "scan-query" not in command:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    # Locate the scan-query token (may be a path like .../bin/scan-query).
    start = None
    for i, tok in enumerate(tokens):
        if tok == "scan-query" or tok.endswith("/scan-query"):
            start = i + 1
            break
    if start is None:
        return None
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            # Skip a flag; if its value is a separate token (not another flag), skip it too.
            if "=" not in tok and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                i += 2
            else:
                i += 1
            continue
        return tok if tok in _SCAN_QUERY_SUBCOMMANDS else None
    return None


# ---------------------------------------------------------------------------
# Quality evaluators — extract key metric from model output text
# ---------------------------------------------------------------------------

_EVAL_VER_NAME_RECALL = "v4"  # _evaluate_develop_br (v4: Form 11 bare Class.method fallback)
_EVAL_VER_SYMBOL = "v1"  # _evaluate_symbol
_EVAL_VER_REVIEW = "v2"  # _evaluate_rv — recall-only for symbol-bearing tasks
_EVAL_VER_OSS = "v1"  # _evaluate_oss
_EVAL_VER_DEBUG = "v1"  # _evaluate_debug
_EVAL_VER_FEATURE = "v1"  # _evaluate_feature
_EVAL_VER_REAL_ISSUE = "v1"  # _evaluate_real_issue


def _extract_int(text: str, patterns: list[str]) -> Optional[int]:
    """Extract the first integer matching any of the given regex patterns.

    Args:
        text: Model output text to search.
        patterns: List of regex patterns; each must have one capture group for the integer.

    Returns:
        Extracted integer, or None when no pattern matched.

    Examples:
        >>> _extract_int("found 42 callers", [r"(\\d+) caller"])
        42
        >>> _extract_int("nothing here", [r"(\\d+) caller"])
    """
    text = re.sub(r"\*+", " ", text)  # strip bold markers before matching
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (IndexError, ValueError):
                continue
    return None


def _extract_names(text: str) -> list[str]:
    """Extract dotted module names matching the repo namespace from model output.

    Args:
        text: Model output text.

    Returns:
        Deduplicated sorted list of dotted names matching the repo namespace.

    Examples:
        >>> _extract_names("see lightning.pytorch.trainer.trainer and lightning.pytorch.loops.loop")
        ['lightning.pytorch.loops.loop', 'lightning.pytorch.trainer.trainer']
    """
    ns_alt = "|".join(re.escape(n) for n in _REPO_NAMESPACE)
    found = re.findall(rf"\b(?:{ns_alt})(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+", text)
    return sorted(set(found))


def _int_close(got: Optional[int], expected: int, tolerance: float = 0.10) -> bool:
    """Return True when got is within tolerance of expected.

    Args:
        got: Extracted integer (None → always False).
        expected: Ground-truth integer.
        tolerance: Fractional tolerance (0.10 = ±10%).

    Returns:
        True when ``abs(got - expected) / max(expected, 1) <= tolerance``.

    Examples:
        >>> _int_close(42, 40, tolerance=0.10)
        True
        >>> _int_close(42, 30, tolerance=0.10)
        False
        >>> _int_close(None, 40)
        False
    """
    if got is None:
        return False
    return abs(got - expected) / max(expected, 1) <= tolerance


def _count_tol_detail(expected: Any, got: Any, **extra: Any) -> dict[str, Any]:
    """Build a count-tolerance scoring_detail dict (threshold fixed at 10%).

    Args:
        expected: Ground-truth count.
        got: Extracted count.
        **extra: Optional additional keys merged into the dict.

    Returns:
        Dict with metric_expected, metric_got, threshold, method, plus any extras.

    Examples:
        >>> _count_tol_detail(10, 9)
        {'metric_expected': 10, 'metric_got': 9, 'threshold': 0.1, 'method': 'count_tolerance'}
        >>> _count_tol_detail(10, 9, check="coupled")
        {'metric_expected': 10, 'metric_got': 9, 'threshold': 0.1, 'method': 'count_tolerance', 'check': 'coupled'}
    """
    return {"metric_expected": expected, "metric_got": got, "threshold": 0.10, "method": "count_tolerance", **extra}


def _evaluate_symbol(task: dict, output_text: str) -> BenchQuality:
    """Evaluate symbol_extraction task: check whether start_line matches ground truth.

    Args:
        task: Task dict from tasks-bench.json.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with correct=True when start_line extracted and within ±5 lines.
    """
    gt = task["ground_truth"]
    expected_start = gt["start_line"]
    qname = gt["qualified_name"]

    # Strip markdown bold markers only — NOT underscores (would destroy start_line key)
    cleaned = re.sub(r"\*{1,2}", "", output_text)

    got_start: Optional[int] = None

    # 1. "start_line: N" or "start line: N" — most specific; check before range patterns
    m = re.search(r"\bstart[_ ]line\s*[:\s]+(\d+)", cleaned, re.IGNORECASE)
    if m:
        got_start = int(m.group(1))

    # 1b. "Start: line N" — bold-stripped form of "**Start**: line N"
    if got_start is None:
        m = re.search(r"\bstart\s*:\s*line\s+(\d+)", cleaned, re.IGNORECASE)
        if m:
            got_start = int(m.group(1))

    # 2. "starts at line N"
    if got_start is None:
        m = re.search(r"\bstarts?\s+at\s+line\s+(\d+)", cleaned, re.IGNORECASE)
        if m:
            got_start = int(m.group(1))

    # 3. Explicit range "Lines N-M" → first number is start (fallback; can match import ranges)
    if got_start is None:
        m = re.search(r"\blines?\W+(\d+)\s*[-–]\s*\d+", cleaned, re.IGNORECASE)
        if m:
            got_start = int(m.group(1))

    # 4. "line N" near the short symbol name (last component of qualified name)
    if got_start is None:
        short = re.escape(qname.split(".")[-1])
        m = re.search(r"line\s+(\d+).*?" + short, cleaned, re.IGNORECASE | re.DOTALL)
        if m:
            got_start = int(m.group(1))

    correct = got_start is not None and abs(got_start - expected_start) <= 5
    # metric_got/metric_expected is a line-number ratio printed as `recall=` diagnostic — not a recall metric
    return BenchQuality(
        scored=True,
        correct=correct,
        metric_expected=expected_start,
        metric_got=got_start,
        extraction_failed=got_start is None,
        evaluator_used="_evaluate_symbol",
        evaluator_version=_EVAL_VER_SYMBOL,
        extracted_metric=got_start,
        scoring_detail={
            "metric_expected": expected_start,
            "metric_got": got_start,
            "threshold": 5,
            "method": "line_tolerance",
        },
    )


def _evaluate_rv(task: dict, output_text: str) -> BenchQuality:
    """Evaluate review_assistance task.

    Primary: count from sq0; for symbol-bearing tasks also validate symbol recall.
    Correct = count within ±10% AND (if symbols present) recall ≥ 0.70.
    If count extraction fails and symbols present, symbol recall alone decides.

    Args:
        task: Task dict from tasks-bench.json.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall set when symbol list available, metric_got/expected otherwise.
    """
    sub_questions = task.get("sub_questions", [])
    if not sub_questions:
        return BenchQuality(scored=False)

    _count_patterns = [
        r"(\d+)\s+undocumented",
        r"(\d+)\s+uncovered",
        r"(\d+)\s+(?:function|symbol|method|class)",
        r"(\d+)\s+(?:production\s+)?call\s*site",
        r"(\d+)\s+(?:production\s+)?calls?\b",
        r"(\d+)\s+(?:total\s+)?(?:unique\s+)?importers?",  # "61 total importers", "56 importers"
        r"(\d+)\s+(?:unique\s+)?modules?\s+(?:import|depend)",  # "N modules import"
        r"(\d+)\s+total\s+importer",
        r"total[:\s]+(\d+)",
        r"count[:\s]+(\d+)",
        r"found\s+(\d+)",
    ]

    sq0_gt = sub_questions[0].get("ground_truth", {})
    expected_count = sq0_gt.get("count")

    # Symbol list from any subquestion (secondary metric for recall display).
    syms = None
    for sq in sub_questions:
        s = sq.get("ground_truth", {}).get("symbols")
        if s:
            syms = s
            break

    if syms:
        # Symbol-bearing tasks (RV-01, RV-05): recall is the primary gate.
        # Count check removed: non-anchored regex grabs stray numbers from verbose
        # codemap output, causing false fails when recall is perfect.
        found = sum(1 for s in syms if re.search(r"\b" + re.escape(s.split(".")[-1]) + r"\b", output_text))
        recall_val = found / max(len(syms), 1)
        got_count = _extract_int(output_text, _count_patterns) if expected_count is not None else None
        correct = recall_val >= 0.70
        return BenchQuality(
            scored=True,
            correct=correct,
            metric_expected=len(syms),
            metric_got=found,
            recall=round(recall_val, 3),
            evaluator_used="_evaluate_rv",
            evaluator_version=_EVAL_VER_REVIEW,
            extracted_metric={"symbols_found": found, "count_got": got_count},
            scoring_detail={
                "metric_expected": len(syms),
                "metric_got": found,
                "threshold": 0.70,
                "method": "recall",
                "count_expected": expected_count,
                "count_got": got_count,
            },
        )

    # No symbol list — count extraction from sq0.
    got_count = _extract_int(output_text, _count_patterns)
    if got_count is None:
        list_items = re.findall(r"^\s*[-*•]\s+\S", output_text, re.MULTILINE)
        if list_items:
            got_count = len(list_items)
    correct = _int_close(got_count, expected_count, tolerance=0.10)
    return BenchQuality(
        scored=True,
        correct=correct,
        metric_expected=expected_count,
        metric_got=got_count,
        extraction_failed=got_count is None,
        evaluator_used="_evaluate_rv",
        evaluator_version=_EVAL_VER_REVIEW,
        extracted_metric=got_count,
        scoring_detail=_count_tol_detail(expected_count, got_count),
    )


def _evaluate_oss(task: dict, output_text: str) -> BenchQuality:
    """Evaluate code_quality task: check primary count from ground_truth.

    Args:
        task: Task dict from tasks-bench.json.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with correct=True when primary count extracted within 10%.
    """
    gt = task["ground_truth"]
    check = gt.get("check", "")

    if check == "coupled":
        expected = gt.get("top_dep_count", 0)
        # Anchor to number immediately before "dep" — avoids forward-scan into summary totals.
        # dep_count field name first (structured output), then "N dep*" literal.
        got = _extract_int(
            output_text,
            [
                r"dep_count[:\s=]+(\d+)",
                r"(\d+)\s+dep(?:endenc|t)",
                r"(\d+)\s+total\s+dep(?:endenc|t)",
                r"\|\s*1\s*\|[^\n]*\|\s*(\d+)\s*\|",  # rank-1 row in dep_count markdown table
            ],
        )
        correct = _int_close(got, expected, tolerance=0.10)
        return BenchQuality(
            scored=True,
            correct=correct,
            metric_expected=expected,
            metric_got=got,
            extraction_failed=got is None,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            extracted_metric=got,
            scoring_detail=_count_tol_detail(expected, got, check=check),
        )

    if check == "xrefs_broken":
        expected = gt.get("broken_count", 0)
        broken_targets = gt.get("broken_targets", [])
        if broken_targets:
            # Count how many known broken target symbols appear in the output — more reliable
            # than parsing "N broken" prose which can grab unrelated sentence counts.
            short_names = [t["target"].split("::")[-1] for t in broken_targets]
            got = sum(1 for name in short_names if name in output_text)
            if got == 0:
                # Fallback: prose extraction when model didn't name symbols
                got_prose = _extract_int(output_text, [r"(\d+)\s+broken", r"broken[:\s]+(\d+)"])
                got = got_prose
        else:
            got = _extract_int(output_text, [r"(\d+)\s+broken", r"broken[:\s]+(\d+)", r"(\d+)\s+xref"])
        correct = got == expected
        return BenchQuality(
            scored=True,
            correct=correct,
            metric_expected=expected,
            metric_got=got,
            extraction_failed=got is None,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            extracted_metric=got,
            scoring_detail={
                "metric_expected": expected,
                "metric_got": got,
                "threshold": 0,
                "method": "exact_match",
                "check": check,
            },
        )

    if check in ("undocumented", "combined_health"):
        expected = gt.get("undocumented_count", 0)
        got = _extract_int(
            output_text,
            [
                r"(\d+)\s+undocumented",
                r"undocumented[:\s]+(\d+)",
                r"undocumented[^:\n]*[:\s—–]+(\d+)",  # "Undocumented public symbols — 3" (no-newline stops greedy bleed)
                r"(\d+)\s+(?:public\s+)?symbols?\s+lack",  # "3 public symbols lack docstrings"
                r"without\s+docstring.*?(\d+)",
            ],
        )
        correct = _int_close(got, expected, tolerance=0.10)
        return BenchQuality(
            scored=True,
            correct=correct,
            metric_expected=expected,
            metric_got=got,
            extraction_failed=got is None,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            extracted_metric=got,
            scoring_detail=_count_tol_detail(expected, got, check=check),
        )

    if check == "uncovered":
        expected = gt.get("uncovered_count", 0)
        got = _extract_int(
            output_text,
            [
                r"(\d+)\s+uncovered",
                r"(\d+)\s+(?:public\s+)?symbols?\s+uncovered",  # "20 public symbols uncovered"
                r"uncovered[:\s]+(\d+)",
                r"uncovered\s+public\s+symbols?[:\s—–]+(\d+)",  # "Uncovered public symbols: 25"
                r"without\s+test.*?(\d+)",
            ],
        )
        correct = _int_close(got, expected, tolerance=0.10)
        return BenchQuality(
            scored=True,
            correct=correct,
            metric_expected=expected,
            metric_got=got,
            extraction_failed=got is None,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            extracted_metric=got,
            scoring_detail=_count_tol_detail(expected, got, check=check),
        )

    return BenchQuality(scored=False)


def _evaluate_develop_br(task: dict, output_text: str) -> BenchQuality:
    """Evaluate develop_blast_radius task: measure caller recall.

    Primary metric: fraction of expected fn_callers found in output (recall ≥ 0.7 = correct).
    Measures whether developer framing + codemap yields comprehensive caller enumeration.

    Args:
        task: Task dict from tasks-bench.json with ground_truth.fn_callers list.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with correct=True when recall >= 0.7; metric_got = TP count.
    """
    gt = task["ground_truth"]
    expected_callers: list[str] = gt.get("fn_callers", [])
    if not expected_callers:
        return BenchQuality(scored=False)

    expected_set = set(expected_callers)

    # Pre-process: if communication.md Long Reply File Dump was used, read actual file.
    # Pattern: "→ .temp/reply-<slug>-YYYY-MM-DD.md" (plain or backtick-wrapped).
    _dump_m = re.search(r"^→\s+`?([^`\s]+\.md)`?\s*$", output_text, re.MULTILINE)
    if _dump_m:
        try:
            with open(_dump_m.group(1)) as _df:
                output_text = output_text + "\n" + _df.read()
        except OSError:
            pass

    # Extract qualified names. Three forms, then normalize to module::Class.method.

    _ns_alt = "|".join(re.escape(n) for n in _REPO_NAMESPACE)
    _ns_pat = f"(?:{_ns_alt})"

    found_raw: list[str] = []
    # Form 1: canonical dotted-namespace form (ns.x.y::Class.method)
    for m in re.finditer(rf"\b({_ns_pat}(?:\.[\w]+)+)::([\w]+(?:\.[\w]+)*)", output_text):
        found_raw.append(f"{m.group(1)}::{m.group(2)}")
    # Form 2: multi-:: chain — captures full chain including Class::method suffix.
    # Matches fabric.x::Class::method AND ns.x::Class::method greedily.
    # Strip trailing backtick/space — backtick-wrapped markdown cells add trailing ` to match.
    for m in re.finditer(r"\b([\w.]+(?:::[\w][^:\s]*)+)", output_text):
        found_raw.append(m.group(1).rstrip("`"))
    # Form 3: file-path with single colon: ns/x/y.py:Class.method
    for m in re.finditer(rf"\b({_ns_pat}(?:/[\w]+)+\.py):([\w]+\.[\w]+)\b", output_text):
        mod = m.group(1).replace("/", ".")[: -len(".py")]
        found_raw.append(f"{mod}::{m.group(2)}")
    # Form 4: src-rooted file path: src/ns/x/y.py::Class.method
    for m in re.finditer(rf"\bsrc/({_ns_pat}(?:/[\w]+)+\.py)::([\w]+(?:\.[\w]+)*)\b", output_text):
        mod = m.group(1).replace("/", ".")[: -len(".py")]
        found_raw.append(f"{mod}::{m.group(2)}")
    # Form 6: grouped "### ns.module.sub" headers + "- Class.method" bullets.
    # Reconstruct module::Class.method from the nearest preceding header.
    _hdr_positions = [
        (hm.start(), hm.group(1)) for hm in re.finditer(rf"^#+\s+({_ns_pat}(?:\.[\w]+)+)", output_text, re.MULTILINE)
    ]
    for bm in re.finditer(r"^[-*]\s+([\w]+\.[\w]+)\s*$", output_text, re.MULTILINE):
        bpos = bm.start()
        cur_mod = None
        for hpos, hmod in _hdr_positions:
            if hpos < bpos:
                cur_mod = hmod
            else:
                break
        if cur_mod:
            found_raw.append(f"{cur_mod}::{bm.group(1)}")
    # Form 7: markdown table "| module | Class.method |" — adjacent cells.
    # Handles backtick-wrapped cells and module-level functions (no Class prefix).
    for tm in re.finditer(
        rf"\|\s*`?({_ns_pat}(?:\.[\w]+)+)`?\s*\|\s*`?([\w]+(?:\.[\w]+)?)`?\s*\|",
        output_text,
    ):
        found_raw.append(f"{tm.group(1)}::{tm.group(2)}")
    # Form 8: section header "### `module` (desc)" or "### `module::Class`" + table function rows.
    # First column of each table row is the function (or method) name.
    _sec_hdr_re = re.compile(rf"^#+\s+`?({_ns_pat}(?:\.[\w]+)+(?:::[\w.]+)?)`?(?:[\s(]|$)", re.MULTILINE)
    _sec_positions = [(hm.start(), hm.group(1)) for hm in _sec_hdr_re.finditer(output_text)]
    _SKIP_CELLS = frozenset({"function", "module", "caller", "class", "method", "name", "#"})
    for row_m in re.finditer(r"^\|\s*`?([\w][^|`\n]*?)`?\s*\|", output_text, re.MULTILINE):
        fn_name = row_m.group(1).strip()
        if not fn_name or fn_name.lower() in _SKIP_CELLS or set(fn_name) <= set("-| "):
            continue
        row_start = row_m.start()
        cur_hdr = None
        for hpos, hval in _sec_positions:
            if hpos < row_start:
                cur_hdr = hval
            else:
                break
        if not cur_hdr:
            continue
        if "::" in cur_hdr:
            found_raw.append(f"{cur_hdr}.{fn_name}")
        else:
            found_raw.append(f"{cur_hdr}::{fn_name}")
    # Form 9: bold-backtick module header + numbered backtick list.
    # Handles: **`ns.mod::Class`** or **ns.module** followed by "1. `Class.method`".
    # Agent used this format when outputting caller lists for FN/BR tasks.
    _bold_hdrs_9 = [
        (bm.start(), bm.group(1))
        for bm in re.finditer(
            rf"\*\*`?({_ns_pat}(?:\.[\w]+)+(?:::[\w.]+)?)`?\*\*",
            output_text,
        )
    ]
    for nm in re.finditer(r"^\s*\d+\.\s+`([\w.]+(?:::[\w.]+)?)`", output_text, re.MULTILINE):
        item_text = nm.group(1).rstrip("`")
        item_pos = nm.start()
        cur_hdr_9 = None
        for hpos, hval in _bold_hdrs_9:
            if hpos < item_pos:
                cur_hdr_9 = hval
            else:
                break
        if "::" in item_text:
            found_raw.append(item_text)
        elif cur_hdr_9:
            hdr_mod = cur_hdr_9.split("::")[0] if "::" in cur_hdr_9 else cur_hdr_9
            found_raw.append(f"{hdr_mod}::{item_text}")
    # Form 10: slash-paired abbreviated callers under same class prefix.
    # Handles "ns.mod::Class.fn1/fn2" (agent collapsed two callers into one token).
    for sm in re.finditer(
        rf"\b({_ns_pat}(?:\.[\w]+)*(?:::[\w]+)?\.[\w]+)/([\w]+)\b",
        output_text,
    ):
        left = sm.group(0).split("/")[0]
        right_fn = sm.group(2)
        found_raw.append(left)
        cls_prefix = left.rsplit(".", 1)[0] if "." in left else left
        found_raw.append(f"{cls_prefix}.{right_fn}")

    # Normalize all extracted tokens → canonical module::Class.method
    _ns_prefixes = [""] + [f"{n}." for n in _REPO_NAMESPACE]
    found_qualnames: set[str] = set()
    for raw in found_raw:
        parts = raw.split("::")
        if len(parts) < 2:
            continue
        # Default: first segment = module, rest = callee
        default = f"{parts[0]}::{'.'.join(parts[1:])}"
        found_qualnames.add(default)
        for pfx in _ns_prefixes:
            candidate = f"{pfx}{default}"
            if candidate in expected_set:
                found_qualnames.add(candidate)
        # Multi-:: form: agent may use :: as path separator throughout.
        # Try all other split points; keep any whose module::callee is in expected_set.
        for split_i in range(2, len(parts)):
            module = ".".join(parts[:split_i])
            callee = ".".join(parts[split_i:])
            for pfx in _ns_prefixes:
                candidate = f"{pfx}{module}::{callee}"
                if candidate in expected_set:
                    found_qualnames.add(candidate)
        # module.Class::method form: agent wrote dot before :: instead of canonical ::.
        # Reclassify by splitting module on its last dot to surface the class component.
        # Fuzzy tier below then handles underscore-prefix mismatch (Class vs _Class).
        if "." in parts[0]:
            m_mod, _, m_cls = parts[0].rpartition(".")
            reclassified = f"{m_mod}::{m_cls}.{'.'.join(parts[1:])}"
            found_qualnames.add(reclassified)
            for pfx in _ns_prefixes:
                cand = f"{pfx}{reclassified}"
                if cand in expected_set:
                    found_qualnames.add(cand)
        # Suffix match: abbreviated module path (e.g. "loops.x" instead of "ns.pytorch.loops.x").
        # Match when callee is exact and GT module ends with .abbreviated_module.
        callee_suffix = ".".join(parts[1:])
        mod_token = parts[0]
        for canonical in expected_callers:
            can_parts = canonical.split("::")
            if len(can_parts) >= 2 and ".".join(can_parts[1:]) == callee_suffix:
                can_mod = can_parts[0]
                if can_mod.endswith("." + mod_token) or can_mod == mod_token:
                    found_qualnames.add(canonical)

    # Form 5: fully-dotted form — agent writes lightning.x.y.fn (no :: separator).
    # Reverse-lookup: for each expected caller, check its dotted equivalent with word-boundary
    # lookarounds to avoid substring FPs (e.g. _fn matching _fn_helper).
    dotted_to_canonical = {c.replace("::", "."): c for c in expected_callers}
    for dotted, canonical in dotted_to_canonical.items():
        pattern = r"(?<![.\w])" + re.escape(dotted) + r"(?![.\w])"
        if re.search(pattern, output_text):
            found_qualnames.add(canonical)

    # Fuzzy tier (always-on): same method name exact, class name underscore-insensitive.
    # Catches format variants like "EvaluationLoop.method" when GT is "_EvaluationLoop.method" —
    # agent clearly identified the caller, just dropped the access-modifier underscore convention.
    def _norm_cls(qn: str) -> str:
        tail = qn.split("::")[-1]
        if "." not in tail:
            return tail
        cls, _, meth = tail.partition(".")
        return f"{cls.lstrip('_')}.{meth}"

    already_exact = expected_set & found_qualnames
    for canonical in expected_callers:
        if canonical not in already_exact and "." in canonical.split("::")[-1]:
            norm = _norm_cls(canonical)
            if any(_norm_cls(qn) == norm for qn in found_qualnames):
                found_qualnames.add(canonical)

    # Form 11: bare Class.method fallback — fires ONLY when all other forms produced nothing.
    # Codemap arm sometimes outputs callers as "_EvaluationLoop._evaluation_step" without module
    # prefix; reverse-lookup against GT by matching the tail component of each expected caller.
    if not found_qualnames:
        for canonical in expected_callers:
            parts = canonical.split("::")
            if len(parts) < 2:
                continue
            tail = parts[-1]  # e.g. "_EvaluationLoop._evaluation_step"
            if "." not in tail:
                continue  # skip bare function names (too short, high FP risk)
            pattern = r"(?<![.\w])" + re.escape(tail) + r"(?![.\w])"
            if re.search(pattern, output_text):
                found_qualnames.add(canonical)
                continue
            # Also match without leading underscores on the class part (EvaluationLoop.method)
            tail_parts = tail.split(".", 1)
            if tail_parts[0].startswith("_"):
                stripped_tail = tail_parts[0].lstrip("_") + "." + tail_parts[1]
                pattern2 = r"(?<![.\w])" + re.escape(stripped_tail) + r"(?![.\w])"
                if re.search(pattern2, output_text):
                    found_qualnames.add(canonical)

    true_positives = len(expected_set & found_qualnames)
    recall = true_positives / max(len(expected_set), 1)
    correct = recall >= 0.70

    return BenchQuality(
        scored=True,
        correct=correct,
        metric_expected=len(expected_set),
        metric_got=true_positives,
        recall=round(recall, 3),
        caller_count_gt=gt["unique_caller_count"],
        extraction_failed=len(found_qualnames) == 0,
        evaluator_used="_evaluate_develop_br",
        evaluator_version=_EVAL_VER_NAME_RECALL,
        extracted_metric=sorted(found_qualnames),
        scoring_detail={
            "metric_expected": len(expected_set),
            "metric_got": true_positives,
            "threshold": 0.70,
            "method": "recall",
            "safety_grade": recall >= 0.90,
        },
    )


def _evaluate_debug(task: dict, output_text: str) -> BenchQuality:
    """Evaluate debug_from_trace task: function name + file basename both present.

    Correct when both the function name and the file basename (without .py) appear
    in the output. recall = hits / 2; correct requires recall == 1.0.

    Args:
        task: Task dict with ground_truth.file, .function, .start_line.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall = fraction of {function, file_basename} found.
    """
    gt = task["ground_truth"]
    fn_name: str = gt.get("function", "")
    file_path: str = gt.get("file", "")
    file_stem = file_path.split("/")[-1].replace(".py", "")

    fn_found = bool(fn_name) and bool(re.search(r"\b" + re.escape(fn_name) + r"\b", output_text, re.IGNORECASE))
    file_found = bool(file_stem) and bool(re.search(r"\b" + re.escape(file_stem) + r"\b", output_text, re.IGNORECASE))

    total = sum([bool(fn_name), bool(file_stem)])
    hits = sum([fn_found, file_found])
    recall = hits / total if total > 0 else 0.0

    return BenchQuality(
        scored=True,
        correct=fn_found and file_found,
        recall=round(recall, 3),
        extraction_failed=not fn_found and not file_found,
        evaluator_used="_evaluate_debug",
        evaluator_version=_EVAL_VER_DEBUG,
        scoring_detail={
            "function": fn_name,
            "fn_found": fn_found,
            "file": file_path,
            "file_found": file_found,
            "recall": recall,
            "method": "word_boundary_match",
        },
    )


def _evaluate_feature(task: dict, output_text: str) -> BenchQuality:
    """Evaluate feature_scaffolding task: entry_point method + primary_file basename.

    Correct when both the method name (last component of entry_point) and the
    primary_file basename appear in the output.

    Args:
        task: Task dict with ground_truth.entry_point, .primary_file.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with correct=True when both components found.
    """
    gt = task["ground_truth"]
    entry_point: str = gt.get("entry_point", "")
    primary_file: str = gt.get("primary_file", "")
    method = entry_point.split(".")[-1] if "." in entry_point else entry_point
    file_stem = primary_file.split("/")[-1].replace(".py", "")

    ep_found = bool(method) and bool(re.search(r"\b" + re.escape(method) + r"\b", output_text, re.IGNORECASE))
    file_found = bool(file_stem) and bool(re.search(r"\b" + re.escape(file_stem) + r"\b", output_text, re.IGNORECASE))

    total = sum([bool(entry_point), bool(primary_file)])
    hits = sum([ep_found, file_found])
    recall = hits / total if total > 0 else 0.0

    return BenchQuality(
        scored=True,
        correct=ep_found and file_found,
        recall=round(recall, 3),
        extraction_failed=not ep_found and not file_found,
        evaluator_used="_evaluate_feature",
        evaluator_version=_EVAL_VER_FEATURE,
        scoring_detail={
            "entry_point": entry_point,
            "ep_found": ep_found,
            "primary_file": primary_file,
            "file_found": file_found,
            "recall": recall,
            "method": "word_boundary_match",
        },
    )


_RI_RECALL_THRESHOLD = 0.70


def _evaluate_real_issue(task: dict, output_text: str) -> BenchQuality:
    """Evaluate real_issue task: file-set recall over ground_truth.files_changed.

    Recall = |GT file basenames found as whole words in output| / |GT files|.
    Correct when recall >= 0.70.

    Args:
        task: Task dict with ground_truth.files_changed list.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall and correct=True when recall >= 0.70.
    """
    gt = task["ground_truth"]
    gt_files: list[str] = gt.get("files_changed", [])
    if not gt_files:
        return BenchQuality(scored=False)

    found = sum(
        1
        for fp in gt_files
        if (stem := fp.split("/")[-1].replace(".py", ""))
        and re.search(r"\b" + re.escape(stem) + r"\b", output_text, re.IGNORECASE)
    )
    recall = found / len(gt_files)

    return BenchQuality(
        scored=True,
        correct=recall >= _RI_RECALL_THRESHOLD,
        recall=round(recall, 3),
        metric_expected=len(gt_files),
        metric_got=found,
        extraction_failed=found == 0,
        evaluator_used="_evaluate_real_issue",
        evaluator_version=_EVAL_VER_REAL_ISSUE,
        scoring_detail={
            "gt_files": gt_files,
            "files_found": found,
            "recall": recall,
            "threshold": _RI_RECALL_THRESHOLD,
            "method": "word_boundary_match",
        },
    )


_EVALUATORS = {
    "symbol_extraction": _evaluate_symbol,
    "fn_call_graph": _evaluate_develop_br,  # name-recall, not count-tolerance: callers are enumerated, not counted
    "review_assistance": _evaluate_rv,
    "code_quality": _evaluate_oss,
    "develop_blast_radius": _evaluate_develop_br,
    "debug_from_trace": _evaluate_debug,
    "feature_scaffolding": _evaluate_feature,
    "real_issue": _evaluate_real_issue,
}


# ---------------------------------------------------------------------------
# Patch sandbox (Tier E)
# ---------------------------------------------------------------------------

# Match the start of a unified diff: a `--- ` / `+++ ` header pair followed by an
# `@@` hunk header. Anchored at line start (MULTILINE) so prose preceding the diff
# is skipped; the diff is assumed to run to EOF (agents emit one diff block last).
_DIFF_RE = re.compile(r"^(?:--- .+\n\+\+\+ .+\n@@.+)", re.MULTILINE)


def _extract_diff(text: str) -> str | None:
    """Return the first unified diff block found in *text*, or None.

    The match anchors on a ``---``/``+++``/``@@`` header sequence and returns
    everything from there to the end of the string, since agents emit the patch
    as a trailing fenced block. Surrounding markdown fences (```` ```diff ````)
    are stripped from the tail when present.

    Args:
        text: Full agent response text.

    Returns:
        The unified diff substring, or None when no diff header is found.

    Examples:
        >>> _extract_diff("here is the fix\\n--- a/x.py\\n+++ b/x.py\\n@@ -1 +1 @@\\n-a\\n+b\\n")
        '--- a/x.py\\n+++ b/x.py\\n@@ -1 +1 @@\\n-a\\n+b\\n'
        >>> _extract_diff("no diff here") is None
        True
    """
    match = _DIFF_RE.search(text)
    if not match:
        return None
    diff = text[match.start() :]
    # Drop a trailing markdown code fence if the agent wrapped the diff.
    fence = diff.find("\n```")
    if fence != -1:
        diff = diff[:fence]
    if not diff.endswith("\n"):
        diff += "\n"
    return diff


class PatchSandbox:
    """Apply an agent-produced diff in an isolated git worktree and run its test.

    The sandbox checks out the task's pre-fix commit in a detached ``git worktree``
    under ``/tmp``, applies the candidate diff, runs the single failing test, then
    tears the worktree down. It measures one signal only: whether that specific
    test passes after the patch — not full-suite health or semantic correctness.

    Args:
        repo_path: Root of a local clone of the target repo with full git history.
        task: Patch-task dict; must carry ``id``, ``pre_fix_commit``, and either
            ``test_command`` or ``failing_test``.

    Examples:
        >>> sandbox = PatchSandbox("/path/to/clone", {  # doctest: +SKIP
        ...     "id": "PT-01",
        ...     "pre_fix_commit": "abc123",
        ...     "failing_test": "tests/test_x.py::test_y",
        ... })
        >>> sandbox.run(diff_text)  # doctest: +SKIP
        True
    """

    def __init__(self, repo_path: str | Path, task: dict) -> None:
        self.repo_path = Path(repo_path)
        self.task = task
        self._worktree = Path("/tmp") / f"patch-bench-{task['id']}"

    def _test_argv(self) -> list[str]:
        """Build the pytest argv from the task's test_command or failing_test."""
        cmd = self.task.get("test_command")
        if cmd:
            return shlex.split(cmd)
        failing = self.task.get("failing_test")
        if not failing:
            raise SandboxError(f"task {self.task['id']}: no test_command or failing_test")
        return ["pytest", failing, "-x"]

    def run(self, diff_text: str) -> bool:
        """Apply *diff_text* at the pre-fix commit and run the failing test.

        Args:
            diff_text: Unified diff text produced by the agent.

        Returns:
            True when the test fails at the pre-fix commit, the patch applies
            cleanly, and the test passes after patching.
            False when the patch fails to apply, the test still fails after
            patching, or the test already passes before patching.

        Raises:
            SandboxError: When the worktree cannot be created (e.g. unknown
                pre-fix commit) — the pass/fail signal is then unobtainable.
        """
        commit = self.task.get("pre_fix_commit")
        if not commit:
            raise SandboxError(f"task {self.task['id']}: missing pre_fix_commit")

        # Pre-clean any stale worktree from a crashed prior run.
        self._cleanup()
        try:
            create = subprocess.run(
                ["git", "-C", str(self.repo_path), "worktree", "add", "--detach", str(self._worktree), commit],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if create.returncode != 0:
                raise SandboxError(f"task {self.task['id']}: worktree add failed at {commit}: {create.stderr.strip()}")

            # Verify the test fails at the pre-fix commit before applying the patch.
            baseline = subprocess.run(
                [*self._test_argv(), "--timeout=60", "-q"],
                cwd=str(self._worktree),
                capture_output=True,
                text=True,
                timeout=600,
            )
            if baseline.returncode == 0:
                # Test already passes before the patch — cannot validate the fix.
                return False

            # Apply the diff. Prefer `git apply` (respects a/ b/ prefixes); fall back to patch -p1.
            patch_file = self._worktree / ".patch-bench.diff"
            patch_file.write_text(diff_text)
            applied = subprocess.run(
                ["git", "-C", str(self._worktree), "apply", "--reject", "--whitespace=nowarn", str(patch_file)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if applied.returncode != 0:
                fallback = subprocess.run(
                    ["patch", "-p1", "-i", str(patch_file)],
                    cwd=str(self._worktree),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if fallback.returncode != 0:
                    # Patch did not apply — count as a failed patch, not a sandbox error.
                    return False

            test = subprocess.run(
                [*self._test_argv(), "--timeout=60", "-q"],
                cwd=str(self._worktree),
                capture_output=True,
                text=True,
                timeout=600,
            )
            return test.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Remove the temp worktree; never raise (best-effort teardown)."""
        if not self._worktree.exists():
            return
        try:
            subprocess.run(
                ["git", "-C", str(self.repo_path), "worktree", "remove", "--force", str(self._worktree)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError):
            pass


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class BenchRunner:
    """Run benchmark tasks against Claude CLI in plain or codemap arm.

    Args:
        model_short: Short model tier name (e.g. "haiku").
        model_id: Full Claude model identifier.
        repo_path: Root of the target repository clone.
        index_path: Path to the pre-built codemap index.
        timeout: Wall-clock seconds per run before killing the subprocess.
    """

    def __init__(
        self,
        model_short: str,
        model_id: str,
        repo_path: Path,
        index_path: Path,
        timeout: int = 300,
    ) -> None:
        self.model_short = model_short
        self.model_id = model_id
        self.repo_path = repo_path
        self.index_path = index_path
        self.timeout = timeout

    def run(self, task: dict, arm: str, update_fn: Optional[Any] = None) -> BenchRun:
        """Run one task in one arm; parse stream-json for metrics.

        Args:
            task: Task dict from tasks-bench.json.
            arm: "plain" or "codemap".
            update_fn: Optional ``(elapsed_s, run)`` callback forwarded to ``_stream``
                for live sub-progress display.

        Returns:
            BenchRun with all metrics filled.
        """
        system = (
            _PLAIN_SYSTEM.format(repo_name=_REPO_NAME, repo_path=str(self.repo_path))
            if arm == "plain"
            else _CODEMAP_SYSTEM_TEMPLATE.format(
                repo_name=_REPO_NAME, index_path=str(self.index_path), repo_path=str(self.repo_path)
            )
        )
        disallow_flags = _ARM_DISALLOWED.get(arm, [])
        allow_flags = _ARM_ALLOWED.get(arm, [])
        # Scale max-turns for develop_blast_radius.
        # Plain arm: no index, needs per-file grep → floor 80, 4× caller count.
        # Codemap arm: fn-rdeps in 1-2 turns → floor 40, 2× caller count.
        caller_count = task.get("ground_truth", {}).get("unique_caller_count", 0)
        if task.get("type") in ("develop_blast_radius", "fn_call_graph"):
            max_turns = max(80, caller_count * 4) if arm == "plain" else max(80, caller_count * 2)
        else:
            max_turns = 40
        cmd = [
            *_CMD,
            "--max-turns",
            str(max_turns),
            "--model",
            self.model_id,
            *disallow_flags,
            *allow_flags,
            "--system-prompt",
            system,
            task["prompt"],
        ]
        # workflow_type groups tasks at a coarser level than task_type; default to task_type
        # so legacy task files (no workflow_type field) still group sensibly.
        workflow_type = task.get("workflow_type") or task["type"]
        result = BenchRun(
            arm=arm,
            task_id=task["id"],
            task_type=task["type"],
            model=self.model_short,
            success=False,
            workflow_type=workflow_type,
        )
        _MAX_RETRIES = 2
        for attempt in range(_MAX_RETRIES + 1):
            result = BenchRun(
                arm=arm,
                task_id=task["id"],
                task_type=task["type"],
                model=self.model_short,
                success=False,
                workflow_type=workflow_type,
            )
            self._stream(cmd, result, arm, update_fn=update_fn)
            if result.input_tokens == 0 and result.output_tokens == 0 and attempt < _MAX_RETRIES:
                result.error = f"api_failure_retry_{attempt + 1}"
                time.sleep(2**attempt)  # exponential backoff: 1s, 2s
                continue
            break

        # Treat budget-exhaustion as incomplete rather than a zero-recall failure.
        # Agent never produced a final answer — scoring partial output_text would measure
        # token luck, not blast-radius comprehension.
        if result.error == "error_max_turns":
            result.incomplete = True
        elif task.get("scoreable") is False:
            # Task explicitly opted out of scoring (scoreable=false) — e.g. tasks-code.json,
            # RI-05 (wrong repo layout). Record token ratio + tool counts only; exclude from
            # accuracy denominator.
            result.quality = BenchQuality(scored=False)
        else:
            evaluator = _EVALUATORS.get(task["type"])
            if evaluator is not None:
                result.quality = evaluator(task, result.output_text)
            # Contamination guards:
            #  - plain arm: detect codemap binary access that bypassed the disallow list
            #    (e.g. invoked via python3 path instead of bare scan-query).
            #  - either arm: detect reads of ground-truth answer files (tasks-bench.json,
            #    benchmark results) which would let the agent copy the expected answer.
            _CODEMAP_MARKERS = ("scan-query", "codemap/bin")
            _ANSWER_MARKERS = ("tasks-bench", "benchmarks/results", "/benchmarks/")
            if arm == "plain" and any(marker in entry for entry in result.tool_log for marker in _CODEMAP_MARKERS):
                result.error = "contaminated"
                result.quality = BenchQuality(scored=False)
            elif any(marker in entry for entry in result.tool_log for marker in _ANSWER_MARKERS):
                result.error = "answer_file_read"
                result.quality = BenchQuality(scored=False)

        return result

    def _env(self, arm: str) -> dict[str, str]:
        """Return subprocess environment; arm-aware to avoid control-arm contamination.

        Args:
            arm: "plain" or "codemap". Plain arm gets no CODEMAP_* vars or bin PATH.

        Returns:
            Dict suitable for subprocess.Popen env argument.
        """
        if arm == "plain":
            env = os.environ.copy()
            env.pop("CODEMAP_INDEX", None)
            env.pop("CODEMAP_ENABLED", None)
            return env
        return _subprocess_env(self.index_path)

    def _stream(
        self,
        cmd: list[str],
        result: BenchRun,
        arm: str,
        update_fn: Optional[Any] = None,
    ) -> None:
        """Launch claude subprocess and parse stream-json events into result.

        Args:
            cmd: Full claude CLI command list.
            result: BenchRun to populate in-place.
            arm: "plain" or "codemap"; forwarded to _env for isolation.
            update_fn: Optional ``(elapsed_s, run)`` callback called ≤2× per second
                with live subprocess state for sub-progress displays.
        """
        pending: dict[str, float] = {}
        t0 = time.monotonic()
        _upd: list[float] = [0.0]  # last update timestamp (list so inner scope can mutate)
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(self.repo_path),
                env=self._env(arm),
            )
            kill_timer = threading.Timer(self.timeout, proc.kill)
            kill_timer.start()
            try:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    ts = time.monotonic()
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._handle(event, result, pending, ts)
                    if update_fn is not None and ts - _upd[0] >= 0.5:
                        update_fn(ts - t0, result)
                        _upd[0] = ts
                stderr_out = proc.stderr.read() if proc.stderr else ""
                proc.wait(timeout=10)
                if not result.success and not result.error and stderr_out:
                    result.error = stderr_out.strip()[:300]
            finally:
                kill_timer.cancel()
            if proc.returncode and proc.returncode < 0 and not result.error:
                result.error = f"timeout ({self.timeout}s)"
                result.incomplete = True
        except subprocess.TimeoutExpired:
            result.error = f"timeout ({self.timeout}s)"
            result.incomplete = True
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)[:300]
        finally:
            result.elapsed_s = time.monotonic() - t0

    @staticmethod
    def _extract_codemap_meta(block: dict, result: "BenchRun") -> None:
        """Parse a tool_result block for scan-query index metadata.

        Extracts ``index.method`` and ``index.not_covered`` from any JSON
        content that looks like a scan-query response, accumulating unique
        values into *result*.

        Args:
            block: A tool_result content block from the Claude stream.
            result: BenchRun to update in-place.
        """
        content = block.get("content", [])
        # content may be a string or a list of content blocks
        texts: list[str] = []
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for cb in content:
                if isinstance(cb, dict) and cb.get("type") == "text":
                    texts.append(cb.get("text", ""))
        for raw in texts:
            try:
                parsed = json.loads(raw)
                idx = parsed.get("index", {})
                method = idx.get("method", "")
                if method and method not in result.codemap_methods:
                    result.codemap_methods.append(method)
                for nc in idx.get("not_covered", []):
                    if nc not in result.codemap_not_covered:
                        result.codemap_not_covered.append(nc)
            except (json.JSONDecodeError, AttributeError):
                pass

    def _handle(self, event: dict, result: BenchRun, pending: dict[str, float], ts: float) -> None:
        """Route a single stream-json event to the appropriate handler.

        Args:
            event: Parsed JSON event dict.
            result: BenchRun to populate in-place.
            pending: Map of tool_use_id → start timestamp (for elapsed tracking).
            ts: Current monotonic timestamp.
        """
        etype = event.get("type", "")

        if etype == "assistant":
            result.turn_count += 1
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    result.output_text += block.get("text", "")
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    tool_id = block.get("id", "")
                    pending[tool_id] = ts
                    if name == "Grep":
                        result.grep_calls += 1
                        key = inp.get("pattern", "")[:60]
                        result.tool_log.append(f"Grep: {key!r}")
                    elif name == "Bash":
                        result.bash_calls += 1
                        cmd = inp.get("command", "")
                        if "scan-query" in cmd or "codemap/bin" in cmd:
                            result.scan_query_calls += 1
                            sub = _parse_scan_query_subcommand(cmd)
                            if sub is not None:
                                result.scan_query_subcommands[sub] = result.scan_query_subcommands.get(sub, 0) + 1
                        result.tool_log.append(f"Bash: {cmd[:80]}")
                    elif name == "Read":
                        result.read_calls += 1
                        result.tool_log.append(f"Read: {inp.get('file_path', '')[:60]}")
                    elif name == "Skill":
                        result.skill_calls += 1
                        _sk = inp.get("skill", "") or ""
                        _sk_short = _sk.split(":")[-1] if ":" in _sk else _sk
                        result.skill_counts[_sk_short] = result.skill_counts.get(_sk_short, 0) + 1
                        result.tool_log.append(f"Skill: {_sk} {inp.get('args', '')}".strip())
                    else:
                        first_val = next((v for v in inp.values() if isinstance(v, str)), "") if inp else ""
                        result.tool_log.append(f"{name}: {first_val[:50]}" if first_val else name)

        elif etype == "user":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") != "tool_result":
                    continue
                tool_id = block.get("tool_use_id", "")
                pending.pop(tool_id, None)
                if result.arm == "codemap":
                    self._extract_codemap_meta(block, result)

        elif etype == "result":
            subtype = event.get("subtype", "")
            usage = event.get("usage", {})
            result.input_tokens = (
                usage.get("input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
            result.output_tokens = usage.get("output_tokens", 0)
            result.success = subtype == "success"
            if not result.success and not result.error:
                result.error = subtype


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _run_correct_symbol(run: BenchRun) -> str:
    """Single-character status symbol for a completed run.

    Returns:
        'c' — contaminated (plain arm accessed codemap binary)
        '!' — incomplete (budget exhausted)
        '+' — correct
        '-' — scored but incorrect
        '?' — not scored
    """
    if run.error == "contaminated":
        return "c"
    if run.incomplete:
        return "!"
    if run.quality.correct:
        return "+"
    if run.quality.scored:
        return "-"
    return "?"


def _effective_recall(run: Optional[BenchRun]) -> Optional[float]:
    """Recall value for summary — mirrors per-run log fallback logic.

    Returns recall directly when set; falls back to metric_got/metric_expected
    for evaluators that don't populate the recall field (symbol_extraction,
    code_quality, count-based review_assistance).

    Args:
        run: A completed benchmark run, or None.

    Returns:
        Recall as a float, or None when not computable.
    """
    if run is None or not run.quality.scored:
        return None
    if run.quality.extraction_failed:
        return None
    if run.quality.recall is not None:
        return run.quality.recall
    if run.quality.metric_got is not None and run.quality.metric_expected:
        return run.quality.metric_got / run.quality.metric_expected
    return None


def _safe_ratio(num: Optional[float], den: Optional[float]) -> float:
    """Divide num by den; return NaN when den is zero or None.

    Args:
        num: Numerator (int or float, or None).
        den: Denominator (int or float, or None).

    Returns:
        num / den, or float('nan') when division is undefined.

    Examples:
        >>> _safe_ratio(10, 4)
        2.5
        >>> import math; math.isnan(_safe_ratio(10, 0))
        True
    """
    if num is None or den is None:
        return float("nan")
    return num / den if den else float("nan")


@dataclass
class TaskRatioRow:
    """One row in the per-task token-ratio summary table."""

    task_id: str
    task_type: str
    plain_tok: int
    codemap_tok: int
    ratio: float
    plain_recall: float | None
    codemap_recall: float | None
    plain_correct: bool | None
    codemap_correct: bool | None
    plain_elapsed_s: float | None
    codemap_elapsed_s: float | None
    time_ratio: float | None


def _token_ratio_table(runs: list[BenchRun]) -> pd.DataFrame:
    """Build a per-task token-ratio table comparing codemap vs plain arms.

    Args:
        runs: All benchmark runs.

    Returns:
        DataFrame with columns: task_id, task_type, plain_tok, codemap_tok, ratio, delta_correct.
    """
    by_task: dict[str, dict[str, BenchRun]] = defaultdict(dict)
    for r in runs:
        by_task[r.task_id][r.arm] = r

    rows = []
    for task_id, arms in sorted(by_task.items()):
        plain = arms.get("plain")
        codemap = arms.get("codemap")
        plain_tok = plain.input_tokens if plain else 0
        codemap_tok = codemap.input_tokens if codemap else 0
        ratio = _safe_ratio(codemap_tok, plain_tok)
        plain_ok = plain.quality.correct if plain and plain.quality.scored else None
        codemap_ok = codemap.quality.correct if codemap and codemap.quality.scored else None
        task_type = (plain or codemap).task_type if (plain or codemap) else ""
        plain_elapsed = plain.elapsed_s if plain else None
        codemap_elapsed = codemap.elapsed_s if codemap else None
        time_ratio = _safe_ratio(codemap_elapsed, plain_elapsed)
        rows.append(
            TaskRatioRow(
                task_id=task_id,
                task_type=task_type,
                plain_tok=plain_tok,
                codemap_tok=codemap_tok,
                ratio=ratio,
                plain_recall=_effective_recall(plain),
                codemap_recall=_effective_recall(codemap),
                plain_correct=plain_ok,
                codemap_correct=codemap_ok,
                plain_elapsed_s=plain_elapsed,
                codemap_elapsed_s=codemap_elapsed,
                time_ratio=time_ratio,
            )
        )
    return pd.DataFrame([asdict(r) for r in rows])


def _workflow_type_of(run: BenchRun) -> str:
    """Return the workflow grouping key for a run.

    Falls back to ``task_type`` when ``workflow_type`` is unset (legacy task
    files that predate the field).

    Args:
        run: A completed benchmark run.

    Returns:
        The workflow grouping key (e.g. ``"query"``, ``"debug"``).

    Examples:
        >>> _workflow_type_of(BenchRun(arm="plain", task_id="X", task_type="symbol_extraction", model="haiku", success=True, workflow_type="query"))
        'query'
        >>> _workflow_type_of(BenchRun(arm="plain", task_id="X", task_type="symbol_extraction", model="haiku", success=True))
        'symbol_extraction'
    """
    return run.workflow_type or run.task_type


def _print_workflow_breakdown(runs: list[BenchRun]) -> None:
    """Print a per-workflow_type breakdown of token ratio and accuracy.

    Groups runs by :func:`_workflow_type_of`. For each workflow type, reports
    the median codemap/plain token ratio (computed per task that has both arms)
    and the codemap-arm accuracy over scored, completed runs.

    Args:
        runs: All benchmark runs (may span multiple arms and workflow types).
    """
    by_wf: dict[str, list[BenchRun]] = defaultdict(list)
    for r in runs:
        by_wf[_workflow_type_of(r)].append(r)
    if not by_wf:
        return

    print("\nPer-workflow_type breakdown:")
    hdr = f"  {'workflow_type':<22}  {'n_tasks':>7}  {'tok× (med)':>10}  {'cm_acc':>10}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for wf in sorted(by_wf):
        wf_runs = by_wf[wf]
        # Token ratio per task: codemap_tok / plain_tok where both arms ran.
        by_task: dict[str, dict[str, BenchRun]] = defaultdict(dict)
        for r in wf_runs:
            by_task[r.task_id][r.arm] = r
        ratios: list[float] = []
        for arms in by_task.values():
            plain = arms.get("plain")
            codemap = arms.get("codemap")
            if plain and codemap and plain.input_tokens:
                ratios.append(codemap.input_tokens / plain.input_tokens)
        ratio_str = f"{statistics.median(ratios):>10.2f}" if ratios else f"{'n/a':>10}"

        cm_scored = [
            r
            for r in wf_runs
            if r.arm == "codemap" and r.quality.scored and not r.quality.extraction_failed and not r.incomplete
        ]
        if cm_scored:
            n_correct = sum(1 for r in cm_scored if r.quality.correct)
            acc_str = f"{n_correct / len(cm_scored):>9.1%}"
        else:
            acc_str = f"{'n/a':>10}"
        n_tasks = len(by_task)
        print(f"  {wf:<22}  {n_tasks:>7}  {ratio_str}  {acc_str}")


def _print_summary(runs: list[BenchRun], model: str) -> None:
    """Print a summary table of token ratios and accuracy to stdout.

    Args:
        runs: All benchmark runs (may span multiple arms).
        model: Short model name shown in header.
    """
    df = _token_ratio_table(runs)
    if df.empty:
        print("No runs to summarise.")
        return

    print(f"\n{'=' * 64}")
    print(f"  Codemap benchmark — model={model}")
    print(f"{'=' * 64}")

    # Build display table manually to support colored Δrecall column.
    hdr = f"{'task_id':<9}  {'plain_tok':>9}  {'cm_tok':>9}  {'tok×':>5}  {'plain_t':>7}  {'cm_t':>7}  {'t×':>5}  {'Δrecall':>9}"
    print(hdr)
    print("-" * len(hdr))
    for _, row in df.iterrows():
        tid = str(row["task_id"])
        ptok = f"{int(row['plain_tok']):>9,}" if pd.notna(row["plain_tok"]) else f"{'n/a':>9}"
        ctok = f"{int(row['codemap_tok']):>9,}" if pd.notna(row["codemap_tok"]) else f"{'n/a':>9}"
        tratio = f"{row['ratio']:>5.2f}" if pd.notna(row["ratio"]) else f"{'n/a':>5}"
        pt = f"{row['plain_elapsed_s'] / 60:>6.1f}m" if pd.notna(row["plain_elapsed_s"]) else f"{'n/a':>7}"
        ct = f"{row['codemap_elapsed_s'] / 60:>6.1f}m" if pd.notna(row["codemap_elapsed_s"]) else f"{'n/a':>7}"
        trm = f"{row['time_ratio']:>5.2f}" if pd.notna(row.get("time_ratio", float("nan"))) else f"{'n/a':>5}"
        pr = row["plain_recall"]
        cr = row["codemap_recall"]
        if pd.notna(pr) and pd.notna(cr):
            delta = cr - pr
            if abs(delta) < 0.01:
                sym = f"{_BLUE}~{delta:.2f}{_RESET}"
                vis = f"~{delta:.2f}"
            elif delta > 0:
                sym = f"{_GREEN}+{delta:.2f}{_RESET}"
                vis = f"+{delta:.2f}"
            else:
                sym = f"{_RED}{delta:.2f}{_RESET}"
                vis = f"{delta:.2f}"
            pad = 7 - len(vis)
            recall_col = " " * max(pad, 0) + sym
        elif pd.notna(cr):
            recall_col = f"{'cm:' + f'{cr:.2f}':>9}"
        elif pd.notna(pr):
            recall_col = f"{'pl:' + f'{pr:.2f}':>9}"
        else:
            recall_col = f"{'n/a':>9}"
        print(f"{tid:<9}  {ptok}  {ctok}  {tratio}  {pt}  {ct}  {trm}  {recall_col}")

    valid = df.dropna(subset=["ratio"])
    if not valid.empty:
        ratios = valid["ratio"].tolist()
        print(
            f"\nToken ratio (codemap/plain):  median={statistics.median(ratios):.2f}  mean={statistics.mean(ratios):.2f}  [{min(ratios):.2f}–{max(ratios):.2f}]"
        )

    valid_t = df.dropna(subset=["time_ratio"])
    if not valid_t.empty:
        time_ratios = valid_t["time_ratio"].tolist()
        plain_times = valid_t["plain_elapsed_s"].tolist()
        codemap_times = valid_t["codemap_elapsed_s"].tolist()
        print(
            f"Time ratio   (codemap/plain):  median={statistics.median(time_ratios):.2f}  mean={statistics.mean(time_ratios):.2f}  [{min(time_ratios):.2f}–{max(time_ratios):.2f}]"
        )
        print(
            f"  plain   median={statistics.median(plain_times) / 60:.1f}m  mean={statistics.mean(plain_times) / 60:.1f}m"
        )
        print(
            f"  codemap median={statistics.median(codemap_times) / 60:.1f}m  mean={statistics.mean(codemap_times) / 60:.1f}m"
        )

    for arm in ("plain", "codemap"):
        arm_runs = [r for r in runs if r.arm == arm and r.quality.scored and not r.quality.extraction_failed]
        extraction_failed_runs = [r for r in runs if r.arm == arm and r.quality.extraction_failed]
        incomplete_runs = [r for r in runs if r.arm == arm and r.incomplete]
        contaminated_runs = [r for r in runs if r.arm == arm and r.error == "contaminated"]
        if arm_runs:
            n_correct = sum(1 for r in arm_runs if r.quality.correct)
            acc = n_correct / len(arm_runs)
            print(f"  {arm} accuracy = {acc:.1%}  ({n_correct}/{len(arm_runs)} scored)")
        if extraction_failed_runs:
            ids = ", ".join(r.task_id for r in extraction_failed_runs)
            print(
                f"  {arm} extraction_failed = {len(extraction_failed_runs)} (metric not found in output — excluded: {ids})"
            )
        if incomplete_runs:
            ids = ", ".join(r.task_id for r in incomplete_runs)
            print(f"  {arm} incomplete = {len(incomplete_runs)} (budget exhausted — not scored: {ids})")
        if contaminated_runs:
            ids = ", ".join(r.task_id for r in contaminated_runs)
            print(
                f"  {arm} contaminated = {len(contaminated_runs)} (codemap accessed in plain arm — not scored: {ids})"
            )
        answer_read_runs = [r for r in runs if r.arm == arm and r.error == "answer_file_read"]
        if answer_read_runs:
            ids = ", ".join(r.task_id for r in answer_read_runs)
            print(f"  {arm} answer_file_read = {len(answer_read_runs)} (GT file accessed — not scored: {ids})")
        _SAFETY_GRADE_TYPES = {"develop_blast_radius", "fn_call_graph"}
        safety_runs = [
            r
            for r in arm_runs
            if r.task_type in _SAFETY_GRADE_TYPES and r.quality.scoring_detail.get("safety_grade") is not None
        ]
        if safety_runs:
            n_safe = sum(1 for r in safety_runs if r.quality.scoring_detail.get("safety_grade"))
            print(f"  {arm} safety-grade (recall>=0.90) = {n_safe}/{len(safety_runs)}")
        if arm == "codemap":
            all_nc = sorted({nc for r in runs if r.arm == "codemap" for nc in r.codemap_not_covered})
            if all_nc:
                print(f"  codemap not_covered gaps: {', '.join(all_nc)}")
            all_methods = sorted({m for r in runs if r.arm == "codemap" for m in r.codemap_methods})
            if all_methods:
                print(f"  codemap query methods used: {', '.join(all_methods)}")

    # Tier E: patch pass rate (failing test → fix → test pass). Only shown when any
    # run carries a patch_pass signal; agents emitting prose without a diff score 0.
    patch_runs = [r for r in runs if r.patch_pass is not None]
    if patch_runs:
        for arm in ("plain", "codemap"):
            arm_patch = [r for r in patch_runs if r.arm == arm]
            if not arm_patch:
                continue
            n_pass = sum(1 for r in arm_patch if r.patch_pass)
            rate = n_pass / len(arm_patch)
            print(f"  patch_pass_rate ({arm}) = {n_pass}/{len(arm_patch)}  ({rate:.1%})")

    _print_workflow_breakdown(runs)


def _save_results(runs: list[BenchRun], model: str) -> Path:
    """Serialise run results to JSONL in the results directory.

    Args:
        runs: All benchmark runs.
        model: Short model name used in filename.

    Returns:
        Path to the written JSONL file.
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = RESULTS_DIR / f"bench-{model}-{ts}.jsonl"
    with out.open("w") as f:
        for r in runs:
            d = asdict(r)
            json.dump(d, f)
            f.write("\n")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(
    repo_path: Path = None,
    index_path: Path = None,
    tasks: list[str] = None,
    tasks_file: list[str] = None,
    task_type: str = None,
    arm: str = "all",
    model: str = "haiku",
    run_all: bool = False,
    patch: bool = False,
    no_save: bool = False,
    timeout: int = None,
) -> None:
    """Entry point: load tasks, run selected arms, print summary.

    Args:
        repo_path: Path to the target repository clone.
        index_path: Path to codemap index JSON.
        tasks: Task IDs to run as a Python list literal, e.g. ``--tasks "['SE-01', 'FN-02']"``.
        tasks_file: Additional task JSON file(s) to load alongside tasks-bench.json (repeatable).
        task_type: Run tasks of this type only.
        arm: Which arm(s) to run (default: all).
        model: Model to use (default: haiku).
        run_all: Run all tasks (CLI flag: ``--run-all``).
        patch: Run patch tasks from tasks-patch.json.
        no_save: Skip writing JSONL results.
        timeout: Per-run timeout in seconds.
    """
    global _REPO_NAME, _REPO_NAMESPACE, _REPO_DEFAULT_PATH

    # fire passes CLI string args regardless of type annotation — coerce Path args explicitly.
    if repo_path is not None:
        repo_path = Path(repo_path)
    if index_path is not None:
        index_path = Path(index_path)

    # Load tasks first — repo header provides identity for evaluators and fallback path
    try:
        with TASKS_FILE.open() as f:
            _raw = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: cannot read {TASKS_FILE}: {exc}")
        sys.exit(1)

    if isinstance(_raw, dict):
        repo_meta = _raw.get("repo", {})
        all_tasks: list[dict] = _raw.get("tasks", [])
    else:
        repo_meta = {}
        all_tasks = _raw

    # Populate repo identity globals from header (evaluators consume these)
    if repo_meta.get("name"):
        _REPO_NAME = repo_meta["name"]
    if repo_meta.get("namespace"):
        _REPO_NAMESPACE = list(repo_meta["namespace"])
    _REPO_DEFAULT_PATH = repo_meta.get("default_path")

    # Append tasks from any --tasks-file; scoreable depends on whether ground_truth is present.
    external_ids: list[str] = []
    if tasks_file:
        for tf in tasks_file:
            try:
                extra = _load_tasks_file(Path(tf))
            except (FileNotFoundError, ValueError) as exc:
                print(f"ERROR: {exc}")
                sys.exit(1)
            known_ids = {t["id"] for t in all_tasks}
            dupes = [t["id"] for t in extra if t["id"] in known_ids]
            if dupes:
                print(f"ERROR: --tasks-file {tf} has task IDs already loaded: {sorted(set(dupes))}")
                sys.exit(1)
            all_tasks.extend(extra)
            external_ids.extend(t["id"] for t in extra)
            n_scored = sum(1 for t in extra if t.get("scoreable") is not False)
            print(f"Loaded {len(extra)} task(s) from {tf} ({n_scored} scoreable)")

    # Append patch tasks (Tier E) when --patch is set. Unlike --tasks-file tasks,
    # patch tasks keep their own scoreable flag and are sandbox-executed in _run_combo.
    patch_ids: list[str] = []
    if patch:
        try:
            with PATCH_TASKS_FILE.open() as f:
                _patch_raw = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"ERROR: cannot read {PATCH_TASKS_FILE}: {exc}")
            sys.exit(1)
        patch_tasks = _patch_raw.get("tasks", []) if isinstance(_patch_raw, dict) else _patch_raw
        known_ids = {t["id"] for t in all_tasks}
        dupes = [t["id"] for t in patch_tasks if t["id"] in known_ids]
        if dupes:
            print(f"ERROR: tasks-patch.json has task IDs already loaded: {sorted(set(dupes))}")
            sys.exit(1)
        all_tasks.extend(patch_tasks)
        patch_ids.extend(t["id"] for t in patch_tasks)
        print(f"Loaded {len(patch_tasks)} patch task(s) from {PATCH_TASKS_FILE.name}")

    patch_id_set = set(patch_ids)

    # Resolve repo path
    if not repo_path:
        _cands: list[Path] = []
        if _REPO_DEFAULT_PATH:
            _cands.append(Path(_REPO_DEFAULT_PATH))
        for cand in _cands:
            if cand.is_dir():
                repo_path = cand
                break
        if not repo_path:
            print("ERROR: cannot find repo. Pass --repo-path.")
            sys.exit(1)
    if not repo_path.is_dir():
        print(f"ERROR: --repo-path {repo_path} is not a directory")
        sys.exit(1)

    # Resolve index
    try:
        index_path = _resolve_index(repo_path, index_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    # Filter tasks
    task_list = all_tasks
    if tasks:
        ids = set(tasks)
        task_list = [t for t in task_list if t["id"] in ids]
        missing = ids - {t["id"] for t in task_list}
        if missing:
            print(f"ERROR: task IDs not found: {sorted(missing)}")
            sys.exit(1)
    elif task_type:
        task_list = [t for t in task_list if t["type"] == task_type]
    elif not run_all:
        # Without --all: run only the externally-supplied subset (--tasks-file / --patch).
        subset = set(external_ids) | patch_id_set
        if subset:
            task_list = [t for t in task_list if t["id"] in subset]
        else:
            print("Specify --tasks, --task-type, --tasks-file, --patch, or --all")
            sys.exit(1)

    if not task_list:
        print("No tasks matched.")
        sys.exit(1)

    # Determine arms
    arms_to_run = list(ARMS) if arm == "all" else [arm]

    # Build runner
    model_short = model
    model_id = MODELS[model_short]
    run_timeout = timeout or _MODEL_TIMEOUT[model_short]
    runner = BenchRunner(
        model_short=model_short, model_id=model_id, repo_path=repo_path, index_path=index_path, timeout=run_timeout
    )

    print(f"Codemap benchmark: {len(task_list)} tasks × {len(arms_to_run)} arm(s) × model={model_short}")
    print(f"  index: {index_path}")
    print(f"  repo:  {repo_path}")
    print()
    print("Task series legend:")
    print("  SE  symbol_extraction     — locate symbol definition (file + line)")
    print("  FN  fn_call_graph         — unique callers of a function (static graph)")
    print("  RV  review_assistance     — doc-gap / rdep / coverage counts for review")
    print("  CQ  code_quality          — coupling, broken xrefs, doc+coverage health")
    print("  BR  develop_blast_radius  — enumerate direct callers before a change (recall ≥ 0.70)")
    print("  DG  debug_from_trace      — identify fn + file from traceback/log (word-boundary match)")
    print("  FT  feature_scaffolding   — identify files to create/modify for a feature (word-boundary match)")
    print("  RI  real_issue            — reproduce + locate files for a GitHub issue (recall ≥ 0.70)")
    print()

    runs: list[BenchRun] = []
    combos = [(task, arm) for task in task_list for arm in arms_to_run]

    def _run_combo(task: dict, arm: str, log_fn: Any, update_fn: Optional[Any] = None) -> BenchRun:
        run = runner.run(task, arm, update_fn=update_fn)
        # Tier E: for scoreable patch tasks, extract the agent diff and execute it in a
        # sandbox to record whether the failing test passes. Non-scoreable stubs (placeholder
        # SHA / no reference) skip the sandbox and report structural GT only.
        if task["id"] in patch_id_set and task.get("scoreable") is not False and run.success:
            diff_text = _extract_diff(run.output_text)
            if diff_text is not None:
                try:
                    run.patch_pass = PatchSandbox(repo_path, task).run(diff_text)
                except SandboxError as exc:
                    run.error = run.error or f"sandbox_error: {exc}"
                    run.patch_pass = None
            else:
                # No diff block in output — agent produced prose only; scores as a fail.
                run.patch_pass = False
        runs.append(run)
        status = "✓" if run.success else "✗"
        correct = _run_correct_symbol(run)
        tok = run.input_tokens
        tok_str = f"{tok / 1_000_000:.1f}M" if tok >= 1_000_000 else f"{tok // 1000:3d}k"
        _eff = _effective_recall(run)
        if not run.quality.scored:
            q_str = "?"
        elif run.quality.extraction_failed:
            q_str = "?"
        elif _eff is not None:
            q_str = f"^{_eff:.3f}" if _eff > 1.0 else f"{_eff:.3f}"
        else:
            q_str = "n/a"
        if run.skill_counts:
            _sk_parts = ",".join(f"{k}:{v:2d}" for k, v in sorted(run.skill_counts.items()))
            _sk_str = f"Sk={_sk_parts}"
        else:
            _sk_str = "Sk= 0"
        tool_summary = (
            f"B={run.bash_calls:2d} G={run.grep_calls:2d} R={run.read_calls:2d} SQ={run.scan_query_calls:2d} {_sk_str}"
        )
        log_fn(
            f"  {status}{correct} {task['id']}\t{arm}\ttok={tok_str}\tt={run.elapsed_s / 60:.1f}m\trecall={q_str}\ttotal={run.quality.metric_expected if run.quality.metric_expected is not None else '?':>4}\t{tool_summary}"
        )
        return run

    def _make_rich_update(
        progress: Any, outer_id: Any, sub_id: Any, task_id: str, arm_name: str, done: int, total: int
    ) -> Any:
        """Return a sub-progress update callback — updates outer description and sub-task bar."""

        def _update(elapsed: float, run: BenchRun) -> None:
            calls = run.grep_calls + run.bash_calls + run.skill_calls
            sk = run.skill_calls
            tool_live = f"B={run.bash_calls} G={run.grep_calls} R={run.read_calls} SQ={run.scan_query_calls} Sk={sk}"
            progress.update(outer_id, description=f"{task_id} {arm_name}")
            progress.update(
                sub_id,
                completed=run.turn_count,
                description=f"  {elapsed / 60:.1f}m calls={calls} {tool_live}",
            )

        return _update

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=_console,
    ) as progress:
        total = len(combos)
        outer = progress.add_task("running", total=total)
        for done, (task, arm) in enumerate(combos, 1):
            caller_count = task.get("ground_truth", {}).get("unique_caller_count", 0)
            if task.get("type") in ("develop_blast_radius", "fn_call_graph"):
                task_max_turns = max(80, caller_count * 4) if arm == "plain" else max(80, caller_count * 2)
            else:
                task_max_turns = 40
            sub = progress.add_task("  0s calls=0", total=task_max_turns)
            progress.update(outer, description=f"{task['id']} {arm}")
            _run_combo(
                task,
                arm,
                progress.console.print,
                update_fn=_make_rich_update(progress, outer, sub, task["id"], arm, done, total),
            )
            progress.remove_task(sub)
            progress.advance(outer)

    _print_summary(runs, model_short)

    if not no_save:
        out = _save_results(runs, model_short)
        print(f"\nResults → {out}")

    failed = [r for r in runs if not r.success]
    if failed:
        print(f"\n{len(failed)} run(s) failed:")
        for r in failed:
            print(f"  {r.task_id}/{r.arm}: {r.error}")
        sys.exit(1)


if __name__ == "__main__":
    fire.Fire(main)
