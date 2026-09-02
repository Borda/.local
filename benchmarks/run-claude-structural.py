#!/usr/bin/env python3
"""Claude-only Codemap structural benchmark across all real-code task series.

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
  DI — diff_impact         (callers and tests affected by a staged change)
  GR — graph_reasoning     (centrality, paths, and transitive function impact)
  MB — module_blast_radius (importer recall for a changed module)

Primary metric:
  token_ratio = codemap_input_tokens / plain_input_tokens per task (lower = better for codemap)

Secondary:
  accuracy = fraction of tasks where key metric matches ground truth within tolerance

## Quick start

  # Build index once (excluded from timing)
  python plugins/codemap-py/bin/scan-index --root ./<repo-dir>

  # Run all tasks, both arms, haiku model
  python benchmarks/run-claude-structural.py --repo-path ./<repo-dir> --run-all

  # Single task, codemap arm only
  python benchmarks/run-claude-structural.py --repo-path ./<repo-dir> \\
      --tasks "['SE-01']" --arm codemap --model haiku

## Requirements

  - claude CLI on PATH
  - Pre-built codemap index in .cache/codemap/<proj>.json or .cache/scan/<proj>.json
  - pip install --group pyproject.toml:bench
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

import fire
import pandas as pd
from rich.console import Console as _Console

# benchmarks/ is not a package; make its private shared package importable
# regardless of how this script is launched (direct path, symlink, or any cwd).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bench_common.benchmark_paths import RESULTS_DIR, TASKS_BENCH_FILE as TASKS_FILE, gt_is_pending  # noqa: E402
from _bench_common.claude_transport import MODEL_TIMEOUT, MODELS, parse_result_usage, stream_claude  # noqa: E402
from _bench_common.codemap_discovery import codemap_bin_on_path, resolve_index_path  # noqa: E402
from _bench_common.presentation import fmt_time, fmt_tok, make_progress  # noqa: E402
from _bench_common.mutation_isolation import IsolatedMutationCell, MutationCleanupError  # noqa: E402
from _bench_common.provider_parity_contracts import (  # noqa: E402
    ARM_CONTRACTS,
    EvaluationResult,
    EvaluatorRegistry,
    PARITY_TIMEOUT_SECONDS,
    TaskPolicy,
    capability_strata,
    canonical_task_hash,
    deterministic_arm_order,
    load_task_policies,
    load_task_suite,
    materialize_task_prompt,
    prompt_hash,
    semantic_suite_hash,
    treatment_adherence,
)

_USE_COLOR = sys.stdout.isatty()
_GREEN = "\033[32m" if _USE_COLOR else ""
_RED = "\033[31m" if _USE_COLOR else ""
_BLUE = "\033[34m" if _USE_COLOR else ""
_RESET = "\033[0m" if _USE_COLOR else ""
_console = _Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# TASKS_FILE and RESULTS_DIR come from benchmark_paths (shared across runners).
PATCH_TASKS_FILE = Path(__file__).parent / "suites" / "tasks-patch.json"

# Synthetic task type assigned to tasks loaded via ``--tasks-file`` that carry a `skill`
# field instead of a `type` field (e.g. tasks-code.json). No evaluator is registered for
# this type; tasks of this type are forced scoreable=False and contribute token-ratio and
# tool-count data only — never accuracy.
_EXTERNAL_TASK_TYPE = "develop_skill"

# Diff-impact tasks stage a scripted change around both arms, then ``DiffImpactStager`` reverts it.
_DIFF_IMPACT_TYPE = "diff_impact"

# real_issue (RI) series reproduces + locates files for a real GitHub issue; those runs routinely
# reach ~2M input tokens (the plain arm greps the whole tree). They therefore run only under the
# release profile or an explicit task selection, never in the fast dev / tiered-haiku default set.
_RI_TASK_TYPE = "real_issue"

# Cost profiles. `dev` selects the dev-tagged subset on haiku for a fast regression signal; `release`
# runs the full matrix including RI. Absent (None) → current behavior, unchanged.
_PROFILE_DEV = "dev"
_PROFILE_RELEASE = "release"
_PROFILES = (_PROFILE_DEV, _PROFILE_RELEASE)

# Per-task JSON tag: `"profiles": ["dev"]` marks membership in the stratified dev subset. Declared in
# tasks-bench.json (not hardcoded here) so the subset can be re-stratified without a code change.
_PROFILE_TAG_KEY = "profiles"

# Per-task JSON tag: `"self_consistency": true` marks a task whose ground truth is derived from the
# same scan-query index the codemap arm queries (uncovered / broken-xref counts). Such tasks still
# run and score, but are excluded from the headline accuracy aggregates and reported separately —
# scoring the codemap arm against index-derived truth would measure agreement with itself, not skill.
_SELF_CONSISTENCY_KEY = "self_consistency"

# Head-meta keys hashed into the index fingerprint (index_sha). These content-defining fields change
# whenever the index is rebuilt over a different tree / scan; `modules` is intentionally excluded so
# the fingerprint stays cheap to compute without loading the whole (large) index body.
_INDEX_META_KEYS = ("scan_version", "scanned_at", "git_sha", "project", "scan_root")

# MODELS and MODEL_TIMEOUT come from claude_transport (shared with run-claude-agentic).

# Tiered protocol (release companion). Each tier runs a progressively smaller task set:
#   haiku  → full suite         sonnet → dev-tagged subset        opus → disagreement adjudication
_TIER_HAIKU = "haiku"
_TIER_SONNET = "sonnet"
_TIER_OPUS = "opus"

ARMS = ("plain", "codemap")
PARITY_ARMS = tuple(ARM_CONTRACTS)
_RESULT_ARM_WIDTH = max(map(len, (*ARMS, *PARITY_ARMS))) + 1
PARITY_ARM_BY_LEGACY_ARM: dict[str, str] = {}
PARITY_MANIFEST_FILE = Path(__file__).parent / "manifests" / "provider-parity-methodology.json"
LEGACY_EXPERIMENT_REVISION = "legacy-unversioned"
_PARITY_MANIFEST = json.loads(PARITY_MANIFEST_FILE.read_text(encoding="utf-8"))
_PRIMARY_SUITE_MANIFEST = next(
    suite for suite in _PARITY_MANIFEST["suites"] if suite["path"] == "benchmarks/suites/tasks-bench.json"
)
PRIMARY_SUITE_RAW_HASH = hashlib.sha256(TASKS_FILE.read_bytes()).hexdigest()
PRIMARY_SUITE_HASH = semantic_suite_hash(load_task_suite(TASKS_FILE))
_PRIMARY_TASK_IDENTITIES = {
    task["id"]: (task["canonical_task_sha256"], task["prompt_sha256"]) for task in _PRIMARY_SUITE_MANIFEST["tasks"]
}
_PRIMARY_TASK_IDS = tuple(_PRIMARY_TASK_IDENTITIES)
_PARITY_TASK_POLICIES = load_task_policies(PARITY_MANIFEST_FILE)
PARITY_EXPERIMENT_REVISION = next(iter(_PARITY_TASK_POLICIES.values())).experiment_revision


def _arm_orders_by_task(
    tasks: list[dict[str, Any]],
    arms: list[str] | tuple[str, ...],
    *,
    model: str,
    provider_parity: bool,
) -> dict[str, tuple[str, ...]]:
    """Return the execution arm order for each selected task.

    Provider-parity runs use the shared revision-bound coordinate policy with
    Claude's empty reasoning-effort coordinate. Legacy and explicitly
    single-arm runs preserve the caller's declared arm order.

    Args:
        tasks: Selected task dictionaries in execution order.
        arms: Arm labels available to each task.
        model: Claude model stratum used by the shared ordering policy.
        provider_parity: Whether to counterbalance the canonical A/B/C arms.

    Returns:
        Mapping from task ID to its ordered arm tuple.

    Raises:
        ValueError: If provider-parity scheduling does not receive exactly the
            canonical A/B/C arms.
    """
    if not provider_parity:
        declared_order = tuple(arms)
        return {task["id"]: declared_order for task in tasks}
    if set(arms) != set(PARITY_ARMS) or len(arms) != len(PARITY_ARMS):
        raise ValueError("provider-parity scheduling requires the canonical A/B/C arms")
    return {
        task["id"]: deterministic_arm_order(
            PARITY_EXPERIMENT_REVISION,
            "claude",
            model,
            task["id"],
            1,
            reasoning_effort="",
        )
        for task in tasks
    }


# ``--setting-sources project,local`` excludes USER-level config from the benchmark subprocess:
# the caveman plugin, the foundry Re:Anchor rules (box header + ▓ footer), user CLAUDE.md, and
# user hooks. Those shaped the agent's output (markdown/backtick decoration, footer prose) and
# inflated tokens equally on both arms — noise, not signal. scan-query still reaches the codemap
# arm via PATH (_subprocess_env), and the plain arm needs no plugins, so both arms run clean.
# Subscription auth is unaffected (auth is not a setting source). Applied to both arms identically.
# ``--no-session-persistence`` makes every cell non-resumable, preventing conversational state reuse.
_CMD = [
    "claude",
    "-p",
    "--no-session-persistence",
    "--verbose",
    "--output-format",
    "stream-json",
    "--setting-sources",
    "project,local",
]

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
    "A_plain": [
        "--disallowed-tools",
        "Skill,Write,Edit,NotebookEdit,mcp__semble__search,mcp__semble__find_related,Bash(scan-query:*),Bash(python3:*),Bash(python:*)",
    ],
    "B_auto": [
        "--disallowed-tools",
        "Write,Edit,NotebookEdit,mcp__semble__search,mcp__semble__find_related,Bash(python3:*),Bash(python:*)",
    ],
    "C_strict": [
        "--disallowed-tools",
        "Write,Edit,NotebookEdit,mcp__semble__search,mcp__semble__find_related,Bash(python3:*),Bash(python:*)",
    ],
}
_ARM_ALLOWED: dict[str, list[str]] = {
    "codemap": ["--allowedTools", "Bash(scan-query:*)"],
    "B_auto": ["--allowedTools", "Bash(scan-query:*)"],
    "C_strict": ["--allowedTools", "Bash(scan-query:*)"],
}

# ---------------------------------------------------------------------------
# Repo identity — populated from tasks-bench.json header in main()
# ---------------------------------------------------------------------------

_REPO_NAME: str = "the repository"
_REPO_NAMESPACE: list[str] = ["lightning", "examples"]
_REPO_LOCAL_PATH: str | None = None


class SandboxError(Exception):
    """Raised when a patch sandbox cannot be set up or torn down.

    Distinct from a failing test: a SandboxError means the harness could not
    create the worktree, check out the pre-fix commit, or apply the diff — the
    pass/fail signal is unobtainable, not that the patch is semantically wrong.
    """


# pytest's own exit codes. Only 0 (all passed) and 1 (tests failed) carry a test result;
# 2-5 mean pytest could not deliver one (interrupted, internal error, bad usage, nothing
# collected). Reading "not 0" as "tests failed" turned a missing plugin or a bad argument
# into a silent zero for every patch task, because the identical error recurred after the
# patch and was scored as an unfixed failure.
PYTEST_EXIT_ALL_PASSED = 0
PYTEST_EXIT_TESTS_FAILED = 1
_PYTEST_RESULT_EXIT_CODES = frozenset({PYTEST_EXIT_ALL_PASSED, PYTEST_EXIT_TESTS_FAILED})
_PYTEST_EXIT_MEANINGS = {
    2: "interrupted",
    3: "internal error",
    4: "usage error",
    5: "no tests collected",
}


def _pin_pytest_interpreter(argv: list[str]) -> list[str]:
    """Rewrite a leading bare ``pytest`` to ``sys.executable -m pytest``.

    Leaves any other command untouched, including an argv that already names an interpreter explicitly.
    """
    if argv and Path(argv[0]).name in {"pytest", "py.test"}:
        return [sys.executable, "-m", "pytest", *argv[1:]]
    return argv


def _describe_pytest_exit(returncode: int) -> str:
    """Describe one non-result pytest exit code for a sandbox error message."""
    return _PYTEST_EXIT_MEANINGS.get(returncode, "unknown pytest failure")


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
        recall: Optional evaluator-specific recall metric; set by develop_br, rv (symbol tasks), debug, feature, and
            real_issue evaluators. None for count-based evaluators (symbol_extraction, code_quality).
        caller_count_gt: Ground-truth unique caller count; used by caller-list evaluators for both fn_call_graph and
            develop_blast_radius.
        extraction_degraded: True when structured-block scoring could not find a
            labeled answer block (e.g. ``## Files`` / ``## Callers``) and fell back to matching
            against the full output text. Diagnostic only — a degraded match still counts, but the
            flag surfaces that the stricter block-scoped match was unavailable for the run.
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
    extraction_degraded: bool = False
    evaluator_used: str | None = None
    evaluator_version: str | None = None
    extracted_metric: Any = None
    scoring_detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _BenchEvaluationResult(EvaluationResult):
    """Shared evaluation result that retains the Claude-specific score diagnostics."""

    bench_quality: BenchQuality = field(default_factory=BenchQuality)


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
        mutation_evidence: Patch-task lifecycle evidence, including an action or
            cleanup failure, retained separately from the semantic test result.
        self_consistency: True when the task's ground truth is derived from the same
            scan-query index the codemap arm queries (uncovered / broken-xref counts).
            Such runs are still scored but excluded from headline accuracy aggregates
            and reported in a separate self-consistency row.
        repo_sha: Provenance — repo HEAD SHA when the run executed; "unknown" on failure.
        index_sha: Provenance — fingerprint of the index head-meta (see ``_index_sha``).
        task_hash: Provenance — sha256 of the canonical task JSON (see ``_task_hash``).
        suite_hash: Provenance — versioned semantic hash of ordered task contracts.
        suite_raw_hash: Audit-only SHA-256 of the source suite file bytes.
        contaminated: True when the existing contamination or answer-file-read guard excluded the row.
        treatment_adherence: Canonical A/B/C assigned-treatment observation; None for legacy arms.
        resumed: True when this line was reused from a prior results file via ``--resume``
            (the claude subprocess was not re-executed for this tuple).
    """

    arm: str
    task_id: str
    task_type: str
    model: str
    success: bool
    workflow_type: str = ""
    capability_strata: tuple[str, ...] = ()
    quality_components: dict[str, float] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0  # Anthropic's total_cost_usd for this run (current prices); 0.0 if absent
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
    contamination_hits: int = 0  # plain arm only: full-string reads/execs touching the codemap index or binary
    scan_query_subcommands: dict[str, int] = field(default_factory=dict)
    used_batch: bool = False  # codemap arm invoked scan-query `batch` (JSON-array multi-query form) at least once
    turn_count: int = 0
    incomplete: bool = False  # budget exhausted before final answer; excluded from accuracy
    codemap_methods: list[str] = field(default_factory=list)
    codemap_not_covered: list[str] = field(default_factory=list)
    patch_pass: bool | None = None  # patch tasks only: True if failing test passed after applying the agent diff
    mutation_evidence: dict[str, Any] = field(default_factory=dict)
    self_consistency: bool = False  # ground truth derived from the queried index; excluded from headline accuracy
    repo_sha: str = "unknown"  # provenance: repo HEAD when the run executed (git rev-parse; "unknown" on failure)
    index_sha: str = "unknown"  # provenance: fingerprint of the index head-meta (see _index_sha)
    task_hash: str | None = None  # provenance: sha256 of the canonical task JSON (see _task_hash)
    prompt_hash: str | None = None
    prompt_sha256: str | None = None  # compatibility alias for prompt_hash
    suite_hash: str | None = None
    suite_raw_hash: str | None = None
    evaluator_id: str | None = None
    evaluator_hash: str | None = None
    envelope_hash: str | None = None
    arm_contract_hash: str = ""
    experiment_revision: str = LEGACY_EXPERIMENT_REVISION
    parity_arm: str = ""
    compliance: bool | None = None  # C_strict usage evidence, separate from task quality
    contaminated: bool = False
    treatment_adherence: bool | None = None
    oracle_class: str = "unknown"
    headline_eligible_v1: bool = False
    scoreable: bool = False
    resumed: bool = False  # True when this line was reused from a prior results file via ``--resume`` (not re-executed)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

# Shared neutral wrapper used by BOTH arms. Everything here is identical across arms —
# repo framing, cwd note, the single efficiency instruction, and the output-format
# requirements per task type — so the token metric is not confounded by prompt asymmetry
# (only one arm being told to stop early). The arm-specific `{tools_section}` differs solely
# in tool availability and syntax; it carries no answering strategy.
_SHARED_SYSTEM_TEMPLATE = """You are a developer investigating the {repo_name} codebase.
Your current working directory IS the repository root ({repo_path}) — use relative paths (e.g. `find . -name "*.py"`) or absolute paths starting with {repo_path}.

{tools_section}

Answer in as few tool calls as possible; do not re-verify results you already have.

Output format requirements:
For symbol location tasks: report exactly in this format:
  file_path: <path>  start_line: <N>  end_line: <M>
For caller count tasks: report the integer count of unique production callers.
For caller list tasks: report all callers as a list of qualified names (module::function).
For file-identification tasks (debugging, feature scaffolding, issue triage): put the relevant files under a `## Files` heading, one repository-relative path per line (e.g. `pkg/sub/module.py`), not a bare filename.
For symbol-review tasks (undocumented / uncovered symbols): put the symbols under a `## Symbols` heading, one qualified name per line.

Be concise and precise. State the exact values you found (counts, line numbers, module names)."""

# Plain arm — tool availability only; scan-query prohibition preserved verbatim.
_PLAIN_TOOLS = """Answer the question using Grep, Bash, Glob, and Read. Do NOT use the Skill tool.
Do NOT use scan-query or any codemap binary — not via bare command, not via python/python3 path.
Rely on standard filesystem and grep operations only."""

# Codemap arm — tool availability plus scan-query invocation syntax and subcommand
# reference. This is tool documentation only; it prescribes no answering strategy
# (no "call scan-query first", "stop after one call", "trust as authoritative", etc.).
_CODEMAP_TOOLS = """You have the scan-query structural index tool available, in addition to Grep, Bash, Glob, and Read.

scan-query is a Python script on your PATH. Invoke it via Bash:
  scan-query --index {index_path} <subcommand> [args]

Subcommands:
  symbol <name> [--with-imports]         — get source + line range of a symbol by name
  find-symbol <pattern>                  — regex search across all symbol qualified names
  symbols <module>                       — list all symbols in a module
  fn-rdeps <qname> [--exclude-tests]    — callers of a function (`count` = unique callers)
  rdeps <module>                         — modules that import a module
  undocumented [module] [--all]          — symbols lacking docstrings
  uncovered [module] [--top N]           — symbols lacking test coverage
  coupled [--top N]                      — most-coupled modules
  xrefs <module> [--broken]             — Sphinx cross-references
  central [--top N] [--exclude-tests]   — most-imported modules, ranked by importer count
  path <source> <target>                 — a shortest import path between two modules
  fn-blast <qname>                       — transitive caller closure of a function
  diff-impact [--base REF]               — structural blast radius of the current git change set
  batch [FILE|-]                         — run many queries in one process (reads a JSON array of {{cmd, args}})"""

_C_STRICT_USE = "\n\nYou must use Codemap at least once for structural investigation; other tools remain allowed."


def _transport_arm(arm: str) -> str:
    """Return the legacy transport setup that implements one arm label."""
    return {"A_plain": "plain", "B_auto": "codemap", "C_strict": "codemap"}.get(arm, arm)


