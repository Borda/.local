#!/usr/bin/env python3
"""Shared helpers for the benchmark runners and task generators.

Anything used by two or more of ``run-*.py`` / ``generate-tasks-*.py`` lives here so
there is a single source of truth. The scripts have hyphenated filenames (not importable as
modules), so each imports this module by sibling name — their own directory is already on
``sys.path`` at runtime, and ``tests/conftest.py`` puts it there for the test loader.

The near-duplicate resolvers (``resolve_index_path``, ``resolve_relative_base``) are unified
here with keyword flags so each caller keeps its exact historical contract via a thin adapter.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Directory (repo-relative) where every runner writes its results JSONL.
RESULTS_DIR = Path("benchmarks/results")

# Short tier name → concrete model id, shared by the agentic and real-codebase runners.
MODELS: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-5",
}

# Per-model wall-clock timeout (seconds). Opus needs more time for complex reasoning.
MODEL_TIMEOUT: dict[str, int] = {"haiku": 210, "sonnet": 420, "opus": 600}

# Canonical benchmark task file (the SE/FN/RV/... suite), shared by the bench runner,
# the task generator, and the CLI runner's OSS lane.
TASKS_BENCH_FILE = Path(__file__).parent / "suites" / "tasks-bench.json"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def fmt_tok(v: float) -> str:
    """Format a token count with a k/M unit suffix.

    Millions get one decimal (``1.5M``); anything ``>=1000`` becomes ``k`` (``937.6k``);
    smaller counts print raw (``842``). Used for both input and output token columns so
    they read consistently across runners.

    Args:
        v: Token count.

    Returns:
        Formatted count, e.g. ``"1.5M"``, ``"937.6k"``, or ``"842"``.

    Examples:
        >>> fmt_tok(1_500_000)
        '1.5M'
        >>> fmt_tok(937_600)
        '937.6k'
        >>> fmt_tok(842)
        '842'
    """
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    return f"{int(v)}"


def fmt_time(seconds: float) -> str:
    """Format an elapsed duration as ``2m5s`` (minutes + seconds).

    The minute part is dropped below one minute (``45s``); seconds are rounded to the nearest
    integer. Used for the per-run and progress time columns so they read consistently across runners.

    Args:
        seconds: Elapsed wall-clock seconds.

    Returns:
        ``"<m>m<s>s"`` at or above a minute, else ``"<s>s"``.

    Examples:
        >>> fmt_time(125)
        '2m5s'
        >>> fmt_time(45.4)
        '45s'
        >>> fmt_time(0)
        '0s'
    """
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs}s" if minutes else f"{secs}s"


# ---------------------------------------------------------------------------
# Task metadata
# ---------------------------------------------------------------------------


def gt_is_pending(task: dict) -> bool:
    """Return whether a task's ground truth is an unmaterialized placeholder.

    A ``gt_pending`` task was authored without its target repo present, so it carries a
    placeholder ground truth and stale stage anchors; runners skip it until it is
    materialized via ``generate-tasks-bench.py --update``.

    Args:
        task: A task dict from a suites/*.json file.

    Returns:
        ``True`` when ``task["ground_truth"]["gt_pending"]`` is truthy, else ``False``.

    Examples:
        >>> gt_is_pending({"ground_truth": {"gt_pending": True}})
        True
        >>> gt_is_pending({"ground_truth": {}})
        False
        >>> gt_is_pending({})
        False
    """
    return bool(task.get("ground_truth", {}).get("gt_pending"))


# ---------------------------------------------------------------------------
# Binary / environment discovery
# ---------------------------------------------------------------------------


def find_codemap_bin(name: str, plugin_root: Path | None = None) -> Path | None:
    """Locate a codemap CLI binary (scan-query / scan-index) on PATH or in the plugin dir.

    Checks ``PATH`` first via :func:`shutil.which`. Falls back to
    ``<plugin_root>/plugins/codemap-py/bin/<name>`` when ``plugin_root`` is given.

    Args:
        name: Binary name to locate (e.g. ``"scan-query"`` or ``"scan-index"``).
        plugin_root: Root of the plugin repository; checked only when the binary is not on PATH.

    Returns:
        Resolved :class:`~pathlib.Path` to the binary, or ``None`` when not found.

    Examples:
        >>> find_codemap_bin("codemap-bin-that-does-not-exist-xyz", None) is None
        True
    """
    which = shutil.which(name)
    if which:
        return Path(which)
    if plugin_root:
        candidate = plugin_root / "plugins" / "codemap-py" / "bin" / name
        if candidate.exists():
            return candidate
    return None


def codemap_bin_on_path(env: dict[str, str]) -> dict[str, str]:
    """Prepend the newest installed codemap-py ``bin/`` dir to ``env['PATH']`` (in place).

    Plugin ``bin/`` dirs are not reliably added to PATH in ``claude -p`` mode, so runners
    inject the codemap ``bin/`` explicitly to keep ``scan-query`` reachable inside skill
    Bash calls. Mutates and returns the same dict for convenient chaining.

    Args:
        env: Environment mapping to augment (typically ``os.environ.copy()``).

    Returns:
        The same ``env`` dict, with ``PATH`` prepended when a bin dir was found.

    Examples:
        >>> "PATH" in codemap_bin_on_path({"PATH": "/usr/bin"})
        True
    """
    plugin_cache = Path.home() / ".claude" / "plugins" / "cache" / "borda-ai-rig" / "codemap-py"
    bin_dirs = sorted(plugin_cache.glob("*/bin"), reverse=True)  # latest version first
    if bin_dirs:
        env["PATH"] = str(bin_dirs[0]) + os.pathsep + env.get("PATH", "")
    return env


