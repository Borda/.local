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

  Ground truth (deterministic, index-derived):
    expected = { m.name for m in index.modules if primary_module in m.direct_imports and not m.name.startswith("tests.") }
    Test modules excluded — blast-radius analysis targets production callers only.
    Reproducible across runs as long as the index does not change.

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
    erec_top10 — erec restricted to top-10 most-central rdeps by dep_count (meaningful for tasks with ≥5 rdeps)

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
  - pip install -r benchmarks/requirements.txt  (tiktoken pandas tabulate rich tqdm semble)
  - uv add semble  (alternative: uv add semble>=0.1.0)
  - Pre-built codemap index (see step 1 above)

## Failure conditions

  A run is marked success=False when any of these occur:
    timeout          — claude subprocess exceeded the 300 s wall-clock limit
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
          "erec_top10": N.N,            ← erec on top-10 most-central rdeps by dep_count; equals erec when |rdeps|≤10
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
    "opus": "claude-opus-4-6",
}

# Per-model wall-clock timeout (seconds). Opus needs more time for complex reasoning.
_MODEL_TIMEOUT: dict[str, int] = {"haiku": 210, "sonnet": 420, "opus": 600}


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
    erec_top10: float = 0.0  # erec restricted to top-10 rdeps by dep_count centrality
    erec_top10_k: int = 0  # actual k used (min(10, |expected|)); equals |expected| when ≤10

    # ── Skill result coverage (codemap arm only; None when not applicable) ──
    skill_coverage: Optional[float] = None
    skill_returned: Optional[int] = None

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
    # Timing metrics (stored in seconds)
    elapsed_s: float = 0.0
    tool_elapsed_s: float = 0.0  # time inside tool execution only
    error: str = ""
    error_type: str = ""  # subtype from result event: error_max_turns | error_non_zero_exit | error_timeout | ""
    # Per-call log for post-run investigation: ["Bash: grep -r 'import'", "Skill: /codemap:query rdeps ..."]
    tool_log: list[str] = field(default_factory=list)
    # Full agent output text — captured for quality scoring
    output_text: str = ""
    quality: QualityScore = field(default_factory=QualityScore)
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
# Quality scoring — deterministic, index-derived ground truth
# ---------------------------------------------------------------------------


class GroundTruth:
    """Index-derived ground truth for quality scoring benchmark runs.

    Loads the codemap index once, pre-computes expected rdep sets per task, and exposes a
    ``score()`` method for comparing agent output against truth.
    """

    _MODULE_RE = re.compile(r"\blightning(?:\.[a-zA-Z_][a-zA-Z0-9_]*)+")
    _PATH_RE = re.compile(r"\bsrc/(lightning(?:/[a-zA-Z_][a-zA-Z0-9_]*)+)\.py\b")

    def __init__(self, index_path: Path, tasks: list[Task]) -> None:
        """Load the codemap index and pre-compute expected rdep sets for each task.

        Args:
            index_path: Path to the pre-built codemap JSON index produced by ``scan-index``.
            tasks: Task definitions used to derive per-task ground-truth rdep sets. Tasks
                without a ``primary_module`` are skipped silently.
        """
        with index_path.open() as f:
            index = json.load(f)
        self.all_modules: set[str] = {m["name"] for m in index.get("modules", []) if m.get("status") == "ok"}
        self.expected: dict[str, set[str]] = {}
        for task in tasks:
            pm = getattr(task, "primary_module", "")
            if not pm:
                continue
            rdeps = {
                m["name"]
                for m in index.get("modules", [])
                if pm in m.get("direct_imports", []) and m.get("status") == "ok" and not m["name"].startswith("tests.")
            }
            self.expected[task.id] = rdeps
        # dep_count = forward import count per module (proxy for centrality; always populated)
        _dep_counts: dict[str, int] = {m["name"]: m.get("dep_count", 0) for m in index.get("modules", [])}
        # Top-10 most-central rdeps per task (by dep_count descending); k=min(10, |rdeps|)
        self.top10_expected: dict[str, frozenset[str]] = {}
        for task in tasks:
            rdeps = self.expected.get(task.id, set())
            if rdeps:
                ranked = sorted(rdeps, key=lambda m: _dep_counts.get(m, 0), reverse=True)[:10]
                self.top10_expected[task.id] = frozenset(ranked)
        self.all_leaf_names: set[str] = {m.split(".")[-1] for m in self.all_modules}
        # Precompute multi-form match patterns for every module in the index
        self._match_patterns: dict[str, list[re.Pattern]] = {m: self._generate_match_set(m) for m in self.all_modules}

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
    ) -> QualityScore:
        """Compute quality score using multi-form matching and optional skill coverage.

        Primary metrics (v2):
            ``erec`` — exposure recall on ``exposure_corpus`` (agent output_text only; tool outputs excluded)
            ``rrec`` — report recall on ``report_corpus`` (final answer after last tool call)
            ``delta`` — erec - rrec
            ``deff`` — erec_tp / max(tool_calls, 1)

        Supplementary:
            ``skill_coverage`` — fraction of expected rdeps in the skill result (codemap only)

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

    @classmethod
    def _extract_modules(cls, text: str) -> set[str]:
        """Extract dotted lightning.* module names from agent output.

        Handles two forms agents use:
        - Dotted: ``lightning.pytorch.trainer.trainer``
        - File path: ``src/lightning/pytorch/trainer/trainer.py`` -> converted to dotted
        """
        dotted = set(cls._MODULE_RE.findall(text))
        from_paths = {m.replace("/", ".") for m in cls._PATH_RE.findall(text)}
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
    _ARM_DISALLOWED: dict[str, list[str]] = {
        "codemap": ["--disallowed-tools", "mcp__semble__search,mcp__semble__find_related"],
        "semble": ["--disallowed-tools", "Skill,Bash"],
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
    _PLAIN_SUPPLEMENT = """

