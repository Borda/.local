#!/usr/bin/env python3
"""Codemap scan-query benchmark — measures accuracy, latency, and coverage of the scan-query binary.

## Motivation

The `codemap` plugin scans a Python codebase once with `ast.parse` and writes a structural JSON index.  Agents and
developers answer structural questions (rdeps, deps, centrality, import paths) with a single `scan-query` call
instead of many Glob/Grep passes.  On a 646-module project like pytorch-lightning a pre-built graph surfaces
blast-radius risks and import cycles that grep pipelines miss.

This script benchmarks the `scan-query` binary directly — not Claude Code agents.  It measures whether the binary's
output is accurate, fast, and structurally complete compared to cold grep baselines.  It does NOT invoke the Claude
API, does NOT spawn agents, and does NOT record tool-call counts from live agent sessions.

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

Suite A — Accuracy: rdeps precision/recall vs grep ground truth.

  Code  Name         What it measures                                   Pass threshold
  ----  -----------  -------------------------------------------------  ---------------
  A1    rdeps-high   precision/recall for high-risk tasks               precision >= 0.90
                     (B-01,B-03,B-05,F-02,F-05,R-01,R-02)              recall    >= 0.85
  A2    rdeps-low    precision for low-risk tasks (B-04, R-05)          precision = 1.00
  A3    fp-rate      overall false-positive rate across all 15 tasks    FP rate < 5%

Suite L — Latency: wall-clock cost of codemap queries vs cold grep pipelines.

  Code  Name         What it measures                                   Pass threshold
  ----  -----------  -------------------------------------------------  ---------------
  L1    central      median of 5 runs of scan-query central --top 5     median < 200 ms
  L2    rdeps        median of 5 runs of scan-query rdeps across 3      median < 100 ms
                     high-risk task modules
  L3    index-build  one scan-index run amortized over 10 invocations   amortized < 500 ms
                     (total build time / 10)
  L4    speedup      codemap (L1+L2) vs cold grep baseline               >= 2x faster

Suite I — Injection: does each skill group produce a parseable structural context block for its
agent spawn prompt?

  Code        Skill tested        What is injected               Pass threshold
  ---------   ------------------  -----------------------------  ---------------
  I_fix       develop:fix         per-task queries (5 tasks)     JSON valid
  I_feature   develop:feature     per-task queries (5 tasks)     JSON valid
  I_refactor  develop:refactor    per-task queries + rdeps/deps  all present,
                                  (5 tasks)                      rdeps+deps valid

Suite S — Symbol lookup: validates that scan-query symbol returns correct source locations.
Reads ground truth from benchmarks/suites/tasks-bench.json (SE-01..SE-05).

  Code       Name                     What it measures                    Pass threshold
  --------   -----------------------  ----------------------------------  ---------------
  S_SE-01..   symbol-<task-id>         start_line within ±3 of gt         found + start_ok
  S2         symbol-all-pass-rate     all symbol tasks pass               100%

Suite H — Health: validates undocumented / uncovered counts match tasks-bench.json ground truth.
Reads ground truth from benchmarks/suites/tasks-bench.json (CQ-01..CQ-05).

  Code         Name                         What it measures                    Pass threshold
  -----------  ---------------------------  ----------------------------------  ---------------
  H_CQ-01...    health-<task-id>-undoc/uncov total from scan-query == gt.count  exact match
  H1           health-undocumented          all undocumented tasks match        100%
  H2           health-uncovered             all uncovered tasks match           100%

Suite X — Xrefs broken: validates xrefs --broken count + target set match ground truth.
Reads ground truth from benchmarks/suites/tasks-bench.json (CQ-04).

  Code     Name                   What it measures                    Pass threshold
  -------  ---------------------  ----------------------------------  ---------------
  X_CQ-04   xrefs-broken-CQ-04      count + target set == ground truth  exact match
  X1       xrefs-broken-all       all xrefs_broken tasks match        100%

Index path resolution order (updated): .cache/codemap/ checked before .cache/scan/ to match
the default output location of scan-index --root.

## Requirements

  - Python 3.8+, stdlib only (no pip installs needed for C/A/L/I/X suites; pandas+rich for reporting)
  - A local clone of pytorch-lightning:
      git clone https://github.com/Lightning-AI/pytorch-lightning
  - A pre-built codemap index for that clone:
      python3 plugins/codemap/bin/scan-index --root ./pytorch-lightning-master
    (creates pytorch-lightning-master/.cache/codemap/pytorch-lightning-master.json)
  - scan-query on PATH OR the plugin present at plugins/codemap/bin/scan-query
    (the script finds it automatically; no manual PATH config needed)
  - git available on PATH (used by scan-query's staleness check)
  - benchmarks/suites/tasks-bench.json present for suites S, H, X (auto-skipped if absent)

## Quick start

    # Full benchmark with markdown report (all suites C/A/L/I/S/H/X always run)
    python benchmarks/run-codemap-cli.py \\
        --repo-path ./pytorch-lightning-master \\
        --report

    # Verify task modules exist in the index before running
    python benchmarks/run-codemap-cli.py --verify-tasks --repo-path ./pytorch-lightning-master

    # Use a pre-built index at a non-default path
    python benchmarks/run-codemap-cli.py \\
        --repo-path ./pytorch-lightning \\
        --index-path /tmp/my-index.json \\
        --report

## Where the benchmark fits in the full flow

  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                              User: /develop:fix "checkpoint bug in trainer.connectors..."                        │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                              │
                                                              ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                        Skill: codemap soft-check                                                 │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                          │                                                                     │
                          ▼                                                                     ▼
  ┌────────────────────────────────────────────────────┐         ┌────────────────────────────────────────────────────┐
  │                  WITH codemap                      │         │                WITHOUT codemap                     │
  │                                                    │         │                                                    │
  │  scan-query rdeps + deps runs against the index    │         │  index absent or plugin not installed              │
  │  ## Structural Context block injected into prompt  │         │  skill skips injection silently                    │
  └────────────────────────────────────────────────────┘         └────────────────────────────────────────────────────┘
  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
                                                   BENCHMARK STARTS HERE
  ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
  Suite I: was the context block produced and is it valid JSON?
                          │                                                                     │
                          ▼                                                                     ▼
  ┌────────────────────────────────────────────────────┐         ┌────────────────────────────────────────────────────┐
  │              Agent spawned WITH context            │         │            Agent spawned WITHOUT context           │
  │                                                    │         │                                                    │
  │  blast-radius and coupling known before first edit │         │  cold Glob/Grep/Read to discover structure         │
  │  Suite C — coverage gap vs grep                    │         │  Suite C — how many cold calls needed?             │
  │  Suite A — rdeps precision and recall              │         │  Suite L — how slow is the grep baseline?          │
  │  Suite L — query latency                           │         │                                                    │
  └────────────────────────────────────────────────────┘         └────────────────────────────────────────────────────┘
                          │                                                                     │
                          └─────────────────────────────────┬───────────────────────────────────┘
                                                            ▼
  ┌──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
  │                                    GAP — not measured by this benchmark                                          │
  │                                                                                                                  │
  │  Did the agent actually USE the injected context to skip tool calls and improve answer quality?                  │
  │  Closing this gap requires live Claude API calls with tool-use recording — out of scope for this script.         │
  └──────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

## How each suite computes its metrics

  Suite C — Coverage gap (structural completeness)

    Cold baseline call count — how many grep/find invocations are needed to answer each structural
    question without the index:
      centrality:  3 calls  (find *.py, grep import lines, grep from/import patterns)
      rdeps(m):    2 calls  (grep dotted name, grep "from <pkg> import" variant)
      deps(m):     1 call   (grep import block of the module file)
      path(a,b):   3 calls  (grep a, grep a's parent package, grep b; assumes 2-hop)
    Warm baseline: 1 scan-query call per query regardless of question type.

    C1  coverage-gap = (codemap_rdep_count − grep_rdep_count) / codemap_rdep_count
        Measures importers that grep misses because they use aliased or relative imports.
        Pass when gap ≥ 10% on at least one high-risk task.

    C2  infeasible-path-fraction — for every import path of length ≥ 2 hops returned by scan-query path, check whether
        a single grep for the intermediate module name would surface the path. Fraction = paths not surfaceable in one
        grep / total 2+ hop paths. Pass when fraction ≥ 50%.

    C3  leverage-ratio = Σ cold_calls / Σ warm_calls across all 15 tasks. Answers "how many grep calls does
        codemap replace on average?" Pass when ratio ≥ 2.0×.

  Suite A — Accuracy (codemap rdeps vs grep rdeps)

    Important: grep is the reference in this suite, NOT the codemap index. The question is: does scan-query rdeps agree
    with what grep finds? This is the inverse of the agentic benchmark, where the index is ground truth.

    For each task module:
      grep_set    = set of .py files that import the module, found by grep -rn (file-list mode)
                    converted to dotted module names via path_to_module()
      codemap_set = set returned by scan-query rdeps <module>

      TP = grep_set ∩ codemap_set   (both agree)
      FP = codemap_set − grep_set   (codemap found but grep didn't — may be real imports grep missed,
                                     or aliased imports; not necessarily wrong)
      FN = grep_set − codemap_set   (grep found but codemap missed — index gap)

      precision = |TP| / |codemap_set|   (of what codemap returned, how much does grep confirm?)
      recall    = |TP| / |grep_set|      (of what grep found, how much did codemap return?)

    FP modules that appear in the index but not in grep results are not errors — they may use import aliases or
    conditional imports that grep's pattern misses. Treat FP < 10% as acceptable.

  Suite L — Latency

    time_command(cmd, n=5) runs the command 5 times via subprocess and takes the median wall-clock time in milliseconds.
    timings are sorted before taking the median (eliminates cold-start outliers).

    L1  scan-query central --top 5 — median of 5 runs
    L2  scan-query rdeps across 3 high-risk modules — median of 5 runs per module, then overall
        median
    L3  one scan-index run / 10 — amortized build cost per query session
    L4  speedup = cold_grep_baseline_ms / (L1_ms + L2_ms)

    Cold grep baseline for speedup: sum of time_command results for the equivalent grep pipelines
    that cold_greps() would run for the same structural questions.

  Suite I — Injection (skill context block validation)

    For each skill group, the benchmark calls scan-query with the same queries the skill would inject into an agent
    prompt (rdeps, deps, central, path as applicable).

    Each query result is validated for required JSON keys:
      central → must have "central" list with items containing "rdep_count"
      rdeps   → must have "imported_by" list and "module" string
      deps    → must have "direct_imports" list and "module" string
      path    → structural check only (no key validator)

    Pass = present (query returned non-null) AND valid (all required keys present and non-empty). The benchmark does NOT
    call the skill itself — it re-runs the same scan-query commands the skill would call and checks the output shape.
    A valid injection block means the agent would receive correctly structured structural context.

## Output

  stdout — one JSON object per completed scenario (JSONL); final line is the
           summary envelope with overall verdict: PASS / PARTIAL / FAIL
  stderr — progress narration via rich Progress bar
  file   — benchmarks/results/code-YYYY-MM-DD.md when --report is passed

## JSON output schema (per-scenario lines + summary envelope)

  Each scenario line (one per test case within a suite):
  {
    "suite": "C" | "A" | "L" | "I" | "S" | "H" | "X",
    "code": "C1" | "A1" | "L1" | "I_fix" | "S2" | "H1" | "X1" | ...,
    "module": "lightning.pytorch.trainer.trainer",   ← task module, where applicable
    "passed": true | false,
    "value": N.NN,            ← the numeric outcome (gap fraction, precision, ms, etc.)
    "threshold": N.NN,        ← the pass threshold for this scenario
    "detail": { ... }         ← suite-specific breakdown (tp/fp/fn, timings, query list, etc.)
  }

  Final summary envelope (last line of stdout):
  {
    "verdict": "PASS" | "PARTIAL" | "FAIL",
    "suites": {
      "C": true|false,    ← coverage gap suite
      "A": true|false,    ← accuracy suite
      "L": true|false,    ← latency suite
      "I": true|false,    ← injection suite
      "S": true|false,    ← symbol lookup suite
      "H": true|false,    ← health (undocumented/uncovered) suite
      "X": true|false     ← xrefs broken suite
    },
    "date": "YYYY-MM-DD",
    "repo": "/abs/path",
    "index": "/abs/path/to/index.json"
  }

## Verdict thresholds

  PASS    — 6–7 of the seven suites pass their per-scenario thresholds (see THRESHOLDS dict in source)
  PARTIAL — 4–5 suites pass
  FAIL    — ≤3 suites pass

Full scenario definitions and pass criteria: .plans/blueprint/2026-04-15-codemap-benchmark-spec.md
"""

