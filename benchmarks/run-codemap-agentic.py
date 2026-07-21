#!/usr/bin/env python3
"""Codemap skill benchmark — agent exploration cost with vs without structural context.

## What this measures

Three arms run the same import-graph navigation tasks:

  plain    — developer with a minimal fix/feature/refactor/review skill; discovers structure via
             Grep / Glob / Bash
  codemap  — same skill extended with /codemap:query; uses the Skill tool for import-graph lookups
             instead of grepping for structural questions (semble MCP blocked via --disallowed-tools)
  semble   — same skill extended with mcp__semble__search; uses the MCP tool for hybrid
             semantic + lexical search for import-graph questions instead of grepping
             (Skill tool blocked via --disallowed-tools)
  combined — both /codemap:query and mcp__semble__search available; agent selects whichever
             tool is best suited for each question; no tools blocked

Core claim under test: one /codemap:query or mcp__semble__search call replaces many Grep passes,
reducing tool call count, elapsed time, and context consumption.

## What is NOT measured (excluded by design)

  scan-index  — builds the codemap import-graph index from the repo's Python sources. This is a
                one-time setup step that runs before the benchmark. Its cost (typically a few
                seconds) is intentionally excluded: it amortises over every subsequent query a
                developer makes and is not part of the per-task exploration loop.

  See: plugins/codemap/bin/scan-index --root <repo>

## Metrics (per task × arm × model)

  Key metrics — headline savings signal:
  elapsed_s          — total wall-clock time for the run
  input_tokens (k)   — cumulative input tokens (system prompt + turns + results)

  Diagnostic metrics — explain how savings were achieved:
  tool_calls         — Grep / Glob / Bash / Skill invocations in the transcript
  tool_result_tokens (k) — tiktoken estimate of tokens in tool result content
  tool_elapsed_s     — wall-clock time inside tool execution (excludes LLM think)

## Savings formula (same as caveman evals)

  savings = 1 − (codemap_metric / plain_metric)   per task
  Reported as median / mean / min / max across tasks, per model tier.

## Quality scoring — exposure recall / report recall / skill coverage

  Purpose: assess whether the agent correctly identified the modules that import the task's primary_module
  (its "reverse dependencies", or rdeps). This is a proxy for blast-radius awareness — the core skill under test.

  Ground truth (deterministic, tool-independent — review C-5):
    Derived from an independent AST scan of the repo, NOT from the codemap index the codemap
    arm queries. Every production .py file is parsed once; imports are inverted into an
    {imported_module: {importers}} map handling absolute, `from X import submodule`, aliased,
    and relative imports. Test modules (tests.*) excluded — blast-radius targets production
    callers only. The index-derived list is kept as a diagnostic: when the two disagree a
    per-task `[gt-divergence]` line is logged (missing_in_index = real importers the index lacks
    = potential plugin blind spot). Falls back to the index-derived list when no repo is scanned.

  Matching strategy — multi-form surface matching (v2):
    For each expected rdep, generate surface forms with 2+ path components:
      full dotted:   lightning.pytorch.trainer.trainer
      file path:     lightning/pytorch/trainer/trainer.py, src/lightning/pytorch/trainer/trainer.py
      2-suffix:      trainer.trainer, trainer/trainer, trainer/trainer.py
      3-suffix:      pytorch.trainer.trainer
    Bare leaf names (e.g., "trainer") are NEVER matched — minimum 2 components avoids false positives.
    All forms are word-boundary-aware and case-insensitive.

  Two-layer metrics:
    erec (exposure recall) — what the agent expressed in its own text:
      corpus = output_text only (agent-generated text; tool outputs excluded)
      erec = |{r in expected : any form matches in corpus}| / |expected|
      Arm-fair: all arms scored on identical corpus type; tool outputs excluded to avoid
      codemap erec being near-tautological (skill echoes rdep list → automatic credit).

    rrec (report recall) — what the agent told the user:
      corpus = output_text after the last tool_use/tool_result event
      rrec = |{r in expected : any form matches in corpus}| / |expected|
      Both arms measured equally on their final answer.

    delta = erec - rrec — information gap (agent saw it but did not report it)
    deff = erec_tp / max(tool_calls, 1) — discovery efficiency (rdeps found per tool call)
    erec_top10 — erec restricted to top-10 most-central rdeps by in-degree (meaningful for tasks with ≥5 rdeps)

    sc (skill coverage, codemap only) — index completeness:
      Parsed from the codemap:query rdeps skill result; measures whether the index contained the answer.

  Interpretation guidance:
    — erec high, rrec low → agent found the rdeps but answered in prose without repeating them
    — erec high for codemap, low for plain → codemap skill provided structural context the plain arm missed
    — sc = 100% + erec = 100% → index is complete AND agent processed the result
    — delta ≈ 0 → agent reported everything it found
    — deff higher for codemap → fewer tool calls needed for the same coverage

## Quick start

  # 1. Build the index once (excluded from benchmark timing)
  python plugins/codemap/bin/scan-index --root /path/to/repo

  # 2. Run all tasks across all model tiers
  python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo --all --report

  # 3. Spot-check one task in plain arm only
  python benchmarks/run-codemap-agentic.py --repo-path /path/to/repo \\
      --tasks T01 --arm plain --model haiku

## Requirements

  - claude CLI on PATH (uses Claude Code subscription — no API key)
  - pip install --group pyproject.toml:bench  (deps in pyproject [dependency-groups] bench)
  - uv add semble  (alternative: uv add semble>=0.1.0)
  - Pre-built codemap index (see step 1 above)

## Failure conditions

  A run is marked success=False when any of these occur:
    timeout          — claude subprocess exceeded its per-model wall-clock limit
                       (haiku 210 s / sonnet 420 s / opus 600 s; see _MODEL_TIMEOUT)
    non-zero exit    — claude returned a non-success subtype in the result event; stderr is captured as error
    codemap no-call  — codemap arm completed without ever invoking the Skill tool; this means the agent fell
                       back to grep/bash entirely, defeating the purpose of the codemap arm
    semble no-call   — semble arm completed without ever calling mcp__semble__search or mcp__semble__find_related
    combined no-call  — combined arm completed without ever calling Skill or any semble MCP tool

  Cross-arm tool contamination is blocked at the CLI level (not just by instruction) via --disallowed-tools:
    codemap arm      — mcp__semble__search and mcp__semble__find_related are hard-blocked
    semble arm       — Skill is hard-blocked

## Terminal output (one line per completed run)

    Each run prints a coloured summary line to stdout via tqdm.write:
    [NN/TT] TASK_ID (type/difficulty) | model  | arm       | elapsed=  NNN.Ns | tokens= NNN.Nk |
    calls= N (Gp= N; Gb= N; Bh= N; Sk= N; semble= N; blk= N; bfi= N)
    | erec= N% rrec= N%  sc= N%   ← quality=n/a when no ground truth
  Quality fields:
    erec  — exposure recall: rdeps found in output_text + codemap skill results (multi-form, 2+ components)
    rrec  — report recall: rdeps found in final answer text after last tool call
    sc    — skill coverage (codemap arm only): fraction of expected rdeps returned by the skill call;
             omitted on plain arm; measures index completeness, not agent verbosity
  Colour coding:
    yellow  — plain arm
    cyan    — codemap arm
    blue    — semble arm
    green   — combined arm (both tools available, agent chooses)
    red     — any arm where success=False (overrides arm colour)

## JSON output schema (benchmarks/results/code-YYYY-MM-DD.json)

  Written after every run (rolling snapshot) so partial results survive interruptions.

  {
    "metadata": {
      "date": "ISO-8601 timestamp",
      "models": "haiku, sonnet, opus",
      "repo": "/abs/path/to/repo",
      "index": "/abs/path/to/index.json",
      "task_count": N
    },
    "results": [
      {
        "arm": "plain" | "codemap" | "semble" | "combined",
        "task_id": "T01",
        "task_type": "fix" | "feature" | "refactor" | "review",
        "model": "haiku" | "sonnet" | "opus",
        "success": true | false,
        "tools": {"grep": N, "glob": N, "bash": N, "skill": N},
        "input_tokens": N,          ← sum of input + cache_creation + cache_read tokens
        "output_tokens": N,
        "tool_result_tokens": N,    ← tiktoken estimate of tool result content
        "elapsed_s": N.N,
        "tool_elapsed_s": N.N,      ← wall-clock inside tool execution only
        "error": "",                ← non-empty on failure
        "tool_log": ["Grep: pattern in path", ...],
        "output_text": "...",       ← full agent text output (used for quality scoring)
        "quality": {
          "scored": true | false,       ← false when task has no primary_module in index
          "erec": N.N,                  ← exposure recall: rdeps found in output_text + codemap results
          "erec_tp": N, "erec_fn": N,   ← multi-form true positives / false negatives on exposure corpus
          "rrec": N.N,                  ← report recall: rdeps found in final answer text
          "rrec_tp": N, "rrec_fn": N,   ← multi-form true positives / false negatives on report corpus
          "delta": N.N,                 ← erec - rrec: information seen but not reported
          "erec_top10": N.N,            ← erec on top-10 most-central rdeps by in-degree; equals erec when |rdeps|≤10
          "erec_top10_k": N,            ← k used: min(10, |expected|)
          "deff": N.N,                  ← erec_tp / max(tool_calls, 1): discovery efficiency
          "skill_coverage": N.N | null, ← codemap arm: fraction of expected rdeps in skill result; null for plain
          "skill_returned": N | null,   ← count of modules the skill call returned; null for plain
          "leaf_recall": N.N,           ← legacy: leaf-name recall on output_text
          "recall": N.N, "precision": N.N, "f1": N.N,  ← legacy aliases
          "tp": N, "fp": N, "fn": N, "leaf_tp": N, "leaf_fn": N, "ambiguous_leaves": N
        }
      }
    ]
  }

## Stream-JSON event parsing

  The benchmark invokes:
      claude -p --verbose --output-format stream-json --system-prompt "..." "task prompt"

  Events parsed:
    {"type":"assistant","message":{"content":[{"type":"tool_use","name":"Grep",...}],...}}
      → increments tool counter; records tool_use_id + timestamp for elapsed tracking
      → text blocks are concatenated into output_text for quality scoring

    {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"...","content":"..."}]}}
      → records elapsed since matching tool_use; tokenises result content with tiktoken

    {"type":"result","usage":{"input_tokens":N,"output_tokens":N,...}}
      → captures final cumulative token usage (all cache partitions summed)
"""

import ast
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import fire
import pandas as pd

from rich.console import Console as _Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

_console = _Console()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RESULTS_DIR = Path("benchmarks/results")

# Model tiers: short name → full model ID (ascending capability / cost)
MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
}

# Per-model wall-clock timeout (seconds). Opus needs more time for complex reasoning.
_MODEL_TIMEOUT: dict[str, int] = {"haiku": 210, "sonnet": 420, "opus": 600}

# Fixed USD price table per million tokens, keyed by short tier (NOT exact model id) so a
# 4.6 vs 4.8 swap does not perturb cross-run cost comparisons. List prices — edit here to
# track Anthropic changes; cache_read = 0.1x input, cache_write = 1.25x input (standard ratios).
# Cost is the fair cross-arm metric because arms differ in how many tokens they burn to reach
# the same answer. Under `claude -p` the codemap skill sub-model never spawns, so every token —
# including skill/scan-query work — bills at the arm's own tier; there is no separate cheaper
# haiku skill-model layer. Cost still separates arms by token volume, not by a per-layer rate mix.
PRICES: dict[str, dict[str, float]] = {
    "haiku": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "sonnet": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "opus": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
}


def run_cost_usd(r: "BenchmarkRun") -> float:
    """Cache-aware USD cost of one run from the fixed PRICES table.

    ``input_tokens`` stores the summed context (uncached + cache_creation + cache_read); when the
    cache breakdown was captured (new runs) cost is billed per component, otherwise the whole sum
    falls back to the full input price — an upper bound flagged in the report Limitations.

    Args:
        r: Completed benchmark run with token counts and a short model tier.

    Returns:
        Estimated cost in USD.

    Examples:
        >>> from types import SimpleNamespace as N
        >>> round(run_cost_usd(N(model="haiku", input_tokens=1_000_000, output_tokens=0,
        ...     cache_read_tokens=0, cache_creation_tokens=0)), 2)
        1.0
    """
    p = PRICES.get(r.model)
    if not p:
        return 0.0
    cache_read = getattr(r, "cache_read_tokens", 0) or 0
    cache_write = getattr(r, "cache_creation_tokens", 0) or 0
    uncached = max(r.input_tokens - cache_read - cache_write, 0)
    return (
        uncached * p["input"]
        + cache_write * p["cache_write"]
        + cache_read * p["cache_read"]
        + r.output_tokens * p["output"]
    ) / 1_000_000


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class QualityScore:
    """Quality score for a single benchmark run.

    Primary metrics (v2 — multi-form matching with 2+ component surface forms):
        ``erec``  — exposure recall: rdeps found in agent output_text (tool outputs excluded)
        ``rrec``  — report recall: rdeps found in agent's final answer after last tool call
        ``delta`` — erec - rrec: information gap (agent saw but did not report)
        ``deff``  — discovery efficiency: erec_tp / max(tool_calls, 1)

    Supplementary (codemap arm only):
        ``skill_coverage``, ``skill_returned``

    Semble-native lens (semble / combined arms only):
        ``chunk_hit_rate`` — expected rdeps whose module/file appears in any retrieved semble chunk

    Legacy fields (``leaf_recall``, ``precision``, ``recall``, ``f1``, ``tp``, ``fp``, ``fn``)
    are retained for backward compatibility; computed via leaf-name matching on output_text.
    """

    scored: bool = False  # False when no ground truth is available

    # ── Primary metrics (v2 — multi-form matching) ──
    erec: float = 0.0  # exposure recall: rdeps found in output_text + codemap results
    erec_tp: int = 0
    erec_fn: int = 0
    rrec: float = 0.0  # report recall: rdeps found in final answer text (after last tool call)
    rrec_tp: int = 0
    rrec_fn: int = 0
    delta: float = 0.0  # erec - rrec: information the agent saw but did not report
    deff: float = 0.0  # discovery efficiency: erec_tp / max(tool_calls, 1)
    erec_top10: float = 0.0  # erec restricted to top-10 rdeps by in-degree (reverse-dep) centrality
    erec_top10_k: int = 0  # actual k used (min(10, |expected|)); equals |expected| when ≤10

    # ── Skill result coverage (codemap arm only; None when not applicable) ──
    skill_coverage: Optional[float] = None
    skill_returned: Optional[int] = None

    # ── Semble-native lens (semble / combined arms only; None when not applicable) ──
    # chunk_hit_rate: fraction of expected rdep modules whose module/file appears in ANY semble
    # search chunk the arm retrieved. A fair semantic-search axis that does not require semble to
    # emit an exhaustive dotted rdep list (review C-5); erec/rrec stay the codemap-native lens.
    chunk_hit_rate: Optional[float] = None

    # ── Targeted-test correctness signal (fix tasks that declare a test_target; None otherwise) ──
    # test_passed: outcome of running the task's declared pytest node on the post-edit sandbox.
    # A stronger correctness signal than keyword recall — recorded alongside erec, never replacing
    # it (review M-4). None when the task declares no test or the test could not be launched.
    test_passed: Optional[bool] = None

    # ── Legacy fields (backward compat — leaf-name matching on output_text) ──
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    leaf_recall: float = 0.0
    leaf_tp: int = 0
    leaf_fn: int = 0
    ambiguous_leaves: int = 0