def _build_system_prompt(arm: str, repo_name: str, repo_path: str, index_path: str) -> str:
    """Assemble the system prompt for one arm from the shared neutral wrapper.

    Both arms receive identical repo framing, the single efficiency instruction, and the
    output-format requirements; only the tool-availability section differs. The plain arm's
    section forbids scan-query; the codemap arm's section documents scan-query syntax and
    subcommands. Keeping every non-tool sentence identical prevents prompt asymmetry from
    confounding the token-ratio headline.

    Args:
        arm: Legacy ``plain``/``codemap`` or canonical A/B/C arm label.
        repo_name: Human-readable repository name for framing.
        repo_path: Absolute path to the repository root (the agent cwd).
        index_path: Path to the pre-built codemap index (codemap arm only; ignored for plain).

    Returns:
        The fully formatted ``--system-prompt`` string for the given arm.

    Examples:
        >>> p = _build_system_prompt("plain", "demo", "/repo", "/x.json")
        >>> "do not re-verify results you already have" in p
        True
        >>> "scan-query" in _build_system_prompt("codemap", "demo", "/repo", "/x.json")
        True
    """
    transport_arm = _transport_arm(arm)
    tools_section = _PLAIN_TOOLS if transport_arm == "plain" else _CODEMAP_TOOLS.format(index_path=index_path)
    if arm == "C_strict":
        tools_section += _C_STRICT_USE
    return _SHARED_SYSTEM_TEMPLATE.format(repo_name=repo_name, repo_path=repo_path, tools_section=tools_section)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_index(repo_path: Path, explicit: Path | None = None) -> Path:
    """Resolve the codemap index path (raises on miss; validates an explicit path).

    Thin adapter over :func:`_bench_common.codemap_discovery.resolve_index_path`: ``-master``/``-main`` stems,
    ``.cache/codemap/`` before ``.cache/scan/``, resolved paths, ``FileNotFoundError`` on a
    miss, and an explicit path must be an existing file.

    Args:
        repo_path: Root of the cloned repository.
        explicit: Explicit ``--index-path`` argument; validated and returned when provided.

    Returns:
        Path to the index JSON file.

    Raises:
        FileNotFoundError: When no index can be found, or an explicit path is not a file.
    """
    return resolve_index_path(repo_path, explicit, strip_suffixes=True, missing="raise", require_explicit_file=True)


def _normalize_external_task(task: dict) -> dict:
    """Normalize one task from a ``--tasks-file`` into the harness task schema.

    External task files use a different schema from tasks-bench.json: ``queries``
    instead of ``expected_queries``, a ``skill`` field instead of ``type``, and
    ``ground_truth_keys`` instead of materialized ``ground_truth`` values (e.g.
    tasks-code.json). Files that DO carry materialized ``ground_truth`` and an
    explicit ``scoreable: true`` (e.g. tasks-debug.json, tasks-feature.json,
    tasks-oss.json) are evaluated normally — their ``scoreable`` field is
    preserved so the registered evaluator runs.

    The original task dict is not mutated; a shallow copy is returned.

    Args:
        task: Raw task dict loaded from a ``--tasks-file``.

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
    """Load and normalize an additional task file passed via ``--tasks-file``.

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


# ---------------------------------------------------------------------------
# Provenance + resume cache (cost lever: ``--resume``)
# ---------------------------------------------------------------------------

# Result-line fields that identify one (task, arm, model) execution against a specific tree + index +
# task definition. Two lines match iff all six agree — the resume key.
_RESUME_KEY_FIELDS = ("task_id", "arm", "model", "repo_sha", "index_sha", "task_hash")