# ---------------------------------------------------------------------------
# Index resolution (unified — callers pick contract via keyword flags)
# ---------------------------------------------------------------------------


def resolve_index_path(
    repo_path: Path,
    explicit: str | Path | None = None,
    *,
    strip_suffixes: bool = True,
    missing: str = "bare",
    require_explicit_file: bool = False,
) -> Path:
    """Resolve the codemap index path under ``<repo>/.cache/{codemap,scan}/``.

    Search order is dir-major: ``.cache/codemap/`` then ``.cache/scan/``; within each,
    ``<repo_name>.json`` (plus ``-master``/``-main``-stripped stems when ``strip_suffixes``),
    then the lexicographically first ``*.json``. Callers pick the miss/explicit contract:

    - ``missing="bare"``: return a constructed (possibly non-existent) path and leave found
      paths unresolved (the "may not be built yet" flow).
    - ``missing="raise"``: ``.resolve()`` found paths and raise ``FileNotFoundError`` on a miss.
    - ``require_explicit_file``: when an explicit path is given, ``.resolve()`` it and raise if
      it is not an existing file.

    Args:
        repo_path: Root of the repository being benchmarked.
        explicit: Caller-supplied index path (e.g. ``--index-path``); short-circuits discovery.
        strip_suffixes: Also try ``-master``/``-main``-stripped stems (disable for exact-name only).
        missing: ``"bare"`` (return computed fallback) or ``"raise"`` (raise on miss).
        require_explicit_file: Validate that an explicit path exists as a file (raises otherwise).

    Returns:
        Path to the index file. Resolved when ``missing="raise"``; unresolved when ``"bare"``.

    Raises:
        FileNotFoundError: When ``missing="raise"`` and nothing is found, or when
            ``require_explicit_file`` is set and the explicit path is not a file.

    Examples:
        >>> import pathlib, tempfile
        >>> resolve_index_path(pathlib.Path(tempfile.gettempdir())).suffix
        '.json'
    """
    raise_mode = missing == "raise"
    if explicit is not None:
        p = Path(explicit)
        if raise_mode:
            p = p.resolve()
        if require_explicit_file and not p.is_file():
            raise FileNotFoundError(f"Explicit index not found: {p}")
        return p

    stems = [repo_path.name]
    if strip_suffixes:
        stems += [repo_path.name.replace("-master", ""), repo_path.name.replace("-main", "")]
    for cache_name in ("codemap", "scan"):
        d = repo_path / ".cache" / cache_name
        for stem in stems:
            candidate = d / f"{stem}.json"
            if candidate.exists():
                return candidate.resolve() if raise_mode else candidate
        if d.is_dir():
            jsons = sorted(d.glob("*.json"))
            if jsons:
                return jsons[0].resolve() if raise_mode else jsons[0]

    if raise_mode:
        raise FileNotFoundError(
            f"No codemap index found under {repo_path}/.cache/{{codemap,scan}}/.\n"
            "Build it first (one-time, not measured):\n"
            f"  python plugins/codemap-py/bin/scan-index --root {repo_path}"
        )
    bare = repo_path.name.replace("-master", "").replace("-main", "")
    return repo_path / ".cache" / "codemap" / f"{bare}.json"