@dataclass
class ToolCounts:
    grep: int = 0
    glob: int = 0
    bash: int = 0
    skill: int = 0  # /codemap:query and other skill invocations via the Skill tool
    semble: int = 0  # mcp__semble__search and mcp__semble__find_related calls
    blocked: int = 0  # tool_use events that returned <tool_use_error> (permission-denied or disallowed)
    bash_for_imports: int = 0  # bash calls matching import-discovery patterns (grep/rg for import)
    index_reads: int = 0  # bash calls that read .cache/codemap/ or .cache/scan/ index files directly

    @property
    def total(self) -> int:
        """Sum of all tool call counts across all arms.

        >>> ToolCounts(grep=3, bash=1, semble=2).total
        6
        >>> ToolCounts().total
        0
        """
        return self.grep + self.glob + self.bash + self.skill + self.semble


@dataclass
class BenchmarkRun:
    """Result of a single benchmark run (one task x arm x model).

    Renamed from RunResult; field names are unchanged, so ``asdict()`` output and serialised JSON
    remain identical.
    """

    arm: str
    task_id: str
    task_type: str
    model: str  # short tier name: haiku / sonnet / opus
    success: bool
    tools: ToolCounts = field(default_factory=ToolCounts)
    # Token metrics
    input_tokens: int = 0
    output_tokens: int = 0
    tool_result_tokens: int = 0  # tiktoken estimate of tool result content
    cache_read_tokens: int = 0  # cache-hit input tokens (billed ~0.1x) — for cache-aware cost
    cache_creation_tokens: int = 0  # cache-write input tokens (billed ~1.25x)
    # Timing metrics (stored in seconds)
    elapsed_s: float = 0.0
    tool_elapsed_s: float = 0.0  # time inside tool execution only
    error: str = ""
    error_type: str = ""  # subtype from result event: error_max_turns | error_non_zero_exit | error_timeout | ""
    # Per-call log for post-run investigation: ["Bash: grep -r 'import'", "Skill: /codemap:query rdeps ..."]
    tool_log: list[str] = field(default_factory=list)
    # Raw tool_use_error payloads (first 2k chars each) for diagnosing skill failures
    tool_errors: list[str] = field(default_factory=list)
    # Full agent output text — captured for quality scoring
    output_text: str = ""
    quality: QualityScore = field(default_factory=QualityScore)
    # Internal — excluded from JSON (see _save_snapshot); populated for fix_single/fix_multicaller tasks
    agent_diff: str = field(default="", repr=False)  # unified diff of agent's edits vs original codebase
    # Transient carrier for the declared targeted-test outcome (run in the sandbox, before cleanup);
    # excluded from JSON — the persisted signal lives in quality.test_passed.
    targeted_test_passed: Optional[bool] = field(default=None, repr=False)
    # Internal fields excluded from JSON serialisation (see _save_snapshot)
    skill_result_text: str = field(default="", repr=False)  # all codemap:query rdeps results joined (for sc)
    codemap_results: list[str] = field(default_factory=list, repr=False)  # ALL codemap skill results (for erec)
    semble_results: list[str] = field(default_factory=list, repr=False)  # ALL semble MCP tool results (for erec)
    last_tool_text_offset: int = field(default=0, repr=False)  # output_text offset after last tool event