## Structural navigation with native tools

Use Grep and Glob for all import graph questions — avoid reading full files
unless the import block alone is not enough:

  What imports X?   Grep the dotted module name across **/*.py
  What does X import?   Read only the import block at the top of X's file
  Blast radius ranking:   Count Grep matches per module; more matches = wider blast
  Import path A → B:   Follow deps of A and rdeps of B until they intersect"""

    _CODEMAP_SUPPLEMENT = """

## codemap plugin installed — follow these steps exactly

You have /codemap:query-code. It answers import-graph questions from a pre-built index.

**SYNTAX — colon separator, never a space:**
  Skill tool name: codemap:query-code      ← correct
  NOT: codemap query-code                  ← wrong — will fail silently

### STEP 1 — One rdeps query (max 3 codemap calls total)

Call:
  /codemap:query-code rdeps <primary_module> [--exclude-tests]

Read the result immediately:
- If "exhaustive": true → list is complete and authoritative. Count the entries.
  Your final list MUST contain exactly that many modules. Go to STEP 2 NOW.
  Do NOT grep. Do NOT call codemap again. Do NOT read files to verify.
- If NOT exhaustive → record the list as your working set. You may make 1-2 more
  codemap calls (e.g. deps or central for context). Then go to STEP 2.

Maximum 3 /codemap:query-code calls total across all steps.

If /codemap:query-code returns <tool_use_error>: skip to STEP 2 with an empty list.

### STEP 2 — Write the report (no more tool calls after this point)

Once you reach STEP 2, do NOT call any tool. Write the answer immediately.

**Hard rules — no exceptions:**
1. NEVER use Grep, Glob, or Bash to verify or extend codemap results — the index is authoritative. Exception: rule 5 (tool error fallback).
2. After seeing "exhaustive": true, your tool calls are complete. Write the report.
3. Maximum 3 codemap:query-code calls — stop even if not exhaustive after 3 calls.
4. NEVER spawn sub-agents for import-graph questions.
5. If /codemap:query-code returns <tool_use_error>: do NOT call codemap:scan. Fall back to Grep for that query only.

Grep/Glob/Bash are permitted only for reading source code (finding a literal string in files).

## Required answer format

Your final answer MUST end with this section:

## Reverse Dependencies Found

Count: <N> distinct modules found.

- lightning.pytorch.trainer.trainer
- lightning.pytorch.loops.fit_loop
- ... (one line per module)

Rules:
- Write "Count: N distinct modules found." where N = exact number in your list
- Full dotted paths only — no shortened names, no file paths, no aliases
- Copy EVERY module from the codemap result — no omissions
- If nothing found: write "Count: 0" and "(none found)"
- This section must be the LAST thing in your answer"""

    _SEMBLE_SUPPLEMENT = """

## semble MCP installed

You have the mcp__semble__search tool available. It performs hybrid semantic + lexical search
across the codebase and returns ranked code chunks with file path and line range.

Tool parameters:
  query (str)   — natural language or code query; pass the task prompt directly or rephrase it
  repo  (str)   — REQUIRED: absolute path to the repository: {repo_path}
  top_k (int)   — number of results; use 20 for thorough coverage (default 5)

Use mcp__semble__search for ALL structural questions:
  Which modules import X?      query="import X" or "from X import", top_k=20
  Blast radius of X?           query="usage of X across the codebase", top_k=20
  Dependency relationships?    pass the full task prompt as query, top_k=20

**Hard rules — no exceptions:**
1. NEVER use Grep, Glob, or Bash to investigate import relationships, including
   running grep/rg/find via Bash shell commands.
2. NEVER spawn sub-agents for import-graph questions.
3. Always set repo="{repo_path}" in every mcp__semble__search call.
4. Maximum 12 semble calls total. After your semble calls are complete, do NOT
   make any additional Bash or Read calls before writing the report.

Grep and Glob are permitted for reading source code. Bash is NOT available in this arm.

## Required answer format

After your tool calls, your final answer MUST end with this section:

## Reverse Dependencies Found

Count: <N> distinct modules found across all semble results.

- lightning.pytorch.trainer.trainer
- lightning.pytorch.loops.fit_loop
- ... (one line per module)

Rules:
- Write "Count: N distinct modules found across all semble results." first, where N is the
  exact number of unique dotted paths you collected across ALL semble calls (not just the last)
- Full dotted paths only — no shortened names, no file paths, no aliases
- Copy EVERY module path from ALL your tool results, even if already mentioned in prose above
- Union all results: if call 1 found A,B,C and call 2 found B,D — list A, B, C, D (not just D)
- If nothing found: write "Count: 0" and "(none found)"
- This section must be the LAST thing in your answer"""

    _COMBINED_SUPPLEMENT = """

## Two structural tools — follow this protocol exactly

You have /codemap:query-code (deterministic index) and mcp__semble__search (semantic search).
Follow the three steps below in order. Do NOT reorder or skip steps.

### STEP 1 — Codemap anchor (always first; max 2 codemap calls)

Call codemap:query-code rdeps on the primary module:
  /codemap:query-code rdeps <module>

Read the result:
  - If it contains "exhaustive": true → the list is complete and authoritative.
    Count the number of entries returned (e.g. "rdeps contains 14 entries").
    Your final list MUST contain exactly that many modules.
    Go directly to STEP 3. Do NOT call semble. Do NOT validate with grep or bash.
  - If it does NOT contain "exhaustive": true → record the returned modules as your
    anchor set and go to STEP 2.

If the result was non-exhaustive, you may make one additional codemap call (deps or central)
for task context — skip this if codemap was exhaustive (you are going directly to STEP 3).
Maximum 2 codemap calls in STEP 1.

If /codemap:query-code returns <tool_use_error>: skip to STEP 2 with an empty anchor set.

### STEP 2 — Semble gap-fill (only if codemap was non-exhaustive)

Call mcp__semble__search to find modules NOT already in your codemap anchor set:
  query: "<primary_module> import" or the task description rephrased, top_k=20
  repo: "{repo_path}"  ← required on every call

After each call, count how many NEW modules (not yet in your set) the result added.
Keep calling semble with varied queries (e.g. "from <module> import", "<module> usage",
"<module> caller", task description rephrased) — each query may surface different files.

**Convergence rule — stop semble when**: two consecutive calls each add 0 new modules.
That signals saturation; proceed to STEP 3 immediately.

Do NOT alternate back to codemap. Merge after each call: running set = codemap anchor ∪ all semble finds so far.

### STEP 3 — Write the report (no more tool calls)

Once you reach STEP 3, do NOT call any tool. Write the answer immediately.

**Hard rules — no exceptions:**
1. NEVER use Grep, Glob, or Bash to investigate import relationships.
2. NEVER spawn sub-agents for import-graph questions.
3. Always set repo="{repo_path}" in every mcp__semble__search call.
4. NEVER alternate between tools after STEP 1 completes (no codemap → semble → codemap loops).

Grep/Glob/Bash are permitted only for reading source code (literal string search).

## Required answer format

Your final answer MUST end with this section:

## Reverse Dependencies Found

Count: <N> distinct modules found.

- lightning.pytorch.trainer.trainer
- lightning.pytorch.loops.fit_loop
- ... (one line per module)

Rules:
- Write "Count: N distinct modules found." where N = exact number of unique dotted paths
  in your list (must equal the codemap entry count if codemap was exhaustive)
- Full dotted paths only — no shortened names, no file paths, no aliases
- Copy EVERY module path from ALL tool results — union of codemap + all semble calls
- If nothing found: write "Count: 0" and "(none found)"
- This section must be the LAST thing in your answer"""

    def _system_prompt(self, task_type: str, arm: str) -> str:
        """Build the system prompt for one arm × task-type combination."""
        base = self._PLAIN_SKILLS.get(task_type, self._PLAIN_SKILLS["fix"])
        if arm == "codemap":
            supplement = self._CODEMAP_SUPPLEMENT
        elif arm == "semble":
            supplement = self._SEMBLE_SUPPLEMENT.format(repo_path=self.repo_path)
        elif arm == "combined":
            supplement = self._COMBINED_SUPPLEMENT.format(repo_path=self.repo_path)
        else:
            supplement = self._PLAIN_SUPPLEMENT
        return base + supplement

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

        # Plain arm runs in a real directory copy (not symlinks) minus .cache/ so that
        # macOS `find`/`rg` can traverse the tree without -L. Other arms run directly
        # in self.repo_path.
        @contextlib.contextmanager
        def _effective_cwd():
            if arm != "plain":
                yield self.repo_path
                return
            import shutil

            with tempfile.TemporaryDirectory(prefix="bench-plain-") as tmpdir:
                tmp = Path(tmpdir)
                cwd = tmp / self.repo_path.name
                shutil.copytree(
                    self.repo_path,
                    cwd,
                    ignore=shutil.ignore_patterns(".cache", ".git"),
                    symlinks=True,
                )
                yield cwd

        _MAX_API_RETRIES = 2
        with _effective_cwd() as cwd:
            for attempt in range(_MAX_API_RETRIES + 1):
                result = BenchmarkRun(
                    arm=arm, task_id=task.id, task_type=task.type, model=self.model_short, success=False
                )
                self._stream_events(cmd, result, update_fn=update_fn, cwd=cwd)
                # 0-token result = API connectivity failure (ConnectionRefused / FailedToOpenSocket);
                # retry up to 2 times before surfacing as error.
                if result.input_tokens == 0 and result.output_tokens == 0 and attempt < _MAX_API_RETRIES:
                    result.error = f"api_failure_retry_{attempt + 1}"
                    time.sleep(2**attempt)  # exponential backoff: 1s, 2s
                    continue
                break
        return result

    @staticmethod
    def _subprocess_env() -> dict[str, str]:
        """Return os.environ augmented with the codemap plugin bin directory on PATH.

        Plugin bin/ directories are not reliably added to PATH in ``claude -p`` mode,
        so we inject it explicitly here. This ensures ``scan-query`` is always reachable
        inside skill Bash calls regardless of how the shell or Claude Code manage PATH.
        """
        env = os.environ.copy()
        plugin_cache = Path.home() / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap"
        bin_dirs = sorted(plugin_cache.glob("*/bin"), reverse=True)  # latest version first
        if bin_dirs:
            env["PATH"] = str(bin_dirs[0]) + os.pathsep + env.get("PATH", "")
        return env

    def _stream_events(
        self,
        cmd: list[str],
        result: BenchmarkRun,
        update_fn: Optional[Callable[[float, "BenchmarkRun"], None]] = None,
        cwd: Optional[Path] = None,
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
                env=self._subprocess_env(),
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
            result.input_tokens = (
                usage.get("input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
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
            # Skip error responses and skill executor status placeholders
            if "<tool_use_error>" in text or text.startswith("Launching skill:"):
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


def _median_metrics(rlist: list[BenchmarkRun]) -> dict[str, float]:
    ok = [r for r in rlist if r.success]
    if not ok:
        return {}
    return {
        "tool_calls": statistics.median([r.tools.total for r in ok]),
        "input_tokens": statistics.median([r.input_tokens for r in ok]),
        "tool_result_tokens": statistics.median([r.tool_result_tokens for r in ok]),
        "tool_elapsed_s": statistics.median([r.tool_elapsed_s for r in ok]),
        "elapsed_s": statistics.median([r.elapsed_s for r in ok]),
        "rrec": statistics.median([r.quality.rrec for r in ok]),
        "erec": statistics.median([r.quality.erec for r in ok]),
        "delta": statistics.median([r.quality.delta for r in ok]),
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

    # Key metrics first — these are the headline savings signal.
    # Diagnostic metrics follow (tool breakdown, tool-only time).
    _METRICS = [
        ("elapsed_s", "Elapsed (s)", _fmt_s),
        ("input_tokens", "Input tokens (k)", _fmt_tokens),
        ("tool_calls", "Tool calls", _fmt_int),
        ("tool_result_tokens", "Tool result tokens (k)", _fmt_tokens),
        ("tool_elapsed_s", "Tool time (s)", _fmt_s),
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

        lines += self._LIMITATIONS_MD

        return "\n".join(lines)

    def _arm_cells(self, arm: str, bv, iv, fmt) -> dict[str, str]:
        have_pair = bv is not None and iv is not None and bv > 0
        saved = f"{1.0 - iv / bv:.0%}" if have_pair else "—"
        arrow = ("↓" if iv < bv else "↑") if have_pair else ""
        return {
            arm.capitalize(): fmt(iv) if iv is not None else "—",
            f"{arm.capitalize()} savings": f"{saved} {arrow}".strip(),
        }

    def _savings_summary(self, agg: dict) -> list[dict]:
        """Build savings rows for one model's aggregated results, one row per arm × metric."""
        baseline = self._BASELINE
        present_arms = {r.arm for r in self.results}
        injected_arms = [a for a in self._INJECTED_ARMS if a in present_arms]
        rows = []
        for arm in injected_arms:
            for key, label, _ in self._METRICS:
                savings_per_task = [
                    1.0 - iv / bv
                    for tid in self.task_ids
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
                bv = agg.get(tid, {}).get(baseline, {}).get(key)
                row = {"Task": tid, "Type": t.type if t else "?", "Plain": fmt(bv) if bv is not None else "—"}
                for arm in injected_arms:
                    iv = agg.get(tid, {}).get(arm, {}).get(key)
                    row.update(self._arm_cells(arm, bv, iv, fmt))
                rows.append(row)
            lines += [f"### {label}", "", pd.DataFrame(rows).to_markdown(index=False), ""]
        return lines


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
        top10_part = f"  e@10={q.erec_top10:4.0%}" if q.erec_top10_k >= 5 else ""
        quality_suffix = f" | {erec_part}{sc_part}{top10_part}"
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
        f" | time={result.elapsed_s:5.1f}s | tok={result.input_tokens / 1000:5.1f}k | calls={result.tools.total:3}"
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
        self.gt = GroundTruth(index_path, tasks)
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
        # agent comprehension, not whether the skill echoed the list back.
        exposure_corpus = result.output_text
        report_corpus = result.output_text[result.last_tool_text_offset :]
        result.quality = self.gt.score(
            task_id=task.id,
            output_text=result.output_text,
            exposure_corpus=exposure_corpus,
            report_corpus=report_corpus,
            tool_calls=result.tools.total,
            skill_result_text=result.skill_result_text or None,
        )
        # Codemap arm that never invoked the Skill tool is a failure —
        # it fell back to grep/bash entirely, defeating the purpose.
        if arm == "codemap" and result.tools.skill == 0 and result.success:
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
        # Degenerate-loop detection: codemap arm that spent ≥70% of calls on Grep
        # ignored the index and fell into a grep loop — mark as failure.
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
        """Overwrite the results JSON with the current snapshot (called after every run)."""
        serialised = []
        for r in self.results:
            d = asdict(r)
            for key in ("skill_result_text", "codemap_results", "semble_results", "last_tool_text_offset"):
                d.pop(key, None)
            serialised.append(d)
        with self.output_path.open("w") as fh:
            json.dump({"metadata": metadata, "results": serialised}, fh, indent=2)


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

    arms = [arm] if arm else ["plain", "codemap", "semble", "combined"]

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