# ---------------------------------------------------------------------------
# Relative-import resolution (unified)
# ---------------------------------------------------------------------------


def resolve_relative_base(
    package: str, level: int, module: Optional[str], *, escape_to_none: bool = True
) -> Optional[str]:
    """Resolve a relative ``from`` import to its absolute base module.

    Ascends ``level - 1`` package components and appends ``module``.

    Args:
        package: Dotted package of the importing module (its ``__package__``).
        level: Number of leading dots (1 = current package, 2 = parent, ...).
        module: Text after the dots (``from ..a.b import x`` → ``"a.b"``); ``None`` for
            ``from . import x``.
        escape_to_none: When ``True`` (default), an over-ascend past the package root, or an
            empty result, returns ``None``. When ``False``, reproduce the permissive form:
            no over-ascend guard (Python negative slicing) and an empty base yields ``""``
            (or the bare ``module`` when a suffix is present).

    Returns:
        Absolute dotted base module. ``None`` on escape/empty when ``escape_to_none`` (else a
        possibly-empty ``str``).

    Examples:
        >>> resolve_relative_base("a.b", 1, "c")
        'a.b.c'
        >>> resolve_relative_base("a", 3, "x") is None
        True
        >>> resolve_relative_base("a", 3, "x", escape_to_none=False)
        'x'
    """
    base_parts = package.split(".") if package else []
    ascend = level - 1
    if escape_to_none and ascend > len(base_parts):
        return None
    kept = base_parts[: len(base_parts) - ascend] if ascend else base_parts
    base = ".".join(kept)
    if module:
        combined = f"{base}.{module}" if base else module
    else:
        combined = base
    if escape_to_none:
        return combined or None
    return combined


def _import_target_kept(name: str, keep: Optional[set[str]]) -> bool:
    """Return True when a dotted import target survives the internal-module filter.

    Args:
        name: Dotted import target.
        keep: Allowlist of internal modules; ``None`` keeps everything.

    Returns:
        True when ``keep`` is ``None`` or ``name`` is a member of it.

    Examples:
        >>> _import_target_kept("a.b", None)
        True
        >>> _import_target_kept("a.b", {"a.b"})
        True
        >>> _import_target_kept("c.d", {"a.b"})
        False
    """
    return keep is None or name in keep


def extract_import_targets(
    tree: ast.Module,
    *,
    package: str = "",
    keep: Optional[set[str]] = None,
    credit_submodules: bool = True,
    symbol_when_bare: bool = False,
) -> set[str]:
    """Collect the dotted import targets referenced by a module's import statements.

    Walks ``import a.b`` aliases and ``from a.b import c`` targets, resolving relative imports
    against ``package``. The flags reproduce each caller's historical contract:

    - ``keep``: when given, only targets in this set are returned (internal-module filter).
    - ``credit_submodules``: also credit ``a.b.c`` for ``from a.b import c`` (not just ``a.b``).
    - ``symbol_when_bare``: when a relative import resolves to an empty base, record the imported
      *symbol* names instead of skipping (and resolve relatives permissively, no over-ascend guard).

    Args:
        tree: Parsed module AST.
        package: Dotted package of the importing module (for relative resolution).
        keep: Optional internal-module allowlist; ``None`` keeps everything.
        credit_submodules: Credit the ``base.name`` submodule form for ``from`` imports.
        symbol_when_bare: Record symbol names when the resolved base is empty (permissive lane).

    Returns:
        Set of dotted names the module imports (filtered by ``keep`` when provided).

    Examples:
        >>> import ast
        >>> t = ast.parse("import a.b\\nfrom c.d import e\\nfrom . import f\\n")
        >>> sorted(extract_import_targets(t, keep={"a.b", "c.d"}))
        ['a.b', 'c.d']
        >>> sorted(extract_import_targets(t, symbol_when_bare=True))
        ['a.b', 'c.d', 'c.d.e', 'f']
    """
    esc = not symbol_when_bare
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _import_target_kept(alias.name, keep):
                    targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                base = resolve_relative_base(package, node.level, node.module, escape_to_none=esc) or ""
            if not base:
                if symbol_when_bare:
                    targets.update(a.name for a in node.names if a.name != "*")
                continue
            if _import_target_kept(base, keep):
                targets.add(base)
            if credit_submodules:
                for alias in node.names:
                    full = f"{base}.{alias.name}"
                    if alias.name != "*" and _import_target_kept(full, keep):
                        targets.add(full)
    return targets