def _repo_sha(repo_path: Path) -> str:
    """Return the repository HEAD SHA, or "unknown" when git is unavailable.

    Args:
        repo_path: Path to the target repository clone.

    Returns:
        The 40-char HEAD SHA, or "unknown" when ``repo_path`` is not a git work tree
        or git is not on PATH.

    Examples:
        >>> _repo_sha(Path("/definitely/not/a/repo/xyzzy"))
        'unknown'
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and sha else "unknown"


def _index_sha(index_path: Path) -> str:
    """Fingerprint the index by hashing its content-defining head-meta fields.

    Only the small :data:`_INDEX_META_KEYS` subset is hashed (``scan_version``,
    ``scanned_at``, ``git_sha``, ``project``, ``scan_root``) — enough to distinguish
    two rebuilds without loading the large ``modules`` body. A missing or unreadable
    index yields "unknown" rather than raising, so provenance degrades gracefully.

    Args:
        index_path: Path to the codemap index JSON file.

    Returns:
        A hex sha256 digest of the canonicalised head-meta subset, or "unknown".

    Examples:
        >>> import json, tempfile
        >>> f = Path(tempfile.mkstemp(suffix=".json")[1])
        >>> _ = f.write_text(json.dumps({"scan_version": 5, "scanned_at": "t", "modules": [1, 2]}))
        >>> len(_index_sha(f))
        64
        >>> _index_sha(Path("/no/such/index.json"))
        'unknown'
    """
    try:
        raw = json.loads(index_path.read_text())
    except (OSError, json.JSONDecodeError):
        return "unknown"
    meta = {k: raw.get(k) for k in _INDEX_META_KEYS}
    payload = json.dumps(meta, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_hash(task: dict) -> str:
    """Return a stable sha256 of the task's JSON definition.

    The task dict is serialised with sorted keys so the digest is invariant to key
    order; any change to prompt, ground truth, or expected queries changes the hash,
    invalidating a stale resume match.

    Args:
        task: A task dict from tasks-bench.json.

    Returns:
        A hex sha256 digest of the canonicalised task JSON.

    Examples:
        >>> _task_hash({"id": "SE-01", "prompt": "p"}) == _task_hash({"prompt": "p", "id": "SE-01"})
        True
    """
    return canonical_task_hash(task)


def _prompt_hash(task: dict) -> str:
    """Return the locked UTF-8 prompt hash for one raw benchmark task.

    Args:
        task: Raw task loaded from a benchmark suite.

    Returns:
        Hexadecimal SHA-256 digest of the task prompt.
    """
    return prompt_hash(task)


def _load_primary_parity_contract() -> tuple[list[dict[str, Any]], Mapping[str, TaskPolicy]]:
    """Load the primary raw suite and its revision-bound shared task policies.

    Returns:
        Raw primary task objects and immutable policies from the locked manifest.
    """
    tasks = load_task_suite(TASKS_FILE)
    if tuple(task["id"] for task in tasks) != _PRIMARY_TASK_IDS:
        raise ValueError("primary suite task order does not match the locked manifest")
    for task in tasks:
        _validate_canonical_task(task)
    if semantic_suite_hash(tasks) != PRIMARY_SUITE_HASH:
        raise ValueError("primary semantic suite hash changed after initialization")
    return tasks, _PARITY_TASK_POLICIES


def _validate_primary_runtime(repo_path: Path, index_path: Path) -> None:
    """Reject a canonical run outside the manifest's locked target and index.

    Args:
        repo_path: Candidate target repository root.
        index_path: Candidate Codemap index for that target.

    Raises:
        ValueError: If the repository, worktree, index bytes, or index metadata differ
            from the locked primary parity inputs.
    """
    target = _PARITY_MANIFEST["target_source"]
    expected_commit = target["commit"]
    if _repo_sha(repo_path) != expected_commit:
        raise ValueError(f"canonical run requires target commit {expected_commit}")
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("canonical run could not verify target worktree cleanliness") from exc
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("canonical run requires a clean target worktree")

    expected_index = _PARITY_MANIFEST["index"]
    if hashlib.sha256(index_path.read_bytes()).hexdigest() != expected_index["raw_sha256"]:
        raise ValueError("canonical run requires the locked index bytes")
    try:
        index_meta = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("canonical run index is not valid JSON") from exc
    for index_field in ("git_sha", "scan_version"):
        if index_meta.get(index_field) != expected_index[index_field]:
            raise ValueError(f"canonical run index {index_field} does not match the locked manifest")


def _validate_canonical_task(task: Mapping[str, Any]) -> None:
    """Reject a known primary task whose locked task or prompt identity changed."""
    task_id = task.get("id")
    expected = _PRIMARY_TASK_IDENTITIES.get(task_id) if isinstance(task_id, str) else None
    if expected is None:
        raise ValueError(f"no locked primary task identity for {task_id!r}")
    task_hash, expected_prompt_hash = expected
    if canonical_task_hash(task) != task_hash:
        raise ValueError(f"task hash mismatch for {task_id!r}")
    if prompt_hash(task) != expected_prompt_hash:
        raise ValueError(f"prompt hash mismatch for {task_id!r}")


def _resume_key(line: dict) -> tuple:
    """Build the resume-match key from a result line (or any dict with the key fields).

    Args:
        line: A dict carrying at least :data:`_RESUME_KEY_FIELDS`.

    Returns:
        A tuple of the six identifying values, in :data:`_RESUME_KEY_FIELDS` order.

    Examples:
        >>> _resume_key({"task_id": "SE-01", "arm": "plain", "model": "haiku",
        ...              "repo_sha": "a", "index_sha": "b", "task_hash": "c"})
        ('SE-01', 'plain', 'haiku', 'a', 'b', 'c')
    """
    return tuple(line.get(f, "unknown") for f in _RESUME_KEY_FIELDS)


def _load_resume_cache(results_dir: Path) -> dict[tuple, dict]:
    """Index every prior result line in *results_dir* by its resume key.

    Scans ``bench-*.jsonl`` files. Later files win on key collision, so a re-run's
    lines shadow an earlier partial run's. Malformed lines are skipped silently.

    Args:
        results_dir: Directory holding prior ``bench-*.jsonl`` result files.

    Returns:
        Mapping from resume key (see :func:`_resume_key`) to the stored line dict.
    """
    cache: dict[tuple, dict] = {}
    if not results_dir.is_dir():
        return cache
    for path in sorted(results_dir.glob("bench-*.jsonl")):
        try:
            text = path.read_text()
        except OSError:
            continue
        for raw in text.splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                line = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(line, dict):
                cache[_resume_key(line)] = line
    return cache


def _run_from_cached(line: dict) -> BenchRun:
    """Reconstruct a :class:`BenchRun` from a cached result line, flagged ``resumed``.

    Only the dataclass fields present in *line* are copied; unknown keys (from a newer
    or older schema) are ignored so a resume across schema drift still yields a usable
    run for reporting. ``quality`` is rebuilt into a :class:`BenchQuality`.

    Args:
        line: A prior result line dict (as written by :func:`_save_results`).

    Returns:
        A BenchRun equal to the cached run with ``resumed=True``.
    """
    field_names = {f.name for f in fields(BenchRun)}
    kwargs = {k: v for k, v in line.items() if k in field_names and k != "quality"}
    q_field_names = {f.name for f in fields(BenchQuality)}
    q_raw = line.get("quality") or {}
    q_kwargs = {k: v for k, v in q_raw.items() if k in q_field_names} if isinstance(q_raw, dict) else {}
    run = BenchRun(**kwargs)
    run.quality = BenchQuality(**q_kwargs)
    run.resumed = True
    return run


# ---------------------------------------------------------------------------
# Cost profiles + tiered protocol (cost levers: ``--profile``, ``--tiered``)
# ---------------------------------------------------------------------------


def _is_dev_task(task: dict) -> bool:
    """Return True when *task* is tagged for the stratified dev subset.

    Args:
        task: A task dict, possibly carrying a ``profiles`` list.

    Returns:
        True when ``_PROFILE_DEV`` is listed in the task's ``profiles`` tag.

    Examples:
        >>> _is_dev_task({"id": "SE-01", "profiles": ["dev"]})
        True
        >>> _is_dev_task({"id": "SE-02"})
        False
    """
    return _PROFILE_DEV in (task.get(_PROFILE_TAG_KEY) or [])


def _is_ri_task(task: dict) -> bool:
    """Return True when *task* belongs to the real_issue (RI) series.

    Args:
        task: A task dict.

    Returns:
        True when the task type is :data:`_RI_TASK_TYPE`.

    Examples:
        >>> _is_ri_task({"id": "RI-01", "type": "real_issue"})
        True
        >>> _is_ri_task({"id": "SE-01", "type": "symbol_extraction"})
        False
    """
    return task.get("type") == _RI_TASK_TYPE


def _gate_ri(tasks: list[dict], profile: Optional[str], explicit: bool) -> list[dict]:
    """Drop RI tasks unless the release profile is active or they were selected explicitly.

    RI runs are ~2M-token outliers; they are excluded from the fast dev / tiered-haiku default
    set. An explicit ``--tasks``/``--task-type`` selection or ``--profile release`` opts them back in.

    Args:
        tasks: The candidate task list after other selection.
        profile: Active profile (``dev``/``release``) or None.
        explicit: True when the caller selected tasks explicitly (``--tasks``/``--task-type``).

    Returns:
        The task list with RI tasks removed when gating applies, else unchanged.

    Examples:
        >>> ri = {"id": "RI-01", "type": "real_issue"}
        >>> se = {"id": "SE-01", "type": "symbol_extraction"}
        >>> [t["id"] for t in _gate_ri([ri, se], None, explicit=False)]
        ['SE-01']
        >>> [t["id"] for t in _gate_ri([ri, se], "release", explicit=False)]
        ['RI-01', 'SE-01']
        >>> [t["id"] for t in _gate_ri([ri, se], None, explicit=True)]
        ['RI-01', 'SE-01']
    """
    if profile == _PROFILE_RELEASE or explicit:
        return tasks
    return [t for t in tasks if not _is_ri_task(t)]


def _apply_profile(tasks: list[dict], profile: Optional[str]) -> list[dict]:
    """Filter *tasks* down to the profile's subset.

    ``dev`` keeps only dev-tagged tasks; ``release`` keeps everything (RI included, gated
    separately). None leaves the list unchanged.

    Args:
        tasks: The candidate task list.
        profile: Active profile (``dev``/``release``) or None.

    Returns:
        The profile-filtered task list.

    Examples:
        >>> tasks = [{"id": "SE-01", "profiles": ["dev"]}, {"id": "SE-02"}]
        >>> [t["id"] for t in _apply_profile(tasks, "dev")]
        ['SE-01']
        >>> [t["id"] for t in _apply_profile(tasks, "release")]
        ['SE-01', 'SE-02']
        >>> [t["id"] for t in _apply_profile(tasks, None)]
        ['SE-01', 'SE-02']
    """
    if profile == _PROFILE_DEV:
        return [t for t in tasks if _is_dev_task(t)]
    return tasks


def _correct_by_task(results_dir: Path, model: str, repo_sha: str, index_sha: str) -> dict[str, bool]:
    """Read prior *model*-tier results and fold each task to a single correctness verdict.

    A task counts as correct for the tier only when every scored arm of that task in the
    matching results (same repo_sha + index_sha) was ``quality.correct``. Used by the tiered
    protocol to find haiku/sonnet disagreements for opus adjudication.

    Args:
        results_dir: Directory holding prior ``bench-*.jsonl`` result files.
        model: Tier model whose lines to read (e.g. ``haiku``).
        repo_sha: Provenance filter — only lines from this repo HEAD count.
        index_sha: Provenance filter — only lines from this index fingerprint count.

    Returns:
        Mapping task_id → conjunctive correctness across scored arms of that tier. Tasks with no
        scored arm are absent from the mapping.
    """
    scored: dict[str, list[bool]] = defaultdict(list)
    for line in _load_resume_cache(results_dir).values():
        if line.get("model") != model or line.get("repo_sha") != repo_sha or line.get("index_sha") != index_sha:
            continue
        quality = line.get("quality") or {}
        if not quality.get("scored") or quality.get("extraction_failed") or line.get("incomplete"):
            continue
        scored[line["task_id"]].append(bool(quality.get("correct")))
    return {tid: all(verdicts) for tid, verdicts in scored.items() if verdicts}


def _tiered_tasks(tasks: list[dict], model: str, results_dir: Path, repo_sha: str, index_sha: str) -> list[dict]:
    """Select the task subset for one tier of the tiered protocol.

    Sequencing (three invocations, one per model):

      * ``haiku``  → the full suite (RI gated separately by profile).
      * ``sonnet`` → the dev-tagged subset only.
      * ``opus``   → only tasks where the haiku and sonnet verdicts disagree (adjudication);
        requires both prior tiers' results in *results_dir*.

    Args:
        tasks: The candidate task list (already profile/RI filtered for the caller).
        model: The tier model being run.
        results_dir: Directory holding prior-tier ``bench-*.jsonl`` result files.
        repo_sha: Provenance filter for reading prior-tier verdicts.
        index_sha: Provenance filter for reading prior-tier verdicts.

    Returns:
        The task subset for this tier. Opus with no disagreements (or missing prior results)
        yields an empty list.
    """
    if model == _TIER_SONNET:
        return [t for t in tasks if _is_dev_task(t)]
    if model == _TIER_OPUS:
        haiku = _correct_by_task(results_dir, _TIER_HAIKU, repo_sha, index_sha)
        sonnet = _correct_by_task(results_dir, _TIER_SONNET, repo_sha, index_sha)
        disagree = {tid for tid in haiku.keys() & sonnet.keys() if haiku[tid] != sonnet[tid]}
        return [t for t in tasks if t["id"] in disagree]
    return tasks


@dataclass
class TaskSelection:
    """Inputs that determine which tasks run, bundled to keep helper signatures small.

    Attributes:
        all_tasks: Every loaded task (bench + any ``--tasks-file`` + patch).
        ids: Explicit ``--tasks`` id set, or None.
        task_type: Explicit ``--task-type`` filter, or None.
        run_all: True when ``--all`` was passed.
        external_ids: IDs supplied via ``--tasks-file``.
        patch_ids: IDs supplied via ``--patch``.
        profile: Active cost profile (``dev``/``release``) or None.
        tiered: True when the tiered protocol is active.
        model: Short model tier name (drives the tiered subset).
    """

    all_tasks: list[dict]
    ids: Optional[set[str]]
    task_type: Optional[str]
    run_all: bool
    external_ids: set[str]
    patch_ids: set[str]
    profile: Optional[str]
    tiered: bool
    model: str


# gt_is_pending comes from benchmark_paths (shared with generate-tasks-bench).


def _base_task_list(sel: TaskSelection) -> Optional[list[dict]]:
    """Apply the explicit/type/subset selection that predates the cost-lever flags.

    Args:
        sel: The bundled selection inputs.

    Returns:
        The base task list, or None when no selection was specified (caller reports the error).
        An empty list means a selector matched nothing.
    """
    if sel.ids is not None:
        return [t for t in sel.all_tasks if t["id"] in sel.ids]
    if sel.task_type:
        return [t for t in sel.all_tasks if t["type"] == sel.task_type]
    if sel.run_all:
        return list(sel.all_tasks)
    subset = sel.external_ids | sel.patch_ids
    if subset:
        return [t for t in sel.all_tasks if t["id"] in subset]
    return None


def _select_tasks(sel: TaskSelection, results_dir: Path, repo_sha: str, index_sha: str) -> Optional[list[dict]]:
    """Resolve the final task list from base selection + profile + RI gating + tiered protocol.

    Order: base selection → profile subset → RI gating → tiered subset. The tiered step reads
    prior-tier results (for opus adjudication) via *results_dir* + provenance filters.

    Args:
        sel: The bundled selection inputs.
        results_dir: Directory holding prior ``bench-*.jsonl`` result files (tiered opus tier).
        repo_sha: Provenance filter for reading prior-tier verdicts.
        index_sha: Provenance filter for reading prior-tier verdicts.

    Returns:
        The final task list, None when no base selector was given, or an empty list when a
        selector matched nothing.
    """
    base = _base_task_list(sel)
    if base is None:
        return None
    explicit = sel.ids is not None or bool(sel.task_type)
    selected = _apply_profile(base, sel.profile)
    selected = _gate_ri(selected, sel.profile, explicit)
    if sel.tiered:
        selected = _tiered_tasks(selected, sel.model, results_dir, repo_sha, index_sha)
    return selected


def _subprocess_env(index_path: Path) -> dict[str, str]:
    """Build subprocess environment with codemap bin dir and CODEMAP_INDEX set.

    Args:
        index_path: Path to the pre-built codemap index.

    Returns:
        Environment dict for subprocess.Popen.
    """
    plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "codemap-py"
    env = codemap_bin_on_path(os.environ.copy(), plugin_root)
    env["CODEMAP_INDEX"] = str(index_path)
    env["CODEMAP_ENABLED"] = "true"
    env["CODEMAP_LOGGING"] = "false"
    return env


# Markers that betray plain-arm access to the codemap index or binary. Matched against
# the FULL untruncated tool input (Bash command / Read path) in _handle, not the truncated tool_log:
# the prebuilt index at .cache/{codemap,scan}/*.json holds every structural answer, so a raw Read/cat
# of it lets the control arm self-serve answers without ever calling scan-query.
_CONTAMINATION_MARKERS: tuple[str, ...] = ("scan-query", "codemap-py/bin", ".cache/codemap", ".cache/scan")


def _is_contaminating_access(text: str) -> bool:
    """Return True when *text* touches the codemap index or binary.

    Backslash path separators are normalised to forward slashes before matching, so a
    Windows-style ``.cache\\codemap\\proj.json`` path — how a real Read ``file_path``
    or Bash argument reports it on Windows — still matches the forward-slash
    :data:`_CONTAMINATION_MARKERS`.

    Args:
        text: A full Bash command string or a Read ``file_path`` (untruncated).

    Returns:
        True when any :data:`_CONTAMINATION_MARKERS` substring is present.

    Examples:
        >>> _is_contaminating_access("cat /repo/.cache/codemap/proj.json")
        True
        >>> _is_contaminating_access("grep -rn Trainer src/")
        False
    """
    return any(marker in text.replace("\\", "/") for marker in _CONTAMINATION_MARKERS)


# Subcommands recognised by scan-query (mirrors the _CODEMAP_TOOLS help block).
# ``central``, ``path``, and ``fn-blast`` back the graph series; ``diff-impact`` backs the
# diff-impact series; ``batch`` is the JSON-array multi-query form (measured, not forced).
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
        "central",
        "path",
        "fn-blast",
        "diff-impact",
        "batch",
    }
)

# Batch mode reads a JSON array of ``{"cmd": ..., "args": [...]}`` items and runs each in one process.
# When the codemap arm uses batch, each inner item's ``cmd`` must still be attributed to its own
# subcommand counter (so batched `fn-rdeps` counts as an `fn-rdeps` use, not vanishing into `batch`).
# The array may be passed as an inline heredoc/echo pipe or a file argument.
_BATCH_SUBCOMMAND = "batch"


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
    # Locate the scan-query executable token (may be a path like .../bin/scan-query).
    start = None
    allowed_prefix = {"env", "command", "time"}
    for i, tok in enumerate(tokens):
        if tok == "scan-query" or tok.endswith("/scan-query"):
            if any(prev not in allowed_prefix and "=" not in prev for prev in tokens[:i]):
                continue
            start = i + 1
            break
    if start is None:
        return None
    i = start
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-"):
            if tok == "--index" and i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                i += 2
            elif tok.startswith("--index="):
                i += 1
            else:
                return None
            continue
        return tok if tok in _SCAN_QUERY_SUBCOMMANDS else None
    return None


# Match a JSON array embedded anywhere in a Bash command line (heredoc body, echo/printf pipe, or an
# inline single-quoted argument). Non-greedy across the whole command; the outermost `[ ... ]` pair is
# taken and re-validated as JSON before any item is trusted, so a stray bracket in prose is rejected.
_BATCH_ARRAY_RE = re.compile(r"\[\s*\{.*\}\s*\]", re.DOTALL)


def _parse_batch_subcommands(command: str) -> list[str]:
    """Return the inner subcommand names of a ``scan-query batch`` invocation.

    Batch mode reads a JSON array of ``{"cmd": <name>, "args": [...]}`` items. Each inner ``cmd`` is a
    real subcommand use that must be attributed to its own counter — a batched ``fn-rdeps`` counts as an
    ``fn-rdeps`` use, not as an opaque ``batch``. Only the ``cmd`` value of each object is extracted;
    unknown ``cmd`` values (not in :data:`_SCAN_QUERY_SUBCOMMANDS`) are dropped. Returns an empty list
    when the command is not a batch invocation or carries no decodable JSON array.

    Args:
        command: Raw Bash command string (as recorded in tool input).

    Returns:
        List of recognised inner subcommand names, in array order (duplicates preserved).

    Examples:
        >>> _parse_batch_subcommands(
        ...     'scan-query batch <<< \\'[{"cmd": "fn-rdeps", "args": ["m::f"]}, {"cmd": "rdeps", "args": ["m"]}]\\''
        ... )
        ['fn-rdeps', 'rdeps']
        >>> _parse_batch_subcommands("scan-query symbol Trainer")
        []
        >>> _parse_batch_subcommands('scan-query batch <<< \\'[{"cmd": "bogus"}]\\'')
        []
    """
    if _parse_scan_query_subcommand(command) != _BATCH_SUBCOMMAND:
        return []
    match = _BATCH_ARRAY_RE.search(command)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    subs: list[str] = []
    for item in items:
        if isinstance(item, dict):
            cmd = item.get("cmd")
            if isinstance(cmd, str) and cmd in _SCAN_QUERY_SUBCOMMANDS:
                subs.append(cmd)
    return subs


def _embedded_json_objects(raw: str) -> list[dict]:
    """Return every JSON object embedded in *raw*, tolerating surrounding prose or trailing text.

    A scan-query ``tool_result`` is sometimes wrapped in a prose preamble, truncated, or
    concatenated with other output, so ``json.loads`` over the whole string raises and its index
    metadata is silently lost (empirically ~16/17 codemap runs recorded no ``index.method`` despite
    running ``rdeps``, producing a false "index-lookup only" signal). This scans for each ``{`` and
    uses :meth:`json.JSONDecoder.raw_decode` — which decodes one value and ignores whatever follows —
    to recover each object regardless of what surrounds it.

    Args:
        raw: A ``tool_result`` text payload (pure JSON, prose+JSON, or concatenated objects).

    Returns:
        Each successfully decoded top-level JSON object, in order of appearance (non-object
        JSON values such as bare arrays or numbers are skipped).

    Examples:
        >>> _embedded_json_objects('prefix {"index": {"method": "rdeps"}} tail')
        [{'index': {'method': 'rdeps'}}]
        >>> _embedded_json_objects('{"a": 1}{"b": 2}')
        [{'a': 1}, {'b': 2}]
        >>> _embedded_json_objects('no json here')
        []
    """
    decoder = json.JSONDecoder()
    objects: list[dict] = []
    i, n = 0, len(raw)
    while i < n:
        if raw[i] != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            i += 1
            continue
        if isinstance(obj, dict):
            objects.append(obj)
        i = max(end, i + 1)  # skip past the decoded span so inner braces are not re-scanned
    return objects


# Legacy per-task turn cap. Canonical provider-parity arms rely exclusively on the shared
# wall-clock budget because Codex has no equivalent public turn-cap control. The old structural
# experiment keeps its existing task-sensitive cap unchanged for historical comparability.
_TURN_FLOOR_DEFAULT = 40
_TURN_FLOOR_CALLER = 80
_TURN_PER_CALLER = 4
_CALLER_TASK_TYPES: frozenset[str] = frozenset({"develop_blast_radius", "fn_call_graph"})


def _max_turns_for_task(task: dict) -> int:
    """Return the legacy per-task ``--max-turns`` cap.

    Caller-enumeration tasks (``develop_blast_radius``, ``fn_call_graph``) scale the cap with the
    ground-truth unique-caller count so a task with many callers gets more head-room; every other
    task type uses a flat floor. The value does not depend on the arm — the plain and the codemap arm
    receive the same cap for a given task. Canonical provider-parity runs omit this CLI flag and
    instead use their shared wall-clock budget.

    Args:
        task: Task dict from tasks-bench.json; reads ``type`` and ``ground_truth.unique_caller_count``.

    Returns:
        The max-turns cap for the task.

    Examples:
        >>> _max_turns_for_task({"type": "symbol_extraction"})
        40
        >>> _max_turns_for_task({"type": "develop_blast_radius", "ground_truth": {"unique_caller_count": 30}})
        120
        >>> _max_turns_for_task({"type": "fn_call_graph", "ground_truth": {"unique_caller_count": 5}})
        80
    """
    if task.get("type") in _CALLER_TASK_TYPES:
        caller_count = task.get("ground_truth", {}).get("unique_caller_count", 0)
        return max(_TURN_FLOOR_CALLER, caller_count * _TURN_PER_CALLER)
    return _TURN_FLOOR_DEFAULT


# ---------------------------------------------------------------------------
# Quality evaluators — extract key metric from model output text
# ---------------------------------------------------------------------------

_EVAL_VER_NAME_RECALL = "v5"  # _evaluate_develop_br (v5: drop .md file-dump; tighten precision for fuzzy tiers)
_EVAL_VER_SYMBOL = "v2"  # _evaluate_symbol — accepts conventional source-location ranges
_EVAL_VER_REVIEW = "v7"  # _evaluate_rv — natural direct-import and uncovered-count grammar
_EVAL_VER_OSS = "v7"  # _evaluate_oss — explicit label-first count grammar for required AST components
_EVAL_VER_DEBUG = "v2"  # _evaluate_debug — v2: structured-block + stem-blocklist matching
_EVAL_VER_FEATURE = "v4"  # _evaluate_feature — accepts one terminal sentence period after the exact entry point
_EVAL_VER_REAL_ISSUE = "v2"  # _evaluate_real_issue — v2: path-with-parent matching in answer block

# Substring-inflation guard. Common single-token file/symbol stems that saturate any
# discussion of the target repo (a bare mention of `trainer` in prose is a free hit). These must
# appear as a QUALIFIED reference — pathed (`.../trainer`), dotted (`x.trainer`), or with a `.py`
# suffix — to count; a bare word never does. Applied symmetrically to both arms (scoring is arm-agnostic).
_STEM_BLOCKLIST: frozenset[str] = frozenset({"trainer", "utils", "core", "types", "base"})

# Section headings that mark the start of a structured answer block. Matching is restricted to text
# AT OR AFTER the earliest such heading so exploration prose before the final answer cannot score.
_ANSWER_LABELS_FILES: tuple[str, ...] = ("files", "root cause", "root-cause", "answer")
_ANSWER_LABELS_SYMBOLS: tuple[str, ...] = ("symbols", "undocumented", "uncovered", "answer")
# Conclusion-only headings for numeric/count answers. Deliberately generic (no early working-section
# nouns like "importers"/"callers") so _answer_region anchors on the FINAL answer, not an exploratory
# heading — a stray count in exploration ("0 symbols of its own") must never outrank the conclusion.
_ANSWER_LABELS_COUNT: tuple[str, ...] = ("answer", "conclusion", "summary", "result", "total")


def _answer_region(output_text: str, labels: tuple[str, ...]) -> tuple[str, bool]:
    """Return the structured answer block of *output_text*, or the full text when none is present.

    Locates the earliest line that is a bare answer heading — a markdown header (``## Files``) or a
    labelled line (``Files:`` / ``**Files**``) whose only content is one of *labels* — and returns
    everything from there to the end. When no such heading exists the full text is returned with a
    ``degraded`` flag so callers can record that block-scoped matching was unavailable.

    Args:
        output_text: The agent's full response text.
        labels: Candidate heading labels for this evaluator family (case-insensitive).

    Returns:
        ``(region, degraded)`` — ``region`` is the answer block (or full text); ``degraded`` is True
        only when no heading matched and the full text was used as a fallback.

    Examples:
        >>> _answer_region("exploring trainer\\n## Files\\npkg/mod.py\\n", ("files",))
        ('## Files\\npkg/mod.py\\n', False)
        >>> region, degraded = _answer_region("just prose about trainer", ("files",))
        >>> degraded
        True
    """
    earliest: Optional[int] = None
    for label in labels:
        pat = rf"(?im)^[ \t]*(?:#{{1,6}}[ \t]*)?\*{{0,2}}[ \t]*{re.escape(label)}[ \t]*:?[ \t]*\*{{0,2}}[ \t]*$"
        m = re.search(pat, output_text)
        if m and (earliest is None or m.start() < earliest):
            earliest = m.start()
    if earliest is None:
        return output_text, True
    return output_text[earliest:], False


def _stem_matches(stem: str, region: str) -> bool:
    """Return True when *stem* is present in *region* as a countable reference.

    Blocklisted ultra-common stems (:data:`_STEM_BLOCKLIST`) count only as a qualified reference —
    preceded by ``/`` or ``.`` (a path or dotted name) or carrying a ``.py`` suffix — never as a bare
    word. All other stems count on a plain word-boundary match.

    Args:
        stem: File stem or symbol short name to look for.
        region: Text to search (typically the structured answer block).

    Returns:
        True when a countable reference to *stem* is found.

    Examples:
        >>> _stem_matches("trainer", "the trainer orchestrates the loop")
        False
        >>> _stem_matches("trainer", "see trainer.py for details")
        True
        >>> _stem_matches("fit_loop", "the fit_loop advances")
        True
    """
    esc = re.escape(stem)
    if stem in _STEM_BLOCKLIST:
        return bool(
            re.search(r"[/.]" + esc + r"\b", region, re.IGNORECASE)
            or re.search(r"\b" + esc + r"\.py\b", region, re.IGNORECASE)
        )
    return bool(re.search(r"\b" + esc + r"\b", region, re.IGNORECASE))


def _ri_file_matches(file_path: str, region: str) -> bool:
    """Return True when *file_path* is referenced in *region* by a pathed form.

    A real_issue file counts only via its full repository-relative path or a path-with-parent form
    (``connectors/logger_connector``) — never a bare basename stem, which for common names (``trainer``)
    is a near-free hit. Leading ``src/`` layout prefixes and the ``.py`` suffix are treated as optional.

    Args:
        file_path: Repository-relative ground-truth path (e.g. ``src/pkg/connectors/logger_connector.py``).
        region: Text to search (typically the structured answer block).

    Returns:
        True when any pathed candidate for *file_path* appears in *region*.

    Examples:
        >>> _ri_file_matches("src/pkg/connectors/logger_connector.py", "edit connectors/logger_connector")
        True
        >>> _ri_file_matches("src/pkg/trainer.py", "the trainer handles this")
        False
    """
    parts = file_path.split("/")
    stem = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    candidates: set[str] = {file_path}
    if file_path.endswith(".py"):
        candidates.add(file_path[:-3])
    if file_path.startswith("src/"):
        candidates.add(file_path[4:])
        if file_path.endswith(".py"):
            candidates.add(file_path[4:-3])
    if len(parts) >= 2:
        candidates.add(f"{parts[-2]}/{parts[-1]}")
        candidates.add(f"{parts[-2]}/{stem}")
    return any(re.search(r"(?<![\w/.-])" + re.escape(cand) + r"(?![\w/.-])", region) for cand in candidates)


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
    text = re.sub(r"[*`]+", " ", text)  # strip bold (*) and inline-code (`) markers before matching
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except (IndexError, ValueError):
                continue
    return None


def _extract_count_answer_first(
    output_text: str, patterns: list[str], labels: tuple[str, ...] = _ANSWER_LABELS_COUNT
) -> Optional[int]:
    """Extract an integer count, preferring the structured answer/conclusion region.

    :func:`_extract_int` returns the first pattern that matches *anywhere*, so on verbose codemap
    output a stray number in exploration ("0 symbols of its own") can outrank the real answer
    ("65 importers"). This scopes extraction to the answer region (:func:`_answer_region`) first and
    only falls back to the full text when that region yields no count — so it never reduces
    extraction success versus a full-text scan, it only prefers the conclusion when one carries a
    count. When no answer heading is present the region *is* the full text (``degraded``), so the
    single region scan already covers everything and the fallback is skipped.

    Args:
        output_text: The agent's full response text.
        patterns: Ordered regex patterns passed through to :func:`_extract_int`.
        labels: Answer-heading labels for :func:`_answer_region` (conclusion markers by default).

    Returns:
        The extracted integer, or ``None`` when neither the answer region nor the full text matches.

    Examples:
        >>> pats = [r"(\\d+)\\s+(?:symbol|method)", r"(\\d+)\\s+importers?"]
        >>> _extract_count_answer_first("has 0 symbols\\n## Answer\\n65 importers\\n", pats)
        65
        >>> _extract_count_answer_first("no answer heading, just 7 methods here", pats)
        7
        >>> _extract_count_answer_first("nothing numeric to find", pats)
    """
    region, degraded = _answer_region(output_text, labels)
    got = _extract_int(region, patterns)
    if got is None and not degraded:
        got = _extract_int(output_text, patterns)
    return got


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
    if got is None or not isinstance(expected, (int, float)):
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


def _score_required_components(
    *,
    count_components: list[tuple[str, Any, Optional[int]]],
    symbol_components: list[tuple[str, list[str], str, bool]],
    evaluator_used: str,
    evaluator_version: str,
    oracle_views: Mapping[str, Any] | None = None,
    check: str | None = None,
) -> BenchQuality:
    """Score every required count or symbol answer and average their fitness.

    A required count contributes bounded relative-error fitness while its documented 10% tolerance remains the binary
    correctness gate. A required symbol set contributes its recall. A task is correct only when every component meets
    its own gate; a missing component is an extraction failure.
    """
    components: dict[str, dict[str, Any]] = {}
    primary_expected: Any = None
    primary_got: Any = None

    for name, expected, got in count_components:
        correct = _int_close(got, expected, tolerance=0.10)
        relative_error: float | None = None
        fitness = 0.0
        if got is not None and isinstance(expected, (int, float)) and not isinstance(expected, bool):
            relative_error = abs(got - expected) / max(abs(expected), 1)
            fitness = max(0.0, 1.0 - relative_error)
        components[name] = {
            "kind": "count",
            "expected": expected,
            "got": got,
            "threshold": 0.10,
            "fitness": fitness,
            "correct": correct,
            "extraction_failed": got is None,
            "relative_error": relative_error,
            "method": "bounded_relative_error",
        }
        if primary_expected is None:
            primary_expected, primary_got = expected, got

    for name, expected_symbols, region, degraded in symbol_components:
        found = sum(1 for symbol in expected_symbols if _stem_matches(symbol.split(".")[-1], region))
        recall = found / max(len(expected_symbols), 1)
        correct = recall >= 0.70
        components[name] = {
            "kind": "symbols",
            "expected": len(expected_symbols),
            "got": found,
            "threshold": 0.70,
            "fitness": recall,
            "correct": correct,
            "extraction_failed": found == 0,
            "extraction_degraded": degraded,
        }
        if primary_expected is None:
            primary_expected, primary_got = len(expected_symbols), found

    if not components:
        return BenchQuality(scored=False)

    details: dict[str, Any] = {
        "metric_expected": primary_expected,
        "metric_got": primary_got,
        "method": "required_component_mean",
        "components": components,
        "fitness_aggregation": "unweighted mean of every required component",
    }
    if check is not None:
        details["check"] = check
    if oracle_views is not None:
        details["oracle_views"] = dict(oracle_views)

    component_values = [float(component["fitness"]) for component in components.values()]
    return BenchQuality(
        scored=True,
        correct=all(bool(component["correct"]) for component in components.values()),
        metric_expected=primary_expected,
        metric_got=primary_got,
        recall=round(sum(component_values) / len(component_values), 3),
        extraction_failed=any(bool(component["extraction_failed"]) for component in components.values()),
        extraction_degraded=any(bool(component.get("extraction_degraded")) for component in components.values()),
        evaluator_used=evaluator_used,
        evaluator_version=evaluator_version,
        extracted_metric={name: component["got"] for name, component in components.items()},
        scoring_detail=details,
    )


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

    # Strip markdown bold (*) and inline-code (`) markers — but NOT underscores (would destroy the
    # start_line key). Agents routinely format the value as `start_line: ``213`` ` (backticks), which
    # left a backtick between the colon and the first digit and defeated every pattern below → !parse.
    cleaned = re.sub(r"[*`]+", "", output_text)

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

    # 3. Compact ``path.py:N-M`` source locations are common final answers and carry an
    # unambiguous source-file anchor; accept them before the deliberately broader prose range.
    if got_start is None:
        m = re.search(r"(?:^|\s)[\w./-]+\.py:(\d+)\s*[-–]\s*\d+\b", cleaned)
        if m:
            got_start = int(m.group(1))

    # 4. Explicit range "Lines N-M" → first number is start (fallback; can match import ranges)
    if got_start is None:
        m = re.search(r"\blines?\W+(\d+)\s*[-–]\s*\d+", cleaned, re.IGNORECASE)
        if m:
            got_start = int(m.group(1))

    # 5. "line N" near the short symbol name (last component of qualified name)
    if got_start is None:
        short = re.escape(qname.split(".")[-1])
        m = re.search(r"line\s+(\d+).*?" + short, cleaned, re.IGNORECASE | re.DOTALL)
        if m:
            got_start = int(m.group(1))

    correct = got_start is not None and abs(got_start - expected_start) <= 5
    # metric_got/metric_expected are raw line numbers (diagnostics in scoring_detail);
    # the recall column derives from `correct` via _effective_recall, not this ratio.
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
    """Evaluate every required review subanswer with continuous component fitness."""
    sub_questions = task.get("sub_questions", [])
    if not sub_questions:
        return BenchQuality(scored=False)
    if not isinstance(sub_questions, list):
        raise ValueError("review sub-questions must be a list")

    _count_patterns = [
        r"(\d+)\s+undocumented",
        r"(\d+)\s+(?:unique\s+)?(?:public\s+)?symbols?(?:\s+are)?\s+uncovered",
        r"(\d+)\s+uncovered",
        r"(\d+)\s+reverse\s+dependenc(?:y|ies)",
        r"(\d+)\s+(?:distinct|unique)\s+production\s+functions?",
        r"(\d+)\s+(?:distinct|unique)\s+production\s+callers?",
        r"(\d+)\s+(?:function|symbol|method|class)",
        r"(\d+)\s+(?:production\s+)?call\s*site",
        r"(\d+)\s+(?:production\s+)?calls?\b",
        r"(\d+)\s+(?:total\s+)?(?:unique\s+)?importers?",  # "61 total importers", "56 importers"
        r"(\d+)\s+(?:total\s+)?modules?\s+including\s+\d+\s+test\s+modules?",
        r"(\d+)\s+(?:unique\s+)?modules?\s+(?:directly\s+)?(?:import|depend)",  # "N modules [directly] import"
        r"(\d+)\s+total\s+importer",
        r"total[:\s]+(\d+)",
        r"count[:\s]+(\d+)",
        r"found\s+(\d+)",
    ]

    validated_questions: list[tuple[str, str, Mapping[str, Any]]] = []
    for index, sub_question in enumerate(sub_questions, start=1):
        if not isinstance(sub_question, Mapping):
            raise ValueError(f"review sub-question {index} must be an object")
        question_id = sub_question.get("id")
        match = sub_question.get("match")
        ground_truth = sub_question.get("ground_truth")
        if not isinstance(question_id, str) or not question_id:
            raise ValueError(f"review sub-question {index} requires a non-empty id")
        if not isinstance(ground_truth, Mapping):
            raise ValueError(f"review sub-question {question_id!r} requires ground_truth")
        if match == "integer_extract":
            expected_count = ground_truth.get("count")
            if isinstance(expected_count, bool) or not isinstance(expected_count, int) or expected_count < 0:
                raise ValueError(f"review sub-question {question_id!r} requires a non-negative integer count")
        elif match == "symbol_name_set":
            expected_symbols = ground_truth.get("symbols")
            if not isinstance(expected_symbols, list) or not all(
                isinstance(symbol, str) for symbol in expected_symbols
            ):
                raise ValueError(f"review sub-question {question_id!r} requires a symbol string list")
        else:
            raise ValueError(f"review sub-question {question_id!r} has unsupported match {match!r}")
        validated_questions.append((question_id, match, ground_truth))

    count_question_count = sum(match == "integer_extract" for _, match, _ in validated_questions)
    if count_question_count > 1:
        raise ValueError("review task has multiple required count components without answer scoping")

    count_components: list[tuple[str, Any, Optional[int]]] = []
    symbol_components: list[tuple[str, list[str], str, bool]] = []
    symbol_region, symbol_degraded = _answer_region(output_text, _ANSWER_LABELS_SYMBOLS)
    for question_id, match, ground_truth in validated_questions:
        if match == "integer_extract":
            got_count = _extract_count_answer_first(output_text, _count_patterns)
            if got_count is None:
                list_items = re.findall(r"^\s*[-*•]\s+\S", output_text, re.MULTILINE)
                if list_items:
                    got_count = len(list_items)
            count_components.append((f"{question_id}.count", ground_truth["count"], got_count))
        else:
            expected_symbols = ground_truth["symbols"]
            symbol_components.append((f"{question_id}.symbols", expected_symbols, symbol_region, symbol_degraded))

    oracle_views = task.get("ground_truth", {}).get("oracle_views")
    return _score_required_components(
        count_components=count_components,
        symbol_components=symbol_components,
        evaluator_used="_evaluate_rv",
        evaluator_version=_EVAL_VER_REVIEW,
        oracle_views=oracle_views if isinstance(oracle_views, Mapping) else None,
    )


def _extract_coupled_ranking(output_text: str, metric_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Extract numbered coupled-ranking rows from bullet or Markdown-table answers."""
    rows_by_rank: dict[int, dict[str, Any]] = {}
    for line in output_text.splitlines():
        rank_match = re.match(r"^\s*\|?\s*(\d+)\s*(?:[.)]|\|)\s*(.*)$", line)
        if rank_match is None:
            continue
        rank = int(rank_match.group(1))
        body = rank_match.group(2)
        name_match = re.search(r"`([^`]+)`|\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b", body)
        if name_match is None:
            continue
        row: dict[str, Any] = {"name": name_match.group(1) or name_match.group(2)}
        for metric_field in metric_fields:
            count_match = re.search(rf"\b{re.escape(metric_field)}\s*[:=]\s*(\d+)", body)
            if count_match is not None:
                row[metric_field] = int(count_match.group(1))
        if len(metric_fields) == 1 and metric_fields[0] not in row:
            count_values = re.findall(r"\b\d+\b", body)
            if not count_values:
                continue
            row[metric_fields[0]] = int(count_values[-1])
        if any(metric_field not in row for metric_field in metric_fields):
            continue
        rows_by_rank.setdefault(rank, row)
    return [rows_by_rank[rank] for rank in sorted(rows_by_rank)]


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
        expected_ranking = gt.get("top_modules")
        if isinstance(expected_ranking, list) and expected_ranking:
            metric_fields = ("dep_count",)
            if not all(isinstance(row, Mapping) and "name" in row and "dep_count" in row for row in expected_ranking):
                raise ValueError("coupled top_modules requires name and dep_count fields")
            expected = [
                {"name": row.get("name"), **{field: row.get(field) for field in metric_fields}}
                for row in expected_ranking
                if isinstance(row, Mapping)
            ]
            got = _extract_coupled_ranking(output_text, metric_fields)
            correct = got == expected
            return BenchQuality(
                scored=True,
                correct=correct,
                metric_expected=expected,
                metric_got=got,
                extraction_failed=not got,
                evaluator_used="_evaluate_oss",
                evaluator_version=_EVAL_VER_OSS,
                extracted_metric=got,
                scoring_detail={
                    "metric_expected": expected,
                    "metric_got": got,
                    "threshold": 0,
                    "method": "ordered_coupled_ranking",
                    "metric_fields": metric_fields,
                },
            )
        expected = gt.get("top_dep_count", 0)
        # Anchor to number immediately before "dep" — avoids forward-scan into summary totals.
        # dep_count field name first (structured output), then "N dep*" literal.
        # Answer-region-scoped (count-fragility fix): prefer the count in the conclusion over a
        # stray dep count in exploratory prose; falls back to full text when the region has none.
        got = _extract_count_answer_first(
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
                got_prose = _extract_count_answer_first(output_text, [r"(\d+)\s+broken", r"broken[:\s]+(\d+)"])
                got = got_prose
        else:
            got = _extract_count_answer_first(output_text, [r"(\d+)\s+broken", r"broken[:\s]+(\d+)", r"(\d+)\s+xref"])
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

    if check == "combined_health":
        undocumented_expected = gt.get("undocumented_count", 0)
        uncovered_expected = gt.get("uncovered_count", 0)
        undocumented_got = _extract_count_answer_first(
            output_text,
            [r"undocumented[\s_-]+count\s*[:=]\s*(\d+)"],
        )
        uncovered_got = _extract_count_answer_first(
            output_text,
            [r"uncovered[\s_-]+count\s*[:=]\s*(\d+)"],
        )
        return _score_required_components(
            count_components=[
                ("undocumented_count", undocumented_expected, undocumented_got),
                ("uncovered_count", uncovered_expected, uncovered_got),
            ],
            symbol_components=[],
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            check=check,
        )

    if check == "undocumented":
        oracle_views = gt.get("oracle_views")
        independent_ast = oracle_views.get("independent_ast", {}) if isinstance(oracle_views, Mapping) else {}
        expected = independent_ast.get("count", gt.get("undocumented_count", 0))
        required_components = gt.get("required_answer_components", [])
        count_patterns = [
            r"independent[\s_-]+ast[\s_-]+count\s*[:=]\s*(\d+)",
        ]
        if "independent_ast_count" in required_components:
            count_patterns.extend(
                [
                    r"independent\s+ast(?:\s+view)?\s*[:=]\s*(\d+)\s+(?:unique\s+)?(?:qualified\s+)?(?:names|symbols)\b",
                ]
            )
        if "independent_ast_count" not in required_components:
            count_patterns.extend(
                [
                    r"independent\s+AST(?:\s+view)?\s*[:—–-]?\s*(\d+)",
                    r"(\d+)\s+unique\s+(?:undocumented\s+)?(?:qualified\s+)?(?:names|symbols)",
                    r"(\d+)\s+undocumented",
                    r"undocumented[:\s]+(\d+)",
                    r"undocumented[^:\n]*[:\s—–]+(\d+)",
                    r"(\d+)\s+(?:public\s+)?symbols?\s+lack",
                    r"without\s+docstring.*?(\d+)",
                ]
            )
        got = _extract_count_answer_first(
            output_text,
            count_patterns,
        )
        expected_symbols = independent_ast.get("symbols", gt.get("undocumented_symbols"))
        symbol_components: list[tuple[str, list[str], str, bool]] = []
        if (
            isinstance(required_components, list)
            and "independent_ast_symbols" in required_components
            and isinstance(expected_symbols, list)
            and all(isinstance(symbol, str) for symbol in expected_symbols)
        ):
            region, degraded = _answer_region(output_text, _ANSWER_LABELS_SYMBOLS)
            symbol_components.append(("independent_ast_symbols", expected_symbols, region, degraded))
        return _score_required_components(
            count_components=[("independent_ast_count", expected, got)],
            symbol_components=symbol_components,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            oracle_views=oracle_views if isinstance(oracle_views, Mapping) else None,
            check=check,
        )

    if check == "uncovered":
        expected = gt.get("uncovered_count", 0)
        required_components = gt.get("required_answer_components", [])
        count_patterns = [
            r"independent[\s_-]+ast[\s_-]+count\s*[:=]\s*(\d+)",
        ]
        if "independent_ast_count" in required_components:
            count_patterns.extend(
                [
                    r"(\d+)\s+uncovered\s+(?:public\s+)?symbols?\b",
                    r"uncovered\s+(?:public\s+)?symbols?\s*[:=]\s*(\d+)",
                    r"uncovered\s+(?:public\s+)?symbols?\s*\(\s*(\d+)\s*\)",
                ]
            )
        if "independent_ast_count" not in required_components:
            count_patterns.extend(
                [
                    r"(\d+)\s+uncovered",
                    r"(\d+)\s+(?:public\s+)?symbols?\s+uncovered",
                    r"uncovered[:\s]+(\d+)",
                    r"uncovered\s+public\s+symbols?[:\s—–]+(\d+)",
                    r"uncovered\s+(?:public\s+)?symbols?\s*\(\s*(\d+)\s*\)",
                    r"without\s+test.*?(\d+)",
                ]
            )
        got = _extract_count_answer_first(
            output_text,
            count_patterns,
        )
        expected_symbols = gt.get("uncovered_symbols")
        symbol_components: list[tuple[str, list[str], str, bool]] = []
        if (
            isinstance(required_components, list)
            and "independent_ast_symbols" in required_components
            and isinstance(expected_symbols, list)
            and all(isinstance(symbol, str) for symbol in expected_symbols)
        ):
            region, degraded = _answer_region(output_text, _ANSWER_LABELS_SYMBOLS)
            symbol_components.append(("independent_ast_symbols", expected_symbols, region, degraded))
        oracle_views = gt.get("oracle_views")
        return _score_required_components(
            count_components=[("independent_ast_count", expected, got)],
            symbol_components=symbol_components,
            evaluator_used="_evaluate_oss",
            evaluator_version=_EVAL_VER_OSS,
            oracle_views=oracle_views if isinstance(oracle_views, Mapping) else None,
            check=check,
        )

    return BenchQuality(scored=False)


# Generic method names that recur across many unrelated classes/modules. A bare
# Class.method tail ending in one of these is too weak a signal to credit a specific caller via the
# no-module fallback (Form 11): the same "Trainer.setup" / "Loop.run" tail can name a different
# caller in a different module. Distinctive names (e.g. `_evaluation_step`) are not blocklisted, so
# legitimate unqualified codemap answers still score.
_COMMON_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "run",
        "setup",
        "teardown",
        "main",
        "forward",
        "step",
        "reset",
        "close",
        "open",
        "start",
        "stop",
        "call",
        "fit",
        "test",
        "validate",
        "predict",
        "update",
        "configure",
        "build",
        "init",
        "load",
        "save",
    }
)


def _module_compatible(gt_module: str, found_module: str) -> bool:
    """Return True when *found_module* may denote the same module as *gt_module*.

    Modules match when they are equal or when one is a dotted suffix of the other — the latter allows
    the legitimate abbreviated-path form (``loops.evaluation_loop`` for
    ``lightning.pytorch.loops.evaluation_loop``) while still rejecting a genuinely different module
    that merely shares a class/method tail (``a.wrong`` vs ``a.right``).

    Args:
        gt_module: Module component of a ground-truth caller (before ``::``).
        found_module: Module component of a caller extracted from the agent output.

    Returns:
        True when the two module strings are compatible.

    Examples:
        >>> _module_compatible("lightning.pytorch.loops.evaluation_loop", "loops.evaluation_loop")
        True
        >>> _module_compatible("a.right", "a.wrong")
        False
        >>> _module_compatible("x.mod", "x.mod")
        True
    """
    if gt_module == found_module:
        return True
    return gt_module.endswith("." + found_module) or found_module.endswith("." + gt_module)


def _norm_cls(qualname: str) -> str:
    """Normalize a qualified caller to its underscore-insensitive ``Class.method`` tail.

    Drops the module prefix and strips leading underscores from the class component, so the
    fuzzy caller tier credits format variants like ``EvaluationLoop.run`` against a ground-truth
    ``_EvaluationLoop.run``. Bare function tails (no ``.``) are returned unchanged.

    Args:
        qualname: Caller in ``module::Class.method`` form (or any tail subset of it).

    Returns:
        The normalized tail used for fuzzy comparison.

    Examples:
        >>> _norm_cls("lightning.loops.evaluation_loop::_EvaluationLoop.run")
        'EvaluationLoop.run'
        >>> _norm_cls("pkg.mod::plain_function")
        'plain_function'
    """
    tail = qualname.split("::")[-1]
    if "." not in tail:
        return tail
    cls, _, meth = tail.partition(".")
    return f"{cls.lstrip('_')}.{meth}"


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
    found_qualnames = _match_callers(output_text, expected_callers)

    true_positives = len(expected_set & found_qualnames)
    recall = true_positives / max(len(expected_set), 1)
    correct = recall >= 0.70

    # Tail-recall diagnostics only — does not affect the recall scalar or the 0.70 threshold above.
    matched_callers, missed_callers = _split_matched_missed(expected_set, found_qualnames)

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
            "matched_callers": matched_callers,
            "missed_callers": missed_callers,
        },
    )