@dataclass
class Task:
    id: str
    type: str
    prompt: str
    primary_module: str = ""
    difficulty: str = "unknown"
    skill: str = ""
    symbol: str = ""  # read_crop tasks: target symbol (e.g. "Trainer.fit")
    expected_keywords: list[str] = field(default_factory=list)  # read_crop tasks: keyword-recall ground truth
    requires_reset: bool = False  # fix tasks: snapshot/restore codebase around each arm run
    codebase_module: str = ""  # fix tasks: top-level module to snapshot (e.g. "lightning")
    expected_patch_keywords: list[str] = field(default_factory=list)  # fix tasks: strings expected in diff +lines
    expected_files: list[str] = field(default_factory=list)  # fix tasks: file-path fragments expected in diff
    test_target: str = ""  # fix tasks: pytest node id/path run on the post-edit sandbox for a correctness signal


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def count_tokens(text: str) -> int:
    """Approximate token count using tiktoken o200k_base (matches caveman evals)."""
    try:
        import tiktoken

        enc = tiktoken.get_encoding("o200k_base")
        return len(enc.encode(text))
    except ImportError:
        return max(1, len(text) // 4)  # ~4 chars/token fallback


def find_index(repo_path: Path, explicit: Optional[Path]) -> Path:
    """Locate the pre-built codemap index for the target repo.

    Checks ``.cache/codemap/`` first, then ``.cache/scan/``. Within each directory,
    prefers ``<repo_name>.json``; falls back to the lexicographically first ``*.json`` file.
    The index is built once by ``scan-index`` and is excluded from benchmark timing; this
    function only validates it exists before any run starts.

    Args:
        repo_path: Root of the repository to benchmark.
        explicit: Caller-supplied index path; returned as-is (resolved) when provided.

    Returns:
        Resolved absolute path to the located index file.

    Raises:
        FileNotFoundError: If no index is found under ``.cache/codemap/`` or ``.cache/scan/``
            and ``explicit`` was not provided.
    """
    if explicit:
        return explicit.resolve()
    for cache_dir in (repo_path / ".cache" / "codemap", repo_path / ".cache" / "scan"):
        preferred = cache_dir / f"{repo_path.name}.json"
        if preferred.exists():
            return preferred.resolve()
        candidates = sorted(cache_dir.glob("*.json"))
        if candidates:
            return candidates[0].resolve()
    raise FileNotFoundError(
        f"No codemap index found in {repo_path / '.cache'}.\n"
        f"Build it first (one-time, not measured):\n"
        f"  python plugins/codemap/bin/scan-index --root {repo_path}"
    )


def check_semble_mcp() -> None:
    """Verify semble is installed and configured as an MCP server before the run starts.

    Checks two things:
      1. The semble Python package is importable (the MCP server ships with it).
      2. `claude mcp get semble` exits 0 — works for all scopes (user / project / local).

    Raises RuntimeError with actionable instructions when either check fails.
    """
    try:
        import semble as _semble  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "semble package not installed — required for the semble arm.\n"
            "Install it:\n"
            "  pip install semble>=0.1.0\n"
            "  # or: uv add semble"
        )

    r = subprocess.run(
        ["claude", "mcp", "get", "semble"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(
            "semble MCP server not configured — run once to register it:\n"
            "  claude mcp add semble -s user -- uvx --from 'semble[mcp]' semble\n"
            "Use -s project instead of -s user to scope to this repo only."
        )


def _unique_path(path: Path) -> Path:
    """Return path unchanged if it doesn't exist; otherwise append a counter suffix."""
    if not path.exists():
        return path
    n = 2
    while (path.parent / f"{path.stem}-{n}{path.suffix}").exists():
        n += 1
    return path.parent / f"{path.stem}-{n}{path.suffix}"


def _tool_key_arg(name: str, inp: dict) -> str:
    """Return a short human-readable argument string for tool call logging.

    >>> _tool_key_arg("Grep", {"pattern": "import auth", "path": "src/"})
    "'import auth' in src/"
    >>> _tool_key_arg("mcp__semble__search", {"query": "import checkpoint_connector", "repo": "/tmp/r", "top_k": 20})
    "query='import checkpoint_connector'"
    >>> _tool_key_arg("mcp__semble__find_related", {"query": "find related", "line": 42})
    "query='find related'"
    """
    if name == "Grep":
        pat = inp.get("pattern", "")
        loc = inp.get("path", "") or inp.get("glob", "")
        return f"{pat!r} in {loc}" if loc else repr(pat)
    if name == "Glob":
        return inp.get("pattern", "")
    if name == "Bash":
        return inp.get("command", "")[:120]
    if name == "Skill":
        return f"{inp.get('skill', '')} {inp.get('args', '')}".strip()
    if name in ("mcp__semble__search", "mcp__semble__find_related"):
        inp_q = inp.get("query", "")[:80]
        return f"query={inp_q!r}"
    return str(inp)[:80]


# ---------------------------------------------------------------------------
# Independent AST-based reverse-dependency scan (tool-independent ground truth)
# ---------------------------------------------------------------------------

_SKIP_DIR_PARTS = frozenset({"tests", "test"})  # top-level test trees excluded from production rdeps


def _iter_py_files(root: Path) -> Iterator[Path]:
    """Yield ``*.py`` files under ``root``, pruning hidden and test directories.

    Directories whose name starts with ``.`` (``.git``, ``.cache``, ``.venv``) and any
    directory named ``tests``/``test`` are skipped — the latter mirrors the index rule that
    blast-radius analysis targets production callers only.

    Args:
        root: Repository root to walk.

    Yields:
        Absolute paths to candidate Python source files.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _SKIP_DIR_PARTS]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def _derive_module_name(py_path: Path, root: Path) -> Optional[str]:
    """Derive the dotted module name of a file from its ``__init__.py`` package chain.

    Walks parent directories upward while each contains an ``__init__.py`` to find the source
    root, then joins the remaining path components. Works for both src-layout and flat layouts
    without consulting the codemap index (fully independent ground-truth derivation).

    Args:
        py_path: Absolute path to a ``.py`` file inside ``root``.
        root: Repository root (used only as a walk boundary).

    Returns:
        Dotted module name (e.g. ``lightning.pytorch.trainer.trainer``); ``__init__.py`` files
        resolve to their package name. ``None`` when no name can be derived.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = pathlib.Path(d)
        ...     _ = (r / "pkg").mkdir()
        ...     _ = (r / "pkg" / "__init__.py").write_text("")
        ...     _ = (r / "pkg" / "mod.py").write_text("")
        ...     _derive_module_name(r / "pkg" / "mod.py", r)
        'pkg.mod'
    """
    parts: list[str] = []
    if py_path.stem != "__init__":
        parts.append(py_path.stem)
    directory = py_path.parent
    while (directory / "__init__.py").exists() and directory != directory.parent:
        parts.append(directory.name)
        directory = directory.parent
    if not parts:
        return None
    parts.reverse()
    return ".".join(parts)


def _resolve_relative_base(package: str, level: int, module: Optional[str]) -> Optional[str]:
    """Resolve a relative ``from`` import to its absolute base module.

    Args:
        package: Dotted package containing the importing module (its ``__package__``).
        level: Number of leading dots (1 = current package, 2 = parent, ...).
        module: Text after the dots (``from ..a.b import x`` → ``"a.b"``); ``None`` for
            ``from . import x``.

    Returns:
        Absolute dotted base module, or ``None`` when the level walks above the package root.

    Examples:
        >>> _resolve_relative_base("a.b", 1, "c")
        'a.b.c'
        >>> _resolve_relative_base("a.b.c", 2, "u") is None  # regular module's package is a.b
        False
    """
    base_parts = package.split(".") if package else []
    ascend = level - 1
    if ascend > len(base_parts):
        return None
    kept = base_parts[: len(base_parts) - ascend] if ascend else base_parts
    if module:
        kept = kept + module.split(".")
    return ".".join(kept) if kept else None


def _extract_import_targets(tree: ast.Module, package: str, all_modules: set[str]) -> set[str]:
    """Collect internal modules a parsed file imports (base and submodule forms).

    Handles ``import a.b.c``, ``import a.b as z``, ``from a.b import c`` (crediting both the
    package ``a.b`` and the submodule ``a.b.c`` when the latter is a real module), and relative
    imports resolved against ``package``. Only targets present in ``all_modules`` are returned,
    so external and symbol-only imports are dropped.

    Args:
        tree: Parsed module AST.
        package: Dotted package of the importing module (for relative resolution).
        all_modules: Set of internal dotted module names to filter targets against.

    Returns:
        Set of internal dotted module names the file depends on.
    """
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in all_modules:
                    targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module if node.level == 0 else _resolve_relative_base(package, node.level, node.module)
            if not base:
                continue
            if base in all_modules:
                targets.add(base)
            for alias in node.names:
                if alias.name != "*" and f"{base}.{alias.name}" in all_modules:
                    targets.add(f"{base}.{alias.name}")
    return targets


def _scan_repo_importers(root: Path) -> dict[str, set[str]]:
    """Build a tool-independent reverse-dependency map by AST-parsing every source file once.

    The walk resolves each production module's imports and inverts them into
    ``{imported_module: {importer_module, ...}}``. This is the ground-truth source for quality
    scoring (review C-5): unlike the codemap index it is not the artefact the codemap arm queries,
    so index blind spots (e.g. ``from pkg import submodule``) surface as divergences instead of
    being invisible.

    Args:
        root: Repository root to scan.

    Returns:
        Mapping from each internal dotted module name to the set of production modules importing it.
    """
    file_module: dict[Path, str] = {}
    for py_file in _iter_py_files(root):
        name = _derive_module_name(py_file, root)
        if name:
            file_module[py_file] = name
    all_modules = set(file_module.values())
    importers: dict[str, set[str]] = defaultdict(set)
    for py_file, module in file_module.items():
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"), filename=str(py_file))
        except (SyntaxError, ValueError):
            continue
        package = module if py_file.stem == "__init__" else module.rpartition(".")[0]
        for target in _extract_import_targets(tree, package, all_modules):
            if target != module:
                importers[target].add(module)
    return importers


# ---------------------------------------------------------------------------
# Quality scoring — deterministic ground truth
# ---------------------------------------------------------------------------


class GroundTruth:
    """Tool-independent ground truth for quality scoring benchmark runs.

    Loads the codemap index once for centrality metadata, then (when a repo path is given)
    derives the authoritative expected rdep sets from an independent AST scan of the repo —
    not from the same index the codemap arm queries. The index-derived list is retained as a
    diagnostic; per-task divergences are logged so index blind spots become visible instead of
    invisible (see review C-5). Exposes a ``score()`` method for comparing agent output to truth.
    """

    @staticmethod
    def _build_module_regexes(packages: set[str]) -> tuple[re.Pattern[str], re.Pattern[str]]:
        """Build dotted-name and ``src/`` path regexes for the given top-level packages.

        The package set is derived from the benchmark's tasks (each ``primary_module``'s
        first dotted component), so the extractor stays repo-agnostic — no package name is
        hardcoded. For ``pytorch-lightning`` (``packages={"lightning"}``) this reproduces the
        legacy ``\\blightning(?:\\.…)+`` behaviour exactly.

        Args:
            packages: Top-level package names to match (e.g. ``{"lightning"}``).

        Returns:
            ``(module_re, path_re)`` — the dotted-name matcher and the ``src/<pkg>/…\\.py``
            matcher. When ``packages`` is empty, both patterns match nothing.

        Examples:
            >>> mod_re, _ = GroundTruth._build_module_regexes({"lightning"})
            >>> mod_re.findall("see lightning.pytorch.trainer.trainer here")
            ['lightning.pytorch.trainer.trainer']
        """
        if not packages:
            never = re.compile(r"(?!x)x")  # matches nothing
            return never, never
        alt = "|".join(re.escape(p) for p in sorted(packages))
        module_re = re.compile(rf"\b(?:{alt})(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+")
        path_re = re.compile(rf"\bsrc/((?:{alt})(?:/[a-zA-Z_][a-zA-Z0-9_]*)+)\.py\b")
        return module_re, path_re

    def __init__(self, index_path: Path, tasks: list[Task], repo_path: Optional[Path] = None) -> None:
        """Load the index and pre-compute expected rdep sets for each task.

        Args:
            index_path: Path to the pre-built codemap JSON index produced by ``scan-index``.
                Used for module inventory and dep-count centrality only, never as the rdep oracle.
            tasks: Task definitions used to derive per-task ground-truth rdep sets. Tasks
                without a ``primary_module`` are skipped silently.
            repo_path: Repository root. When provided, expected rdeps come from an independent
                AST scan and divergences from the index are logged. When ``None`` (unit tests that
                supply only an index), the index-derived list is used as a fallback.
        """
        with index_path.open() as f:
            index = json.load(f)
        self.all_modules: set[str] = {m["name"] for m in index.get("modules", []) if m.get("status") == "ok"}
        # Top-level package name(s) for the repo under test, derived from the tasks' primary
        # modules (first dotted component) — keeps module extraction repo-agnostic (no hardcode).
        self.packages: set[str] = {
            getattr(t, "primary_module", "").split(".")[0] for t in tasks if getattr(t, "primary_module", "")
        }
        self._module_re, self._path_re = self._build_module_regexes(self.packages)
        self.index_expected: dict[str, set[str]] = self._index_rdeps(index, tasks)
        # Independent oracle: {imported_module: {importer, ...}}; empty when no repo path supplied.
        self.ast_importers: dict[str, set[str]] = _scan_repo_importers(repo_path) if repo_path else {}
        self.expected, self.divergences = self._resolve_expected(tasks, used_ast=bool(repo_path))
        # in-degree = reverse-dependency count per module (how many modules import it), derived from
        # the index import graph. Tasks define "central" as "imported by the most modules" — i.e.
        # in-degree — so top-10 ranks by in-degree, NOT dep_count. dep_count is the forward import
        # count (out-degree) and would rank on the opposite axis, measuring recall on the wrong
        # modules (review M-3).
        _in_degrees: dict[str, int] = defaultdict(int)
        for m in index.get("modules", []):
            if m.get("status") != "ok":
                continue
            for imported in m.get("direct_imports", []):
                _in_degrees[imported] += 1
        # Top-10 most-central rdeps per task (by in-degree descending); k=min(10, |rdeps|)
        self.top10_expected: dict[str, frozenset[str]] = {}
        for task in tasks:
            rdeps = self.expected.get(task.id, set())
            if rdeps:
                ranked = sorted(rdeps, key=lambda m: _in_degrees.get(m, 0), reverse=True)[:10]
                self.top10_expected[task.id] = frozenset(ranked)
        self.all_leaf_names: set[str] = {m.split(".")[-1] for m in self.all_modules}
        # Match patterns cover the index inventory plus any AST-only expected rdep, so an arm that
        # finds a real importer the index missed can still be credited in the corpus.
        pattern_targets = set(self.all_modules)
        for rdeps in self.expected.values():
            pattern_targets |= rdeps
        self._match_patterns: dict[str, list[re.Pattern]] = {m: self._generate_match_set(m) for m in pattern_targets}
        self._emit_divergences()

    @staticmethod
    def _index_rdeps(index: dict, tasks: list[Task]) -> dict[str, set[str]]:
        """Derive the diagnostic index-based rdep set per task from ``direct_imports``."""
        modules = index.get("modules", [])
        out: dict[str, set[str]] = {}
        for task in tasks:
            pm = getattr(task, "primary_module", "")
            if not pm:
                continue
            out[task.id] = {
                m["name"]
                for m in modules
                if pm in m.get("direct_imports", []) and m.get("status") == "ok" and not m["name"].startswith("tests.")
            }
        return out

    def _resolve_expected(self, tasks: list[Task], used_ast: bool) -> tuple[dict[str, set[str]], dict[str, dict]]:
        """Select expected rdeps (AST when scanned, else index) and record index divergences.

        Args:
            tasks: Task definitions to resolve expected rdeps for.
            used_ast: True when an AST scan ran; its result becomes authoritative.

        Returns:
            ``(expected, divergences)`` where divergences maps task_id to
            ``{"ast", "index", "missing_in_index", "missing_in_ast"}`` for tasks that disagree.
        """
        if not used_ast:
            return dict(self.index_expected), {}
        expected: dict[str, set[str]] = {}
        divergences: dict[str, dict] = {}
        for task in tasks:
            pm = getattr(task, "primary_module", "")
            if not pm:
                continue
            ast_set = {m for m in self.ast_importers.get(pm, set()) if not m.startswith("tests.")}
            expected[task.id] = ast_set
            index_set = self.index_expected.get(task.id, set())
            missing_in_index = ast_set - index_set
            missing_in_ast = index_set - ast_set
            if missing_in_index or missing_in_ast:
                divergences[task.id] = {
                    "ast": len(ast_set),
                    "index": len(index_set),
                    "missing_in_index": sorted(missing_in_index),
                    "missing_in_ast": sorted(missing_in_ast),
                }
        return expected, divergences

    def _emit_divergences(self) -> None:
        """Print one visible line per task where the AST oracle and index disagree.

        A non-empty ``missing_in_index`` means the AST scan found real importers the index lacks —
        a potential plugin blind spot and the harness's added diagnostic value (review C-5).
        """
        for task_id, d in sorted(self.divergences.items()):
            print(
                f"[gt-divergence] {task_id}: ast={d['ast']} index={d['index']} "
                f"missing_in_index={d['missing_in_index']} missing_in_ast={d['missing_in_ast']}"
            )

    @staticmethod
    def _generate_match_set(module: str) -> list[re.Pattern]:
        """Generate multi-form regex patterns for a module name.

        Each pattern requires at least 2 path components to avoid bare leaf-name false positives.
        Forms generated: full dotted path, file path variants, 2-component and 3-component suffixes.
        """
        parts = module.split(".")
        forms: set[str] = set()
        # Full dotted path: lightning.pytorch.trainer.trainer
        forms.add(module)
        # File path forms: lightning/pytorch/trainer/trainer.py, src/...
        file_path = module.replace(".", "/") + ".py"
        forms.add(file_path)
        forms.add("src/" + file_path)
        # 2-component suffix (minimum specificity): trainer.trainer, trainer/trainer
        if len(parts) >= 2:
            s2 = ".".join(parts[-2:])
            forms.add(s2)
            forms.add("/".join(parts[-2:]))
            forms.add("/".join(parts[-2:]) + ".py")
        # 3-component suffix: pytorch.trainer.trainer
        if len(parts) >= 3:
            forms.add(".".join(parts[-3:]))
        return [re.compile(r"\b" + re.escape(f) + r"\b", re.IGNORECASE) for f in forms]

    def _rdep_found(self, rdep: str, corpus: str) -> bool:
        """Return True if any multi-form pattern for ``rdep`` matches in ``corpus``."""
        for pat in self._match_patterns.get(rdep, []):
            if pat.search(corpus):
                return True
        return False

    def score(
        self,
        task_id: str,
        output_text: str,
        exposure_corpus: str,
        report_corpus: str,
        tool_calls: int = 0,
        skill_result_text: str | None = None,
        semble_result_text: str | None = None,
    ) -> QualityScore:
        """Compute quality score using multi-form matching and optional coverage lenses.

        Primary metrics (v2):
            ``erec`` — exposure recall on ``exposure_corpus`` (agent output_text only; tool outputs excluded)
            ``rrec`` — report recall on ``report_corpus`` (final answer after last tool call)
            ``delta`` — erec - rrec
            ``deff`` — erec_tp / max(tool_calls, 1)

        Supplementary:
            ``skill_coverage`` — fraction of expected rdeps in the skill result (codemap only)
            ``chunk_hit_rate`` — fraction of expected rdeps whose module/file appears in any
                retrieved semble chunk (semble / combined only); ``None`` when no semble corpus

        Legacy:
            ``leaf_recall`` etc. — leaf-name matching on ``output_text`` for backward compat
        """
        exp = self.expected.get(task_id, set())
        if not exp:
            return QualityScore(scored=False)

        # ── Primary: multi-form matching (v2) ──
        erec_matched = {r for r in exp if self._rdep_found(r, exposure_corpus)}
        rrec_matched = {r for r in exp if self._rdep_found(r, report_corpus)}
        n_exp = len(exp)
        erec_tp = len(erec_matched)
        rrec_tp = len(rrec_matched)
        erec = erec_tp / n_exp
        rrec = rrec_tp / n_exp
        delta = erec - rrec
        deff = erec_tp / max(tool_calls, 1)

        # erec@10 — exposure recall on top-10 most-central rdeps
        top10 = self.top10_expected.get(task_id)
        if top10:
            top10_tp = sum(1 for r in top10 if self._rdep_found(r, exposure_corpus))
            erec_top10 = top10_tp / len(top10)
            erec_top10_k = len(top10)
        else:
            erec_top10 = erec
            erec_top10_k = n_exp

        # ── Skill coverage (codemap arm only) ──
        # Two capture paths:
        # 1. Agent ran scan-query via Bash → skill_result_text is raw JSON → parse imported_by.
        # 2. Agent used Skill tool → tool returns rendered markdown, one module per line →
        #    extract dotted module names via regex (require ≥1 dot to avoid YAML-key false-positives).
        # Prose error text (blocked, permission denied) → None (unscored), not sc=0%.
        skill_coverage: Optional[float] = None
        skill_returned: Optional[int] = None
        if skill_result_text:
            returned: Optional[set] = None
            try:
                data = json.loads(skill_result_text)
                if "imported_by" in data:
                    returned = set(data["imported_by"])
            except (json.JSONDecodeError, AttributeError, TypeError):
                # Rendered markdown path — extract lines that look like dotted module paths.
                modules = re.findall(r"^([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)\s*$", skill_result_text, re.MULTILINE)
                if modules:
                    returned = set(modules)
            if returned is not None:
                skill_returned = len(returned)
                skill_coverage = len(returned & exp) / n_exp

        # ── Semble chunk-hit rate (semble / combined arm only) ──
        # Module-file granularity: an expected rdep counts as hit if any of its surface forms
        # appears in the concatenated semble search chunks — semantic search need not enumerate
        # exact dotted rdeps to get credit (review C-5).
        chunk_hit_rate: Optional[float] = None
        if semble_result_text:
            chunk_hits = sum(1 for r in exp if self._rdep_found(r, semble_result_text))
            chunk_hit_rate = chunk_hits / n_exp

        # ── Legacy: leaf-name matching on output_text ──
        expected_leaves = {m.split(".")[-1] for m in exp}
        ambiguous = sum(1 for leaf in expected_leaves if len(leaf) < 6)
        matched_leaves = {
            lf for lf in expected_leaves if re.search(r"\b" + re.escape(lf) + r"\b", output_text, re.IGNORECASE)
        }
        leaf_tp = len(matched_leaves)
        leaf_fn = len(expected_leaves) - leaf_tp
        leaf_recall = leaf_tp / len(expected_leaves) if expected_leaves else 0.0
        all_output_leaves = {
            lf for lf in self.all_leaf_names if re.search(r"\b" + re.escape(lf) + r"\b", output_text, re.IGNORECASE)
        }
        leaf_fp = len(all_output_leaves - expected_leaves)
        prec = leaf_tp / (leaf_tp + leaf_fp) if (leaf_tp + leaf_fp) > 0 else 0.0
        f1 = 2 * prec * leaf_recall / (prec + leaf_recall) if (prec + leaf_recall) > 0 else 0.0

        return QualityScore(
            scored=True,
            # v2 primary
            erec=erec,
            erec_tp=erec_tp,
            erec_fn=n_exp - erec_tp,
            rrec=rrec,
            rrec_tp=rrec_tp,
            rrec_fn=n_exp - rrec_tp,
            delta=delta,
            deff=deff,
            erec_top10=erec_top10,
            erec_top10_k=erec_top10_k,
            # Skill coverage
            skill_coverage=skill_coverage,
            skill_returned=skill_returned,
            # Semble-native lens
            chunk_hit_rate=chunk_hit_rate,
            # Legacy
            precision=prec,
            recall=leaf_recall,
            f1=f1,
            tp=leaf_tp,
            fp=leaf_fp,
            fn=leaf_fn,
            leaf_recall=leaf_recall,
            leaf_tp=leaf_tp,
            leaf_fn=leaf_fn,
            ambiguous_leaves=ambiguous,
        )

    def _extract_modules(self, text: str) -> set[str]:
        """Extract dotted package-namespaced module names from agent output.

        Matches only the repo's own top-level packages (``self.packages``, derived from the
        tasks' primary modules), so a non-lightning repo works without editing code.

        Handles two forms agents use:
        - Dotted: ``lightning.pytorch.trainer.trainer``
        - File path: ``src/lightning/pytorch/trainer/trainer.py`` -> converted to dotted
        """
        dotted = set(self._module_re.findall(text))
        from_paths = {m.replace("/", ".") for m in self._path_re.findall(text)}
        return dotted | from_paths


# ---------------------------------------------------------------------------
# Claude CLI runner
# ---------------------------------------------------------------------------


class ModelRunner:
    """Runs benchmark tasks against a specific Claude model tier.

    Encapsulates model identity, repo path, and timeout. The ``run()`` method launches a Claude
    subprocess and parses stream-json events into a ``BenchmarkRun`` result.

    Arm prompts and CLI constants live here — only ModelRunner constructs or launches claude;
    nothing else needs them.
    """

    # Base claude CLI invocation
    _CMD = ["claude", "-p", "--verbose", "--output-format", "stream-json", "--max-turns", "40"]
    # Tools counted as exploration overhead
    EXPLORATION_TOOLS = {"Grep", "Glob", "Bash", "Skill", "mcp__semble__search", "mcp__semble__find_related"}
    # Tools blocked per arm via --disallowed-tools to enforce mutual exclusion
    # Bash is kept available for every non-plain arm (and plain) so each has the same read-only
    # shell fallback on a primary-tool error; blocking it for semble alone was an asymmetric
    # handicap (review H-5). Only the primary discriminator differs: codemap blocks semble MCP,
    # semble blocks the Skill tool, plain blocks both structural entry points.
    _ARM_DISALLOWED: dict[str, list[str]] = {
        "codemap": ["--disallowed-tools", "mcp__semble__search,mcp__semble__find_related"],
        "semble": ["--disallowed-tools", "Skill"],
        "plain": ["--disallowed-tools", "Skill,mcp__semble__search,mcp__semble__find_related"],
        "combined": [],
    }

    # Tools pre-approved per arm via --allowedTools (semble/combined need MCP pre-approved in -p mode)
    _ARM_ALLOWED: dict[str, list[str]] = {
        "codemap": ["--allowedTools", "Bash(scan-query:*)"],
        "semble": ["--allowedTools", "mcp__semble__search,mcp__semble__find_related"],
        "combined": ["--allowedTools", "Bash(scan-query:*),mcp__semble__search,mcp__semble__find_related"],
    }

    # Arm system prompts -------------------------------------------------------
    # PLAIN arm:   minimal fix/feature/refactor/review skill, no codemap.
    # CODEMAP arm: same skill + /codemap:query instruction.
    _PLAIN_SKILLS: dict[str, str] = {
        "fix": (
            "You are a software engineer fixing a bug in a Python codebase. "
            "Before writing any fix, investigate the affected module: understand what "
            "other modules depend on it and what it depends on, so you know the full "
            "blast radius of any interface change."
        ),
        "feature": (
            "You are a software engineer adding a new feature to a Python codebase. "
            "Before writing any code, explore the relevant modules to identify "
            "integration points, coupling risks, and which files you will need to modify."
        ),
        "refactor": (
            "You are a software engineer refactoring a Python codebase. "
            "Before changing anything, map out every module that imports the code "
            "being restructured so you understand the full scope of the change."
        ),
        "review": (
            "You are a software engineer reviewing a code change in a Python codebase. "
            "Identify all modules that depend on the changed code, assess the blast "
            "radius, and flag the highest regression risks."
        ),
    }
    # Shared efficiency sentence — identical for every arm so tool-call count reflects the
    # agent's own choices, not asymmetric steering (see benchmark review C-4).
    _EFFICIENCY = "\n\nAnswer in as few tool calls as possible; do not re-verify results you already have."

    # Shared, arm-neutral answer format. This is the erec/rrec extraction target and MUST be
    # identical across all four arms — any per-arm wording here would bias the measured signal.
    # Placeholders are generic (no hardcoded corpus paths) so no arm is primed with example modules.
    _ANSWER_FORMAT = """

## Required answer format

Your final answer MUST end with this section:

## Reverse Dependencies Found

Count: <N> distinct modules found.

- <full.dotted.module.path>
- <full.dotted.module.path>
- ... (one line per module)

Rules:
- Write "Count: N distinct modules found." where N = the exact number in your list
- Full dotted paths only — no shortened names, no file paths, no aliases
- List every module you found — no omissions
- If nothing found: write "Count: 0" and "(none found)"
- This section must be the LAST thing in your answer"""

    # Per-arm supplements below carry tool availability + invocation syntax ONLY. No call caps,
    # no "do not verify" rules, no step protocols — that steering is the measured signal and would
    # manufacture the savings it claims to observe (benchmark review C-4).
    _PLAIN_SUPPLEMENT = """

## Tools available

Grep, Glob, Bash, and Read are available for exploring the codebase and its import graph."""

    _CODEMAP_SUPPLEMENT = """

## Tools available

You have the /codemap:query-code skill (via the Skill tool). It answers import-graph questions
from a pre-built structural index.

Syntax — colon separator, never a space:
  codemap:query-code      (correct)
  codemap query-code      (wrong — fails silently)

Invocation:
  /codemap:query-code rdeps <primary_module> [--exclude-tests]

Grep, Glob, Bash, and Read remain available.

If /codemap:query-code returns <tool_use_error>, run one Grep/Bash fallback for the same query."""

    _SEMBLE_SUPPLEMENT = """

## Tools available

You have the mcp__semble__search and mcp__semble__find_related tools. They perform hybrid
semantic + lexical search across the codebase and return ranked code chunks with file path
and line range.

Parameters:
  query (str)   — natural language or code query
  repo  (str)   — REQUIRED: absolute path to the repository: {repo_path}
  top_k (int)   — number of results (default 5; raise it for broader coverage)

Grep, Glob, Bash, and Read are available for reading source code; the Skill tool is not.

If mcp__semble__search returns <tool_use_error>, run one Grep/Bash fallback for the same query."""

    _COMBINED_SUPPLEMENT = """

## Tools available

You have both /codemap:query-code (Skill tool, deterministic index) and mcp__semble__search /
mcp__semble__find_related (semantic search). Choose whichever fits each question.

codemap syntax — colon separator, never a space:
  /codemap:query-code rdeps <primary_module> [--exclude-tests]

semble parameters:
  query (str), repo (str, REQUIRED: {repo_path}), top_k (int)

Grep, Glob, Bash, and Read remain available.

If a structural tool returns <tool_use_error>, run one Grep/Bash fallback for the same query."""

    # read_crop task family — measures READ cost: extract ONE symbol's contract using the
    # fewest tokens of file content. Headline metric is tool_result_tokens (codemap `symbol`
    # extraction vs plain whole-file Read); correctness via keyword recall (score_read_crop).
    _READCROP_BASE = (
        "You are a software engineer answering a precise question about ONE symbol "
        "(function / method / class) in a Python codebase. Find that symbol's source, then state "
        "its full contract — every parameter and what it does. Use the FEWEST tokens of file "
        "content possible: do NOT read unrelated code, and do NOT read an entire large module file "
        "when you only need one symbol."
    )
    _READCROP_PLAIN = (
        "\n\n## Reading tools\n"
        "Use Grep to locate the symbol's definition line, then Read ONLY the needed line range "
        "(pass offset/limit) — never read the whole file if the symbol is a small part of it."
    )
    _READCROP_CODEMAP = (
        "\n\n## codemap installed — extract the symbol directly\n"
        "Run `scan-query symbol <Name> --with-imports` (via Bash) to get JUST that symbol's source "
        "with its imports — a fraction of the tokens of the full file. Do NOT Read the whole module "
        "file. The `symbols[].source` field is the authoritative source; render the contract from it."
    )
    _READCROP_SEMBLE = (
        "\n\n## semble installed — search then read the chunk\n"
        'Call mcp__semble__search with query naming the symbol and repo="{repo_path}", top_k=5. '
        "Read only the returned chunk's line range — do not read the whole file."
    )

    # fix_single task family — single-function / single-file bug fix; scored by diff keyword recall.
    _FIXSINGLE_BASE = (
        "You are a software engineer fixing a specific bug in a Python codebase. "
        "Read the relevant source file(s), understand the described issue, then apply the "
        "**minimal fix** using the Edit tool. Do not refactor unrelated code. "
        "The fix should be complete and correct — the scorer checks the diff for expected change markers."
    )
    _FIXSINGLE_PLAIN = (
        "\n\n## Tools\n"
        "Use Grep to locate the relevant class/function, then Read only the needed lines. "
        "Apply the fix with Edit."
    )
    _FIXSINGLE_CODEMAP = (
        "\n\n## codemap installed\n"
        "Use `scan-query symbol <Name>` (via Bash) to locate and read the target symbol "
        "before editing. For single-file fixes, codemap's symbol extraction shows the relevant "
        "code without reading the whole file."
    )
    _FIXSINGLE_SEMBLE = (
        "\n\n## semble installed\n"
        'Call mcp__semble__search with the symbol name and repo="{repo_path}" to locate the '
        "relevant code, then apply the fix with Edit."
    )

    # fix_multicaller task family — signature change that requires updating multiple callers;
    # scored by diff keyword recall + file recall. Codemap's rdeps is the decisive tool here.
    _FIXMULTI_BASE = (
        "You are a software engineer making a signature change that touches multiple call sites. "
        "Before writing any code: **find ALL callers of the function being changed**. "
        "Then edit the function definition AND every caller. Miss a caller = incomplete fix."
    )
    _FIXMULTI_PLAIN = (
        "\n\n## Tools\n"
        "Use grep/bash to find all callers of the function (search for the function name as a string). "
        "Edit the definition first, then each caller."
    )
    # Tool availability + syntax ONLY — no "do this FIRST", no "do NOT grep", no "decisive
    # advantage" framing. That steering was the measured signal and manufactured the tool-call
    # gap (review N3, mirroring C-4 for the rdep supplements).
    _FIXMULTI_CODEMAP = (
        "\n\n## codemap installed\n"
        "The /codemap:query-code skill (via the Skill tool) answers caller / import-graph "
        "questions from a pre-built structural index.\n"
        "Syntax — colon separator, never a space:\n"
        "  /codemap:query-code rdeps <primary_module> [--exclude-tests]\n"
        "Grep, Glob, Bash, and Read remain available."
    )
    _FIXMULTI_SEMBLE = (
        "\n\n## semble installed\n"
        'Call mcp__semble__search with the function name and repo="{repo_path}" to locate callers, '
        "then edit the definition and all callers."
    )

    def _system_prompt(self, task_type: str, arm: str) -> str:
        """Build the system prompt for one arm × task-type combination.

        The shared ``_EFFICIENCY`` sentence is appended for every task family (fix, read_crop,
        and rdep) so no arm is uniquely nudged toward more or fewer tool calls (review N3). The
        rdep-only ``_ANSWER_FORMAT`` block is not appended to fix / read_crop prompts — those are
        scored by diff / keyword recall, not by a reverse-dependency list.
        """
        if task_type == "fix_single":
            supplement = {
                "codemap": self._FIXSINGLE_CODEMAP,
                "semble": self._FIXSINGLE_SEMBLE.format(repo_path=self.repo_path),
            }.get(arm, self._FIXSINGLE_PLAIN)
            return self._FIXSINGLE_BASE + supplement + self._EFFICIENCY
        if task_type == "fix_multicaller":
            supplement = {
                "codemap": self._FIXMULTI_CODEMAP,
                "semble": self._FIXMULTI_SEMBLE.format(repo_path=self.repo_path),
            }.get(arm, self._FIXMULTI_PLAIN)
            return self._FIXMULTI_BASE + supplement + self._EFFICIENCY
        if task_type == "read_crop":
            supplement = {
                "codemap": self._READCROP_CODEMAP,
                "semble": self._READCROP_SEMBLE.format(repo_path=self.repo_path),
            }.get(arm, self._READCROP_PLAIN)
            return self._READCROP_BASE + supplement + self._EFFICIENCY
        base = self._PLAIN_SKILLS.get(task_type, self._PLAIN_SKILLS["fix"])
        if arm == "codemap":
            supplement = self._CODEMAP_SUPPLEMENT
        elif arm == "semble":
            supplement = self._SEMBLE_SUPPLEMENT.format(repo_path=self.repo_path)
        elif arm == "combined":
            supplement = self._COMBINED_SUPPLEMENT.format(repo_path=self.repo_path)
        else:
            supplement = self._PLAIN_SUPPLEMENT
        # Efficiency sentence and answer format are shared across all four arms (review C-4).
        return base + self._EFFICIENCY + supplement + self._ANSWER_FORMAT

    def __init__(
        self,
        model_short: str,
        model_id: str,
        repo_path: Path,
        timeout: int = 300,
    ) -> None:
        self.model_short = model_short
        self.model_id = model_id
        self.repo_path = repo_path
        self.timeout = timeout

    def run(
        self,
        task: Task,
        arm: str,
        update_fn: Optional[Callable[[float, "BenchmarkRun"], None]] = None,
    ) -> BenchmarkRun:
        """Run one task in one arm and return the parsed metrics.

        Launches a ``claude`` subprocess in stream-json mode and delegates event parsing
        to ``_stream_events``. Retries up to two times when the API returns zero tokens
        (connectivity failure). On the third failure the result is returned as-is.

        Args:
            task: The task to execute.
            arm: Benchmark arm identifier (``plain``, ``codemap``, ``semble``, or
                ``combined``). Controls which tools are allowed/disallowed and which
                system prompt supplement is injected.
            update_fn: Optional live-progress callback invoked (at most every 0.5 s)
                with ``(elapsed_seconds, partial_result)``. Used by the rich Progress bar
                in ``Benchmark.run()``. Pass ``None`` to disable.

        Returns:
            Populated ``BenchmarkRun`` with tool counts, token metrics, timing, and
            raw output text ready for quality scoring.
        """
        import contextlib
        import tempfile

        system_prompt = self._system_prompt(task.skill or task.type, arm)
        disallow_flags = self._ARM_DISALLOWED.get(arm, [])
        allow_flags = self._ARM_ALLOWED.get(arm, [])
        cmd = [
            *self._CMD,
            "--model",
            self.model_id,
            *disallow_flags,
            *allow_flags,
            "--system-prompt",
            system_prompt,
            task.prompt,
        ]

        _diff_capture: list[str] = []
        _test_capture: list[Optional[bool]] = []

        @contextlib.contextmanager
        def _effective_cwd():
            # EVERY arm runs in an isolated copy of the repo so agent edits can never mutate
            # self.repo_path. Blocking Edit/Write is not enough: the codemap and combined arms keep
            # Bash, so an agent could still write through the shell — only a throwaway copy bounds
            # the blast radius. Query (non-reset) arms previously ran in-place, letting a stray edit
            # contaminate later runs (review M-5); they now copy like every other arm.
            import shutil

            prefix = "bench-fix-" if task.requires_reset else "bench-copy-"
            with tempfile.TemporaryDirectory(prefix=prefix) as tmpdir:
                tmp = Path(tmpdir)
                cwd = tmp / self.repo_path.name
                shutil.copytree(
                    self.repo_path,
                    cwd,
                    ignore=shutil.ignore_patterns(".cache", ".git"),
                    symlinks=True,
                )
                # codemap / combined arms need the prebuilt index present in the sandbox;
                # otherwise the /codemap:query-code Step 0 would build it inside the measured
                # window (review H-3). The sandbox dir keeps the original repo name, so the
                # repo-name-derived index file (<repo>.json) resolves unchanged (git is absent →
                # resolve_proj_index falls back to the CWD basename). Plain and semble arms are
                # left index-free — plain for isolation, semble because it never queries the index.
                if arm in ("codemap", "combined"):
                    self._seed_index_cache(cwd)
                yield cwd
                if task.requires_reset:
                    import subprocess as _sp

                    proc = _sp.run(
                        ["diff", "-ru", "--no-dereference", str(self.repo_path), str(cwd)],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )
                    _diff_capture.append(proc.stdout)
                    # Opt-in correctness signal: run the task's declared pytest node on the sandbox
                    # (post-edit, pre-cleanup) so a semantically wrong edit that merely emits the
                    # right keywords does not score full recall unchecked (review M-4).
                    if task.test_target:
                        _test_capture.append(self._run_targeted_test(cwd, task.test_target))

        _MAX_API_RETRIES = 2
        with _effective_cwd() as cwd:
            # Each benchmark task is an independent agent session. Clear the
            # inject-preamble session-once flag so each task receives the
            # codemap status line regardless of inter-task timing.
            _flag = Path(tempfile.gettempdir()) / f"codemap-preamble-{cwd.name}"
            _flag.unlink(missing_ok=True)

            for attempt in range(_MAX_API_RETRIES + 1):
                result = BenchmarkRun(
                    arm=arm, task_id=task.id, task_type=task.type, model=self.model_short, success=False
                )
                self._stream_events(cmd, result, update_fn=update_fn, cwd=cwd, arm=arm)
                # 0-token result = API connectivity failure (ConnectionRefused / FailedToOpenSocket);
                # retry up to 2 times before surfacing as error.
                if result.input_tokens == 0 and result.output_tokens == 0 and attempt < _MAX_API_RETRIES:
                    result.error = f"api_failure_retry_{attempt + 1}"
                    time.sleep(2**attempt)  # exponential backoff: 1s, 2s
                    continue
                break
        if _diff_capture:
            result.agent_diff = _diff_capture[0]
        if _test_capture:
            result.targeted_test_passed = _test_capture[0]
        return result

    def _run_targeted_test(self, cwd: Path, test_target: str) -> Optional[bool]:
        """Run a task's declared pytest target on the post-edit sandbox and report pass/fail.

        Args:
            cwd: Sandbox repository root containing the agent's applied edits.
            test_target: pytest node id or path (e.g. ``tests/foo/test_bar.py::test_case``).

        Returns:
            ``True`` when pytest exits 0, ``False`` on any non-zero exit, and ``None`` when pytest
            could not be launched at all (missing binary / environment error) so a launch failure
            is never miscredited as a genuine test failure.
        """
        import subprocess as _sp

        try:
            proc = _sp.run(
                [sys.executable, "-m", "pytest", test_target, "-q", "-p", "no:cacheprovider"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, _sp.SubprocessError):
            return None
        return proc.returncode == 0

    def _seed_index_cache(self, cwd: Path) -> None:
        """Copy the prebuilt codemap index cache dirs into a sandbox copy of the repo.

        Only ``.cache/codemap`` and ``.cache/scan`` are copied from the original repo (never the
        whole ``.cache``), so the structural index is present in the sandbox without dragging in
        unrelated cache trees. Missing source dirs are skipped silently.

        Args:
            cwd: Sandbox repository root the index should be seeded into.
        """
        import shutil

        for sub in ("codemap", "scan"):
            source = self.repo_path / ".cache" / sub
            if source.is_dir():
                shutil.copytree(source, cwd / ".cache" / sub, symlinks=True)

    @staticmethod
    def _subprocess_env(arm: str = "") -> dict[str, str]:
        """Return os.environ augmented with codemap PATH and the benchmark's build opt-out.

        Plugin bin/ directories are not reliably added to PATH in ``claude -p`` mode, so the
        codemap ``bin/`` dir is injected explicitly to keep ``scan-query`` reachable inside skill
        Bash calls. For the codemap and combined arms ``SCAN_NO_AUTOBUILD=1`` is set so the
        /codemap:query-code Step 0 never runs ``scan-index --incremental`` inside the measured
        window — the benchmark builds the index out of band (review N2 / H-3). A genuinely
        missing index then fails loudly instead of being silently rebuilt mid-task.

        Args:
            arm: Benchmark arm; only ``codemap`` / ``combined`` receive the build opt-out.

        Returns:
            A copy of the process environment with PATH (and, for structural arms, the opt-out).
        """
        env = os.environ.copy()
        plugin_cache = Path.home() / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap"
        bin_dirs = sorted(plugin_cache.glob("*/bin"), reverse=True)  # latest version first
        if bin_dirs:
            env["PATH"] = str(bin_dirs[0]) + os.pathsep + env.get("PATH", "")
        if arm in ("codemap", "combined"):
            env["SCAN_NO_AUTOBUILD"] = "1"
        return env

    def _stream_events(
        self,
        cmd: list[str],
        result: BenchmarkRun,
        update_fn: Optional[Callable[[float, "BenchmarkRun"], None]] = None,
        cwd: Optional[Path] = None,
        arm: str = "",
    ) -> None:
        """Launch the claude subprocess, enforce wall-clock timeout, and parse stream-json events.

        Reads stdout line-by-line and routes each JSON event to ``_handle_event``.
        Calls ``update_fn(elapsed_s, result)`` at most every 0.5 s while the subprocess
        is running. Kills the subprocess via a ``threading.Timer`` at ``self.timeout``
        seconds and records the error on *result*.

        Args:
            cmd: Full ``claude`` CLI command list, constructed by ``run()``.
            result: Mutable ``BenchmarkRun`` populated in-place as events arrive.
            update_fn: Optional throttled callback; signature
                ``(elapsed_seconds: float, result: BenchmarkRun) -> None``.
                Invoked at most every 0.5 s. Pass ``None`` to disable.
            cwd: Working directory for the subprocess. Defaults to ``self.repo_path``.
                Plain-arm runs pass a symlink-based stripped copy without ``.cache/``.
            arm: Benchmark arm; forwarded to ``_subprocess_env`` so the codemap / combined
                arms receive the ``SCAN_NO_AUTOBUILD`` opt-out.
        """
        pending: dict[str, float] = {}
        pending_codemap_ids: set[str] = set()  # all codemap skill calls (for erec corpus)
        pending_rdeps_ids: set[str] = set()  # codemap rdeps calls specifically (for sc)
        pending_semble_ids: set[str] = set()  # all semble MCP calls (for erec corpus)
        t_start = time.monotonic()
        _last_update = 0.0
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=str(cwd if cwd is not None else self.repo_path),
                env=self._subprocess_env(arm),
            )
            kill_timer = threading.Timer(self.timeout, proc.kill)
            kill_timer.start()
            try:
                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    ts = time.monotonic()
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._handle_event(
                        event, result, pending, pending_codemap_ids, pending_rdeps_ids, pending_semble_ids, ts
                    )
                    if update_fn and (ts - _last_update) >= 0.5:
                        update_fn(ts - t_start, result)
                        _last_update = ts
                stderr_out = proc.stderr.read() if proc.stderr else ""
                proc.wait(timeout=10)
                if not result.success and not result.error and stderr_out:
                    result.error = stderr_out.strip()[:300]
            finally:
                kill_timer.cancel()
            if proc.returncode and proc.returncode < 0 and not result.error:
                result.error = f"timeout ({self.timeout}s)"
        except subprocess.TimeoutExpired:
            proc.kill()
            result.error = f"timeout ({self.timeout}s)"
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)[:300]
        finally:
            result.elapsed_s = time.monotonic() - t_start

    def _handle_event(
        self,
        event: dict,
        result: BenchmarkRun,
        pending: dict[str, float],
        pending_codemap_ids: set[str],
        pending_rdeps_ids: set[str],
        pending_semble_ids: set[str],
        ts: float,
    ) -> None:
        """Route a parsed stream-json event to the appropriate handler."""
        etype = event.get("type", "")

        if etype == "assistant":
            event_text_start = len(result.output_text)
            event_has_tool_use = any(b.get("type") == "tool_use" for b in event.get("message", {}).get("content", []))
            for block in event.get("message", {}).get("content", []):
                self._on_tool_use(block, result, pending, ts)
                if block.get("type") == "text":
                    result.output_text += block.get("text", "")
                # Track codemap skill calls for erec corpus + skill_coverage
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    tool_id = block.get("id", "")
                    skill_str = block.get("input", {}).get("skill", "")
                    args_str = block.get("input", {}).get("args", "")
                    if "codemap" in skill_str:
                        pending_codemap_ids.add(tool_id)
                        if "rdeps" in args_str or "rdeps" in skill_str:
                            pending_rdeps_ids.add(tool_id)
                elif block.get("type") == "tool_use" and block.get("name") == "Bash":
                    tool_id = block.get("id", "")
                    cmd = block.get("input", {}).get("command", "")
                    # In claude -p mode the skill sub-model never spawns; capture scan-query rdeps
                    # Bash calls as the equivalent fallback so sc/erec are meaningful.
                    # Match both "scan-query rdeps <m>" and "/path/to/scan-query rdeps <m>".
                    if re.search(r"(?:^|/)scan-query\s+rdeps\s+\S", cmd):
                        pending_codemap_ids.add(tool_id)
                        pending_rdeps_ids.add(tool_id)
                elif block.get("type") == "tool_use" and block.get("name") in (
                    "mcp__semble__search",
                    "mcp__semble__find_related",
                ):
                    tool_id = block.get("id", "")
                    result.tools.semble += 1
                    pending_semble_ids.add(tool_id)
            if not event_has_tool_use and len(result.output_text) > event_text_start:
                result.last_tool_text_offset = event_text_start
        elif etype == "user":
            # Tool results arrive as {"type":"user","message":{"content":[{"type":"tool_result",...}]}}
            for block in event.get("message", {}).get("content", []):
                if block.get("type") != "tool_result":
                    continue
                tool_id = block.get("tool_use_id", "")
                if tool_id in pending:
                    result.tool_elapsed_s += ts - pending.pop(tool_id)
                is_codemap = tool_id in pending_codemap_ids
                is_rdeps = tool_id in pending_rdeps_ids
                is_semble = tool_id in pending_semble_ids
                content_raw = block.get("content", "")
                if is_codemap:
                    pending_codemap_ids.discard(tool_id)
                if is_rdeps:
                    pending_rdeps_ids.discard(tool_id)
                if is_semble:
                    pending_semble_ids.discard(tool_id)
                # Detect blocked/permission-denied results and track separately
                _content_str = (
                    content_raw
                    if isinstance(content_raw, str)
                    else " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content_raw)
                )
                if "<tool_use_error>" in _content_str and (is_semble or is_codemap):
                    result.tools.blocked += 1
                    if not result.error_type:
                        result.error_type = "skill_blocked"
                self._on_tool_result(content_raw, result, is_codemap=is_codemap, is_rdeps=is_rdeps, is_semble=is_semble)
            # Advance report boundary: anything the model writes AFTER this tool_result event is the
            # final answer.  Without this, last_tool_text_offset stays 0 when the model emits no
            # pure-text event after its last tool call (Scenario-2 bug), making rrec corpus = full
            # output_text preamble and producing misleading rrec values.
            if any(b.get("type") == "tool_result" for b in event.get("message", {}).get("content", [])):
                result.last_tool_text_offset = len(result.output_text)
        elif etype == "result":
            usage = event.get("usage", {})
            # input_tokens is only the uncached portion; sum all parts for real context usage
            result.cache_creation_tokens = usage.get("cache_creation_input_tokens", 0)
            result.cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            result.input_tokens = usage.get("input_tokens", 0) + result.cache_creation_tokens + result.cache_read_tokens
            result.output_tokens = usage.get("output_tokens", 0)
            subtype = event.get("subtype", "")
            result.success = subtype == "success"
            if not result.success:
                result.error_type = subtype  # e.g. "error_max_turns", "error_non_zero_exit"

    def _on_tool_use(
        self,
        block: dict,
        result: BenchmarkRun,
        pending: dict[str, float],
        ts: float,
    ) -> None:
        """Update tool counts, log, and timing for one tool_use content block."""
        if block.get("type") != "tool_use":
            return
        name = block.get("name", "")
        tool_id = block.get("id", "")
        inp = block.get("input", {})
        attr = name.lower()
        if hasattr(result.tools, attr):
            setattr(result.tools, attr, getattr(result.tools, attr) + 1)
        result.tool_log.append(f"{name}: {_tool_key_arg(name, inp)}")
        if name in self.EXPLORATION_TOOLS and tool_id:
            pending[tool_id] = ts
        if name == "Bash":
            cmd = inp.get("command", "")
            # Patterns typical of manual import graph discovery (not file-reading)
            if re.search(r"\b(grep|rg)\b.*\bimport\b|\bgrep\b.*\bfrom\b|\bimport\b.*-r\b", cmd):
                result.tools.bash_for_imports += 1
            # Detect direct reads of the codemap index JSON (isolation violation in plain arm)
            if re.search(r"\.cache/codemap/|\.cache/scan/", cmd):
                result.tools.index_reads += 1

    @staticmethod
    def _on_tool_result(
        content: str | list,
        result: BenchmarkRun,
        is_codemap: bool = False,
        is_rdeps: bool = False,
        is_semble: bool = False,
    ) -> None:
        """Accumulate token count and capture codemap/semble results from a tool result content field.

        Skips content that contains ``<tool_use_error>`` or starts with
        ``"Launching skill:"`` (skill-executor status placeholders).

        Args:
            content: Raw ``content`` field from the ``tool_result`` event — either a plain
                string or a list of content blocks.
            result: The accumulating ``BenchmarkRun`` updated in-place.
            is_codemap: True when this result is from any codemap skill call. Not currently
                used for corpus capture (rdeps calls are distinguished by ``is_rdeps``);
                reserved for future per-call filtering.
            is_rdeps: True when this result is from a ``codemap:query rdeps`` call.
                Appends the text to ``result.codemap_results`` and ``result.skill_result_text``
                (used for exposure-recall corpus and skill-coverage scoring).
            is_semble: True when this result is from a semble MCP tool call
                (``mcp__semble__search`` or ``mcp__semble__find_related``). Appends the
                text to ``result.semble_results`` for the exposure-recall corpus.
        """

        def _capture(text: str) -> None:
            result.tool_result_tokens += count_tokens(text)
            # Skip error responses and skill executor status placeholders from corpus
            if "<tool_use_error>" in text or text.startswith("Launching skill:"):
                if "<tool_use_error>" in text:
                    result.tool_errors.append(text[:2000])
                return
            if is_rdeps:
                result.codemap_results.append(text)
                result.skill_result_text += ("\n" if result.skill_result_text else "") + text
            if is_semble:
                result.semble_results.append(text)

        if isinstance(content, str):
            _capture(content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    text = c.get("text") or c.get("content") or ""
                    if isinstance(text, str):
                        _capture(text)
                elif isinstance(c, str):
                    _capture(c)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _normalize_match_text(text: str) -> str:
    """Normalise text for whitespace-tolerant keyword matching.

    Drops whitespace flanking operators and punctuation so brittle literals like ``"< 1"`` match
    ``"<1"`` (and ``"<  1"``), while preserving single spaces between word tokens so distinct
    identifiers are never merged into false matches. Case is folded to lower.

    Args:
        text: Raw diff / answer text, or a single expected keyword.

    Returns:
        The normalised, lower-cased string ready for substring comparison.

    Examples:
        >>> _normalize_match_text("if patience < 1:")
        'if patience<1:'
        >>> _normalize_match_text("< 1") in _normalize_match_text("guard patience<1 here")
        True
        >>> _normalize_match_text("raise Error")  # word-word spaces are preserved
        'raise error'
    """
    collapsed = re.sub(r"\s*([^\w\s])\s*", r"\1", text)
    return re.sub(r"\s+", " ", collapsed).strip().lower()


def score_read_crop(output_text: str, expected_keywords: list[str]) -> QualityScore:
    """Keyword-recall scorer for read_crop tasks (no rdeps ground truth).

    ``erec``/``rrec`` are reused as keyword recall so the metric flows through the existing
    report columns; the headline efficiency signal is ``tool_result_tokens`` (read cost),
    reported separately. A keyword is matched case-insensitively as a substring of the answer.

    Args:
        output_text: Full agent answer text.
        expected_keywords: Ground-truth identifiers the correct contract must mention.

    Returns:
        QualityScore with recall in ``erec``/``rrec``; ``scored=False`` when no keywords given.

    Examples:
        >>> s = score_read_crop("uses prog_bar and on_step", ["prog_bar", "on_step", "logger"])
        >>> round(s.erec, 2), s.erec_tp, s.erec_fn
        (0.67, 2, 1)
    """
    if not expected_keywords:
        return QualityScore(scored=False)
    haystack = _normalize_match_text(output_text)
    hits = sum(1 for k in expected_keywords if _normalize_match_text(k) in haystack)
    n = len(expected_keywords)
    rec = hits / n
    return QualityScore(scored=True, erec=rec, erec_tp=hits, erec_fn=n - hits, rrec=rec, rrec_tp=hits, rrec_fn=n - hits)


def score_fix(
    diff_text: str,
    expected_patch_keywords: list[str],
    expected_files: list[str],
    test_passed: Optional[bool] = None,
) -> QualityScore:
    """Keyword-recall scorer for fix_single / fix_multicaller tasks.

    Checks the unified diff of agent edits for expected change markers. ``erec`` measures
    keyword recall in added lines; ``rrec`` measures file recall (were the right files changed).
    Keyword matching is whitespace-tolerant (see ``_normalize_match_text``) so operator literals
    like ``"< 1"`` are not defeated by an agent writing ``"<1"``.

    ``test_passed`` carries a stronger, opt-in correctness signal recorded *alongside* erec (it
    never replaces the recall column): when the task declares a targeted test, the caller runs it
    on the post-edit sandbox and passes the outcome here. It stays ``None`` for tasks with no
    declared test, so tasks without one are unaffected.

    Args:
        diff_text: Output of ``diff -ru original copy`` after agent run.
        expected_patch_keywords: Strings expected in diff added lines (``+`` prefix).
        expected_files: Relative file-path fragments expected in ``+++ b/...`` headers.
        test_passed: Outcome of the task's declared targeted test (True/False), or ``None`` when
            the task declares no test or the test could not be launched.

    Returns:
        QualityScore with keyword recall in ``erec``, file-change recall in ``rrec``, and the
        opt-in ``test_passed`` correctness signal. Returns ``scored=False`` when no keywords given.

    Examples:
        >>> d = "+        if patience < 1:\\n+            raise MisconfigurationException('patience')"
        >>> s = score_fix(d, ["patience < 1", "MisconfigurationException"], ["early_stopping.py"])
        >>> s.erec
        1.0
        >>> s.rrec  # no +++ header in that diff snippet — file path absent
        0.0
    """
    if not expected_patch_keywords:
        return QualityScore(scored=False)
    added_lines = "\n".join(
        line[1:] for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    haystack = _normalize_match_text(added_lines)
    hits = sum(1 for k in expected_patch_keywords if _normalize_match_text(k) in haystack)
    erec = round(hits / len(expected_patch_keywords), 3)
    # diff -ru produces "+++ /full/path\t<timestamp>"; git diff produces "+++ b/path"
    changed_files = set(re.findall(r"^\+\+\+ (?:b/)?(.+?)(?:\t.*)?$", diff_text, re.MULTILINE))
    rrec = 0.0
    if expected_files:
        file_hits = sum(1 for f in expected_files if any(f in cf for cf in changed_files))
        rrec = round(file_hits / len(expected_files), 3)
    return QualityScore(
        scored=True,
        erec=erec,
        erec_tp=hits,
        erec_fn=len(expected_patch_keywords) - hits,
        rrec=rrec,
        test_passed=test_passed,
    )


def _median_metrics(rlist: list[BenchmarkRun]) -> dict[str, float | None]:
    ok = [r for r in rlist if r.success]
    if not ok:
        return {}
    chunk_vals = [r.quality.chunk_hit_rate for r in ok if r.quality.chunk_hit_rate is not None]
    return {
        "tool_calls": statistics.median([r.tools.total for r in ok]),
        "input_tokens": statistics.median([r.input_tokens for r in ok]),
        "cost_usd": statistics.median([run_cost_usd(r) for r in ok]),
        "tool_result_tokens": statistics.median([r.tool_result_tokens for r in ok]),
        "tool_elapsed_s": statistics.median([r.tool_elapsed_s for r in ok]),
        "elapsed_s": statistics.median([r.elapsed_s for r in ok]),
        "rrec": statistics.median([r.quality.rrec for r in ok]),
        "erec": statistics.median([r.quality.erec for r in ok]),
        "delta": statistics.median([r.quality.delta for r in ok]),
        # None when no run in the cell carried a semble corpus (plain / codemap arms).
        "chunk_hit_rate": statistics.median(chunk_vals) if chunk_vals else None,
        "success_rate": len(ok) / len(rlist),
    }


def aggregate(
    results: list[BenchmarkRun],
    task_ids: list[str],
    model_short: str | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    """Return {task_id: {arm: {metric: value}}} optionally filtered to one model tier."""
    filtered = [r for r in results if model_short is None or r.model == model_short]
    by_task_arm: dict[str, dict[str, list[BenchmarkRun]]] = defaultdict(lambda: defaultdict(list))
    for r in filtered:
        by_task_arm[r.task_id][r.arm].append(r)

    out: dict[str, dict[str, dict[str, float]]] = {}
    for tid in task_ids:
        out[tid] = {}
        for arm, rlist in by_task_arm.get(tid, {}).items():
            out[tid][arm] = _median_metrics(rlist)
    return out


# ---------------------------------------------------------------------------
# Report renderer
# ---------------------------------------------------------------------------


class Report:
    """Renders a markdown benchmark report from a set of completed runs.

    Encapsulates the savings summary, per-task tables, and report assembly logic. All
    report-specific constants are class-level attributes.
    """

    _BASELINE = "plain"
    _INJECTED_ARMS = ("codemap", "semble", "combined")
    _NO_PAIRS_MD = "_(no completed plain + injected arm pairs)_"

    # Limitations appended verbatim to every report
    _LIMITATIONS_MD = [
        "## Limitations",
        "",
        "- Purely quantitative — answer quality / correctness is not scored",
        "- Tool time tracks wall-clock including I/O; LLM think time is not isolated",
        "- tiktoken o200k_base approximates Claude's tokeniser (not exact)",
        "- Cost ($) uses the fixed PRICES table (list prices, version-agnostic per tier); runs without a captured cache breakdown bill all input at full price = upper bound",
        "- Results vary across runs; model tier is the primary variance axis here",
        "- Tested on pytorch-lightning; generalisation to other corpora not assessed",
        "",
    ]

    @staticmethod
    def _fmt_tokens(v: float) -> str:
        return f"{v / 1000:.1f}k"

    @staticmethod
    def _fmt_s(v: float) -> str:
        return f"{v:.1f}s"

    @staticmethod
    def _fmt_int(v: float) -> str:
        return f"{v:.0f}"

    @staticmethod
    def _fmt_usd(v: float) -> str:
        return f"${v:.3f}"

    @staticmethod
    def _fmt_pct(v: float) -> str:
        return f"{v:.0%}"

    # Task types scored by diff/keyword recall, not by a reverse-dependency list. Their
    # efficiency (token / tool-call) savings are suppressed because the arms differ in edit
    # workload, not in structural-discovery cost — a savings figure there would be biased
    # (review N3). Quality (erec/rrec keyword recall) is still rendered for them.
    _FIX_TYPES = ("fix_single", "fix_multicaller")

    # Key metrics first — these are the headline savings signal.
    # Diagnostic metrics follow (tool breakdown, tool-only time).
    # cost_usd is the fair cross-arm metric (arms run different-priced models).
    _METRICS = [
        ("elapsed_s", "Elapsed (s)", _fmt_s),
        ("cost_usd", "Cost ($)", _fmt_usd),
        ("input_tokens", "Input tokens (k)", _fmt_tokens),
        ("tool_calls", "Tool calls", _fmt_int),
        ("tool_result_tokens", "Tool result tokens (k)", _fmt_tokens),
        ("tool_elapsed_s", "Tool time (s)", _fmt_s),
    ]

    # Quality lenses rendered as absolute per-arm medians (never as savings — higher is better).
    # chunk_hit_rate is the semble-native lens and is None (rendered "—") for plain / codemap.
    _QUALITY_METRICS = [
        ("erec", "Exposure recall (erec)", _fmt_pct),
        ("rrec", "Report recall (rrec)", _fmt_pct),
        ("chunk_hit_rate", "Chunk hit rate (semble lens)", _fmt_pct),
    ]

    def __init__(self, results: list[BenchmarkRun], tasks: list[Task], metadata: dict) -> None:
        self.results = results
        self.task_ids = [t.id for t in tasks]
        self.task_meta: dict[str, Task] = {t.id: t for t in tasks}
        self.metadata = metadata
        result_models = {r.model for r in results}
        self.model_tiers: list[str] = [m for m in MODELS if m in result_models]
        for m in result_models:
            if m not in self.model_tiers:
                self.model_tiers.append(m)

    def render(self) -> str:
        """Produce the full markdown report string."""
        models_label = ", ".join(self.model_tiers) if self.model_tiers else self.metadata.get("models", "n/a")

        repeat = self.metadata.get("repeat", 1)
        lines = [
            f"# Codemap Skill Benchmark Report — {self.metadata.get('date', 'n/a')}",
            "",
            f"**Models**: {models_label}  ",
            f"**Repo**: {self.metadata.get('repo', 'n/a')}  ",
            f"**Index**: {self.metadata.get('index', 'n/a')}  ",
            f"**Tasks**: {len(self.task_ids)}  ",
            f"**Repeat runs**: {repeat}  ",
            "",
            "> Savings = 1 − (arm / plain) per task; positive = arm needs less.",
            "",
        ]

        # ── Cross-model savings summary ──────────────────────────────────
        if len(self.model_tiers) > 1:
            lines += ["## Savings Summary by Model", ""]
            for m in self.model_tiers:
                agg = aggregate(self.results, self.task_ids, model_short=m)
                summary_rows = self._savings_summary(agg)
                lines.append(f"### {m.capitalize()}")
                lines.append("")
                if summary_rows:
                    lines.append(pd.DataFrame(summary_rows).to_markdown(index=False))
                else:
                    lines.append(self._NO_PAIRS_MD)
                lines.append("")
        else:
            m = self.model_tiers[0] if self.model_tiers else None
            agg = aggregate(self.results, self.task_ids, model_short=m)
            summary_rows = self._savings_summary(agg)
            lines += ["## Savings Summary", ""]
            if summary_rows:
                lines.append(pd.DataFrame(summary_rows).to_markdown(index=False))
            else:
                lines.append(self._NO_PAIRS_MD)
            lines.append("")

        # ── Per-model per-task tables ────────────────────────────────────
        for m in self.model_tiers:
            agg = aggregate(self.results, self.task_ids, model_short=m)
            lines.append(f"## Detail — {m.capitalize()}")
            lines.append("")
            lines += self._per_task_tables(agg)
            lines += [f"## Quality & reliability — {m.capitalize()}", ""]
            lines += self._per_task_quality_tables(agg)
            lines += self._success_table(m)
            lines += self._failures_section(m)

        lines += self._LIMITATIONS_MD

        return "\n".join(lines)

    def _arm_cells(self, arm: str, bv, iv, fmt, savings_applicable: bool = True) -> dict[str, str]:
        have_pair = savings_applicable and bv is not None and iv is not None and bv > 0
        if not savings_applicable:
            saved, arrow = "n/a", ""
        else:
            saved = f"{1.0 - iv / bv:.0%}" if have_pair else "—"
            arrow = ("↓" if iv < bv else "↑") if have_pair else ""
        return {
            arm.capitalize(): fmt(iv) if iv is not None else "—",
            f"{arm.capitalize()} savings": f"{saved} {arrow}".strip(),
        }

    def _efficiency_task_ids(self) -> list[str]:
        """Task ids eligible for efficiency savings — fix-family tasks are excluded (review N3)."""
        return [tid for tid in self.task_ids if (t := self.task_meta.get(tid)) and t.type not in self._FIX_TYPES]

    def _savings_summary(self, agg: dict) -> list[dict]:
        """Build savings rows for one model's aggregated results, one row per arm × metric.

        Each row carries ``n`` — the number of tasks where BOTH the plain baseline and the arm
        succeeded — so the denominator behind every savings figure is visible (review H-4).
        Fix-family tasks are excluded from the efficiency denominators (review N3).
        """
        baseline = self._BASELINE
        present_arms = {r.arm for r in self.results}
        injected_arms = [a for a in self._INJECTED_ARMS if a in present_arms]
        eligible = self._efficiency_task_ids()
        rows = []
        for arm in injected_arms:
            for key, label, _ in self._METRICS:
                savings_per_task = [
                    1.0 - iv / bv
                    for tid in eligible
                    for bv in [agg.get(tid, {}).get(baseline, {}).get(key)]
                    for iv in [agg.get(tid, {}).get(arm, {}).get(key)]
                    if bv and iv and bv > 0
                ]
                if not savings_per_task:
                    continue
                rows.append(
                    {
                        "Arm": arm,
                        "Metric": label,
                        "n": len(savings_per_task),
                        "Median savings": f"{statistics.median(savings_per_task):.0%}",
                        "Mean savings": f"{statistics.mean(savings_per_task):.0%}",
                        "Min savings": f"{min(savings_per_task):.0%}",
                        "Max savings": f"{max(savings_per_task):.0%}",
                    }
                )
        return rows

    def _per_task_tables(self, agg: dict) -> list[str]:
        """Return markdown lines for per-task metric tables, with dynamic columns for all injected arms."""
        baseline = self._BASELINE
        present_arms = {r.arm for r in self.results}
        injected_arms = [a for a in self._INJECTED_ARMS if a in present_arms]
        lines: list[str] = []
        for key, label, fmt in self._METRICS:
            rows = []
            for tid in self.task_ids:
                t = self.task_meta.get(tid)
                savings_ok = not (t and t.type in self._FIX_TYPES)
                bv = agg.get(tid, {}).get(baseline, {}).get(key)
                row = {"Task": tid, "Type": t.type if t else "?", "Plain": fmt(bv) if bv is not None else "—"}
                for arm in injected_arms:
                    iv = agg.get(tid, {}).get(arm, {}).get(key)
                    row.update(self._arm_cells(arm, bv, iv, fmt, savings_applicable=savings_ok))
                rows.append(row)
            lines += [f"### {label}", "", pd.DataFrame(rows).to_markdown(index=False), ""]
        return lines

    def _rendered_arms(self) -> list[str]:
        """Baseline plus every injected arm that produced at least one run, in canonical order."""
        present_arms = {r.arm for r in self.results}
        return [self._BASELINE] + [a for a in self._INJECTED_ARMS if a in present_arms]

    def _per_task_quality_tables(self, agg: dict) -> list[str]:
        """Render absolute per-arm quality medians (erec / rrec / chunk hit rate) — no savings.

        Quality is a correctness lens where higher is better, so it is shown as absolute
        percentages for every arm (review H-4). ``chunk_hit_rate`` is the semble-native lens and
        renders "—" for arms that carry no semble corpus.
        """
        arms = self._rendered_arms()
        lines: list[str] = []
        for key, label, fmt in self._QUALITY_METRICS:
            rows = []
            for tid in self.task_ids:
                t = self.task_meta.get(tid)
                row = {"Task": tid, "Type": t.type if t else "?"}
                for arm in arms:
                    v = agg.get(tid, {}).get(arm, {}).get(key)
                    row[arm.capitalize()] = fmt(v) if v is not None else "—"
                rows.append(row)
            lines += [f"### {label}", "", pd.DataFrame(rows).to_markdown(index=False), ""]
        return lines

    def _cell_counts(self, model: str) -> dict[str, dict[str, list[int]]]:
        """Return ``{task_id: {arm: [n_total, n_success]}}`` for one model tier.

        Unlike ``aggregate`` (which drops all-failed cells), this keeps every cell so failures are
        countable — a cell where every run failed still reports ``[n_total, 0]`` (review H-4).
        """
        counts: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for r in self.results:
            if r.model != model:
                continue
            cell = counts[r.task_id][r.arm]
            cell[0] += 1
            if r.success:
                cell[1] += 1
        return counts

    def _success_table(self, model: str) -> list[str]:
        """Render a per-task success-rate table (successful / total runs) for every arm."""
        counts = self._cell_counts(model)
        arms = self._rendered_arms()
        rows = []
        for tid in self.task_ids:
            row = {"Task": tid}
            for arm in arms:
                n_total, n_ok = counts.get(tid, {}).get(arm, [0, 0])
                row[arm.capitalize()] = f"{n_ok}/{n_total}" if n_total else "—"
            rows.append(row)
        return ["### Success rate (successful / total runs)", "", pd.DataFrame(rows).to_markdown(index=False), ""]

    def _failures_section(self, model: str) -> list[str]:
        """List every failed run for one model tier so drops are visible, not silently omitted."""
        fails = [r for r in self.results if r.model == model and not r.success]
        if not fails:
            return ["### Failed runs", "", "_No failed runs._", ""]
        rows = [{"Task": r.task_id, "Arm": r.arm, "Error": (r.error_type or r.error or "failed")[:80]} for r in fails]
        return ["### Failed runs", "", pd.DataFrame(rows).to_markdown(index=False), ""]


# ---------------------------------------------------------------------------
# Run-loop helpers
# ---------------------------------------------------------------------------


# ANSI colors for run-line output — arm colors make plain/codemap/semble/combined quads easy to scan
_COLOR_PLAIN = "\033[33m"  # yellow
_COLOR_CODEMAP = "\033[36m"  # cyan
_COLOR_SEMBLE = "\033[34m"  # blue
_COLOR_COMBINED = "\033[32m"  # green
_COLOR_FAIL = "\033[31m"  # red — overrides arm color on failure
_COLOR_RESET = "\033[0m"

_ARM_COLOR = {
    "plain": _COLOR_PLAIN,
    "codemap": _COLOR_CODEMAP,
    "semble": _COLOR_SEMBLE,
    "combined": _COLOR_COMBINED,
}


def _run_line(run_n: int, total_runs: int, task: Task, model_short: str, arm: str, result: BenchmarkRun) -> str:
    """Format the one-line progress summary printed after each run."""
    if not result.success:
        label = result.error_type or result.error or "failed"
        error_suffix = f" | ✗ {label}"
    else:
        error_suffix = ""
    tc = result.tools
    q = result.quality
    if q.scored:
        erec_part = f"erec={q.erec:4.0%} rrec={q.rrec:4.0%}"
        sc_part = f"  sc={q.skill_coverage:4.0%}" if q.skill_coverage is not None else ""
        chr_part = f"  chr={q.chunk_hit_rate:4.0%}" if q.chunk_hit_rate is not None else ""
        top10_part = f"  e@10={q.erec_top10:4.0%}" if q.erec_top10_k >= 5 else ""
        quality_suffix = f" | {erec_part}{sc_part}{chr_part}{top10_part}"
    else:
        quality_suffix = "\t| quality=n/a"
    # Flag possibly-degenerate codemap runs (very few total calls with 0% quality)
    degenerate_note = ""
    if arm == "codemap" and result.tools.total < 6 and result.tools.skill > 0 and q.scored and q.erec == 0.0:
        degenerate_note = " ⚑degenerate?"
    task_num = task.id.lstrip("T")
    difficulty = task.difficulty
    return (
        f"[{run_n:0{len(str(total_runs))}}/{total_runs}] {task_num} ({difficulty}) | {model_short:<6} | {arm:<8}"
        f" | time={result.elapsed_s:5.1f}s | ${run_cost_usd(result):6.3f} | tok={result.input_tokens / 1000:5.1f}k | calls={result.tools.total:3}"
        f" (Gp={tc.grep:2}; Gb={tc.glob:2}; Bh={tc.bash:2}; Sk={tc.skill:2}; Sm={tc.semble:2}; blk={tc.blocked:2}; bfi={tc.bash_for_imports:2}; idx={tc.index_reads:2})"
        f"{quality_suffix}"
        f"{error_suffix}{degenerate_note}"
    )


def _iter_combos(
    tasks: list[Task],
    models: list[tuple[str, str]],
    arms: list[str],
    repeat: int,
) -> Iterator[tuple[Task, str, str, str, int]]:
    for task in tasks:
        for model_short, model_id in models:
            for arm in arms:
                for rep in range(repeat):
                    yield task, model_short, model_id, arm, rep


# ---------------------------------------------------------------------------
# Benchmark orchestrator
# ---------------------------------------------------------------------------


class Benchmark:
    """Orchestrates the full benchmark run: iterates tasks x arms x models.

    Constructs ``GroundTruth`` internally from the index, manages result accumulation, tool-call
    logging, and snapshot persistence.
    """

    def __init__(
        self,
        tasks: list[Task],
        arms: list[str],
        models: list[tuple[str, str]],
        repo_path: Path,
        index_path: Path,
        output_path: Path,
        log_path: Path,
        repeat: int = 1,
    ) -> None:
        self.tasks = tasks
        self.arms = arms
        self.models = models
        self.repo_path = repo_path
        self.output_path = output_path
        self.log_path = log_path
        self.repeat = max(1, repeat)
        self.gt = GroundTruth(index_path, tasks, repo_path=repo_path)
        self.results: list[BenchmarkRun] = []

    def _iter_combos(self) -> Iterator[tuple[Task, str, str, str, int]]:
        return _iter_combos(self.tasks, self.models, self.arms, self.repeat)

    def _run_single(
        self,
        task: Task,
        model_short: str,
        model_id: str,
        arm: str,
        run_n: int,
        total_runs: int,
        print_fn: Callable[[str], None],
        metadata: dict,
        update_fn: Optional[Callable[[float, "BenchmarkRun"], None]] = None,
    ) -> BenchmarkRun:
        runner = ModelRunner(model_short, model_id, self.repo_path, timeout=_MODEL_TIMEOUT.get(model_short, 300))
        result = runner.run(task, arm, update_fn=update_fn)
        # Build corpora for v2 quality scoring.
        # erec uses agent-text only — tool outputs excluded so codemap arm erec measures
        # agent comprehension, not whether the skill echoed the list back. The semble chunk
        # corpus feeds the semble-native chunk_hit_rate lens (review C-5); erec/rrec stay the
        # codemap-native rdep-recall lens.
        exposure_corpus = result.output_text
        report_corpus = result.output_text[result.last_tool_text_offset :]
        semble_corpus = "\n".join(result.semble_results) or None
        result.quality = self.gt.score(
            task_id=task.id,
            output_text=result.output_text,
            exposure_corpus=exposure_corpus,
            report_corpus=report_corpus,
            tool_calls=result.tools.total,
            skill_result_text=result.skill_result_text or None,
            semble_result_text=semble_corpus,
        )
        # read_crop tasks have no rdeps ground truth — score by keyword recall instead,
        # and exempt them from the codemap-skill-required guard (they use scan-query symbol
        # via Bash, not the Skill tool).
        if task.type == "read_crop":
            result.quality = score_read_crop(result.output_text, task.expected_keywords)
        if task.type in ("fix_single", "fix_multicaller"):
            result.quality = score_fix(
                result.agent_diff,
                task.expected_patch_keywords,
                task.expected_files,
                test_passed=result.targeted_test_passed,
            )
        # Degenerate-loop detection MUST precede the no-skill-call guard below. A codemap arm that
        # ignored the index and grepped its way through has skill == 0, which the no-call guard
        # would otherwise claim first (labelling it "codemap skill never called") — leaving the
        # ≥70% grep-ratio classification unreachable for blast-radius tasks (review M-2). Ordering
        # it first lets a grep-heavy zero-skill run be labelled degenerate_grep_loop; a zero-skill
        # run that is NOT grep-heavy still falls through to the no-call guard.
        if result.arm == "codemap" and result.success:
            total_calls = result.tools.total
            grep_like = result.tools.grep + result.tools.bash_for_imports
            if total_calls > 0 and result.tools.skill == 0 and grep_like / total_calls >= 0.70:
                result.success = False
                result.error_type = "degenerate_grep_loop"
                result.error = (
                    f"codemap arm used no codemap skill; fell back to grep "
                    f"({grep_like}/{total_calls} grep-like calls = {grep_like / total_calls:.0%}); "
                    f"index not used"
                )
        # Codemap arm that never invoked the Skill tool (and did not already fail the degenerate
        # check above) is a failure — it fell back to grep/bash entirely, defeating the purpose.
        # fix tasks use Edit (not Skill), so exempt them from this guard.
        if (
            arm == "codemap"
            and result.tools.skill == 0
            and result.success
            and task.type not in ("read_crop", "fix_single", "fix_multicaller")
        ):
            result.success = False
            result.error = "codemap skill never called"
        # Semble arm: failure if never called semble, or all calls were permission-blocked.
        if arm == "semble" and result.success:
            effective_semble = result.tools.semble - result.tools.blocked
            if result.tools.semble == 0:
                result.success = False
                result.error = "semble tool never called"
            elif effective_semble <= 0:
                result.success = False
                result.error = "semble tool called but all invocations were blocked (permission denied)"
        # Combined arm: failure if no structural tool was ever called or all semble were blocked.
        if arm == "combined" and result.success:
            effective_semble = result.tools.semble - result.tools.blocked
            if result.tools.skill == 0 and result.tools.semble == 0:
                result.success = False
                result.error = "combined arm: neither codemap skill nor semble tool called"
            elif result.tools.skill == 0 and effective_semble <= 0:
                result.success = False
                result.error = "combined arm: all semble calls were blocked (permission denied)"
        # Skill-error failure: codemap/combined arm where the skill returned tool_use_error.
        # These runs fell back to grep — not measuring codemap benefit; exclude from metrics.
        if result.arm in ("codemap", "combined") and result.success and result.error_type == "skill_blocked":
            result.success = False
            result.error_type = "codemap_skill_errored"
            result.error = (
                "codemap skill returned <tool_use_error>; run fell back to grep — "
                "not a valid codemap measurement; re-run after fixing skill invocation"
            )
        # Plain arm isolation check: flag any run that read the codemap index JSON via Bash.
        # Currently low-yield (agents usually guess the wrong home-dir path) but the vector is
        # real — a single correct path read hands the agent the full index for free.
        if result.arm == "plain" and result.tools.index_reads > 0:
            result.error_type = "plain_index_contamination"
            result.error = (
                f"plain arm read .cache/codemap/ or .cache/scan/ index via Bash "
                f"({result.tools.index_reads} read(s)) — isolation violated; exclude from baseline"
            )
            result.success = False
        self._write_tool_log(result)
        color = _COLOR_FAIL if not result.success else _ARM_COLOR.get(arm, "")
        print_fn(f"{color}{_run_line(run_n, total_runs, task, model_short, arm, result)}{_COLOR_RESET}")
        self._save_snapshot(metadata)
        return result

    def run(self, metadata: dict) -> list[BenchmarkRun]:
        """Execute all benchmark runs and return the accumulated results."""
        total_runs = len(self.tasks) * len(self.arms) * len(self.models) * self.repeat
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=_console,
        ) as progress:
            outer = progress.add_task("running", total=total_runs)
            for run_n, (task, model_short, model_id, arm, _) in enumerate(self._iter_combos(), start=1):
                sub = progress.add_task(f"  {task.id} | {model_short} | {arm}", total=None)
                progress.update(outer, description=f"{task.id} | {model_short} | {arm}")

                def _make_update(
                    sub_id: int = sub,
                ) -> Callable[[float, "BenchmarkRun"], None]:
                    def _update(elapsed: float, run: BenchmarkRun) -> None:
                        calls = run.tools.total
                        tool_live = f"B={run.tools.bash} G={run.tools.grep} Sk={run.tools.skill} Sm={run.tools.semble}"
                        progress.update(
                            sub_id,
                            description=f"  {elapsed / 60:.1f}m calls={calls} {tool_live}",
                        )

                    return _update

                result = self._run_single(
                    task,
                    model_short,
                    model_id,
                    arm,
                    run_n,
                    total_runs,
                    print_fn=lambda text: progress.console.print(text, markup=False, highlight=False),
                    metadata=metadata,
                    update_fn=_make_update(),
                )
                progress.remove_task(sub)
                progress.advance(outer)
                self.results.append(result)
        return self.results

    def _write_tool_log(self, result: BenchmarkRun) -> None:
        """Append one JSON line to the tool-call log for post-run investigation."""
        with self.log_path.open("a") as fh:
            fh.write(
                json.dumps(
                    {"task_id": result.task_id, "arm": result.arm, "model": result.model, "calls": result.tool_log}
                )
                + "\n"
            )

    def _save_snapshot(self, metadata: dict) -> None:
        """Atomically overwrite the results JSON with the current snapshot.

        Called after every run onto a single rolling file. The payload is written to a temp file
        in the output directory first, then ``os.replace`` swaps it into place — an atomic rename
        on POSIX. A SIGINT/kill mid-write therefore leaves the results file either fully old or
        fully new, never a truncated mix that would lose every accumulated run (review M-1). The
        temp file is removed if serialisation fails so no ``.tmp`` residue accumulates.
        """
        import tempfile

        serialised = []
        for r in self.results:
            d = asdict(r)
            for key in (
                "skill_result_text",
                "codemap_results",
                "semble_results",
                "last_tool_text_offset",
                "targeted_test_passed",
            ):
                d.pop(key, None)
            serialised.append(d)
        payload = {"metadata": metadata, "results": serialised}
        out = self.output_path
        fd, tmp_name = tempfile.mkstemp(dir=str(out.parent), prefix=f".{out.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_name, out)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    repo_path: Path,
    index: Path = None,
    tasks_file: Path = Path("benchmarks/suites/tasks-agentic.json"),
    model: str = None,
    arm: str = None,
    run_all: bool = False,
    tasks: list[str] = None,
    report: bool = False,
    output: Path = None,
    repeat: int = 1,
    dry_run: bool = False,
) -> None:
    """Codemap skill benchmark — agent exploration cost with vs without structural context.

    Args:
        repo_path: Path to the indexed repo.
        index: Explicit index path (auto-discovered if omitted).
        tasks_file: Task definition file.
        model: Run a single model tier (default: all — haiku/sonnet/opus).
        arm: Run only one arm (default: all four).
        run_all: Run all tasks in both arms.
        tasks: Run specific task IDs only.
        report: Write markdown report alongside JSON.
        output: JSON output path (auto-named if omitted).
        repeat: Repeat runs per (task, arm, model) cell; median aggregated.
        dry_run: Print plan without running claude.
    """
    # fire passes CLI string args regardless of type annotation — coerce Path args explicitly.
    repo_path = Path(repo_path)
    if index is not None:
        index = Path(index)
    tasks_file = Path(tasks_file)
    if output is not None:
        output = Path(output)

    if not run_all and not tasks and not arm and not dry_run:
        sys.exit("Specify --run_all to run everything, or narrow with --tasks / --arm.")

    # ── Load tasks ────────────────────────────────────────────────────────
    if not tasks_file.exists():
        sys.exit(f"Tasks file not found: {tasks_file}")
    with tasks_file.open() as f:
        raw = json.load(f)
        task_list = raw["tasks"] if isinstance(raw, dict) else raw
        all_tasks: list[Task] = [
            Task(
                id=t["id"],
                type=t["type"],
                prompt=t["prompt"],
                primary_module=t.get("primary_module", ""),
                difficulty=t.get("difficulty", "unknown"),
                skill=t.get("skill", ""),
                symbol=t.get("symbol", ""),
                expected_keywords=t.get("expected_keywords", []),
                requires_reset=t.get("requires_reset", False),
                codebase_module=t.get("codebase_module", ""),
                expected_patch_keywords=t.get("expected_patch_keywords", []),
                expected_files=t.get("expected_files", []),
                test_target=t.get("test_target", ""),
            )
            for t in task_list
        ]
    if tasks:
        all_tasks = [t for t in all_tasks if t.id in tasks]
    if not all_tasks:
        sys.exit("No tasks to run.")

    # ── Locate prerequisites (validated before any run starts) ──────────
    repo_path = repo_path.resolve()
    index_path = find_index(repo_path, index)

    arms = [arm] if arm else ["plain", "codemap", "semble"]
    if not arm:
        print("[→ note:        'all' excludes 'combined' — run with --arm combined to include it]")

    if "semble" in arms or "combined" in arms:
        check_semble_mcp()
    repeat = max(1, repeat)
    models_to_run: list[tuple[str, str]] = [(model, MODELS[model])] if model else list(MODELS.items())
    total_runs = len(all_tasks) * len(arms) * len(models_to_run) * repeat

    model_names = ", ".join(m for m, _ in models_to_run)

    # ── Output path + tool-call log ───────────────────────────────────────
    date_slug = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_path = output or (RESULTS_DIR / f"code-{date_slug}.json")
    # Tool-call log: one JSON line per run, for post-run investigation of bash commands
    log_dir = Path(".temp") / f"bench-{date_slug}"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "tool-calls.jsonl"

    print(f"[→ repo:        {repo_path}]")
    print(f"[→ index:       {index_path}]")
    print(f"[→ models:      {model_names}]")
    print(f"[→ tasks:       {len(all_tasks)}, arms: {len(arms)}, models: {len(models_to_run)}, repeat: {repeat}]")
    print(f"[→ total runs:  {total_runs}]")
    print(f"[→ tool log:    {log_path}]")

    if dry_run:
        for task, model_short, _, arm, rep in _iter_combos(all_tasks, models_to_run, arms, repeat):
            print(f"  [DRY RUN] {task.id} ({task.type}) | {model_short} | {arm} | rep={rep + 1}/{repeat}")
        return

    if "codemap" in arms:
        _sample_runner = ModelRunner("haiku", MODELS["haiku"], repo_path)
        _sample = _sample_runner._system_prompt("fix", "codemap")
        print(f"[→ codemap arm:  skill + /codemap:query available ({len(_sample)} chars for fix type)]")
    if "combined" in arms:
        _sample_runner = ModelRunner("haiku", MODELS["haiku"], repo_path)
        _sample = _sample_runner._system_prompt("fix", "combined")
        print(f"[→ combined arm: both codemap + semble available ({len(_sample)} chars for fix type)]")
    output_path = _unique_path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    metadata = {
        "date": datetime.now(timezone.utc).isoformat(),
        "models": model_names,
        "repo": str(repo_path),
        "index": str(index_path),
        "task_count": len(all_tasks),
        "repeat": repeat,
    }

    # ── Construct benchmark and show ground truth info ────────────────────
    benchmark = Benchmark(
        tasks=all_tasks,
        arms=arms,
        models=models_to_run,
        repo_path=repo_path,
        index_path=index_path,
        output_path=output_path,
        log_path=log_path,
        repeat=repeat,
    )
    print(f"[→ quality gt:   {len(benchmark.gt.expected)} tasks with rdep ground truth]")

    # ── Run ───────────────────────────────────────────────────────────────
    all_results = benchmark.run(metadata)

    # ── Report ────────────────────────────────────────────────────────────
    if report:
        report_obj = Report(all_results, all_tasks, {**metadata, "date": date_slug})
        report_md = report_obj.render()
        report_path = output_path.with_suffix(".md")
        report_path.write_text(report_md)
        print(f"\n→ Report: {report_path}")

    print(f"→ Data:   {output_path}")


if __name__ == "__main__":
    fire.Fire(main)