# ---------------------------------------------------------------------------
# Filesystem / repo walking
# ---------------------------------------------------------------------------

# Directory names pruned from a source walk by default (build/venv cruft, never source).
PY_WALK_SKIP = frozenset({"__pycache__", ".venv", "venv"})


def prune_walk_dirs(dirnames: list[str], *, skip: frozenset[str] = PY_WALK_SKIP) -> list[str]:
    """In-place prune of an :func:`os.walk` ``dirnames`` list: drop dotfiles and ``skip`` names.

    Mutates ``dirnames[:]`` so ``os.walk`` does not descend into hidden/cruft/`skip` dirs, and
    returns it for convenience. This is the shared body behind every runner's walk loop.

    Args:
        dirnames: The mutable ``dirnames`` list yielded by ``os.walk`` (edited in place).
        skip: Directory names to prune in addition to any dotfile-prefixed dir.

    Returns:
        The same ``dirnames`` list, pruned.

    Examples:
        >>> ds = ["pkg", ".git", "__pycache__", "sub"]
        >>> prune_walk_dirs(ds)
        ['pkg', 'sub']
        >>> ds
        ['pkg', 'sub']
    """
    dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in skip]
    return dirnames


def iter_py_files(root: Path, *, skip: frozenset[str] = PY_WALK_SKIP) -> Iterator[Path]:
    """Yield ``*.py`` files under ``root``, pruning hidden and ``skip`` directories.

    Directories whose name starts with ``.`` (``.git``, ``.cache``) and any name in ``skip``
    are not descended into. Callers pass their own ``skip`` set (e.g. ``{"tests", "test"}`` to
    exclude test trees) — the default excludes only build/venv cruft.

    Args:
        root: Repository root to walk.
        skip: Directory names to prune (in addition to any dotfile-prefixed dir).

    Yields:
        Absolute paths to candidate Python source files.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = pathlib.Path(d)
        ...     _ = (r / "a.py").write_text("")
        ...     _ = (r / "__pycache__").mkdir()
        ...     _ = (r / "__pycache__" / "b.py").write_text("")
        ...     sorted(p.name for p in iter_py_files(r))
        ['a.py']
    """
    for dirpath, dirnames, filenames in os.walk(root):
        prune_walk_dirs(dirnames, skip=skip)
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def walk_py_modules(
    root: Path,
    *,
    skip: frozenset[str] = PY_WALK_SKIP,
    keep: Optional[Callable[[str], bool]] = None,
) -> Iterator[tuple[Path, str, "ast.Module"]]:
    """Yield ``(path, rel_path, tree)`` for every parseable ``*.py`` file under ``root``.

    Bundles the walk+prune+``.py``-filter+``rel_path``-normalise+``ast.parse``-skip-``SyntaxError``
    scaffold shared by the AST oracle scans. ``rel_path`` is POSIX-normalised
    (``os.sep`` → ``/``) so callers can apply path regexes portably. Files that fail to parse are
    silently skipped, matching the oracle's tolerant scan.

    Args:
        root: Repository root to walk.
        skip: Directory names to prune (in addition to any dotfile-prefixed dir).
        keep: Optional predicate on the POSIX ``rel_path``; when given, only files for which it
            returns truthy are parsed and yielded (e.g. ``lambda r: not TEST_RE.search(r)`` to drop
            test modules, or ``lambda r: bool(TEST_RE.search(r))`` to keep only them). ``keep`` is
            evaluated *before* parsing, so unwanted files are never read.

    Yields:
        ``(path, rel_path, tree)`` triples — absolute path, POSIX repo-relative path, parsed AST.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = pathlib.Path(d)
        ...     _ = (r / "a.py").write_text("import os\\n")
        ...     _ = (r / "bad.py").write_text("def (\\n")  # unparsable — skipped
        ...     [rel for _p, rel, _t in walk_py_modules(r)]
        ['a.py']
    """
    for dirpath, dirnames, filenames in os.walk(root):
        prune_walk_dirs(dirnames, skip=skip)
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            rel_path = str(path.relative_to(root)).replace(os.sep, "/")
            if keep is not None and not keep(rel_path):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
            except SyntaxError:
                continue
            yield path, rel_path, tree