def _match_callers(output_text: str, expected_callers: list[str]) -> set[str]:
    """Extract ground-truth callers named in *output_text* for caller and diff-impact scoring.

    The multi-form caller matcher shared by the develop_blast_radius / fn_call_graph evaluators and the
    diff-impact evaluator. It recognises the eleven output shapes agents emit for caller
    lists — canonical ``module::Class.method``, multi-``::`` chains, file-path forms, grouped headers +
    bullets, markdown tables, bold-backtick + numbered lists, slash-paired abbreviations, a fully-dotted
    reverse lookup, an always-on underscore-insensitive fuzzy tier gated on module compatibility, and a
    bare ``Class.method`` fallback that fires only when every other form produced nothing and rejects
    generic method tails. Only ``output_text`` is scored — no file is read (a ``→ foo.md`` pointer is
    ordinary text, since Write/Edit are blocked on both arms).

    Args:
        output_text: The agent's full response text.
        expected_callers: Ground-truth caller qualified names (``module::Class.method``).

    Returns:
        Candidate qualified names found in *output_text*. Callers intersect this with their expected
        set to get the true positives; the returned set may include normalization artifacts (e.g. an
        alternate ``::`` split) that fall outside the expected set and are discarded by that
        intersection.

    Examples:
        >>> found = _match_callers("caller: a.b::Foo.bar", ["a.b::Foo.bar", "a.b::Baz.qux"])
        >>> sorted(found & {"a.b::Foo.bar", "a.b::Baz.qux"})
        ['a.b::Foo.bar']
        >>> _match_callers("nothing relevant", ["a.b::Foo.bar"]) & {"a.b::Foo.bar"}
        set()
    """
    found_raw = _extract_caller_raw_forms(output_text)
    return _normalize_caller_forms(found_raw, output_text, expected_callers)


def _extract_caller_raw_forms(output_text: str) -> list[str]:  # noqa: C901
    """Extract raw ``module::callee`` tokens from *output_text* across ten regex output shapes.

    The first phase of :func:`_match_callers`: scans the agent output for every caller
    shape agents emit — canonical ``ns.x::Class.method``, multi-``::`` chains, ``.py:``/``src/`` file
    paths, grouped headers + bullets, markdown tables, section-header + rows, bold-backtick + numbered
    lists, and slash-paired abbreviations — and returns the raw tokens (pre-normalization). Kept as a
    single function because the forms share the ``_ns_pat`` alternation and header-position scans;
    ``# noqa: C901`` because splitting the ten independent, extensively-tested regex blocks further
    would fragment tightly-coupled matching logic without reducing real risk.

    Args:
        output_text: The agent's full response text.

    Returns:
        Raw ``module::callee`` candidate tokens (unnormalized; may contain duplicates/artifacts).
    """
    # Extract qualified names. Ten regex forms; :func:`_normalize_caller_forms` maps them to canonical.
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

    return found_raw