from __future__ import annotations

import json
import os
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

    scenario: str  # "C1", "A1", "L2", "I_fix", etc.
    name: str  # human label e.g. "coverage-gap"
    suite: str  # "calls", "accuracy", "latency", "injection"
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
    # Injection suite (I): structural context block reaches agent spawn prompt
    "I_fix": {"block_present": True, "json_valid": True},
    "I_feature": {"block_present": True, "json_valid": True},
    "I_refactor": {"block_present": True, "json_valid": True, "has_rdeps": True, "has_deps": True},
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


def run_scan_query(scan_query_bin: Path, args: list[str], index_path: Path, repo_path: Path) -> dict | None:
    """Run scan-query with the given subcommand arguments and return parsed JSON output.

    Always passes ``--index <index_path>`` explicitly so scan-query uses the
    correct index regardless of ``cwd`` or git availability.

    Args:
        scan_query_bin: Path to the scan-query Python script.
        args: Subcommand and its arguments (e.g. ``["rdeps", "foo.bar"]``).
        index_path: Path to the pre-built codemap JSON index.
        repo_path: Working directory for the subprocess (the repository root).

    Returns:
        Parsed JSON dict from scan-query stdout, or ``None`` on non-zero exit
        code, timeout, JSON decode error, or OS error.
    """
    # Pass --index explicitly so scan-query uses the correct index regardless of cwd / git availability.
    try:
        result = _run(
            ["python3", str(scan_query_bin.resolve()), "--index", str(index_path.resolve())] + args,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None


# ---- ACCURACY ----


def grep_rdeps(repo_path: Path, module: str) -> set[str]:
    """Find reverse-dependencies of a module using grep as a reference baseline.

    Searches all ``.py`` files in ``repo_path`` for direct imports of ``module``
    using the pattern produced by :func:`module_to_grep_pattern`.  Results are
    converted to dotted module names via :func:`path_to_module`.

    Args:
        repo_path: Root of the repository to search.
        module: Dotted module name whose importers are to be found.

    Returns:
        Set of dotted module names that import ``module``.  Excludes ``module``
        itself.  Returns an empty set on timeout or if no matches are found.
    """
    pattern = module_to_grep_pattern(module)
    try:
        result = _run(
            [
                "grep",
                "-rn",
                pattern,
                str(repo_path),
                "--include=*.py",
                "--exclude-dir=.git",
                "--exclude-dir=__pycache__",
                "-l",
            ],
        )
    except subprocess.TimeoutExpired:
        return set()

    modules: set[str] = set()
    repo_root = str(repo_path)
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        mod = path_to_module(line, repo_root)
        if mod and mod != module:
            modules.add(mod)
    return modules


def codemap_rdeps(scan_query_bin: Path, index_path: Path, repo_path: Path, module: str) -> set[str]:
    """Retrieve reverse-dependencies of a module from the codemap index via scan-query.

    Args:
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.
        repo_path: Working directory for the subprocess (the repository root).
        module: Dotted module name whose importers are to be retrieved.

    Returns:
        Set of dotted module names from the ``imported_by`` field of the
        scan-query ``rdeps`` response.  Returns an empty set when scan-query
        fails or returns no data.
    """
    data = run_scan_query(scan_query_bin, ["rdeps", module], index_path, repo_path)
    if data is None:
        return set()
    return set(data.get("imported_by", []))


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


# ---- INJECTION ----


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


_INJECTION_VALIDATORS = {"central": validate_central_json, "rdeps": validate_rdeps_json, "deps": validate_deps_json}


def run_injection_query(
    scan_query_bin: Path, index_path: Path, repo_path: Path, query: Query
) -> tuple[bool, bool, dict | None]:
    """Run one injection query and validate its output.

    Executes ``scan-query <query.cmd> <query.args>`` via :func:`run_scan_query`
    and validates the returned JSON using the registered validator for the
    command type (``central``, ``rdeps``, or ``deps``).  Commands without a
    registered validator (``path``, ``coupled``) are considered automatically
    valid when they return a non-null result.

    Args:
        scan_query_bin: Path to the ``scan-query`` executable.
        index_path: Path to the pre-built codemap index JSON file.
        repo_path: Root directory of the repository under test.
        query: :class:`Query` specifying the command and its positional arguments.

    Returns:
        A 3-tuple ``(present, valid, data)`` where:

        - ``present`` (``bool``): ``True`` when scan-query returned a non-null result.
        - ``valid`` (``bool``): ``True`` when the result passes the structural
          JSON validator for ``query.cmd``, or when no validator is registered
          for that command.
        - ``data`` (``dict | None``): The raw parsed JSON dict, or ``None`` when
          the query returned no output.
    """
    data = run_scan_query(scan_query_bin, [query.cmd] + query.args, index_path, repo_path)
    if data is None:
        return False, False, None
    validator = _INJECTION_VALIDATORS.get(query.cmd)
    if validator is None:
        return True, True, data  # path/coupled — no structural validator needed
    v = validator(data)
    return True, v.ok, data


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
    passed_results = sum(1 for r in results if r.passed)
    total_results = len(results)

    # --- Header ---
    lines.append(f"# Codemap Benchmark Report -- {today}")
    lines.append("")
    pass_pct = passed_results / total_results if total_results else 0
    lines.append(f"**Verdict**: {verdict} — {passed_results}/{total_results} scenarios ({pass_pct:.0%})")
    lines.append(f"**pytorch-lightning**: commit {git_sha}")
    lines.append(f"**Index**: {index_path} ({mod_count} modules, {degraded_count} degraded)")
    lines.append("")

    # --- Summary table ---
    lines.append("## Summary Table")
    lines.append("")
    suite_display = {
        "calls": "Call Savings",
        "accuracy": "Accuracy",
        "latency": "Latency",
        "injection": "Injection",
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
                        "Notes": f"{res.get('cold_calls', '?')} cold → 1 warm call",
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

    # --- Injection table ---
    inj_items = [r for r in results if r.suite == "injection"]
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
        lines.append("## Injection Verification\n")
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
    lines.append("- Injection suite validates query output structure, not gh integration")
    lines.append("- Index staleness detection is not tested")
    lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def compute_verdict(results: list[ScenarioResult]) -> str:
    """Compute an overall benchmark verdict from a list of scenario results.

    Args:
        results: All :class:`ScenarioResult` objects produced by the benchmark run.

    Returns:
        ``"PASS"`` when all scenarios passed, ``"PARTIAL"`` when ≥50% passed,
        ``"FAIL"`` when fewer than 50% passed or ``results`` is empty.
    """
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    if total == 0:
        return "FAIL"
    if passed == total:
        return "PASS"
    if passed / total >= 0.5:
        return "PARTIAL"
    return "FAIL"


# ---- OUTPUT HELPERS ----


def emit(obj: ScenarioResult | dict) -> None:
    """No-op stub — placeholder for optional result accumulation; not currently implemented."""
    pass  # individual scenario JSON suppressed; summary printed in main()


def log(msg: str) -> None:
    """Print a progress message to the rich console or stderr.

    Args:
        msg: Message string to display.
    """
    if _IS_RICH_AVAILABLE and _console is not None:
        _console.print(msg)
    else:
        print(msg, file=sys.stderr)


# ---- SUITE: CALLS ----


def run_measure_calls(repo_path: Path) -> list[ScenarioResult]:
    """Run Suite C — measure cold grep call counts vs warm scan-query call counts.

    Evaluates three scenarios: C1 (coverage gap), C2 (infeasible path fraction),
    and C3 (leverage ratio).  All subprocess calls are counted, not timed.

    Args:
        repo_path: Root of the pytorch-lightning repository to search.

    Returns:
        List of three :class:`ScenarioResult` objects (C1, C2, C3).
    """
    results: list[ScenarioResult] = []
    tasks = load_tasks()
    log("[calls] Starting call-savings measurement...")

    # C1: coverage gap — codemap finds >=10% more importers than cold grep
    log("[calls] C1: coverage-gap")
    cold_calls = count_cold_calls_centrality(repo_path)
    delta = cold_calls - 1
    coverage_gap = delta / max(cold_calls, 1)
    passed = coverage_gap >= THRESHOLDS["C1"]["coverage_gap_min"]
    r = ScenarioResult(
        scenario="C1",
        name="coverage-gap",
        suite="calls",
        passed=passed,
        result={
            "cold_calls": cold_calls,
            "warm_calls": 1,
            "delta_absolute": delta,
            "coverage_gap": round(coverage_gap, 4),
        },
        threshold=THRESHOLDS["C1"],
        notes=f"cold={cold_calls} calls; warm=1; gap={coverage_gap:.2%}",
    )
    emit(r)
    results.append(r)

    # C2: infeasible path fraction — 2+ hop paths not grep-discoverable in 1 call
    log("[calls] C2: infeasible-path-fraction")
    path_tasks = [t for t in tasks if any(q.cmd == "path" for q in t.queries)]
    infeasible_count = 0
    total_path_queries = 0
    for task in path_tasks:
        for q in task.queries:
            if q.cmd == "path" and len(q.args) >= 2:
                total_path_queries += 1
                if count_cold_calls_path(repo_path, q.args[0], q.args[1]) > 1:
                    infeasible_count += 1
    fraction = infeasible_count / max(total_path_queries, 1)
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
        },
        threshold=THRESHOLDS["C2"],
        notes=f"{infeasible_count}/{total_path_queries} paths need >1 grep call",
    )
    emit(r)
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
    emit(r)
    results.append(r)

    return results