def module_from_init_chain(path: Path) -> str:
    """Derive a dotted module name by walking a file's ``__init__.py`` package chain.

    Ascends from ``path`` while each parent directory is a package (contains ``__init__.py``),
    collecting package names; the walk stops at the first non-package ancestor (the ``src/`` dir
    in a src-layout repo, or the repo root in a flat layout), so no ``src.`` prefix is emitted.

    Args:
        path: Absolute path to a ``.py`` file whose parent directory is a package.

    Returns:
        Dotted module name (an ``__init__.py`` resolves to its package name); ``""`` when the
        file is not inside any package.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = pathlib.Path(d)
        ...     _ = (r / "pkg").mkdir()
        ...     _ = (r / "pkg" / "__init__.py").write_text("")
        ...     _ = (r / "pkg" / "mod.py").write_text("")
        ...     module_from_init_chain(r / "pkg" / "mod.py")
        'pkg.mod'
    """
    parts: list[str] = []
    if path.stem != "__init__":
        parts.append(path.stem)
    directory = path.parent
    while (directory / "__init__.py").exists() and directory != directory.parent:
        parts.append(directory.name)
        directory = directory.parent
    parts.reverse()
    return ".".join(parts)


def git_toplevel() -> Path | None:
    """Return the current git working tree's top-level directory, or ``None``.

    Used to locate the plugin repo root (for ``plugins/codemap-py/bin/`` lookups) when the
    codemap binaries are not on ``PATH``.

    Returns:
        Absolute path to the git top-level, or ``None`` when not in a repo / git unavailable.
    """
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return Path(r.stdout.strip()) if r.returncode == 0 else None


# ---------------------------------------------------------------------------
# Task JSON / rich progress
# ---------------------------------------------------------------------------


def unwrap_tasks(parsed: Any) -> list:
    """Return the task list from a parsed suite file, accepting both container shapes.

    Suite files are either a bare JSON list of tasks or an object with a ``"tasks"`` key
    (alongside repo metadata). This normalizes both to the list.

    Args:
        parsed: The ``json.load`` result of a suite file.

    Returns:
        The task list (``parsed["tasks"]`` for a dict, else ``parsed`` unchanged).

    Examples:
        >>> unwrap_tasks({"tasks": [1, 2]})
        [1, 2]
        >>> unwrap_tasks([1, 2])
        [1, 2]
    """
    return parsed["tasks"] if isinstance(parsed, dict) else parsed


def make_progress(console: Any):
    """Build the standard five-column rich ``Progress`` used by every runner's live bar.

    ``rich`` is imported lazily so this module stays importable where rich is optional
    (the CLI runner guards its rich import).

    Args:
        console: The rich ``Console`` to render into.

    Returns:
        A configured ``rich.progress.Progress`` (spinner · description · bar · percent).
    """
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )


# ---------------------------------------------------------------------------
# claude -p stream-json subprocess loop
# ---------------------------------------------------------------------------


@dataclass
class ResultUsage:
    """Token/cost fields parsed from a stream-json ``result`` event."""

    input_tokens: int = 0  # uncached input + cache_creation + cache_read (real context size)
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0  # Anthropic's total_cost_usd (current prices); 0.0 when absent
    subtype: str = ""  # e.g. "success", "error_max_turns", "error_non_zero_exit"
    success: bool = False