def _normalize_caller_forms(found_raw: list[str], output_text: str, expected_callers: list[str]) -> set[str]:  # noqa: C901
    """Map raw caller tokens to canonical ``module::Class.method`` and match them to *expected_callers*.

    The second phase of :func:`_match_callers`: normalizes each raw token from
    :func:`_extract_caller_raw_forms` (default split, multi-``::`` split points, ``module.Class::method``
    reclassification, abbreviated-suffix match), adds the fully-dotted reverse lookup (Form 5), the
    always-on underscore-insensitive fuzzy tier (gated on :func:`_module_compatible`), and the bare
    ``Class.method`` fallback (Form 11, module-blind, fired only when nothing else matched and rejecting
    generic method tails). ``# noqa: C901`` because these normalization tiers are interdependent and
    order-sensitive; splitting further would fragment tested matching semantics without reducing risk.

    Args:
        found_raw: Raw ``module::callee`` tokens from :func:`_extract_caller_raw_forms`.
        output_text: The agent's full response text (needed for the Form 5 / Form 11 reverse lookups).
        expected_callers: Ground-truth caller qualified names.

    Returns:
        Candidate canonical qualified names (intersect with expected set for true positives).
    """
    expected_set = set(expected_callers)
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
    # The module is now compared too (via _module_compatible): matching on the
    # Class.method tail alone credited a wrong-module same-tail caller (a `Loop.run` in a different
    # module scored the GT caller). Requiring module compatibility keeps the underscore tolerance
    # while rejecting cross-module tail collisions.
    already_exact = expected_set & found_qualnames
    for canonical in expected_callers:
        if canonical not in already_exact and "." in canonical.split("::")[-1]:
            norm = _norm_cls(canonical)
            gt_mod = canonical.split("::")[0]
            if any(_norm_cls(qn) == norm and _module_compatible(gt_mod, qn.split("::")[0]) for qn in found_qualnames):
                found_qualnames.add(canonical)

    # Form 11: bare Class.method fallback — fires ONLY when all other forms produced nothing.
    # Codemap arm sometimes outputs callers as "_EvaluationLoop._evaluation_step" without module
    # prefix; reverse-lookup against GT by matching the tail component of each expected caller.
    # This tier carries NO module qualification, so a bare Class.method whose method is
    # a generic name (`Loop.run`, `Trainer.setup`) is rejected: the same tail can name a different
    # caller in a different module. Distinctive method tails (`_evaluation_step`) still credit.
    if not found_qualnames:
        for canonical in expected_callers:
            parts = canonical.split("::")
            if len(parts) < 2:
                continue
            tail = parts[-1]  # e.g. "_EvaluationLoop._evaluation_step"
            if "." not in tail:
                continue  # skip bare function names (too short, high FP risk)
            if tail.rsplit(".", 1)[-1].lstrip("_") in _COMMON_METHOD_NAMES:
                continue  # unqualified bare common tail — too weak to credit a specific caller
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

    return found_qualnames


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

    # Score inside the structured answer block; require blocklisted file stems to appear
    # as a qualified reference (`x.py` or a path), never as a bare prose word.
    region, degraded = _answer_region(output_text, _ANSWER_LABELS_FILES)
    fn_found = bool(fn_name) and bool(re.search(r"\b" + re.escape(fn_name) + r"\b", region, re.IGNORECASE))
    file_found = bool(file_stem) and _stem_matches(file_stem, region)

    total = sum([bool(fn_name), bool(file_stem)])
    hits = sum([fn_found, file_found])
    recall = hits / total if total > 0 else 0.0

    return BenchQuality(
        scored=True,
        correct=fn_found and file_found,
        recall=round(recall, 3),
        extraction_failed=not fn_found and not file_found,
        extraction_degraded=degraded,
        evaluator_used="_evaluate_debug",
        evaluator_version=_EVAL_VER_DEBUG,
        scoring_detail={
            "function": fn_name,
            "fn_found": fn_found,
            "file": file_path,
            "file_found": file_found,
            "recall": recall,
            "method": "answer_block_stem_match",
        },
    )


def _evaluate_feature(task: dict, output_text: str) -> BenchQuality:
    """Evaluate feature_scaffolding task: exact labelled entry point and file path.

    Correct when the answer explicitly labels the task's full entry point and
    repository-relative primary file. This prevents exploratory prose from
    accidentally crediting a different final recommendation.

    Args:
        task: Task dict with ground_truth.entry_point, .primary_file.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with correct=True when both components found.
    """
    gt = task["ground_truth"]
    entry_point: str = gt.get("entry_point", "")
    primary_file: str = gt.get("primary_file", "")
    # Score only explicit conclusion fields. A Class.method can appear during exploration while the
    # final answer names a different extension point, so substring matching is not a valid oracle.
    region, degraded = _answer_region(output_text, _ANSWER_LABELS_FILES)
    entry_pattern = r"(?im)^\s*(?:[-*]\s*)?entry[\s_-]*point\s*:\s*`?" + re.escape(entry_point) + r"`?\.?\s*$"
    file_pattern = r"(?im)^\s*(?:[-*]\s*)?primary[\s_-]*file\s*:\s*`?" + re.escape(primary_file) + r"`?\s*$"
    ep_found = bool(entry_point) and bool(re.search(entry_pattern, region))
    file_found = bool(primary_file) and bool(re.search(file_pattern, region))

    total = sum([bool(entry_point), bool(primary_file)])
    hits = sum([ep_found, file_found])
    recall = hits / total if total > 0 else 0.0

    return BenchQuality(
        scored=True,
        correct=ep_found and file_found,
        recall=round(recall, 3),
        extraction_failed=not ep_found and not file_found,
        extraction_degraded=degraded,
        evaluator_used="_evaluate_feature",
        evaluator_version=_EVAL_VER_FEATURE,
        scoring_detail={
            "entry_point": entry_point,
            "ep_found": ep_found,
            "primary_file": primary_file,
            "file_found": file_found,
            "recall": recall,
            "method": "labelled_entry_point_and_primary_file",
        },
    )


_RI_RECALL_THRESHOLD = 0.70