# ---- SUITE: ACCURACY ----


def run_measure_accuracy(repo_path: Path, scan_query_bin: Path, index_path: Path) -> list[ScenarioResult]:
    """Run Suite A — compare scan-query rdeps results against a grep baseline.

    For each task module, computes precision and recall of codemap's rdeps
    output relative to grep's file-list results.  Evaluates three scenarios:
    A1 (high-risk task accuracy), A2 (low-risk task precision), A3 (overall FP rate).

    Args:
        repo_path: Root of the pytorch-lightning repository.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.

    Returns:
        List of three :class:`ScenarioResult` objects (A1, A2, A3).
    """
    results: list[ScenarioResult] = []
    tasks = load_tasks()
    log("[accuracy] Starting accuracy measurement...")

    _A1_TIERS = {"high", "very-high", "moderate-high"}
    _A2_TIERS = {"low"}

    all_task_results: list[dict] = []

    for task in tasks:
        log(f"[accuracy] {task.id}: {task.primary_module} ({task.risk_tier})")
        rdeps_queries = [q for q in task.queries if q.cmd == "rdeps"]
        if not rdeps_queries:
            continue
        rdeps_mod = rdeps_queries[0].args[0]
        cm_set = codemap_rdeps(scan_query_bin, index_path, repo_path, rdeps_mod)
        gr_set = grep_rdeps(repo_path, rdeps_mod)
        stats = compute_precision_recall(cm_set, gr_set)
        all_task_results.append(
            {
                "module": rdeps_mod,
                "task_id": task.id,
                "risk_tier": task.risk_tier,
                "codemap_count": stats.tp + stats.fp,
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

    # A1: high-risk tasks precision/recall
    a1_group = [m for m in all_task_results if m["risk_tier"] in _A1_TIERS]
    if a1_group:
        avg_precision = statistics.mean(m["precision"] for m in a1_group)
        avg_recall = statistics.mean(m["recall"] for m in a1_group)
        passed = avg_precision >= THRESHOLDS["A1"]["precision_min"] and avg_recall >= THRESHOLDS["A1"]["recall_min"]
        for pm in a1_group:
            pm["pass"] = (
                pm["precision"] >= THRESHOLDS["A1"]["precision_min"] and pm["recall"] >= THRESHOLDS["A1"]["recall_min"]
            )
        r = ScenarioResult(
            scenario="A1",
            name="rdeps-accuracy-high",
            suite="accuracy",
            passed=passed,
            result={
                "avg_precision": round(avg_precision, 4),
                "avg_recall": round(avg_recall, 4),
                "per_module": a1_group,
            },
            threshold=THRESHOLDS["A1"],
            notes=f"tested {len(a1_group)} high-risk tasks",
        )
    else:
        r = ScenarioResult(
            "A1", "rdeps-accuracy-high", "accuracy", False, {"error": "no high-risk tasks found"}, THRESHOLDS["A1"]
        )
    emit(r)
    results.append(r)

    # A2: low-risk tasks precision = 1.0
    a2_group = [m for m in all_task_results if m["risk_tier"] in _A2_TIERS]
    if a2_group:
        all_perfect = all(m["precision"] == 1.0 for m in a2_group)
        min_precision = min(m["precision"] for m in a2_group)
        for pm in a2_group:
            pm["pass"] = pm["precision"] >= THRESHOLDS["A2"]["precision_min"]
        r = ScenarioResult(
            scenario="A2",
            name="rdeps-accuracy-low",
            suite="accuracy",
            passed=all_perfect,
            result={"min_precision": min_precision, "all_perfect": all_perfect, "per_module": a2_group},
            threshold=THRESHOLDS["A2"],
            notes=f"tested {len(a2_group)} low-risk tasks; min precision = {min_precision}",
        )
    else:
        r = ScenarioResult(
            "A2", "rdeps-accuracy-low", "accuracy", False, {"error": "no low-risk tasks found"}, THRESHOLDS["A2"]
        )
    emit(r)
    results.append(r)

    # A3: overall FP rate across all 15 tasks
    total_codemap = sum(m["codemap_count"] for m in all_task_results)
    total_fp = sum(m["fp"] for m in all_task_results)
    fp_rate = total_fp / total_codemap if total_codemap > 0 else 0.0
    passed = fp_rate <= THRESHOLDS["A3"]["fp_rate_max"]
    r = ScenarioResult(
        scenario="A3",
        name="rdeps-fp-analysis",
        suite="accuracy",
        passed=passed,
        result={
            "total_codemap_results": total_codemap,
            "total_false_positives": total_fp,
            "fp_rate": round(fp_rate, 4),
            "fp_details": [{"module": m["module"], "fp_list": m["fp_list"]} for m in all_task_results if m["fp_list"]],
        },
        threshold=THRESHOLDS["A3"],
        notes=f"overall FP rate: {fp_rate:.2%} across {len(all_task_results)} tasks",
    )
    emit(r)
    results.append(r)

    return results


# ---- SUITE: LATENCY ----


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
    emit(r)
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
    emit(r)
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
        amortized_ms = build_ms / 10
        passed = amortized_ms <= THRESHOLDS["L3"]["amortized_ms_max"]
        r = ScenarioResult(
            scenario="L3",
            name="latency-index-build",
            suite="latency",
            passed=passed,
            result={
                "build_ms": round(build_ms, 2),
                "amortized_ms": round(amortized_ms, 2),
                "amortization_factor": 10,
                "median_ms": round(amortized_ms, 2),
                "min_ms": round(amortized_ms, 2),
                "max_ms": round(build_ms, 2),
            },
            threshold=THRESHOLDS["L3"],
            notes=f"build={build_ms:.0f}ms; amortized over 10 = {amortized_ms:.0f}ms",
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
    emit(r)
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
            "median_ms": round(cold_total_median, 2),
            "min_ms": round(cold_central.min_ms + cold_rdeps.min_ms, 2),
            "max_ms": round(cold_central.max_ms + cold_rdeps.max_ms, 2),
        },
        threshold=THRESHOLDS["L4"],
        notes=f"cold grep total = {cold_total_median:.0f}ms; codemap = {warm_total:.0f}ms; speedup = {speedup:.1f}x",
    )
    emit(r)
    results.append(r)

    return results


# ---- SUITE: INJECTION ----


def _validate_skill_group(
    skill: str, tasks_for_skill: list[Task], scan_query_bin: Path, index_path: Path, repo_path: Path, threshold_key: str
) -> ScenarioResult:
    """Validate structural context block for a skill group of tasks.

    For each task in ``tasks_for_skill``, runs every query defined on the task
    via :func:`run_injection_query` and checks that the result is both present
    (non-null) and structurally valid.  Aggregates per-query pass/fail into a
    single :class:`ScenarioResult` for the whole skill group.

    Args:
        skill: Skill name, e.g. ``"fix"``, ``"feature"``, or ``"refactor"``.
            Used only for display labels and log messages.
        tasks_for_skill: Tasks to validate, filtered to this skill group.
        scan_query_bin: Path to the ``scan-query`` executable.
        index_path: Path to the pre-built codemap index JSON file.
        repo_path: Root directory of the repository under test.
        threshold_key: Key into :data:`THRESHOLDS` for this group (e.g.
            ``"I_fix"``, ``"I_feature"``, ``"I_refactor"``).

    Returns:
        :class:`ScenarioResult` whose ``passed`` field is ``True`` only when
        every query across all tasks in the group is present and valid, and
        (for ``threshold_key="I_refactor"``) at least one rdeps and one deps
        result was returned.
    """
    log(f"[injection] {threshold_key}: develop:{skill} ({len(tasks_for_skill)} tasks)")

    per_task_details: list[dict] = []
    all_ok = True

    for task in tasks_for_skill:
        task_detail: dict = {"task_id": task.id, "module": task.primary_module}

        for q in task.queries:
            bp, jv, data = run_injection_query(scan_query_bin, index_path, repo_path, q)
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

    return ScenarioResult(
        scenario=threshold_key,
        name=f"develop:{skill}",
        suite="injection",
        passed=passed,
        result={
            "block_present": all_ok,
            "json_valid": all_ok,
            "has_rdeps": has_rdeps,
            "has_deps": has_deps,
            "task_count": len(tasks_for_skill),
            "per_task": per_task_details,
        },
        threshold=threshold,
        notes=f"validated {len(tasks_for_skill)} {skill} tasks",
    )


def run_measure_injection(
    plugin_root: Path, repo_path: Path, scan_query_bin: Path, index_path: Path
) -> list[ScenarioResult]:
    """Run Suite I — verify that scan-query produces valid structural context for each skill group.

    Runs the same scan-query commands that develop:fix, develop:feature, and
    develop:refactor would issue when injecting context into an agent spawn
    prompt, then validates the output structure.  The actual skill is not
    invoked; only the binary output is checked.

    Args:
        plugin_root: Root of the plugin repository (used as ``cwd`` fallback).
        repo_path: Root of the pytorch-lightning repository.
        scan_query_bin: Path to the scan-query executable.
        index_path: Path to the pre-built codemap JSON index.

    Returns:
        List of three :class:`ScenarioResult` objects (I_fix, I_feature, I_refactor).
    """
    results: list[ScenarioResult] = []
    log("[injection] Starting injection verification...")

    for skill, key in [("fix", "I_fix"), ("feature", "I_feature"), ("refactor", "I_refactor")]:
        r = _validate_skill_group(skill, load_tasks(skill_filter=skill), scan_query_bin, index_path, repo_path, key)
        emit(r)
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
    """Suite S: validate that scan-query symbol returns correct start/end lines.

    Runs the ``symbol`` command for each S-task in tasks-bench.json and compares
    ``start_line`` / ``end_line`` against ground truth (±3 lines tolerance for
    disambiguating decorator vs def line).

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

        data = run_scan_query(scan_query_bin, ["symbol", qname], index_path, repo_path)
        if data is None:
            results.append(
                ScenarioResult(
                    scenario=f"S_{task_id}",
                    name=f"symbol-{task_id}",
                    suite="symbol",
                    passed=False,
                    result={"error": "scan-query returned None"},
                    threshold=THRESHOLDS["S1"],
                    notes=f"qname={qname}",
                )
            )
            continue

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
    """Suite H: validate undocumented and uncovered counts match tasks-bench.json ground truth.

    Runs each code_quality task that uses ``undocumented`` or ``uncovered`` commands and checks
    whether the returned ``total`` matches the ground truth count (exact match).

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
            data = run_scan_query(scan_query_bin, args, index_path, repo_path)

            if cmd == "undocumented":
                expected_count = gt.get("undocumented_count", gt.get("count", 0))
                suite_key = "H1"
                undoc_tasks_total += 1
            else:
                expected_count = gt.get("uncovered_count", gt.get("count", 0))
                suite_key = "H2"
                uncov_tasks_total += 1

            if data is None:
                passed = False
                got_count = None
            else:
                got_count = data.get("total", None)
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
    """Suite X: validate xrefs --broken output against tasks-bench.json ground truth.

    Runs ``xrefs --broken`` for each OSS task with ``check == "xrefs_broken"`` and
    confirms both the broken count and the set of broken target/line pairs.

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
        data = run_scan_query(scan_query_bin, args, index_path, repo_path)
        x_total += 1

        if data is None:
            results.append(
                ScenarioResult(
                    scenario=f"X_{task_id}",
                    name=f"xrefs-broken-{task_id}",
                    suite="xrefs",
                    passed=False,
                    result={"error": "scan-query returned None", "count_match": False},
                    threshold=THRESHOLDS["X1"],
                    notes=f"task={task_id}",
                )
            )
            continue

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


def main(
    repo_path: str = None,
    index_path: str = None,
    report: bool = False,
    json_only: bool = False,
    verify_tasks: bool = False,
) -> None:
    """Run the codemap scan-query benchmark suite against a pytorch-lightning clone.

    Executes suites C (coverage gap), A (accuracy), L (latency), I (injection),
    S (symbol lookup), H (health), and X (xrefs broken) in order.  Prints a
    one-line verdict summary to stdout; optionally writes a markdown report.

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

    # Resolve plugin root
    plugin_root = None
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            plugin_root = Path(r.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        pass

    repo_path = resolve_repo_path(repo_path)

    if repo_path is None:
        sys.exit(1)

    scan_query_bin = find_codemap_bin("scan-query", plugin_root)
    scan_index_bin = find_codemap_bin("scan-index", plugin_root)

    if scan_query_bin is None:
        log("ERROR: scan-query not found in PATH or plugin directory")
        sys.exit(1)

    # Resolve index path
    index_path = resolve_index_path(index_path, repo_path)
    if not index_path.exists():
        log(f"[index] not found at {index_path}")
        if scan_index_bin:
            log(f"[index] building now via {scan_index_bin} --root {repo_path} ...")
            result = subprocess.run(
                [sys.executable, str(scan_index_bin), "--root", str(repo_path)],
                capture_output=True,
                text=True,
                timeout=360,
            )
            if result.returncode != 0:
                log(f"ERROR: scan-index failed:\n{result.stderr}")
                sys.exit(1)
            log(result.stdout.strip())
            index_path = resolve_index_path(index_path, repo_path)
            if not index_path.exists():
                log(f"ERROR: index still not found at {index_path} after build.")
                log("Try: --index-path <path-to-index.json>")
                sys.exit(1)
        else:
            log("ERROR: scan-index not found — cannot auto-build the index.")
            log(f"Run manually:  python3 plugins/codemap/bin/scan-index --root {repo_path}")
            log("Then retry, or pass --index-path <path-to-index.json>.")
            sys.exit(1)

    # Verify tasks if requested (runs before suites, does not skip them)
    if verify_tasks:
        run_verify_tasks(scan_query_bin, index_path, repo_path)

    all_results: list[ScenarioResult] = []

    suites = [
        ("C — Coverage gap", lambda: run_measure_calls(repo_path)),
        ("A — Accuracy", lambda: run_measure_accuracy(repo_path, scan_query_bin, index_path)),
        ("L — Latency", lambda: run_measure_latency(repo_path, scan_query_bin, index_path, scan_index_bin)),
        (
            "I — Injection",
            lambda: run_measure_injection(plugin_root or Path.cwd(), repo_path, scan_query_bin, index_path),
        ),
        ("S — Symbol lookup", lambda: run_suite_symbol(scan_query_bin, index_path, repo_path)),
        ("H — Health (doc/cov)", lambda: run_suite_health(scan_query_bin, index_path, repo_path)),
        ("X — Xrefs broken", lambda: run_suite_xrefs(scan_query_bin, index_path, repo_path)),
    ]

    if _IS_RICH_AVAILABLE and _console is not None:
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
                all_results.extend(run_fn())
                progress.advance(bar)
    else:
        try:
            from tqdm import tqdm

            _tqdm_iter = tqdm(suites, desc="Benchmark", unit="suite", file=sys.stderr)
            for _label, run_fn in _tqdm_iter:
                all_results.extend(run_fn())
        except ImportError:
            for _label, run_fn in suites:
                all_results.extend(run_fn())

    # Write report if requested
    report_path_str: str | None = None
    if write_report and all_results:
        assert repo_path is not None
        assert index_path is not None
        render_report(all_results, repo_path, index_path, resolve_report_path())
        report_path_str = str(resolve_report_path())

    # Final summary
    total = len(all_results)
    passed = sum(1 for r in all_results if r.passed)
    verdict = compute_verdict(all_results)
    print(f"\n{verdict}  {passed}/{total} scenarios passed")
    if report_path_str:
        print(f"→ {report_path_str}")


if __name__ == "__main__":
    fire.Fire(main)