def parse_result_usage(event: dict) -> ResultUsage:
    """Parse the usage/cost fields from a stream-json ``result`` event.

    ``input_tokens`` in the event is only the uncached portion, so real context usage sums it
    with the cache-creation and cache-read parts. ``cost_usd`` is Anthropic's own per-run
    ``total_cost_usd`` (cache-aware, current prices), or ``0.0`` when the event omits it.

    Args:
        event: A decoded stream-json event with ``type == "result"``.

    Returns:
        A :class:`ResultUsage` with tokens, cost, subtype, and success flag.

    Examples:
        >>> ev = {"usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 5},
        ...       "total_cost_usd": 0.25, "subtype": "success"}
        >>> u = parse_result_usage(ev)
        >>> (u.input_tokens, u.output_tokens, u.cost_usd, u.success)
        (100, 5, 0.25, True)
        >>> parse_result_usage({"subtype": "error_max_turns"}).success
        False
    """
    usage = event.get("usage", {})
    cache_creation = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    subtype = event.get("subtype", "")
    return ResultUsage(
        input_tokens=usage.get("input_tokens", 0) + cache_creation + cache_read,
        output_tokens=usage.get("output_tokens", 0),
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        cost_usd=event.get("total_cost_usd", 0.0) or 0.0,
        subtype=subtype,
        success=subtype == "success",
    )


@dataclass
class StreamOutcome:
    """Result of :func:`stream_claude` — mechanics only; callers map to their own run dataclass."""

    elapsed_s: float = 0.0
    returncode: Optional[int] = None  # process exit code (negative → killed by signal)
    stderr: str = ""  # captured stderr, only when the process was waited on cleanly
    error: Optional[str] = None  # message from an unexpected exception (not a timeout)
    exc_timeout: bool = False  # True when proc.wait() raised TimeoutExpired


def stream_claude(
    cmd: list[str],
    *,
    timeout: float,
    cwd: Path | str,
    env: dict[str, str],
    on_event: Callable[[dict, float], None],
    update_fn: Optional[Callable[[float], None]] = None,
) -> StreamOutcome:
    """Run a ``claude -p`` stream-json subprocess: kill-timer, line-by-line event parse, timing.

    Launches ``cmd``, arms a ``threading.Timer`` that kills the process at ``timeout`` seconds,
    reads stdout line-by-line decoding each JSON event and passing it to ``on_event(event, ts)``,
    and calls ``update_fn(elapsed_s)`` at most every 0.5 s. This is the shared measurement loop;
    all per-arm/​per-dataclass scoring lives in the caller's ``on_event`` closure. The returned
    :class:`StreamOutcome` reports mechanics (elapsed, returncode, stderr, timeout) — the caller
    maps those onto its own run object, since the error-precedence and any ``incomplete`` flag
    differ per runner.

    Args:
        cmd: Full ``claude`` CLI command list.
        timeout: Wall-clock kill deadline in seconds.
        cwd: Working directory for the subprocess.
        env: Environment mapping for the subprocess.
        on_event: Called once per decoded stream-json event as ``(event, monotonic_ts)``.
        update_fn: Optional throttled progress callback ``(elapsed_seconds,)``; ≤ every 0.5 s.

    Returns:
        A :class:`StreamOutcome` describing how the process ended.
    """
    t0 = time.monotonic()
    outcome = StreamOutcome()
    last_update = 0.0
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(cwd),
            env=env,
        )
        kill_timer = threading.Timer(timeout, proc.kill)
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
                on_event(event, ts)
                if update_fn is not None and (ts - last_update) >= 0.5:
                    update_fn(ts - t0)
                    last_update = ts
            stderr_read = proc.stderr.read() if proc.stderr else ""
            proc.wait(timeout=10)
            outcome.stderr = stderr_read  # only reached when wait() did not raise
        finally:
            kill_timer.cancel()
        outcome.returncode = proc.returncode
    except subprocess.TimeoutExpired:
        if proc is not None:
            proc.kill()
        outcome.exc_timeout = True
    except Exception as exc:  # noqa: BLE001
        outcome.error = str(exc)[:300]
    finally:
        outcome.elapsed_s = time.monotonic() - t0
    return outcome