def _evaluate_real_issue(task: dict, output_text: str) -> BenchQuality:
    """Evaluate real_issue task: file-set recall over ground_truth.files_changed.

    Recall = |GT files referenced by a pathed form in the answer block| / |GT files|.
    A file counts only via its full relative path or a path-with-parent form — a bare
    basename stem no longer scores. Correct when recall >= 0.70.

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

    # Require a full relative path or path-with-parent inside the structured answer block —
    # a bare basename stem (`trainer`) is a near-free hit and no longer counts.
    region, degraded = _answer_region(output_text, _ANSWER_LABELS_FILES)
    found = sum(1 for fp in gt_files if _ri_file_matches(fp, region))
    recall = found / len(gt_files)

    return BenchQuality(
        scored=True,
        correct=recall >= _RI_RECALL_THRESHOLD,
        recall=round(recall, 3),
        metric_expected=len(gt_files),
        metric_got=found,
        extraction_failed=found == 0,
        extraction_degraded=degraded,
        evaluator_used="_evaluate_real_issue",
        evaluator_version=_EVAL_VER_REAL_ISSUE,
        scoring_detail={
            "gt_files": gt_files,
            "files_found": found,
            "recall": recall,
            "threshold": _RI_RECALL_THRESHOLD,
            "method": "answer_block_path_match",
        },
    )


# ---------------------------------------------------------------------------
# Diff-impact and graph evaluators
# ---------------------------------------------------------------------------

_DI_RECALL_THRESHOLD = 0.70  # caller recall AND test-file recall must each clear this for DI correctness
_GR_RECALL_THRESHOLD = 0.70  # central set-overlap / fn-blast recall threshold
_MB_RECALL_THRESHOLD = 0.70  # module_blast_radius importer (import fan-in) recall threshold

# Tail-recall instrumentation (additive diagnostics only): matched/missed name lists are recorded in
# scoring_detail so a run's exact hit/miss split can be inspected without re-scoring. They never feed
# the recall scalar or the pass threshold. Lists are sorted and bounded to keep the JSONL line small on
# high-fan-in tasks (hundreds of callers/importers); the count fields carry the untruncated totals.
_TAIL_LIST_CAP = 50


def _split_matched_missed(expected: set[str], found: set[str]) -> tuple[list[str], list[str]]:
    """Return ``(matched, missed)`` sorted, each bounded to :data:`_TAIL_LIST_CAP` names (tail-recall).

    Additive diagnostics for the caller / importer recall evaluators: the intersection is the matched
    set, the difference is the missed set. Both are sorted for stable output and truncated to the cap so
    a high-fan-in task does not bloat the result line — the evaluator's own count fields remain the
    authoritative totals.

    Args:
        expected: Ground-truth qualified names.
        found: Names matched in the agent output.

    Returns:
        ``(matched, missed)`` — sorted name lists, each at most :data:`_TAIL_LIST_CAP` long.

    Examples:
        >>> _split_matched_missed({"a", "b", "c"}, {"a", "c"})
        (['a', 'c'], ['b'])
        >>> _split_matched_missed({"x"}, set())
        ([], ['x'])
    """
    matched = sorted(expected & found)[:_TAIL_LIST_CAP]
    missed = sorted(expected - found)[:_TAIL_LIST_CAP]
    return matched, missed


def _module_mentioned(module: str, output_text: str) -> bool:
    """Return True when dotted *module* is named in *output_text* (exact or abbreviated-suffix form).

    A module counts when its full dotted name appears, or when a distinctive dotted suffix of it
    appears (``loops.evaluation_loop`` for ``lightning.pytorch.loops.evaluation_loop``) — the same
    abbreviation tolerance the caller matcher grants. A single-component tail is too weak and is not
    accepted on its own. Word-boundary lookarounds prevent substring false positives.

    Args:
        module: Dotted module name from ground truth.
        output_text: Agent's full response text.

    Returns:
        True when the module is named by an exact or ≥2-component-suffix form.

    Examples:
        >>> _module_mentioned("lightning.pytorch.loops.evaluation_loop", "see loops.evaluation_loop")
        True
        >>> _module_mentioned("a.b.c", "unrelated prose")
        False
    """
    forms = {module}
    parts = module.split(".")
    for start in range(1, len(parts) - 1):  # ≥2-component suffixes only
        forms.add(".".join(parts[start:]))
    return any(re.search(r"(?<![\w.])" + re.escape(f) + r"(?![\w.])", output_text) for f in forms)


def _set_recall(expected: list[str], predicate: Any) -> tuple[int, float]:
    """Return ``(hits, recall)`` for *expected* items, each tested by *predicate*.

    Args:
        expected: Ground-truth items.
        predicate: One-argument callable returning True when the item is present in the output.

    Returns:
        ``(hits, recall)`` — recall is ``hits / len(expected)`` (0.0 when *expected* is empty).

    Examples:
        >>> _set_recall(["a", "b"], lambda x: x == "a")
        (1, 0.5)
        >>> _set_recall([], lambda x: True)
        (0, 0.0)
    """
    hits = sum(1 for item in expected if predicate(item))
    return hits, (hits / len(expected) if expected else 0.0)


def _explicit_h2_section(output_text: str, label: str) -> tuple[str, bool]:
    """Return one exact Markdown H2 answer section without cross-section fallback.

    Diff-impact prompts require separate ``## Callers`` and ``## Tests`` lists. Restricting their evaluators to these
    bounded sections keeps exploratory prose and misplaced answers from becoming scoreable evidence.
    """
    pattern = rf"(?im)^##[ \t]+{re.escape(label)}[ \t]*$"
    match = re.search(pattern, output_text)
    if match is None:
        return "", False
    next_heading = re.search(r"(?m)^##[ \t]+", output_text[match.end() :])
    end = match.end() + next_heading.start() if next_heading is not None else len(output_text)
    return output_text[match.end() : end], True


def _evaluate_diff_impact(task: dict, output_text: str) -> BenchQuality:
    """Evaluate scoped DI callers/tests with continuous precision-recall fitness.

    A diff-impact task stages a change and asks for the blast radius: which modules/callers are affected
    and which tests to run. Correctness requires BOTH the caller recall (reusing the develop_br
    multi-form matcher, :func:`_match_callers`) and the test-module recall (dotted-name match) to clear
    0.70 — a good blast-radius answer names both what breaks and what to re-run.

    Args:
        task: Task dict; reads ``ground_truth.fn_callers`` and ``.test_modules``.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with averaged caller/test F1 fitness; binary correctness keeps
        the transparent per-component recall thresholds.
    """
    gt = task["ground_truth"]
    expected_callers: list[str] = gt.get("fn_callers", [])
    expected_tests: list[str] = gt.get("test_modules", [])
    if not expected_callers and not expected_tests:
        return BenchQuality(scored=False)

    callers_section, callers_section_found = _explicit_h2_section(output_text, "Callers")
    tests_section, tests_section_found = _explicit_h2_section(output_text, "Tests")
    found_callers = _match_callers(callers_section, expected_callers)
    caller_hits = len(set(expected_callers) & found_callers)
    caller_recall = caller_hits / len(expected_callers) if expected_callers else 1.0
    caller_candidates = set(_extract_caller_raw_forms(callers_section))
    caller_precision = caller_hits / len(caller_candidates) if caller_candidates else 0.0
    caller_fitness = (
        2 * caller_precision * caller_recall / (caller_precision + caller_recall)
        if caller_precision + caller_recall
        else 0.0
    )

    test_hits, test_recall = _set_recall(expected_tests, lambda m: _module_mentioned(m, tests_section))
    if not expected_tests:
        test_recall = 1.0
    test_candidates = set(re.findall(r"\b(?:tests|parity)_[\w.]+", tests_section))
    test_precision = test_hits / len(test_candidates) if test_candidates else 0.0
    test_fitness = (
        2 * test_precision * test_recall / (test_precision + test_recall) if test_precision + test_recall else 0.0
    )

    correct = caller_recall >= _DI_RECALL_THRESHOLD and test_recall >= _DI_RECALL_THRESHOLD
    return BenchQuality(
        scored=True,
        correct=correct,
        metric_expected=len(expected_callers),
        metric_got=caller_hits,
        recall=round((caller_fitness + test_fitness) / 2, 3),
        caller_count_gt=gt.get("unique_caller_count"),
        extraction_failed=not found_callers and test_hits == 0,
        evaluator_used="_evaluate_diff_impact",
        scoring_detail={
            "caller_recall": round(caller_recall, 3),
            "test_recall": round(test_recall, 3),
            "caller_precision": round(caller_precision, 3),
            "test_precision": round(test_precision, 3),
            "caller_fitness": round(caller_fitness, 3),
            "test_fitness": round(test_fitness, 3),
            "caller_expected": len(expected_callers),
            "caller_got": caller_hits,
            "test_expected": len(expected_tests),
            "test_got": test_hits,
            "callers_section_found": callers_section_found,
            "tests_section_found": tests_section_found,
            "threshold": _DI_RECALL_THRESHOLD,
            "method": "scoped_caller_test_f1_with_recall_gates",
        },
    )


def _evaluate_graph_central(task: dict, output_text: str) -> BenchQuality:
    """Evaluate whether a ``graph_central`` result overlaps the top-N central modules by at least 0.70.

    The agent lists the most-imported modules; correctness is the fraction of ground-truth central
    modules named in the output (order-insensitive set overlap).

    Args:
        task: Task dict; reads ``ground_truth.central_modules``.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall = set overlap.
    """
    gt = task["ground_truth"]
    expected: list[str] = gt.get("central_modules", [])
    if not expected:
        return BenchQuality(scored=False)
    hits, recall = _set_recall(expected, lambda m: _module_mentioned(m, output_text))
    return BenchQuality(
        scored=True,
        correct=recall >= _GR_RECALL_THRESHOLD,
        metric_expected=len(expected),
        metric_got=hits,
        recall=round(recall, 3),
        extraction_failed=hits == 0,
        evaluator_used="_evaluate_graph_central",
        scoring_detail={
            "metric_expected": len(expected),
            "metric_got": hits,
            "threshold": _GR_RECALL_THRESHOLD,
            "method": "set_overlap",
        },
    )


def _evaluate_graph_path(task: dict, output_text: str) -> BenchQuality:
    """Evaluate whether a ``graph_path`` result equals the oracle path.

    The ground-truth path is the unique shortest import chain. The agent's chain matches when every GT
    hop module is named in the output AND they appear in the GT order — a correct answer must trace the
    same chain. Because pairs are chosen where the shortest path is unique (generator enforces
    ``path_is_unique``), the single oracle path is the only valid answer.

    Args:
        task: Task dict; reads ``ground_truth.import_path`` (list of module names, source→target).
        output_text: Agent's full response text.

    Returns:
        BenchQuality; correct when every hop is present in GT order.
    """
    gt = task["ground_truth"]
    path: list[str] = gt.get("import_path") or []
    if not path:
        return BenchQuality(scored=False)
    positions = [_module_first_pos(hop, output_text) for hop in path]
    all_present = all(pos is not None for pos in positions)
    in_order = all_present and all(
        positions[i] < positions[i + 1]  # type: ignore[operator]
        for i in range(len(positions) - 1)
    )
    hits = sum(1 for pos in positions if pos is not None)
    return BenchQuality(
        scored=True,
        correct=bool(in_order),
        metric_expected=len(path),
        metric_got=hits,
        recall=round(hits / len(path), 3),
        extraction_failed=hits == 0,
        evaluator_used="_evaluate_graph_path",
        scoring_detail={
            "expected_path": path,
            "hops_found": hits,
            "in_order": bool(in_order),
            "method": "ordered_chain_match",
        },
    )


def _module_first_pos(module: str, output_text: str) -> Optional[int]:
    """Return the first character offset at which *module* is named, or ``None``.

    Uses the same exact/≥2-component-suffix matching as :func:`_module_mentioned`, returning the
    earliest match offset across all accepted forms so path-order can be checked.

    Args:
        module: Dotted module name.
        output_text: Agent's full response text.

    Returns:
        Earliest match offset, or None when the module is not named.

    Examples:
        >>> _module_first_pos("a.b.c", "start a.b.c end")
        6
        >>> _module_first_pos("a.b.c", "nothing") is None
        True
    """
    forms = {module}
    parts = module.split(".")
    for start in range(1, len(parts) - 1):
        forms.add(".".join(parts[start:]))
    positions = [
        m.start()
        for f in forms
        if (m := re.search(r"(?<![\w.])" + re.escape(f) + r"(?![\w.])", output_text)) is not None
    ]
    return min(positions) if positions else None


def _evaluate_graph_fn_blast(task: dict, output_text: str) -> BenchQuality:
    """Evaluate whether ``graph_fn_blast`` transitive-caller recall is at least 0.70.

    Reuses the develop_br multi-form caller matcher (:func:`_match_callers`) against the depth-N
    transitive caller closure.

    Args:
        task: Task dict; reads ``ground_truth.blast_callers``.
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall over the transitive closure.
    """
    gt = task["ground_truth"]
    expected: list[str] = gt.get("blast_callers", [])
    if not expected:
        return BenchQuality(scored=False)
    found = _match_callers(output_text, expected)
    hits = len(set(expected) & found)
    recall = hits / len(expected)
    return BenchQuality(
        scored=True,
        correct=recall >= _GR_RECALL_THRESHOLD,
        metric_expected=len(expected),
        metric_got=hits,
        recall=round(recall, 3),
        extraction_failed=not found,
        evaluator_used="_evaluate_graph_fn_blast",
        scoring_detail={
            "metric_expected": len(expected),
            "metric_got": hits,
            "threshold": _GR_RECALL_THRESHOLD,
            "method": "recall",
        },
    )


def _evaluate_module_blast_radius(task: dict, output_text: str) -> BenchQuality:
    """Evaluate whether ``module_blast_radius`` importer recall is at least 0.70.

    The reverse relation of the develop_br per-function caller recall, at module granularity: given a
    target module, the agent enumerates the modules that IMPORT it (its rdeps). Correctness is the
    fraction of ground-truth importers named in the output, matched by :func:`_module_mentioned` — an
    exact dotted name or a ≥2-component dotted suffix, NEVER a bare single-component leaf. Handling of extraction
    failures mirrors :func:`_evaluate_develop_br`: when not a single importer is named the run
    is flagged ``extraction_failed`` and excluded from the accuracy denominator upstream.

    Args:
        task: Task dict; reads ``ground_truth.importers`` (dotted module names).
        output_text: Agent's full response text.

    Returns:
        BenchQuality with recall = importer recall; correct when recall ≥ 0.70.
    """
    gt = task["ground_truth"]
    expected_importers: list[str] = gt.get("importers", [])
    if not expected_importers:
        return BenchQuality(scored=False)

    expected_set = set(expected_importers)
    found = {m for m in expected_set if _module_mentioned(m, output_text)}
    hits = len(found)
    recall = hits / max(len(expected_set), 1)
    correct = recall >= _MB_RECALL_THRESHOLD

    # Tail-recall diagnostics only — does not affect the recall scalar or the threshold above.
    matched_importers, missed_importers = _split_matched_missed(expected_set, found)

    return BenchQuality(
        scored=True,
        correct=correct,
        metric_expected=len(expected_set),
        metric_got=hits,
        recall=round(recall, 3),
        extraction_failed=hits == 0,
        evaluator_used="_evaluate_module_blast_radius",
        extracted_metric=sorted(found),
        scoring_detail={
            "metric_expected": len(expected_set),
            "metric_got": hits,
            "threshold": _MB_RECALL_THRESHOLD,
            "method": "recall",
            "matched_importers": matched_importers,
            "missed_importers": missed_importers,
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
    "diff_impact": _evaluate_diff_impact,
    "graph_central": _evaluate_graph_central,
    "graph_path": _evaluate_graph_path,
    "graph_fn_blast": _evaluate_graph_fn_blast,
    "module_blast_radius": _evaluate_module_blast_radius,
}


@dataclass(frozen=True)
class _BenchEvaluatorAdapter:
    """Callable adapter from one detailed Claude evaluator to the provider-neutral contract.

    Attributes:
        evaluator: Existing evaluator that returns the detailed Claude score object.

    Examples:
        >>> detailed = BenchQuality(scored=True, correct=True, recall=0.5)
        >>> adapter = _BenchEvaluatorAdapter(lambda _task, _output: detailed)
        >>> adapter({}, "answer").quality_score
        0.5
    """

    evaluator: Callable[[Mapping[str, Any], str], BenchQuality]

    def __call__(self, task: Mapping[str, Any], output_text: str) -> EvaluationResult:
        """Evaluate one response once and package its normalized and detailed scores.

        Args:
            task: Task mapping handed to the wrapped evaluator.
            output_text: Agent response text to score.

        Returns:
            A shared evaluator result that preserves that exact detailed score.
        """
        quality = self.evaluator(task, output_text)
        quality_score = quality.recall if quality.scored and quality.recall is not None else float(quality.correct)
        if not quality.scored:
            quality_score = None
        components: dict[str, float] = {}
        if quality.scored and quality.recall is not None:
            components["recall"] = float(quality.recall)
        required_components = quality.scoring_detail.get("components")
        if isinstance(required_components, Mapping):
            for name, component in required_components.items():
                if not isinstance(name, str) or not isinstance(component, Mapping):
                    continue
                fitness = component.get("fitness")
                if isinstance(fitness, (int, float)) and not isinstance(fitness, bool):
                    components[f"subanswer:{name}"] = float(fitness)
        for name in ("caller_recall", "test_recall"):
            value = quality.scoring_detail.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                components[name] = float(value)
        return _BenchEvaluationResult(
            scored=quality.scored,
            correct=quality.correct,
            quality_score=quality_score,
            extraction_failed=quality.extraction_failed,
            components=components,
            bench_quality=quality,
        )


def _wrap_bench_evaluator(
    evaluator: Callable[[Mapping[str, Any], str], BenchQuality],
) -> Callable[[Mapping[str, Any], str], EvaluationResult]:
    """Adapt one detailed Claude evaluator to the provider-neutral result contract.

    Args:
        evaluator: Existing evaluator that returns the detailed Claude score object.

    Returns:
        A callable that scores one response into a shared evaluator result, preserving
        that exact detailed score.

    Examples:
        >>> detailed = BenchQuality(scored=False, correct=False)
        >>> wrapped = _wrap_bench_evaluator(lambda _task, _output: detailed)
        >>> wrapped({}, "answer").scored
        False
    """
    return _BenchEvaluatorAdapter(evaluator)


_SHARED_EVALUATORS = EvaluatorRegistry(
    {task_type: _wrap_bench_evaluator(evaluator) for task_type, evaluator in _EVALUATORS.items()}
)


def _evaluate_shared_task(
    task: Mapping[str, Any], output_text: str, *, registry: EvaluatorRegistry | None = None
) -> BenchQuality:
    """Score one task through the shared registry and retain Claude diagnostics.

    Args:
        task: Raw scoreable task definition.
        output_text: Claude response text.
        registry: Test-only replacement registry; uses the locked runner registry by default.

    Returns:
        The exact detailed score produced by the one shared evaluator invocation.

    Raises:
        TypeError: If a scoreable task's registry result lacks Claude diagnostics.
        ValueError: If a scoreable task type is not registered.
    """
    result = (registry or _SHARED_EVALUATORS).evaluate(task, output_text)
    if not isinstance(result, _BenchEvaluationResult):
        raise TypeError("shared evaluator did not return Claude benchmark diagnostics")
    return result.bench_quality


def _evaluator_provenance(task: Mapping[str, Any]) -> tuple[str, str]:
    """Return the exact evaluator identity and source hash for one task contract."""
    if task.get("scoreable") is False:
        evaluator_id = "unscored"
        return evaluator_id, hashlib.sha256(b"scoreable=false bypass").hexdigest()
    task_type = task.get("type")
    evaluator = _EVALUATORS.get(task_type) if isinstance(task_type, str) else None
    if evaluator is None:
        raise ValueError(f"unknown evaluator for scoreable task type {task_type!r}")
    evaluator_id = evaluator.__name__
    source = inspect.getsource(evaluator).encode("utf-8")
    return evaluator_id, hashlib.sha256(evaluator_id.encode("utf-8") + b"\n" + source).hexdigest()


def _arm_contract_hash(arm: str) -> str:
    """Return the locked semantic arm hash for canonical arms only."""
    return ARM_CONTRACTS[arm]["contract_sha256"] if arm in ARM_CONTRACTS else ""


# ---------------------------------------------------------------------------
# Diff-impact staging
# ---------------------------------------------------------------------------


class DirtyTreeError(Exception):
    """Raised when the target tree already has uncommitted changes at DI-series start.

    A diff-impact task stages a synthetic change and reverts it with ``git checkout -- <paths>``. That revert is only
    safe when the touched paths were clean beforehand — reverting a path the user had already modified would silently
    destroy their edits. So the series refuses to run against a dirty tree rather than risk clobbering pre-existing
    changes.
    """


class DiffImpactStager:
    """Stage a scripted synthetic change in the target repository, then robustly revert it.

    A diff-impact task ships a ``stage`` spec containing either a file/find/replace mapping or a file/append mapping for
    each edit to a widely called signature or function body. The stager applies every edit inside a ``with`` block. On
    exit, whether successful or exceptional, it reverts every touched path with ``git checkout -- <path>`` so the change
    is present for both arms of the task and gone afterwards. The tree is verified clean (via
    ``git status --porcelain`` scoped to the touched paths) before staging: a dirty path aborts the
    whole series with :class:`DirtyTreeError` rather than risk clobbering the user's own edits.

    Args:
        repo_path: Root of the target repository (a git clone).
        stage_spec: List of edit dicts from the task's ``stage`` field.

    Examples:
        >>> stager = DiffImpactStager("/repo", [{"file": "a.py", "find": "x", "replace": "y"}])  # doctest: +SKIP
        >>> with stager:  # doctest: +SKIP
        ...     run_both_arms()  # change is live here
        >>> # change is reverted on block exit, even if run_both_arms raised
    """

    def __init__(self, repo_path: str | Path, stage_spec: list[dict]) -> None:
        self.repo_path = Path(repo_path)
        self.stage_spec = stage_spec
        self._touched: list[Path] = []
        self.revert_error: str | None = None

    def _rel_paths(self) -> list[str]:
        """Return the repo-relative paths named by the stage spec (deduplicated, order-preserving)."""
        seen: dict[str, None] = {}
        for edit in self.stage_spec:
            rel = edit.get("file", "")
            if rel:
                seen.setdefault(rel, None)
        return list(seen)

    def _assert_clean(self) -> None:
        """Raise :class:`DirtyTreeError` when any staged path already has uncommitted changes."""
        rels = self._rel_paths()
        if not rels:
            return
        proc = subprocess.run(
            ["git", "-C", str(self.repo_path), "status", "--porcelain", "--", *rels],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise DirtyTreeError(f"git status failed in {self.repo_path}: {proc.stderr.strip()}")
        if proc.stdout.strip():
            raise DirtyTreeError(
                f"target tree is dirty at DI start — refusing to stage (would risk clobbering): "
                f"{proc.stdout.strip().splitlines()[:5]}"
            )

    def _apply(self) -> None:
        """Apply every edit in the stage spec, recording each touched path for revert."""
        for edit in self.stage_spec:
            rel = edit.get("file", "")
            if not rel:
                continue
            fpath = self.repo_path / rel
            text = fpath.read_text(encoding="utf-8")
            if "append" in edit:
                text = text + edit["append"]
            elif "find" in edit and "replace" in edit:
                if edit["find"] not in text:
                    raise DirtyTreeError(f"stage find-text not present in {rel}: {edit['find']!r}")
                text = text.replace(edit["find"], edit["replace"], 1)
            else:
                raise DirtyTreeError(f"stage edit for {rel} needs 'append' or 'find'+'replace'")
            fpath.write_text(text, encoding="utf-8")
            if fpath not in self._touched:
                self._touched.append(fpath)

    def revert(self) -> None:
        """Restore every touched path via ``git checkout -- <path>``.

        Never raises, so it is safe from ``__enter__``'s failure path and from
        ``__exit__`` while another exception propagates. The git result is no longer
        discarded: a failed revert leaves the *shared* target tree carrying the staged
        synthetic change, which every later task then sees as a dirty tree far from the
        task that caused it. The failure is recorded in ``revert_error`` and the touched
        paths are retained, so ``__exit__`` can escalate and the evidence survives.
        """
        rels = self._rel_paths()
        if not rels:
            return
        try:
            restored = subprocess.run(
                ["git", "-C", str(self.repo_path), "checkout", "--", *rels],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            self.revert_error = f"git checkout raised: {exc}"
            return
        if restored.returncode != 0:
            self.revert_error = (
                f"git checkout exited {restored.returncode} for {', '.join(rels)}: {restored.stderr.strip()[:300]}"
            )
            return
        self.revert_error = None
        self._touched = []

    def __enter__(self) -> "DiffImpactStager":
        self._assert_clean()
        try:
            self._apply()
        except Exception:
            # A later edit's anchor may be missing (stale spec vs repo drift) after earlier edits
            # already wrote to disk. __exit__ does NOT run when __enter__ raises, so revert here or
            # the target tree is left partially modified and every subsequent DI task sees a dirty tree.
            self.revert()
            raise
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # Revert runs whether the arms succeeded or raised — the change must never outlive the task.
        self.revert()
        if self.revert_error is None:
            return
        # The shared tree is still mutated. Escalate so the run stops here rather than
        # letting every later task inherit the contamination, but never mask an
        # in-flight exception that is already carrying the real cause.
        if exc_type is None:
            raise DirtyTreeError(
                f"staged diff-impact change was not reverted; target tree is still mutated: {self.revert_error}"
            )


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
        self._worktree: Path | None = None
        self._worktree_active = False
        self.last_mutation_evidence: dict[str, Any] = {}

    def _test_argv(self) -> list[str]:
        """Build the pytest argv from the task's test_command or failing_test.

        A bare ``pytest`` resolves against ``PATH`` and can select an interpreter other than the one running the harness
        — three benchmark lanes were resolving pytest three different ways while their results were compared as one
        measurement. The binary is pinned to ``sys.executable -m pytest`` here, matching the codex lane.
        """
        cmd = self.task.get("test_command")
        if cmd:
            return _pin_pytest_interpreter(shlex.split(cmd))
        failing = self.task.get("failing_test")
        if not failing:
            raise SandboxError(f"task {self.task['id']}: no test_command or failing_test")
        return [sys.executable, "-m", "pytest", failing, "-x"]

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

        cell = IsolatedMutationCell(self._allocate_worktree, self._cleanup)

        def evaluate(worktree: Path) -> bool:
            create = subprocess.run(
                ["git", "-C", str(self.repo_path), "worktree", "add", "--detach", str(worktree), commit],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if create.returncode != 0:
                raise SandboxError(f"task {self.task['id']}: worktree add failed at {commit}: {create.stderr.strip()}")
            self._worktree_active = True

            # Verify the test fails at the pre-fix commit before applying the patch.
            baseline = subprocess.run(
                [*self._test_argv(), "--timeout=60", "-q"],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=600,
            )
            if baseline.returncode not in _PYTEST_RESULT_EXIT_CODES:
                # pytest never produced a test result, so neither run is evidence about
                # the patch. Surfacing this as a sandbox error keeps the cell unscored
                # instead of recording a fabricated failure.
                raise SandboxError(
                    f"task {self.task['id']}: baseline pytest exited {baseline.returncode} "
                    f"({_describe_pytest_exit(baseline.returncode)}); "
                    f"no baseline test result: {baseline.stderr.strip()[:300]}"
                )
            if baseline.returncode == PYTEST_EXIT_ALL_PASSED:
                # Test already passes before the patch — cannot validate the fix.
                return False

            # Apply the diff. Prefer `git apply` (respects a/ b/ prefixes); fall back to patch -p1.
            # `--reject` is deliberately absent: it applies the hunks it can and still exits
            # non-zero, which left the fallback re-applying the same file onto an already
            # half-patched tree. The tree is reset between attempts for the same reason.
            patch_file = worktree / ".patch-bench.diff"
            patch_file.write_text(diff_text)
            applied = subprocess.run(
                ["git", "-C", str(worktree), "apply", "--whitespace=nowarn", str(patch_file)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if applied.returncode != 0:
                self._reset_worktree(worktree)
                fallback = subprocess.run(
                    ["patch", "-p1", "-i", str(patch_file)],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if fallback.returncode != 0:
                    # Patch did not apply — count as a failed patch, not a sandbox error.
                    return False

            # Remove the harness's own scratch files so they cannot be collected as tests
            # or read as source by the scored run.
            self._clean_patch_artifacts(worktree)

            test = subprocess.run(
                [*self._test_argv(), "--timeout=60", "-q"],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                timeout=600,
            )
            if test.returncode not in _PYTEST_RESULT_EXIT_CODES:
                raise SandboxError(
                    f"task {self.task['id']}: post-patch pytest exited {test.returncode} "
                    f"({_describe_pytest_exit(test.returncode)}); "
                    f"no post-patch test result: {test.stderr.strip()[:300]}"
                )
            return test.returncode == PYTEST_EXIT_ALL_PASSED

        try:
            return cell.run(evaluate)
        except subprocess.TimeoutExpired:
            return False
        except MutationCleanupError as exc:
            raise SandboxError(f"task {self.task['id']}: {exc}") from exc
        finally:
            evidence = cell.last_evidence
            self.last_mutation_evidence = {
                "worktree": str(evidence.worktree) if evidence.worktree is not None else None,
                "action_error": evidence.action_error,
                "cleanup_error": evidence.cleanup_error,
                "restored": evidence.restored,
            }

    def _reset_worktree(self, worktree: Path) -> None:
        """Discard any partially applied hunks before the fallback apply attempt."""
        reset = subprocess.run(
            ["git", "-C", str(worktree), "checkout", "--", "."],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if reset.returncode != 0:
            raise SandboxError(
                f"task {self.task['id']}: worktree reset before fallback apply failed: {reset.stderr.strip()}"
            )

    def _clean_patch_artifacts(self, worktree: Path) -> None:
        """Remove the harness diff file and any ``.rej``/``.orig`` files it produced."""
        for path in [worktree / ".patch-bench.diff", *worktree.rglob("*.rej"), *worktree.rglob("*.orig")]:
            path.unlink(missing_ok=True)

    def _allocate_worktree(self) -> Path:
        """Allocate a unique private worktree path for one attempt or retry."""
        root = Path(tempfile.mkdtemp(prefix=f"patch-bench-{self.task['id']}-"))
        self._worktree = root / "repo"
        self._worktree_active = False
        return self._worktree

    def _cleanup(self, worktree: Path) -> None:
        """Restore and remove one private worktree or raise with cleanup evidence."""
        if self._worktree_active:
            reset = subprocess.run(
                ["git", "-C", str(worktree), "reset", "--hard", "HEAD"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if reset.returncode != 0:
                raise SandboxError(f"task {self.task['id']}: worktree reset failed: {reset.stderr.strip()}")
            remove = subprocess.run(
                ["git", "-C", str(self.repo_path), "worktree", "remove", str(worktree)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if remove.returncode != 0:
                raise SandboxError(f"task {self.task['id']}: worktree remove failed: {remove.stderr.strip()}")
            self._worktree_active = False
        if worktree.exists():
            raise SandboxError(f"task {self.task['id']}: worktree remains after cleanup")
        try:
            worktree.parent.rmdir()
        except OSError as exc:
            raise SandboxError(f"task {self.task['id']}: worktree parent cleanup failed") from exc


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
        resume_cache: When non-None, a prior-results cache (see :func:`_load_resume_cache`);
            a matching (task, arm, model, repo_sha, index_sha, task_hash) tuple is reused
            instead of re-executing the claude subprocess. None disables resume (default).
        task_policies: Locked task policies used to stamp current-revision parity provenance.
    """

    def __init__(
        self,
        model_short: str,
        model_id: str,
        repo_path: Path,
        index_path: Path,
        timeout: int = 300,
        resume_cache: Optional[dict[tuple, dict]] = None,
        task_policies: Mapping[str, TaskPolicy] | None = None,
        suite_hash: str | None = None,
        suite_raw_hash: str | None = None,
    ) -> None:
        self.model_short = model_short
        self.model_id = model_id
        self.repo_path = repo_path
        self.index_path = index_path
        self.timeout = timeout
        self.resume_cache = resume_cache
        self.task_policies = task_policies
        self.suite_hash = suite_hash
        self.suite_raw_hash = suite_raw_hash
        # Provenance stamped on every run so results can be matched on a later ``--resume`` pass.
        self.repo_sha = _repo_sha(repo_path)
        self.index_sha = _index_sha(index_path)

    def _stamp_provenance(self, result: BenchRun, task: dict, task_hash: str) -> None:
        """Attach provenance + self-consistency metadata to *result* in place.

        Args:
            result: The BenchRun to annotate.
            task: The task dict being run.
            task_hash: Precomputed sha256 of the task JSON.
        """
        result.repo_sha = self.repo_sha
        result.index_sha = self.index_sha
        result.task_hash = task_hash
        result.prompt_hash = _prompt_hash(task)
        result.prompt_sha256 = result.prompt_hash
        result.suite_hash = self.suite_hash
        result.suite_raw_hash = self.suite_raw_hash
        result.evaluator_id, result.evaluator_hash = _evaluator_provenance(task)
        envelope = _build_system_prompt(result.arm, _REPO_NAME, str(self.repo_path), str(self.index_path))
        result.envelope_hash = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
        result.arm_contract_hash = _arm_contract_hash(result.arm)
        result.self_consistency = bool(task.get(_SELF_CONSISTENCY_KEY))
        result.scoreable = task.get("scoreable") is not False
        if result.arm not in ARM_CONTRACTS:
            result.experiment_revision = LEGACY_EXPERIMENT_REVISION
            result.parity_arm = ""
            result.oracle_class = "legacy"
            result.headline_eligible_v1 = False
            return
        policy = self.task_policies.get(result.task_id) if self.task_policies is not None else None
        if policy is None:
            raise ValueError(f"no locked task policy for canonical task {result.task_id!r}")
        result.experiment_revision = policy.experiment_revision
        result.parity_arm = result.arm
        result.oracle_class = policy.oracle_class
        result.headline_eligible_v1 = policy.headline_eligible_v1
        result.scoreable = policy.scoreable

    def run(self, task: dict, arm: str, update_fn: Optional[Any] = None) -> BenchRun:
        """Run one task in one arm; parse stream-json for metrics.

        When a resume cache is active and holds a matching prior result for this
        (task, arm, model, repo_sha, index_sha, task_hash) tuple, that line is reused
        (``resumed=True``) and the claude subprocess is skipped entirely.

        Args:
            task: Task dict from tasks-bench.json.
            arm: "plain" or "codemap".
            update_fn: Optional ``(elapsed_s, run)`` callback forwarded to ``_stream``
                for live sub-progress display.

        Returns:
            BenchRun with all metrics filled.
        """
        task_hash = _task_hash(task)
        if arm in ARM_CONTRACTS:
            if self.suite_hash != PRIMARY_SUITE_HASH:
                raise ValueError("canonical run requires the locked primary suite hash")
            _validate_canonical_task(task)
        if self.resume_cache is not None:
            key = (task["id"], arm, self.model_short, self.repo_sha, self.index_sha, task_hash)
            cached = self.resume_cache.get(key)
            expected_revision = PARITY_EXPERIMENT_REVISION if arm in ARM_CONTRACTS else LEGACY_EXPERIMENT_REVISION
            expected_contract_hash = _arm_contract_hash(arm)
            cached_revision = cached.get("experiment_revision", LEGACY_EXPERIMENT_REVISION) if cached else None
            cached_contract_hash = cached.get("arm_contract_hash", "") if cached else None
            if (
                cached is not None
                and cached_revision == expected_revision
                and cached_contract_hash == expected_contract_hash
            ):
                run = _run_from_cached(cached)
                self._stamp_provenance(run, task, task_hash)
                return run
        result = self._execute(task, arm, update_fn=update_fn)
        self._stamp_provenance(result, task, task_hash)
        return result

    def _execute(self, task: dict, arm: str, update_fn: Optional[Any] = None) -> BenchRun:
        """Execute one (task, arm) via the claude subprocess and score the output.

        Split out of :meth:`run` so the resume fast-path stays a thin guard. Contains the
        subprocess launch, retry loop, incomplete/scoreable handling, and contamination guards.

        Args:
            task: Task dict from tasks-bench.json.
            arm: "plain" or "codemap".
            update_fn: Optional live-progress callback forwarded to ``_stream``.

        Returns:
            A freshly executed BenchRun (provenance stamped by the caller).
        """
        system = _build_system_prompt(arm, _REPO_NAME, str(self.repo_path), str(self.index_path))
        disallow_flags = _ARM_DISALLOWED.get(arm, [])
        allow_flags = _ARM_ALLOWED.get(arm, [])
        # Codex has no equivalent public turn cap, so parity arms use only their shared wall clock.
        # Legacy labels retain their exact historical per-task cap.
        turn_flags = [] if arm in ARM_CONTRACTS else ["--max-turns", str(_max_turns_for_task(task))]
        cmd = [
            *_CMD,
            *turn_flags,
            "--model",
            self.model_id,
            *disallow_flags,
            *allow_flags,
            "--system-prompt",
            system,
            materialize_task_prompt(task),
        ]
        # workflow_type groups tasks at a coarser level than task_type; default to task_type
        # so legacy task files (no workflow_type field) still group sensibly.
        workflow_type = task.get("workflow_type") or task["type"]
        task_capability_strata = capability_strata(task)
        result = BenchRun(
            arm=arm,
            task_id=task["id"],
            task_type=task["type"],
            model=self.model_short,
            success=False,
            workflow_type=workflow_type,
            capability_strata=task_capability_strata,
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
                capability_strata=task_capability_strata,
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
            shared_evaluation = _SHARED_EVALUATORS.evaluate(task, result.output_text)
            if not isinstance(shared_evaluation, _BenchEvaluationResult):
                raise TypeError("shared evaluator did not return Claude benchmark diagnostics")
            result.quality = shared_evaluation.bench_quality
            result.quality_components = shared_evaluation.components
            # Contamination guards:
            #  - plain arm: detect codemap binary OR prebuilt-index access that bypassed the disallow
            #    list — either invoked via python3 path instead of bare scan-query, or a raw
            #    Read/cat of .cache/{codemap,scan}/*.json (the full structural answer). The primary
            #    signal is result.contamination_hits, counted in _handle against the FULL untruncated
            #    tool input; the truncated tool_log scan is kept as a fallback.
            #  - either arm: detect reads of ground-truth answer files (tasks-bench.json,
            #    benchmark results) which would let the agent copy the expected answer.
            _ANSWER_MARKERS = ("tasks-bench", "benchmarks/results", "/benchmarks/")
            _log_contaminated = any(marker in entry for entry in result.tool_log for marker in _CONTAMINATION_MARKERS)
            if _transport_arm(arm) == "plain" and (result.contamination_hits > 0 or _log_contaminated):
                result.error = "contaminated"
                result.quality = BenchQuality(scored=False)
            elif any(marker in entry for entry in result.tool_log for marker in _ANSWER_MARKERS):
                result.error = "answer_file_read"
                result.quality = BenchQuality(scored=False)

        if arm == "C_strict":
            result.compliance = result.scan_query_calls > 0
        result.contaminated = result.error in {"contaminated", "answer_file_read"}
        if arm in ARM_CONTRACTS:
            result.treatment_adherence = treatment_adherence(
                arm,
                codemap_use_compliance=result.compliance,
                contaminated=result.contaminated,
            )
        return result

    def _env(self, arm: str) -> dict[str, str]:
        """Return subprocess environment; arm-aware to avoid control-arm contamination.

        Args:
            arm: "plain" or "codemap". Plain arm gets no CODEMAP_* vars or bin PATH.

        Returns:
            Dict suitable for subprocess.Popen env argument.
        """
        if _transport_arm(arm) == "plain":
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

        def _on_event(event: dict, ts: float) -> None:
            self._handle(event, result, pending, ts)

        outcome = stream_claude(
            cmd,
            timeout=self.timeout,
            cwd=self.repo_path,
            env=self._env(arm),
            on_event=_on_event,
            update_fn=(lambda elapsed: update_fn(elapsed, result)) if update_fn is not None else None,
        )
        # Map mechanics onto the run, preserving this lane's error precedence and the incomplete flag:
        # stderr (on a non-success run) → timeout (marks incomplete) → any unexpected exception.
        result.elapsed_s = outcome.elapsed_s
        if not result.success and not result.error and outcome.stderr:
            result.error = outcome.stderr.strip()[:300]
        if outcome.returncode is not None and outcome.returncode < 0 and not result.error:
            result.error = f"timeout ({self.timeout}s)"
            result.incomplete = True
        if outcome.exc_timeout:
            result.error = f"timeout ({self.timeout}s)"
            result.incomplete = True
        if outcome.error and not result.error:
            result.error = outcome.error

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
        # Scan for the scan-query JSON object even when it is embedded in prose, truncated, or
        # concatenated — requiring the whole tool_result to be pure JSON silently dropped index
        # metadata (~16/17 codemap runs recorded no method despite running rdeps).
        for raw in texts:
            for parsed in _embedded_json_objects(raw):
                idx = parsed.get("index")
                if not isinstance(idx, dict):
                    continue
                method = idx.get("method", "")
                if method and method not in result.codemap_methods:
                    result.codemap_methods.append(method)
                for nc in idx.get("not_covered", []):
                    if nc not in result.codemap_not_covered:
                        result.codemap_not_covered.append(nc)

    @staticmethod
    def _record_tool_use(name: str, inp: dict, result: BenchRun) -> None:
        """Record one tool_use block into *result*: per-tool counters, contamination, and tool_log.

        Args:
            name: Tool name (e.g. "Grep", "Bash", "Read", "Skill").
            inp: The tool_use ``input`` dict.
            result: BenchRun to update in-place.
        """
        if name == "Grep":
            result.grep_calls += 1
            result.tool_log.append(f"Grep: {inp.get('pattern', '')[:60]!r}")
        elif name == "Bash":
            result.bash_calls += 1
            cmd = inp.get("command", "")
            if "scan-query" in cmd or "codemap-py/bin" in cmd:
                result.scan_query_calls += 1
                sub = _parse_scan_query_subcommand(cmd)
                if sub is not None:
                    result.scan_query_subcommands[sub] = result.scan_query_subcommands.get(sub, 0) + 1
                # In batch mode, attribute each inner {cmd} to its own subcommand
                # counter so a batched fn-rdeps counts as fn-rdeps, and flag used_batch for the run.
                # The outer `batch` counter above is kept so total batch invocations stay visible.
                if sub == _BATCH_SUBCOMMAND:
                    result.used_batch = True
                    for inner in _parse_batch_subcommands(cmd):
                        result.scan_query_subcommands[inner] = result.scan_query_subcommands.get(inner, 0) + 1
            # Count index/binary access on the FULL command (plain arm only).
            if _transport_arm(result.arm) == "plain" and _is_contaminating_access(cmd):
                result.contamination_hits += 1
            result.tool_log.append(f"Bash: {cmd[:80]}")
        elif name == "Read":
            result.read_calls += 1
            file_path = inp.get("file_path", "")
            # A plain-arm Read of the prebuilt index is contamination; check the FULL
            # untruncated path before it is clipped for the display log.
            if _transport_arm(result.arm) == "plain" and _is_contaminating_access(file_path):
                result.contamination_hits += 1
            result.tool_log.append(f"Read: {file_path[:60]}")
        elif name == "Skill":
            result.skill_calls += 1
            _sk = inp.get("skill", "") or ""
            _sk_short = _sk.split(":")[-1] if ":" in _sk else _sk
            result.skill_counts[_sk_short] = result.skill_counts.get(_sk_short, 0) + 1
            result.tool_log.append(f"Skill: {_sk} {inp.get('args', '')}".strip())
        else:
            first_val = next((v for v in inp.values() if isinstance(v, str)), "") if inp else ""
            result.tool_log.append(f"{name}: {first_val[:50]}" if first_val else name)

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
                    pending[block.get("id", "")] = ts
                    self._record_tool_use(block.get("name", ""), block.get("input", {}) or {}, result)

        elif etype == "user":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") != "tool_result":
                    continue
                tool_id = block.get("tool_use_id", "")
                pending.pop(tool_id, None)
                if _transport_arm(result.arm) == "codemap":
                    self._extract_codemap_meta(block, result)

        elif etype == "result":
            # Anthropic's own cost (total_cost_usd) is captured here — current prices, cache-aware,
            # per model. When the result event omits it the $ column is dropped (in/out tokens remain).
            u = parse_result_usage(event)
            result.input_tokens = u.input_tokens
            result.output_tokens = u.output_tokens
            result.cost_usd = u.cost_usd
            result.success = u.success
            if not result.success and not result.error:
                result.error = u.subtype


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
    """Recall value in [0, 1] for summary display.

    Returns the true recall when an evaluator sets it. Evaluators that score by
    line tolerance or count (symbol_extraction, code_quality, count-based
    review_assistance) never populate ``recall``; for those the 0-1 signal is
    binary correctness over the task's ground truth — 1.0 when the answer landed
    within tolerance, 0.0 otherwise (a scored-but-failed extraction is a genuine
    miss, not an unknown). The former ``metric_got / metric_expected`` fallback
    is a raw line-number / count ratio that can exceed 1.0, so it is *not* recall
    and must not wear the recall label; the raw values remain in scoring_detail
    for diagnostics.

    Args:
        run: A completed benchmark run, or None.

    Returns:
        Recall as a float in [0, 1], or None when the run was not scored or its
        answer could not be parsed (extraction_failed) — parse failures are a
        separate signal from a wrong-but-parsed answer (which scores 0.0).

    Examples:
        >>> _effective_recall(None) is None
        True
    """
    if run is None or not run.quality.scored:
        return None
    if run.quality.extraction_failed:
        # Parse failure — the harness could not extract an answer from the output.
        # This is a parser-coverage signal, NOT evaluation degradation, so it is
        # kept out of the recall metric (surfaced separately with a distinct sign).
        return None
    if run.quality.recall is not None:
        return run.quality.recall
    return 1.0 if run.quality.correct else 0.0


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
    plain_cost: float | None
    codemap_cost: float | None
    cost_ratio: float | None  # codemap $ / plain $ — price-accurate cross-arm comparison


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
        # Price-accurate cross-arm cost from each run's captured total_cost_usd (None when absent).
        plain_cost = plain.cost_usd if plain and plain.cost_usd else None
        codemap_cost = codemap.cost_usd if codemap and codemap.cost_usd else None
        cost_ratio = _safe_ratio(codemap_cost, plain_cost)
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
                plain_cost=plain_cost,
                codemap_cost=codemap_cost,
                cost_ratio=cost_ratio,
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
        >>> run = BenchRun(
        ...     arm="plain", task_id="X", task_type="symbol_extraction", model="haiku", success=True,
        ...     workflow_type="query",
        ... )
        >>> _workflow_type_of(run)
        'query'
        >>> run = BenchRun(arm="plain", task_id="X", task_type="symbol_extraction", model="haiku", success=True)
        >>> _workflow_type_of(run)
        'symbol_extraction'
    """
    return run.workflow_type or run.task_type


def _print_workflow_breakdown(runs: list[BenchRun]) -> None:
    """Print a per-workflow_type breakdown of token ratio and accuracy.

    Groups runs by :func:`_workflow_type_of`. For each workflow type, reports
    the median and mean codemap/plain token ratio (computed per task that has both arms)
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
    hdr = f"  {'workflow_type':<22}  {'n_tasks':>7}  {'tok× (med)':>10}  {'tok× (mean)':>11}  {'cm_acc':>10}"
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
        ratio_mean_str = f"{statistics.mean(ratios):>11.2f}" if ratios else f"{'n/a':>11}"

        # Headline accuracy excludes self-consistency (index-derived GT) runs — same rule as the
        # top-level per-arm accuracy, so the per-workflow_type figure stays consistent with it.
        cm_scored = [
            r
            for r in wf_runs
            if r.arm == "codemap"
            and r.quality.scored
            and not r.quality.extraction_failed
            and not r.incomplete
            and not _is_self_consistency(r)
        ]
        if cm_scored:
            n_correct = sum(1 for r in cm_scored if r.quality.correct)
            acc_str = f"{n_correct / len(cm_scored):>9.1%}"
        else:
            acc_str = f"{'n/a':>10}"
        n_tasks = len(by_task)
        print(f"  {wf:<22}  {n_tasks:>7}  {ratio_str}  {ratio_mean_str}  {acc_str}")


def _arm_extracted(run: Optional[BenchRun]) -> bool:
    """Return True when *run* produced a scored, extracted, completed metric.

    A run counts as "extracted" only when it was scored, did not fail extraction, and was not cut
    off by the turn budget. Contaminated / answer-file-read runs carry ``scored=False`` and are
    therefore excluded too.

    Args:
        run: A benchmark run for one arm, or None when that arm did not run.

    Returns:
        True when the run yielded a usable score for the paired comparison.
    """
    return bool(run and run.quality.scored and not run.quality.extraction_failed and not run.incomplete)


def _is_self_consistency(run: Optional[BenchRun]) -> bool:
    """Return True when *run* is a self-consistency (index-derived ground truth) task.

    Args:
        run: A benchmark run, or None.

    Returns:
        True when the run carries the ``self_consistency`` flag.

    Examples:
        >>> _is_self_consistency(None)
        False
        >>> r = BenchRun(arm="codemap", task_id="CQ-02", task_type="code_quality", model="haiku", success=True)
        >>> r.self_consistency = True
        >>> _is_self_consistency(r)
        True
    """
    return bool(run and run.self_consistency)


def _paired_accuracy(runs: list[BenchRun]) -> Optional[dict[str, int]]:
    """Compute paired accuracy over tasks where BOTH arms extracted successfully.

    The per-arm accuracy printed elsewhere drops ``extraction_failed`` runs independently per arm, so
    the plain and codemap figures are computed over different task subsets and different n — an
    unpaired comparison. This view restricts both arms to the SAME task set: only tasks where the
    plain AND the codemap run were each scored, extracted a metric, and completed. Both arm accuracies
    then share one denominator, the paired-n, so the headline comparison is like-for-like.

    Self-consistency tasks (index-derived ground truth) are excluded — the codemap arm would be scored
    against the same index it queries. They are reported separately by :func:`_print_self_consistency`.

    Args:
        runs: All benchmark runs (both arms, all tasks).

    Returns:
        Dict with ``n`` (paired task count), ``plain_correct``, and ``codemap_correct``; None when no
        task has both arms extracted.
    """
    by_task: dict[str, dict[str, BenchRun]] = defaultdict(dict)
    for r in runs:
        by_task[r.task_id][r.arm] = r
    paired = [
        arms
        for arms in by_task.values()
        if _arm_extracted(arms.get("plain"))
        and _arm_extracted(arms.get("codemap"))
        and not _is_self_consistency(arms.get("codemap"))
    ]
    if not paired:
        return None
    return {
        "n": len(paired),
        "plain_correct": sum(1 for a in paired if a["plain"].quality.correct),
        "codemap_correct": sum(1 for a in paired if a["codemap"].quality.correct),
    }


def _print_self_consistency(runs: list[BenchRun]) -> None:
    """Print a separate self-consistency accuracy row (index-derived ground truth).

    These tasks (e.g. uncovered / broken-xref counts) are excluded from the headline accuracy
    aggregates because the codemap arm is scored against the very index it queries. Reporting them
    apart keeps the headline honest while still surfacing the self-agreement signal.

    Args:
        runs: All benchmark runs (both arms, all tasks).
    """
    sc = [r for r in runs if _is_self_consistency(r) and _arm_extracted(r)]
    if not sc:
        return
    ids = sorted({r.task_id for r in sc})
    print(f"\n  Self-consistency (index-derived GT — excluded from headline accuracy; tasks: {', '.join(ids)}):")
    for arm in ("plain", "codemap"):
        arm_sc = [r for r in sc if r.arm == arm]
        if not arm_sc:
            continue
        n_correct = sum(1 for r in arm_sc if r.quality.correct)
        print(f"    {arm}   = {n_correct / len(arm_sc):.1%}  ({n_correct}/{len(arm_sc)})")


def _print_paired_accuracy(runs: list[BenchRun]) -> None:
    """Print the paired accuracy view (both arms extracted, shared denominator).

    Args:
        runs: All benchmark runs (both arms, all tasks).
    """
    paired = _paired_accuracy(runs)
    if paired is None:
        return
    n = paired["n"]
    pc = paired["plain_correct"]
    cc = paired["codemap_correct"]
    print(f"\n  Paired accuracy (both arms extracted, paired-n={n}):")
    print(f"    plain   = {pc / n:.1%}  ({pc}/{n})")
    print(f"    codemap = {cc / n:.1%}  ({cc}/{n})")


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

    print(f"\n\n{'=' * 64}")
    print(f"  Codemap benchmark — model={model}")
    print(f"{'=' * 64}")

    # Build display table manually to support colored Δrecall column.
    hdr = f"{'task_id':<9}  {'plain_tok':>9}  {'cm_tok':>9}  {'tok×':>5}  {'$×':>5}  {'plain_t':>7}  {'cm_t':>7}  {'t×':>5}  {'Δrecall':>9}"
    print(hdr)
    print("-" * len(hdr))
    for _, row in df.iterrows():
        tid = str(row["task_id"])
        ptok = f"{int(row['plain_tok']):>9,}" if pd.notna(row["plain_tok"]) else f"{'n/a':>9}"
        ctok = f"{int(row['codemap_tok']):>9,}" if pd.notna(row["codemap_tok"]) else f"{'n/a':>9}"
        tratio = f"{row['ratio']:>5.2f}" if pd.notna(row["ratio"]) else f"{'n/a':>5}"
        cratio = f"{row['cost_ratio']:>5.2f}" if pd.notna(row.get("cost_ratio", float("nan"))) else f"{'n/a':>5}"
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
        print(f"{tid:<9}  {ptok}  {ctok}  {tratio}  {cratio}  {pt}  {ct}  {trm}  {recall_col}")

    valid = df.dropna(subset=["ratio"])
    if not valid.empty:
        ratios = valid["ratio"].tolist()
        print(
            f"\nToken ratio (codemap/plain):  median={statistics.median(ratios):.2f}  mean={statistics.mean(ratios):.2f}  [{min(ratios):.2f}–{max(ratios):.2f}]"
        )

    valid_c = df.dropna(subset=["cost_ratio"])
    if not valid_c.empty:
        cost_ratios = valid_c["cost_ratio"].tolist()
        print(
            f"Cost ratio  (codemap/plain):  median={statistics.median(cost_ratios):.2f}  mean={statistics.mean(cost_ratios):.2f}  [{min(cost_ratios):.2f}–{max(cost_ratios):.2f}]  (price-accurate)"
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
            f"  plain   median={fmt_time(statistics.median(plain_times))}  mean={fmt_time(statistics.mean(plain_times))}"
        )
        print(
            f"  codemap median={fmt_time(statistics.median(codemap_times))}  mean={fmt_time(statistics.mean(codemap_times))}"
        )

    for arm in ("plain", "codemap"):
        # Denominator matches canonical accuracy and _arm_extracted: scored, parsed, and
        # NOT budget-cut. Timeout-incomplete runs get scored on partial output but must be excluded
        # here too, else the per-arm % counts a run the headline verdict drops.
        arm_runs = [r for r in runs if r.arm == arm and _arm_extracted(r)]
        extraction_failed_runs = [r for r in runs if r.arm == arm and r.quality.extraction_failed]
        incomplete_runs = [r for r in runs if r.arm == arm and r.incomplete]
        contaminated_runs = [r for r in runs if r.arm == arm and r.error == "contaminated"]
        # Headline accuracy excludes self-consistency (index-derived GT) runs; they are reported by
        # _print_self_consistency below so the codemap arm is never credited for agreeing with itself.
        headline_runs = [r for r in arm_runs if not _is_self_consistency(r)]
        if headline_runs:
            n_correct = sum(1 for r in headline_runs if r.quality.correct)
            acc = n_correct / len(headline_runs)
            print(f"  {arm} accuracy = {acc:.1%}  ({n_correct}/{len(headline_runs)} scored)")
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

    # Paired accuracy: both arms scored over the SAME both-extracted task set. The
    # per-arm figures above use different denominators (each arm drops its own extraction failures),
    # so the paired view is the like-for-like headline comparison with its shared n stated.
    _print_paired_accuracy(runs)

    # Self-consistency row: index-derived GT tasks, reported apart from the headline accuracy.
    _print_self_consistency(runs)

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


@dataclass(frozen=True)
class _RichSubProgressUpdate:
    """Live sub-progress callback for one (task, arm) combo.

    Instances are passed as ``BenchRunner.run(update_fn=...)``: each call refreshes the outer
    bar's description and the per-run sub-bar with the current turn count and tool tallies.

    Attributes:
        progress: Active rich ``Progress`` instance.
        outer_id: Progress task id of the outer (whole-run) bar.
        sub_id: Progress task id of this combo's sub-bar.
        task_id: Benchmark task id shown in the outer description.
        arm_name: Arm label shown in the outer description.

    Examples:
        >>> update = _RichSubProgressUpdate(None, 0, 1, "SE-01", "codemap")
        >>> update.task_id, update.arm_name
        ('SE-01', 'codemap')
    """

    progress: Any
    outer_id: Any
    sub_id: Any
    task_id: str
    arm_name: str

    def __call__(self, elapsed: float, run: BenchRun) -> None:
        """Refresh both progress rows from the in-flight run.

        Args:
            elapsed: Seconds since the run's subprocess started.
            run: The ``BenchRun`` being populated in place.
        """
        calls = run.grep_calls + run.bash_calls + run.skill_calls
        sk = run.skill_calls
        tool_live = f"B={run.bash_calls} G={run.grep_calls} R={run.read_calls} SQ={run.scan_query_calls} Sk={sk}"
        self.progress.update(self.outer_id, description=f"{self.task_id} {self.arm_name}")
        self.progress.update(
            self.sub_id,
            completed=run.turn_count,
            description=f"  {fmt_time(elapsed)} calls={calls} {tool_live}",
        )


@dataclass
class _StructuralRunLoop:
    """Per-run execution state shared by the combo and task-arm drivers.

    Bundles what a single ``main()`` invocation needs to execute one (task, arm) combo, so the
    drivers are module-level methods instead of closures over ``main``'s locals.

    Attributes:
        runner: Configured ``BenchRunner`` executing each combo.
        repo_path: Root of the target repository clone (sandbox + staging root).
        arm_orders: Per-task arm labels in their actual execution order.
        patch_ids: Task ids that carry a patch reference and may be sandbox-scored.
        runs: Accumulator every completed run is appended to, in completion order.

    Examples:
        >>> loop = _StructuralRunLoop(None, Path("."), {"SE-01": ("codemap",)}, {"PT-01"}, [])
        >>> loop.arm_orders["SE-01"], sorted(loop.patch_ids)
        (('codemap',), ['PT-01'])
    """

    runner: Any
    repo_path: Path
    arm_orders: Mapping[str, tuple[str, ...]]
    patch_ids: set[str]
    runs: list[BenchRun] = field(default_factory=list)

    def run_combo(self, task: dict, arm: str, log_fn: Any, update_fn: Optional[Any] = None) -> BenchRun:
        """Execute one (task, arm) combo, record it, and log its one-line result.

        Args:
            task: Task dict to run.
            arm: Arm label to run it under.
            log_fn: Single-argument printer for the result line (rich console or ``print``).
            update_fn: Optional live-progress callback forwarded to the runner.

        Returns:
            The completed ``BenchRun``, already appended to ``self.runs``.
        """
        run = self.runner.run(task, arm, update_fn=update_fn)
        # Tier E: for scoreable patch tasks, extract the agent diff and execute it in a
        # sandbox to record whether the failing test passes. Non-scoreable stubs (placeholder
        # SHA / no reference) skip the sandbox and report structural GT only.
        if task["id"] in self.patch_ids and task.get("scoreable") is not False and run.success:
            diff_text = _extract_diff(run.output_text)
            if diff_text is not None:
                sandbox = PatchSandbox(self.repo_path, task)
                try:
                    run.patch_pass = sandbox.run(diff_text)
                except SandboxError as exc:
                    run.error = run.error or f"sandbox_error: {exc}"
                    run.patch_pass = None
                run.mutation_evidence = sandbox.last_mutation_evidence
            else:
                # No diff block in output — agent produced prose only; scores as a fail.
                run.patch_pass = False
        self.runs.append(run)
        status = "✓" if run.success else "✗"
        correct = _run_correct_symbol(run)
        # in/out token split (k/M via shared fmt_tok) plus Anthropic's own per-run cost. The $ is
        # omitted (in/out only) when the run carried no total_cost_usd — no price table to go stale.
        cost_str = f" ${run.cost_usd:.3f}" if run.cost_usd else ""
        _eff = _effective_recall(run)
        # Three distinct states, never conflated:
        #   number  — scored & parsed: recall in [0, 1] (0.000 = wrong answer, real miss)
        #   !parse  — scored but answer unparsable: parser-coverage issue, NOT degradation
        #   ?unscored — not scored (for example, contaminated or non-evaluable)
        if _eff is not None:
            q_str = f"{_eff:.3f}"
        elif run.quality.scored and run.quality.extraction_failed:
            q_str = "!parse"
        else:
            q_str = "?unscored"
        # Sk (Skill-tool calls) omitted from the terminal line: the codemap arm queries
        # scan-query via Bash (counted in SQ), never the Skill tool, so it is always 0 here.
        # The raw skill_counts field is still recorded in the results JSONL if it ever fires.
        tool_summary = f"B={run.bash_calls:2d} G={run.grep_calls:2d} R={run.read_calls:2d} SQ={run.scan_query_calls:2d}"
        # Ranking evaluators retain their complete oracle in telemetry; the terminal total is
        # the number of expected rows, matching the scalar-count meaning used by other tasks.
        metric_expected = run.quality.metric_expected
        metric_total = len(metric_expected) if isinstance(metric_expected, list) else metric_expected
        metric_total_str = "?" if metric_total is None else str(metric_total)
        log_fn(
            f"  {status}{correct} {task['id']} {arm:<{_RESULT_ARM_WIDTH}}"
            f"\ttok: in={fmt_tok(run.input_tokens):>6} out={fmt_tok(run.output_tokens):>5}{cost_str}"
            f" time={fmt_time(run.elapsed_s):<6} recall={q_str:<9}"
            f"\ttotal={metric_total_str:>4}\t{tool_summary}"
        )
        return run

    def _run_arms(self, task: dict, progress: Any, outer: Any) -> None:
        """Run every selected arm for one task against the current (possibly staged) tree.

        Args:
            task: Task dict.
            progress: Active rich Progress instance.
            outer: Outer progress task id.
        """
        for arm_name in self.arm_orders[task["id"]]:
            task_max_turns = _max_turns_for_task(task)
            sub = progress.add_task("  0s calls=0", total=task_max_turns)
            progress.update(outer, description=f"{task['id']} {arm_name}")
            self.run_combo(
                task,
                arm_name,
                progress.console.print,
                update_fn=_RichSubProgressUpdate(progress, outer, sub, task["id"], arm_name),
            )
            progress.remove_task(sub)
            progress.advance(outer)

    def run_task_arms(self, task: dict, progress: Any, outer: Any) -> None:
        """Run every selected arm for one task, staging a diff-impact change around both arms.

        A ``diff_impact`` task with a ``stage`` spec applies the synthetic change once (via
        :class:`DiffImpactStager`), runs BOTH arms against the staged tree, then reverts on block exit —
        so both arms see the identical change and the tree is restored regardless of per-arm outcome.
        Every other task runs its arms directly. Progress bookkeeping is unchanged.

        Args:
            task: Task dict.
            progress: Active rich Progress instance.
            outer: Outer progress task id.
        """
        stage_spec = task.get("stage") if task.get("type") == _DIFF_IMPACT_TYPE else None
        if stage_spec:
            with DiffImpactStager(self.repo_path, stage_spec):
                self._run_arms(task, progress, outer)
        else:
            self._run_arms(task, progress, outer)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(  # noqa: PLR0913 — fire CLI adapter: every param is a keyword flag with a default (0 required)
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
    resume: bool = False,
    profile: str = None,
    tiered: bool = False,
    dry_run: bool = False,
    provider_parity: bool = False,
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
        resume: Reuse matching prior results (same task/arm/model + repo/index/task provenance)
            from the results dir instead of re-executing them (CLI flag: ``--resume``).
        profile: Cost profile ``dev`` (haiku-only stratified subset, fast regression signal) or
            ``release`` (full matrix incl. RI). Absent → current behavior, unchanged.
        tiered: Tiered protocol (release companion): run haiku full, sonnet on the dev subset, and
            opus only on haiku/sonnet disagreements. Select the tier via ``--model`` per invocation.
        dry_run: Validate the locked inputs and print canonical A/B/C planned cells without Claude execution.
        provider_parity: Run the canonical A/B/C arms together in the shared deterministic order.
    """
    global _REPO_NAME, _REPO_NAMESPACE, _REPO_LOCAL_PATH

    if profile is not None and profile not in _PROFILES:
        print(f"ERROR: --profile must be one of {_PROFILES}, got {profile!r}")
        sys.exit(1)
    # The dev profile is a haiku-only fast signal — pin the model regardless of ``--model``.
    if profile == _PROFILE_DEV:
        model = _TIER_HAIKU

    # fire passes CLI string args regardless of type annotation — coerce Path args explicitly.
    if repo_path is not None:
        repo_path = Path(repo_path)
    if index_path is not None:
        index_path = Path(index_path)

    # Load raw tasks first — legacy arms intentionally remain usable when a later
    # parity revision no longer matches this checked-out source suite.
    try:
        with TASKS_FILE.open() as f:
            _raw = json.load(f)
        all_tasks = load_task_suite(TASKS_FILE)
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: cannot read {TASKS_FILE}: {exc}")
        sys.exit(1)
    task_policies: Mapping[str, TaskPolicy] | None = None

    if isinstance(_raw, dict):
        repo_meta = _raw.get("repo", {})
    else:
        repo_meta = {}

    # Populate repo identity globals from header (evaluators consume these)
    if repo_meta.get("name"):
        _REPO_NAME = repo_meta["name"]
    if repo_meta.get("namespace"):
        _REPO_NAMESPACE = list(repo_meta["namespace"])
    _REPO_LOCAL_PATH = repo_meta.get("local_path")

    # Append tasks from any ``--tasks-file``; scoreable depends on whether ground_truth is present.
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

    # Append patch tasks (Tier E) when ``--patch`` is set. Unlike ``--tasks-file`` tasks,
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
        if _REPO_LOCAL_PATH:
            _cands.append(Path(_REPO_LOCAL_PATH))  # header local_path = .sandbox/pytorch-lightning (run from root)
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

    # Provenance fingerprints — shared by task selection (tiered) and the runner (resume + stamping).
    repo_sha = _repo_sha(repo_path)
    index_sha = _index_sha(index_path)

    # Task IDs must exist before selection filters run so a typo fails loudly.
    if tasks:
        ids = set(tasks)
        missing = ids - {t["id"] for t in all_tasks}
        if missing:
            print(f"ERROR: task IDs not found: {sorted(missing)}")
            sys.exit(1)
    else:
        ids = None

    selection = TaskSelection(
        all_tasks=all_tasks,
        ids=ids,
        task_type=task_type,
        run_all=run_all,
        external_ids=set(external_ids),
        patch_ids=patch_id_set,
        profile=profile,
        tiered=tiered,
        model=model,
    )
    task_list = _select_tasks(selection, RESULTS_DIR, repo_sha, index_sha)
    if task_list is None:
        print("Specify --tasks, --task-type, --tasks-file, --patch, --all, or --profile")
        sys.exit(1)

    if not task_list:
        print("No tasks matched.")
        sys.exit(1)

    # Exclude tasks whose ground truth is still a placeholder (gt_pending): their stage anchors and
    # expected callers were authored without this target repo, so staging and scoring are unreliable
    # until `generate-tasks-bench.py --update` materialises them. The generator's validator already
    # honours this flag; the runner must too, or a stale DI anchor derails the run.
    pending = [t for t in task_list if gt_is_pending(t)]
    if pending:
        ids = ", ".join(t["id"] for t in pending)
        print(
            f"⊘ Skipping {len(pending)} task(s) with pending ground truth — run "
            f"`generate-tasks-bench.py --update` against the target repo to materialise them: {ids}"
        )
        task_list = [t for t in task_list if not gt_is_pending(t)]
    if not task_list:
        print("No runnable tasks after excluding pending ground truth.")
        sys.exit(1)

    # Determine arms. Provider-parity and dry runs plan the current canonical A/B/C
    # matrix; normal runs retain the historical legacy defaults until a caller
    # selects A/B/C.
    if provider_parity and arm != "all":
        print("ERROR: --provider-parity cannot be combined with a specific --arm")
        sys.exit(1)
    allowed_arms = {*ARMS, *PARITY_ARMS}
    canonical_matrix = provider_parity or (dry_run and arm == "all")
    arms_to_run = list(PARITY_ARMS) if canonical_matrix else (list(ARMS) if arm == "all" else [arm])
    invalid_arms = sorted(set(arms_to_run) - allowed_arms)
    if invalid_arms:
        print(f"ERROR: unsupported arm labels: {invalid_arms}")
        sys.exit(1)

    canonical_requested = dry_run or provider_parity or any(arm_name in ARM_CONTRACTS for arm_name in arms_to_run)
    if canonical_requested:
        try:
            _, task_policies = _load_primary_parity_contract()
            _validate_primary_runtime(repo_path, index_path)
        except (OSError, ValueError) as exc:
            print(f"ERROR: cannot start canonical parity run: {exc}")
            sys.exit(1)

    try:
        arm_orders = _arm_orders_by_task(
            task_list,
            arms_to_run,
            model=model,
            provider_parity=canonical_matrix,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    if dry_run:
        for task in task_list:
            for arm_name in arm_orders[task["id"]]:
                print(f"PLAN\t{task['id']}\t{arm_name}")
        return

    # Build runner
    model_short = model
    model_id = MODELS[model_short]
    run_timeout = (
        timeout
        if timeout is not None
        else PARITY_TIMEOUT_SECONDS
        if canonical_requested
        else MODEL_TIMEOUT[model_short]
    )
    resume_cache = _load_resume_cache(RESULTS_DIR) if resume else None
    runner = BenchRunner(
        model_short=model_short,
        model_id=model_id,
        repo_path=repo_path,
        index_path=index_path,
        timeout=run_timeout,
        resume_cache=resume_cache,
        task_policies=task_policies,
        suite_hash=PRIMARY_SUITE_HASH if canonical_requested else None,
        suite_raw_hash=PRIMARY_SUITE_RAW_HASH if canonical_requested else None,
    )

    print(f"\n{'─' * 64}")
    print(f"  ▶ RUN START — model={model_short}")
    print(f"{'─' * 64}")
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
    print("  MB  module_blast_radius   — enumerate modules that import a target (importer recall ≥ 0.70)")
    print()

    runs: list[BenchRun] = []
    combos = [(task, arm) for task in task_list for arm in arm_orders[task["id"]]]
    run_loop = _StructuralRunLoop(
        runner=runner,
        repo_path=repo_path,
        arm_orders=arm_orders,
        patch_ids=patch_id_set,
        runs=runs,
    )

    with make_progress(_console) as progress:
        total = len(combos)
        outer = progress.add_task("running", total=total)
        _dirty_skips: list[tuple[str, str]] = []  # DI tasks skipped (un-stageable), reported after the run
        for task in task_list:
            try:
                run_loop.run_task_arms(task, progress, outer)
            except DirtyTreeError as exc:
                # This diff-impact task could not stage its synthetic change — either the tree is
                # dirty, or a find-anchor is stale vs the current target repo. The stager already
                # reverted any partial edit (see __enter__), so skip THIS task and continue: one
                # un-stageable task must never abort the whole run or discard the summary and the
                # results already gathered for every other task.
                progress.console.print(f"[yellow]⚠ skipped DI task {task['id']} (cannot stage): {exc}[/yellow]")
                _dirty_skips.append((task["id"], str(exc)))

    _print_summary(runs, model_short)

    if not no_save:
        out = _save_results(runs, model_short)
        print(f"\nResults → {out}")

    if _dirty_skips:
        print(
            f"\n{len(_dirty_skips)} diff-impact task(s) skipped — could not stage (dirty tree or stale find-anchor vs the target repo):"
        )
        for tid, why in _dirty_skips:
            print(f"  {tid}: {why}")

    failed = [r for r in runs if not r.success]
    if failed:
        print(f"\n{len(failed)} run(s) failed:")
        for r in failed:
            print(f"  {r.task_id}/{r.arm}: {r.error}")
        sys.exit(1)


if __name__ == "__main__":
    fire.Fire(main)
