#!/usr/bin/env python3
"""Ground truth generator and validator for benchmarks/tasks-bench.json.

Runs the scan-query commands implied by each task and validates (or refreshes)
the ground_truth dict stored in the task file.

Usage:
    # Validate all tasks against live index
    python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir>

    # Validate a single task
    python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir> --task SE-01

    # Refresh ground truth from live scan-query output
    python benchmarks/generate-tasks-bench.py --repo-path ./<repo-dir> --update

Requirements:
    - repo clone with a pre-built codemap index (see tasks-bench.json "repo.default_path")
    - scan-query on PATH or at plugins/codemap-py/bin/scan-query
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import fire

TASKS_FILE = Path(__file__).parent / "suites" / "tasks-bench.json"

# Test-file / test-directory detection — mirrors scan-index ``_TEST_PATH_RE`` so the AST oracle
# excludes the same test modules scan-query does (review N1). Matched against repo-relative paths.
_TEST_PATH_RE = re.compile(r"(^|/)tests?/|/test_[^/]+\.py$|/[^/]+_test\.py$|/conftest\.py$")


def _src_root_from_config(repo: Path) -> Path | None:
    """Read an explicit package location from pyproject.toml / setup.cfg (scan-index Strategy 1).

    Mirrors scan-index ``_detect_src_root_from_config``: matches a ``where = ["<dir>", ...]`` array
    (the ``[tool.setuptools.packages.find]`` location) and returns the first entry that resolves to a
    real directory under *repo*. The regex handles single-line array syntax only.

    Args:
        repo: Repository root directory.

    Returns:
        The configured source directory, or None when no readable config names one.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = Path(d)
        ...     _ = (r / "lib").mkdir()
        ...     _ = (r / "pyproject.toml").write_text('where = ["lib"]\\n')
        ...     _src_root_from_config(r).name
        'lib'
    """
    for config in (repo / "pyproject.toml", repo / "setup.cfg"):
        if not config.exists():
            continue
        m = re.search(r"where\s*=\s*\[([^\]]+)\]", config.read_text(errors="replace"))
        if not m:
            continue
        for entry in re.findall(r'["\']([^"\']+)["\']', m.group(1)):
            candidate = repo / entry
            if candidate.is_dir():
                return candidate
    return None


def _detect_src_root(repo: Path) -> Path:
    """Detect the source root for *loose* (non-package) modules, mirroring scan-index.

    Applies scan-index ``detect_src_root`` Strategy 1 (pyproject/setup.cfg ``where = [...]``) then
    Strategy 3 (``<repo>/src`` when it exists without an ``__init__.py``); returns *repo* otherwise.
    Strategy 2 (the ``__init__.py`` chain) is applied per file by :func:`_module_from_init_chain`, so
    it is intentionally omitted here — a loose module has no package chain to walk.

    Args:
        repo: Repository root directory.

    Returns:
        Directory a loose module's path is made relative to when deriving its dotted name.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = Path(d)
        ...     _ = (r / "src").mkdir()
        ...     _detect_src_root(r).name
        'src'
    """
    cfg = _src_root_from_config(repo)
    if cfg is not None:
        return cfg
    src_dir = repo / "src"
    if src_dir.is_dir() and not (src_dir / "__init__.py").exists():
        return src_dir
    return repo


def _module_from_init_chain(fpath: Path) -> str:
    """Derive a dotted module name by walking the file's ``__init__.py`` package chain (Strategy 2).

    Ascends from *fpath* while each parent directory is a package (contains ``__init__.py``),
    collecting package names; the walk stops at the first non-package ancestor — naturally the
    ``src/`` directory in a src-layout repo or the repo root in a flat layout. Mirrors scan-index
    ``detect_src_root`` Strategy 2, so the emitted name carries no ``src.`` prefix.

    Args:
        fpath: Absolute path to a ``.py`` file whose parent directory is a package.

    Returns:
        Dotted module name; an ``__init__.py`` file resolves to its package name.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = Path(d)
        ...     _ = (r / "pkg").mkdir()
        ...     _ = (r / "pkg" / "__init__.py").write_text("")
        ...     _ = (r / "pkg" / "mod.py").write_text("")
        ...     _module_from_init_chain(r / "pkg" / "mod.py")
        'pkg.mod'
    """
    parts: list[str] = []
    if fpath.stem != "__init__":
        parts.append(fpath.stem)
    directory = fpath.parent
    while (directory / "__init__.py").exists() and directory != directory.parent:
        parts.append(directory.name)
        directory = directory.parent
    parts.reverse()
    return ".".join(parts)


def _module_name_for(fpath: Path, repo: Path, src_root: Path) -> str:
    """Derive the dotted module name of *fpath* in scan-query's namespace (review N1).

    A file inside a package (its parent holds an ``__init__.py``) is named by its ``__init__.py``
    chain (:func:`_module_from_init_chain`, scan-index Strategy 2); a loose module is named relative
    to *src_root* (scan-index Strategy 1/3), which strips a ``src/`` layout prefix. Both branches emit
    the repo namespace with no ``src.`` prefix, so callers are directly comparable to scan-query — for
    any repo layout, with no hardcoded namespace list.

    Args:
        fpath: Absolute path to the ``.py`` file being named.
        repo: Repository root directory (fallback base when *fpath* is outside *src_root*).
        src_root: Loose-module source root from :func:`_detect_src_root`.

    Returns:
        Dotted module name (e.g. ``lightning.pytorch.trainer.trainer`` or ``flatpkg.mod``).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     r = Path(d)
        ...     _ = (r / "src" / "pkg").mkdir(parents=True)
        ...     f = r / "src" / "pkg" / "mod.py"
        ...     _ = f.write_text("")
        ...     _module_name_for(f, r, _detect_src_root(r))
        'pkg.mod'
    """
    if (fpath.parent / "__init__.py").exists():
        return _module_from_init_chain(fpath)
    base = src_root if fpath.is_relative_to(src_root) else repo
    return ".".join(fpath.relative_to(base).with_suffix("").parts)


# ---- BINARY RESOLUTION ----


def find_codemap_bin(name: str, plugin_root: Path | None = None) -> Path | None:
    """Locate a codemap CLI binary by PATH lookup or plugin directory fallback.

    Args:
        name: Binary name to find (e.g. "scan-query").
        plugin_root: Optional project root containing plugins/codemap-py/bin/.

    Returns:
        Resolved path or None if not found.
    """
    which = shutil.which(name)
    if which:
        return Path(which)
    if plugin_root:
        candidate = plugin_root / "plugins" / "codemap-py" / "bin" / name
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


class _QualifiedCallFinder(ast.NodeVisitor):
    """AST visitor crediting only callers whose call receiver statically resolves to the target.

    Conservative (precision-first) qualified caller oracle for ground truth (review N1). Unlike
    :class:`_CallFinder` (simple-name match, which over-approximates), an attribute call
    ``recv.method()`` is credited only when *recv* resolves to the target's class — ``self`` / ``cls``
    inside that class, or a direct ``Class.method()`` / ``Class().method()`` reference — so a
    same-named method on an unrelated class is never counted. Bare ``name()`` calls carry no class
    ambiguity and are credited. Receivers that cannot be resolved statically are skipped rather than
    guessed, so the emitted set is a subset of the true caller set (precision over recall for GT).

    Args:
        target_class: Simple name of the class defining the target method, or None for a
            module-level function target.
        target_simple: Simple name of the target function or method.
        target_module_tail: Last component of the TARGET's module — used to resolve a
            module-level-function attribute call ``mod.func()``. None when unknown.
        rel_module: Structurally derived dotted module path of the file being walked (no ``src.`` prefix).
        callers: Mutable set accumulating ``"<module>::<scope>"`` caller strings.
    """

    def __init__(
        self,
        target_class: str | None,
        target_simple: str,
        target_module_tail: str | None,
        rel_module: str,
        callers: set[str],
    ) -> None:
        self._target_class = target_class
        self._target_simple = target_simple
        self._target_module_tail = target_module_tail
        self._rel_module = rel_module
        self._callers = callers
        self._scope_stack: list[str] = []
        self._class_stack: list[str] = []

    def _scope(self) -> str:
        return ".".join(self._scope_stack) if self._scope_stack else "<module>"

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope_stack.append(node.name)
        self.generic_visit(node)
        self._scope_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope_stack.append(node.name)
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()
        self._scope_stack.pop()

    def _receiver_class(self, recv: ast.expr) -> str | None:
        """Resolve the class simple name of an attribute-call receiver, or None when ambiguous."""
        if isinstance(recv, ast.Name):
            if recv.id in ("self", "cls"):
                return self._class_stack[-1] if self._class_stack else None
            return recv.id if recv.id[:1].isupper() else None
        if isinstance(recv, ast.Call):
            fn = recv.func
            if isinstance(fn, ast.Name) and fn.id[:1].isupper():
                return fn.id
            if isinstance(fn, ast.Attribute) and fn.attr[:1].isupper():
                return fn.attr
        return None

    def _credits(self, node: ast.Call) -> bool:
        """Return True when *node* is a call to the target that resolves to the target's qualname."""
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == self._target_simple
        if isinstance(func, ast.Attribute) and func.attr == self._target_simple:
            if self._target_class is None:
                # Module-level function accessed as `<module>.func()`: credit only when the receiver
                # names the TARGET module (its last component), not the caller's own module.
                recv = func.value
                tail = recv.attr if isinstance(recv, ast.Attribute) else getattr(recv, "id", None)
                return tail is not None and tail == self._target_module_tail
            return self._receiver_class(func.value) == self._target_class
        return False

    def visit_Call(self, node: ast.Call) -> None:
        if self._scope_stack and self._credits(node):
            self._callers.add(f"{self._rel_module}::{self._scope()}")
        self.generic_visit(node)


def _walk_caller_sets(primary_fn: str, repo: Path) -> tuple[set[str], set[str], str | None]:
    """Walk repo AST once, returning both the qualified (authoritative) and loose caller sets (review N1).

    The qualified set (:class:`_QualifiedCallFinder`) is the authoritative ground truth: it credits a
    caller only when the call receiver statically resolves to the target's class/module. The loose set
    (:class:`_CallFinder`) matches by simple name and is retained purely as a divergence diagnostic.
    Test modules are excluded (matching scan-query) and each caller's module name is derived structurally
    by :func:`_module_name_for` (``__init__.py`` chain / detected src root), so emitted callers carry no
    ``src.`` prefix and are directly comparable to scan-query output for any repo layout.

    Args:
        primary_fn: Qualified name like ``"mod::Class.method"`` or ``"mod::func"``.
        repo: Repository root directory.

    Returns:
        (qualified_callers, loose_callers, error_reason).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text("class Foo:\\n    def c(self):\\n        self.bar()\\n")
        ...     q, loose, err = _walk_caller_sets("m::Foo.bar", repo)
        >>> sorted(q), err
        (['m::Foo.c'], None)
    """
    tail = primary_fn.split("::")[-1]
    parts = tail.split(".")
    target_simple = parts[-1]
    target_class = parts[-2] if len(parts) >= 2 else None
    # Target module tail resolves module-level `mod.func()` attribute calls. primary_fn's module is
    # already scan-query-namespaced ground truth, so its last component is the receiver name to match.
    target_module = primary_fn.split("::")[0]
    target_module_tail = target_module.split(".")[-1] if target_module else None

    src_root = _detect_src_root(repo)
    qualified: set[str] = set()
    loose: set[str] = set()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel_path = str(fpath.relative_to(repo)).replace(os.sep, "/")
            if _TEST_PATH_RE.search(rel_path):
                continue
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
            except SyntaxError:
                continue
            rel_module = _module_name_for(fpath, repo, src_root)
            _CallFinder(target_simple, rel_module, loose).visit(tree)
            _QualifiedCallFinder(target_class, target_simple, target_module_tail, rel_module, qualified).visit(tree)

    return qualified, loose, None


def _callers_via_ast(primary_fn: str, repo: Path) -> tuple[set[str], str | None]:
    """Return the authoritative (qualified) caller set of ``primary_fn`` independent of scan-query.

    Thin wrapper over :func:`_walk_caller_sets` exposing only the qualified set (review N1). The loose
    simple-name set is available via :func:`_walk_caller_sets` for divergence diagnostics.

    Args:
        primary_fn: Qualified name like ``"mod::Class.method"`` or ``"mod::func"``.
        repo: Repository root directory.

    Returns:
        (caller_set, error_reason) — ``"<module>::<scope>"`` strings for each statically-resolved
        caller; error_reason is None on success.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text("def caller():\\n    target()\\n")
        ...     callers, err = _callers_via_ast("m::target", repo)
        >>> sorted(callers), err
        (['m::caller'], None)
    """
    qualified, _loose, error = _walk_caller_sets(primary_fn, repo)
    return qualified, error


def _undocumented_via_ast(repo: Path, module: str | None = None) -> tuple[set[str], str | None]:
    """Independent AST oracle for the ``undocumented`` check: public symbols with no docstring.

    Mirrors scan-query ``cmd_undocumented`` / ``_is_public_symbol`` (plugins/codemap-py/bin/
    scan-query): a symbol is *public* when no dotted component of its qualified name starts
    with ``_`` (excludes dunders, private helpers, private classes); test modules are skipped.
    A symbol is *undocumented* when :func:`ast.get_docstring` returns falsy. Qualified names
    are module-relative (``Class.method`` / ``func`` / ``Class``), matching scan-query's
    ``qualified_name`` field so the two sets are directly comparable.

    Args:
        repo: Repository root directory.
        module: Optional dotted module name to restrict the scan to (resolved against
            ``<repo>/<parts>.py`` then ``<repo>/src/<parts>.py``). When None, every
            non-test Python file under ``repo`` is scanned.

    Returns:
        (undocumented_qualnames, error_reason) — error is None on success, a short message
        when a requested ``module`` cannot be resolved to a file.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text("def pub():\\n    pass\\n")
        ...     syms, err = _undocumented_via_ast(repo)
        >>> sorted(syms), err
        (['pub'], None)
    """
    files, error = _resolve_module_files(repo, module)
    if error:
        return set(), error
    undocumented: set[str] = set()
    for fpath in files:
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
        except SyntaxError:
            continue
        _UndocFinder(undocumented).visit(tree)
    return undocumented, None


def _resolve_module_files(repo: Path, module: str | None) -> tuple[list[Path], str | None]:
    """Resolve which Python files a docstring scan should cover.

    Args:
        repo: Repository root directory.
        module: Optional dotted module name; when given, resolved to a single file.

    Returns:
        (files, error_reason). When ``module`` is None, all non-test ``.py`` files under
        ``repo`` (skipping hidden / cache / virtualenv dirs). When ``module`` is set but no
        matching file exists, ``([], "<reason>")``.
    """
    if module:
        parts = module.split(".")
        for base in (repo, repo / "src"):
            cand = base.joinpath(*parts).with_suffix(".py")
            if cand.is_file():
                return [cand], None
        return [], f"module {module!r} not resolvable under {repo}/ or {repo}/src/"
    files: list[Path] = []
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for name in names:
            if name.endswith(".py") and not name.startswith("test_") and not name.endswith("_test.py"):
                files.append(Path(root) / name)
    return files, None


class _UndocFinder(ast.NodeVisitor):
    """AST visitor recording public symbols (functions, classes, methods) lacking a docstring.

    Qualified names are the dotted scope within the module (``Class.method``); a symbol is
    public when no component starts with ``_`` (matches scan-query ``_is_public_symbol``).

    Args:
        undocumented: Mutable set accumulating undocumented public qualified names.
    """

    def __init__(self, undocumented: set[str]) -> None:
        self._undoc = undocumented
        self._scope: list[str] = []

    def _record(self, name: str, node: ast.AST) -> None:
        qname = ".".join([*self._scope, name])
        if _is_public_qualname(qname) and not ast.get_docstring(node):
            self._undoc.add(qname)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node.name, node)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.name, node)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def _is_public_qualname(name: str) -> bool:
    """Return True when no dotted component of *name* starts with ``_`` (scan-query rule).

    Examples:
        >>> _is_public_qualname("Trainer.fit")
        True
        >>> _is_public_qualname("_Cache.get")
        False
        >>> _is_public_qualname("Trainer.__init__")
        False
    """
    if not name:
        return False
    return all(part and not part.startswith("_") for part in name.split("."))


class _PublicSymbolFinder(ast.NodeVisitor):
    """AST visitor recording every public symbol (function, class, method), documented or not.

    Qualified names are the dotted scope within the module (``Class.method``); a symbol is public
    when no component starts with ``_`` (matches scan-query ``_is_public_symbol``). Unlike
    :class:`_UndocFinder`, docstring presence is irrelevant — this enumerates the full public surface
    so the uncovered oracle (review C-2) can subtract test-referenced symbols from it.

    Args:
        symbols: Mutable set accumulating public qualified names.
    """

    def __init__(self, symbols: set[str]) -> None:
        self._symbols = symbols
        self._scope: list[str] = []

    def _record(self, name: str) -> None:
        qname = ".".join([*self._scope, name])
        if _is_public_qualname(qname):
            self._symbols.add(qname)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node.name)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node.name)
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()


def _is_patch_call(func: ast.expr) -> bool:
    """Return True when *func* is a ``patch(...)`` / ``patch.object(...)`` / ``mock.patch(...)`` callee."""
    if isinstance(func, ast.Name):
        return func.id == "patch"
    if isinstance(func, ast.Attribute):
        return func.attr in ("patch", "object")
    return False


class _TestRefFinder(ast.NodeVisitor):
    """AST visitor collecting the simple names a test module references (review C-2).

    Mirrors scan-query's coverage definition independently: a public symbol is *covered* when a test
    reaches it either through a call/attribute reference (its ``fn_rdep_test_count`` analogue) or
    through a ``patch("pkg.mod.Symbol")`` string target (its ``mock_rdep_count`` analogue). Every
    ``Name``/``Attribute`` identifier is recorded, plus the last dotted component of each string
    argument to a patch call.

    Args:
        refs: Mutable set accumulating referenced simple names.
    """

    def __init__(self, refs: set[str]) -> None:
        self._refs = refs

    def visit_Name(self, node: ast.Name) -> None:
        self._refs.add(node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._refs.add(node.attr)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_patch_call(node.func):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._refs.add(arg.value.split(".")[-1])
        self.generic_visit(node)


def _collect_test_references(repo: Path) -> set[str]:
    """Return the set of simple names referenced by any test module under *repo* (review C-2).

    Args:
        repo: Repository root directory.

    Returns:
        Referenced simple names (call/attribute identifiers and patch-string tails) from every test
        file (matched by :data:`_TEST_PATH_RE`).
    """
    refs: set[str] = set()
    for root, dirs, names in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for name in names:
            if not name.endswith(".py"):
                continue
            fpath = Path(root) / name
            rel = str(fpath.relative_to(repo)).replace(os.sep, "/")
            if not _TEST_PATH_RE.search(rel):
                continue
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
            except SyntaxError:
                continue
            _TestRefFinder(refs).visit(tree)
    return refs


def _uncovered_via_ast(repo: Path, module: str | None = None) -> tuple[set[str], str | None]:
    """Independent AST oracle for the ``uncovered`` check: public symbols no test references (review C-2).

    Mirrors scan-query ``cmd_uncovered`` independently: a public symbol (per :func:`_is_public_qualname`,
    no leading-underscore component) in a non-test module is *uncovered* when its simple name is not
    referenced by any test module — neither called/accessed (``fn_rdep_test_count`` analogue) nor named
    in a ``patch(...)`` string target (``mock_rdep_count`` analogue). Qualified names are module-relative
    (``Class.method`` / ``func`` / ``Class``), matching scan-query's ``qualified_name`` field.

    Approximate like the caller oracle: coverage is matched by the symbol's simple name, so it
    over-approximates *coverage* (a same-named symbol referenced anywhere by a test marks all of them
    covered) — i.e. it may under-report uncovered symbols. Divergence from scan-query is surfaced
    loudly by the caller; scan-query is never used as the ground truth.

    Args:
        repo: Repository root directory.
        module: Optional dotted module name to restrict the scan to; None scans every non-test module.

    Returns:
        (uncovered_qualnames, error_reason) — error is None on success, a short message when a
        requested ``module`` cannot be resolved to a file.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text("def orphan():\\n    pass\\n\\n\\ndef used():\\n    pass\\n")
        ...     tests = repo / "tests"; tests.mkdir()
        ...     _ = (tests / "test_m.py").write_text("def test_it():\\n    used()\\n")
        ...     syms, err = _uncovered_via_ast(repo)
        >>> sorted(syms), err
        (['orphan'], None)
    """
    referenced = _collect_test_references(repo)
    files, error = _resolve_module_files(repo, module)
    if error:
        return set(), error
    public: set[str] = set()
    for fpath in files:
        rel = str(fpath.relative_to(repo)).replace(os.sep, "/")
        if _TEST_PATH_RE.search(rel):
            continue
        try:
            tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
        except SyntaxError:
            continue
        _PublicSymbolFinder(public).visit(tree)
    uncovered = {qname for qname in public if qname.split(".")[-1] not in referenced}
    return uncovered, None


def _module_imports(tree: ast.Module) -> set[str]:
    """Return the dotted import targets of a module (mirrors scan-index ``extract_imports``).

    Collects every ``import x.y`` alias name and every ``from x.y import z`` module target — exactly
    the set scan-index stores as ``direct_imports`` and scan-query ``rdeps`` matches against. Relative
    imports (``from . import x``, ``node.module is None``) are skipped, matching scan-index.

    Args:
        tree: Parsed AST of the module.

    Returns:
        Set of dotted import-target module names.

    Examples:
        >>> import ast
        >>> src = "import a.b\\nfrom c.d import e\\nfrom . import f\\n"
        >>> sorted(_module_imports(ast.parse(src)))
        ['a.b', 'c.d']
    """
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _build_import_graph(repo: Path, exclude_tests: bool = True) -> dict[str, set[str]]:
    """Build the repo's module import graph, edges restricted to in-repo modules (review DI/GR).

    Mirrors scan-query ``rdeps``/``central`` semantics: module *A* imports module *M* iff *M* appears
    literally as an import target of *A* (``import M`` or ``from M import ...``) AND *M* is itself a repo
    module. External/stdlib targets are dropped (rdeps only lists repo module ``name`` values). Module
    names are derived structurally by :func:`_module_name_for` (no ``src.`` prefix), so keys and edge
    targets match scan-query output for any repo layout.

    Args:
        repo: Repository root directory.
        exclude_tests: When True, omit test modules as both graph nodes and edge sources/targets
            (matches ``rdeps --exclude-tests`` / ``central --exclude-tests``).

    Returns:
        Mapping ``{module: set(imported_repo_modules)}`` for every scanned module.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "a.py").write_text("import b\\n")
        ...     _ = (repo / "b.py").write_text("import os\\n")
        ...     g = _build_import_graph(repo)
        >>> sorted(g["a"]), sorted(g["b"])
        (['b'], [])
    """
    src_root = _detect_src_root(repo)
    raw: dict[str, set[str]] = {}
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel_path = str(fpath.relative_to(repo)).replace(os.sep, "/")
            if exclude_tests and _TEST_PATH_RE.search(rel_path):
                continue
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
            except SyntaxError:
                continue
            raw[_module_name_for(fpath, repo, src_root)] = _module_imports(tree)
    in_repo = set(raw)
    return {mod: {tgt for tgt in tgts if tgt in in_repo} for mod, tgts in raw.items()}


def _central_via_ast(repo: Path, top: int, exclude_tests: bool = True) -> list[tuple[str, int]]:
    """Return the top-N most-imported repo modules ranked by importer count (review GR).

    Independent AST oracle for scan-query ``central``: each module's rank is its in-degree in the
    import graph (:func:`_build_import_graph`) — the number of repo modules importing it. Ties are
    broken by module name for determinism.

    Args:
        repo: Repository root directory.
        top: Number of top-ranked modules to return.
        exclude_tests: When True, exclude test modules (matches ``central --exclude-tests``).

    Returns:
        List of ``(module, importer_count)`` pairs, highest count first, length ``<= top``.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "hub.py").write_text("x = 1\\n")
        ...     _ = (repo / "a.py").write_text("import hub\\n")
        ...     _ = (repo / "b.py").write_text("import hub\\n")
        ...     _central_via_ast(repo, top=1)
        [('hub', 2)]
    """
    graph = _build_import_graph(repo, exclude_tests=exclude_tests)
    in_degree: dict[str, int] = {mod: 0 for mod in graph}
    for importers in graph.values():
        for target in importers:
            in_degree[target] = in_degree.get(target, 0) + 1
    ranked = sorted(in_degree.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:top]


def _import_path_via_ast(repo: Path, source: str, target: str, exclude_tests: bool = True) -> list[str] | None:
    """Return a shortest import path ``source -> ... -> target`` over the import graph, or None (review GR).

    Independent AST oracle for scan-query ``path``: breadth-first search over
    :func:`_build_import_graph` yields a shortest module chain where each step is a direct import.
    Returns None when no path exists. When several shortest paths exist, the one found first under a
    name-sorted neighbour expansion is returned; callers needing a unique answer should pick pairs with
    a single shortest path (see :func:`_shortest_path_is_unique`).

    Args:
        repo: Repository root directory.
        source: Dotted module name to start from.
        target: Dotted module name to reach.
        exclude_tests: When True, exclude test modules from the graph.

    Returns:
        List of module names from *source* to *target* inclusive, or None when unreachable.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "a.py").write_text("import b\\n")
        ...     _ = (repo / "b.py").write_text("import c\\n")
        ...     _ = (repo / "c.py").write_text("x = 1\\n")
        ...     _import_path_via_ast(repo, "a", "c")
        ['a', 'b', 'c']
    """
    graph = _build_import_graph(repo, exclude_tests=exclude_tests)
    if source not in graph or target not in graph:
        return None
    queue: list[list[str]] = [[source]]
    seen: set[str] = {source}
    while queue:
        path = queue.pop(0)
        node = path[-1]
        if node == target:
            return path
        for neighbour in sorted(graph.get(node, set())):
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append([*path, neighbour])
    return None


def _shortest_path_is_unique(repo: Path, source: str, target: str, exclude_tests: bool = True) -> bool:
    """Return True when exactly one shortest import path connects *source* to *target* (review GR).

    A path task's ground truth is only well-defined when the shortest path is unique — otherwise the
    agent could report a different, equally-short chain. This counts shortest paths by BFS layer: each
    node's count is the sum of its predecessors' counts within the previous layer; the target is unique
    when its accumulated count is exactly one.

    Args:
        repo: Repository root directory.
        source: Dotted source module name.
        target: Dotted target module name.
        exclude_tests: When True, exclude test modules from the graph.

    Returns:
        True when a unique shortest path exists; False when zero or multiple shortest paths exist.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "a.py").write_text("import b\\nimport c\\n")
        ...     _ = (repo / "b.py").write_text("import d\\n")
        ...     _ = (repo / "c.py").write_text("import d\\n")
        ...     _ = (repo / "d.py").write_text("x = 1\\n")
        ...     _shortest_path_is_unique(repo, "a", "d")
        False
    """
    graph = _build_import_graph(repo, exclude_tests=exclude_tests)
    if source not in graph or target not in graph:
        return False
    path_counts: dict[str, int] = {source: 1}
    visited: set[str] = {source}
    frontier = [source]
    while frontier and target not in visited:
        next_counts: dict[str, int] = {}
        for node in frontier:
            for neighbour in graph.get(node, set()):
                if neighbour not in visited:
                    next_counts[neighbour] = next_counts.get(neighbour, 0) + path_counts[node]
        visited.update(next_counts)
        path_counts.update(next_counts)
        frontier = list(next_counts)
    return path_counts.get(target, 0) == 1


def _fn_blast_via_ast(primary_fn: str, repo: Path, depth: int = 2) -> tuple[set[str], str | None]:
    """Return the transitive caller closure of *primary_fn* up to *depth* hops (review GR).

    Independent AST oracle for scan-query ``fn-blast``: starts from the direct callers
    (:func:`_callers_via_ast`) and repeats the caller walk on each newly-found caller, up to *depth*
    levels. The result is the union of all callers reachable within *depth* hops (excluding the target
    itself). Test modules are excluded throughout, matching the direct-caller oracle.

    Args:
        primary_fn: Qualified target name ``"module::Class.method"`` or ``"module::func"``.
        repo: Repository root directory.
        depth: Maximum transitive hop count (default 2).

    Returns:
        (transitive_caller_set, error_reason) — error is None on success.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     _ = (repo / "m.py").write_text(
        ...         "def target():\\n    pass\\n\\n\\n"
        ...         "def mid():\\n    target()\\n\\n\\n"
        ...         "def top():\\n    mid()\\n"
        ...     )
        ...     blast, err = _fn_blast_via_ast("m::target", repo, depth=2)
        >>> sorted(blast), err
        (['m::mid', 'm::top'], None)
    """
    reached: set[str] = set()
    frontier = {primary_fn}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for fn in frontier:
            callers, err = _callers_via_ast(fn, repo)
            if err is not None:
                return reached, err
            for caller in callers:
                if caller != primary_fn and caller not in reached:
                    reached.add(caller)
                    next_frontier.add(caller)
        frontier = next_frontier
        if not frontier:
            break
    return reached, None


def _test_modules_importing_via_ast(repo: Path, module: str) -> tuple[set[str], str | None]:
    """Return test modules whose imports include *module* (DI test-file mapping oracle, review DI).

    Independent AST oracle for the diff-impact test-file recall metric: a change to *module* should be
    covered by re-running the test modules that import it. Scans every test file (matched by
    :data:`_TEST_PATH_RE`) and credits it when *module* is an exact import target (``import module`` or
    ``from module import ...``). Emitted names are the test modules' structural dotted paths.

    Args:
        repo: Repository root directory.
        module: Dotted name of the changed module.

    Returns:
        (test_module_names, error_reason) — error is None on success.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     repo = Path(d)
        ...     tests = repo / "tests"; tests.mkdir()
        ...     _ = (tests / "test_a.py").write_text("from pkg.mod import f\\n")
        ...     _ = (tests / "test_b.py").write_text("import other\\n")
        ...     mods, err = _test_modules_importing_via_ast(repo, "pkg.mod")
        >>> sorted(mods), err
        (['tests.test_a'], None)
    """
    src_root = _detect_src_root(repo)
    found: set[str] = set()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", ".venv", "venv")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            rel_path = str(fpath.relative_to(repo)).replace(os.sep, "/")
            if not _TEST_PATH_RE.search(rel_path):
                continue
            try:
                tree = ast.parse(fpath.read_text(encoding="utf-8", errors="ignore"), filename=str(fpath))
            except SyntaxError:
                continue
            if module in _module_imports(tree):
                found.add(_module_name_for(fpath, repo, src_root))
    return found, None


def _warn_ast_divergence(task_id: str, kind: str, ast_only: list[str], scan_only: list[str]) -> None:
    """Print a loud warning when the AST oracle and scan-query disagree (potential plugin bug).

    Args:
        task_id: Task identifier for the banner.
        kind: What diverged (e.g. ``"fn-rdeps callers"``).
        ast_only: Items the AST oracle found that scan-query missed.
        scan_only: Items scan-query reported that the AST oracle did not find.
    """
    if not ast_only and not scan_only:
        return
    bar = "!" * 72
    print(bar)
    print(f"! AST/scan-query DIVERGENCE [{task_id}] {kind} — potential scan-query (plugin) bug")
    if ast_only:
        print(f"!   only AST oracle ({len(ast_only)}): {ast_only[:10]}{'...' if len(ast_only) > 10 else ''}")
    if scan_only:
        print(f"!   only scan-query ({len(scan_only)}): {scan_only[:10]}{'...' if len(scan_only) > 10 else ''}")
    print(bar)


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
    scan_callers = sorted(set(e["caller"] for e in called_by))

    # AST oracle is AUTHORITATIVE for caller lists (review C-2): scan-query fn-rdeps is the
    # very tool the codemap arm invokes, so grading it against its own output is circular.
    # The QUALIFIED AST walk (receiver-resolved) is the ground truth — the loose simple-name walk
    # over-approximates (same-named methods in unrelated classes) and is kept only as a diagnostic
    # (review N1). Module names are derived structurally (no `src.` prefix) and test modules excluded.
    ast_callers, ast_loose, _ast_err = _walk_caller_sets(primary_fn, repo)
    callers = sorted(ast_callers)
    unique_count = len(callers)

    # AST/scan-query divergence now signals a POTENTIAL scan-query (plugin) bug — surface it
    # loudly; never silently overwrite the authoritative oracle with the tool's output.
    ast_only = sorted(ast_callers - set(scan_callers))
    scan_only = sorted(set(scan_callers) - ast_callers)
    _warn_ast_divergence(task.get("id", "?"), "fn-rdeps callers", ast_only, scan_only)

    live_gt: dict[str, Any] = {
        "fn_callers": callers,  # AUTHORITATIVE — qualified AST oracle (receiver-resolved)
        "unique_caller_count": unique_count,
        "exclude_tests": gt.get("exclude_tests", False),
        "note": gt.get("note", "static edges only (import/local/self-resolved); dynamic dispatch excluded by design"),
        "fn_callers_scan": scan_callers,  # diagnostic — output of the tool under test
        "fn_callers_ast_loose": sorted(ast_loose),  # diagnostic — simple-name over-approximation (review N1)
        "scan_caller_count": len(scan_callers),
        "raw_caller_count": raw_count,  # diagnostic — scan-query `count` field
        "ast_divergence": {
            "ast_only": ast_only,
            "scan_only": scan_only,
            "scan_caller_count": len(scan_callers),
        },
    }

    problems: list[str] = []
    if unique_count != gt.get("unique_caller_count"):
        problems.append(
            f"unique_caller_count (AST oracle): expected {gt.get('unique_caller_count')}, got {unique_count}"
        )

    expected_set = set(gt.get("fn_callers", []))
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


def _validate_undocumented_ast(
    task: dict,
    gt: dict,
    module: str | None,
    scan_count: int,
    scan_syms: list[str],
    repo: Path,
    live_gt: dict[str, Any],
) -> tuple[list[str], str]:
    """Validate a pure ``undocumented`` check against the independent AST oracle.

    The AST oracle (:func:`_undocumented_via_ast`) is authoritative; scan-query output is
    stored under ``*_scan`` diagnostic keys only (review C-2). Mutates ``live_gt`` in place
    with both authoritative and diagnostic values, and warns loudly on divergence.

    Args:
        task: Task dict (used for its id in divergence warnings).
        gt: Existing ground_truth to compare against.
        module: Dotted module name to scope the AST scan to, or None for repo-wide.
        scan_count: ``total`` reported by scan-query (diagnostic).
        scan_syms: Symbol list reported by scan-query (diagnostic).
        repo: Repository root directory.
        live_gt: Live ground-truth dict, mutated in place.

    Returns:
        (problems, error_reason). ``error_reason`` is non-empty only when the AST oracle
        could not resolve the requested module (caller returns a hard failure).
    """
    ast_syms, ast_err = _undocumented_via_ast(repo, module)
    if ast_err:
        return [], f"undocumented AST oracle failed: {ast_err}"
    live_syms = sorted(ast_syms)
    live_gt["undocumented_count"] = len(live_syms)
    live_gt["undocumented_symbols"] = live_syms
    live_gt["undocumented_count_scan"] = scan_count
    live_gt["undocumented_symbols_scan"] = scan_syms
    scan_set = set(scan_syms)
    _warn_ast_divergence(
        task.get("id", "?"), "undocumented symbols", sorted(ast_syms - scan_set), sorted(scan_set - ast_syms)
    )

    problems: list[str] = []
    expected_count = gt.get("undocumented_count", 0)
    expected_syms = set(gt.get("undocumented_symbols", []))
    if len(live_syms) != expected_count:
        problems.append(f"undocumented_count (AST oracle): expected {expected_count}, got {len(live_syms)}")
    if ast_syms != expected_syms:
        problems.append(
            f"undocumented_symbols (AST oracle) mismatch: missing={sorted(expected_syms - ast_syms)[:3]}, "
            f"extra={sorted(ast_syms - expected_syms)[:3]}"
        )
    return problems, ""


def _validate_uncovered_ast(
    task: dict,
    gt: dict,
    module: str | None,
    scan_count: int,
    scan_syms: list[str],
    repo: Path,
    live_gt: dict[str, Any],
) -> tuple[list[str], str]:
    """Validate a pure ``uncovered`` check against the independent AST oracle (review C-2 remainder).

    The AST oracle (:func:`_uncovered_via_ast`) is authoritative; scan-query output is stored under
    ``*_scan`` diagnostic keys only. Mutates ``live_gt`` in place with both authoritative and
    diagnostic values, and warns loudly on divergence. Mirrors :func:`_validate_undocumented_ast`.

    Args:
        task: Task dict (used for its id in divergence warnings).
        gt: Existing ground_truth to compare against.
        module: Dotted module name to scope the AST scan to, or None for repo-wide.
        scan_count: ``total`` reported by scan-query (diagnostic).
        scan_syms: Symbol list reported by scan-query (diagnostic).
        repo: Repository root directory.
        live_gt: Live ground-truth dict, mutated in place.

    Returns:
        (problems, error_reason). ``error_reason`` is non-empty only when the AST oracle could not
        resolve the requested module (caller returns a hard failure).
    """
    ast_syms, ast_err = _uncovered_via_ast(repo, module)
    if ast_err:
        return [], f"uncovered AST oracle failed: {ast_err}"
    live_syms = sorted(ast_syms)
    live_gt["uncovered_count"] = len(live_syms)
    live_gt["uncovered_symbols"] = live_syms
    live_gt["uncovered_count_scan"] = scan_count
    live_gt["uncovered_symbols_scan"] = scan_syms
    scan_set = set(scan_syms)
    _warn_ast_divergence(
        task.get("id", "?"), "uncovered symbols", sorted(ast_syms - scan_set), sorted(scan_set - ast_syms)
    )

    problems: list[str] = []
    expected_count = gt.get("uncovered_count", 0)
    expected_syms = set(gt.get("uncovered_symbols", []))
    if len(live_syms) != expected_count:
        problems.append(f"uncovered_count (AST oracle): expected {expected_count}, got {len(live_syms)}")
    if ast_syms != expected_syms:
        problems.append(
            f"uncovered_symbols (AST oracle) mismatch: missing={sorted(expected_syms - ast_syms)[:3]}, "
            f"extra={sorted(ast_syms - expected_syms)[:3]}"
        )
    return problems, ""


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
        if not isinstance(data.get("total"), int):
            return False, None, "undocumented total is missing or not an int"
        if not isinstance(data.get("undocumented"), list):
            return False, None, "undocumented result is missing or not a list"
        if any(not isinstance(e, dict) for e in data["undocumented"]):
            return False, None, "undocumented result contains non-object entries"
        scan_count = data.get("total", 0)
        scan_syms = [e.get("qualified_name", "") for e in data.get("undocumented", [])]
        if scan_count != len(scan_syms):
            return False, None, "undocumented total conflicts with symbol count"
        if check == "undocumented":
            # AST oracle is authoritative (review C-2) — scan-query is the tool under test.
            module = next((a for a in q.get("args", []) if not str(a).startswith("-")), None)
            undoc_problems, undoc_err = _validate_undocumented_ast(
                task, gt, module, scan_count, scan_syms, repo, live_gt
            )
            if undoc_err:
                return False, None, undoc_err
            problems.extend(undoc_problems)
        else:
            # TODO(review C-2): combined_health undocumented/uncovered GT still scan-query-derived
            # (circular) — needs the independent AST oracle wired the same way as the pure
            # `undocumented` check above.
            live_gt["undocumented_count"] = scan_count
            live_gt["undocumented_symbols"] = scan_syms

    if check in ("uncovered", "combined_health"):
        q = next((q for q in expected_queries if q["cmd"] == "uncovered"), None)
        if q is None:
            return False, None, "no uncovered query found"
        data = run_scan_query(sq, ["uncovered"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query uncovered returned None"
        if not isinstance(data.get("total"), int):
            return False, None, "uncovered total is missing or not an int"
        if not isinstance(data.get("uncovered"), list):
            return False, None, "uncovered result is missing or not a list"
        if any(not isinstance(e, dict) for e in data["uncovered"]):
            return False, None, "uncovered result contains non-object entries"
        scan_count = data.get("total", 0)
        scan_syms = [e.get("qualified_name", "") for e in data.get("uncovered", [])]
        if scan_count != len(scan_syms):
            return False, None, "uncovered total conflicts with symbol count"
        if check == "uncovered":
            # AST oracle is authoritative (review C-2 remainder) — scan-query is the tool under test.
            module = next((a for a in q.get("args", []) if not str(a).startswith("-")), None)
            uncov_problems, uncov_err = _validate_uncovered_ast(task, gt, module, scan_count, scan_syms, repo, live_gt)
            if uncov_err:
                return False, None, uncov_err
            problems.extend(uncov_problems)
        else:
            # TODO(review C-2 remainder): combined_health bundles undocumented+uncovered and its
            # uncovered slice is still scan-query-derived (circular). The pure `uncovered` check
            # above is now oracle-backed; combined_health refreshes only via --update-from-tool.
            live_gt["uncovered_count"] = scan_count
            live_gt["uncovered_symbols"] = scan_syms

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
        if not isinstance(coupled, list):
            return False, None, "coupled result is not a list"
        if not coupled:
            return False, None, "coupled result is empty"
        top = coupled[0]
        if not isinstance(top, dict):
            return False, None, "coupled top result is not an object"
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
        # TODO(review C-2 remainder): xrefs_broken GT remains scan-query-derived (circular). A faithful
        # independent oracle is out of scope here because scan-query reads `sphinx_xrefs[*].target`
        # values that scan-index ALREADY resolved to `module::name` keys at index-build time (parsing
        # `:func:`/`:class:`/`:meth:`/`:exc:`/`mkdocs` roles, stripping `~`, resolving relative/current-
        # module refs). Reproducing that normalization independently means re-implementing scan-index's
        # `_SPHINX_RESOLVABLE_ROLES` extraction + target resolution against an AST-built symbol map — a
        # different (likely divergent) normalization would make the oracle non-comparable rather than
        # independent. What is missing precisely: (1) an AST docstring-role parser emitting raw targets;
        # (2) a faithful re-implementation of scan-index's raw-target → `module::name` normalization;
        # (3) an AST symbol-map builder to resolve `broken = target not in symbol_map`. Until (1)-(3)
        # exist, xrefs_broken stays behind --update-from-tool (see _update_is_oracle_backed).
        q = expected_queries[0]
        data = run_scan_query(sq, ["xrefs"] + q.get("args", []), index, repo)
        if data is None:
            return False, None, "scan-query xrefs returned None"
        broken = data.get("broken", [])
        if not isinstance(broken, list):
            return False, None, "xrefs broken result is not a list"
        if any(not isinstance(b, dict) for b in broken):
            return False, None, "xrefs broken result contains non-object entries"
        live_count = data.get("count", len(broken))
        if not isinstance(live_count, int):
            return False, None, "xrefs broken count is not an int"
        if live_count != len(broken):
            return False, None, "xrefs broken count conflicts with target count"
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


# ---- DIFF-IMPACT / GRAPH VALIDATORS (AST-oracle-backed; no scan-query dependency) ----
#
# These validators compute ground truth exclusively from the independent AST oracles
# (:func:`_callers_via_ast`, :func:`_test_modules_importing_via_ast`, :func:`_central_via_ast`,
# :func:`_import_path_via_ast`, :func:`_fn_blast_via_ast`). scan-query is never consulted for their
# GT — it is the tool the codemap arm invokes, so grading it against its own output is circular. Each
# validator honours a ``gt_pending`` flag: when a task ships with ``gt_pending: true`` (target repo
# absent at authoring time) the validator computes and writes the oracle GT and clears the flag,
# rather than failing on the empty placeholder.


def _gt_is_pending(task: dict) -> bool:
    """Return True when a task carries an unresolved ``gt_pending`` placeholder.

    A ``gt_pending`` task was authored without a target repo present, so its ``ground_truth`` holds
    empty placeholders. Validators treat such tasks as *always-compute* under ``--update`` (never a
    hard validation failure) and clear the flag once real oracle GT is written.

    Args:
        task: Task dict from tasks-bench.json.

    Returns:
        True when ``task["ground_truth"].get("gt_pending")`` is truthy.

    Examples:
        >>> _gt_is_pending({"ground_truth": {"gt_pending": True}})
        True
        >>> _gt_is_pending({"ground_truth": {"gt_pending": False}})
        False
        >>> _gt_is_pending({"ground_truth": {}})
        False
    """
    return bool(task.get("ground_truth", {}).get("gt_pending"))


def _validate_diff_impact(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate a ``diff_impact`` task: AST caller + test-module oracle for a staged change.

    A diff-impact task stages a scripted change to ``primary_fn`` (a widely-called function) and asks
    for the blast radius — direct callers plus the test modules that import the changed module. Ground
    truth is the *pre-change* AST caller set (:func:`_callers_via_ast`) unioned with the test modules
    importing the changed module (:func:`_test_modules_importing_via_ast`); both are independent of
    scan-query. ``sq``/``index`` are unused (kept for the uniform validator signature).

    Args:
        task: Task dict; reads ``primary_fn`` and ``primary_module``.
        sq: Path to scan-query (unused — GT is AST-only).
        index: Path to codemap index (unused).
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason).
    """
    del sq, index  # GT is AST-oracle-only; scan-query never consulted for diff-impact GT.
    gt = task.get("ground_truth", {})
    primary_fn = task.get("primary_fn", "")
    primary_module = task.get("primary_module", "") or primary_fn.split("::")[0]
    if not primary_fn or "::" not in primary_fn:
        return False, None, "diff_impact task needs a `primary_fn` of the form module::qualname"

    callers, cerr = _callers_via_ast(primary_fn, repo)
    if cerr is not None:
        return False, None, f"caller oracle failed: {cerr}"
    test_mods, terr = _test_modules_importing_via_ast(repo, primary_module)
    if terr is not None:
        return False, None, f"test-module oracle failed: {terr}"

    caller_list = sorted(callers)
    test_list = sorted(test_mods)
    live_gt: dict[str, Any] = {
        "fn_callers": caller_list,
        "unique_caller_count": len(caller_list),
        "test_modules": test_list,
        "test_module_count": len(test_list),
        "gt_source": "ast-caller-oracle + test-import-oracle",
        "gt_pending": False,
    }
    if _gt_is_pending(task):
        return False, live_gt, "gt_pending: computed oracle GT (pass --update to write)"

    problems = _diff_problems(gt, live_gt)
    return (not problems), live_gt, "; ".join(problems)


def _diff_problems(gt: dict, live_gt: dict) -> list[str]:
    """Return the mismatches between stored and freshly-computed diff-impact GT.

    Args:
        gt: Ground truth currently stored in the task file.
        live_gt: Freshly-computed oracle ground truth.

    Returns:
        A list of human-readable problem strings; empty when GT matches.
    """
    problems: list[str] = []
    if set(gt.get("fn_callers", [])) != set(live_gt["fn_callers"]):
        problems.append(
            f"fn_callers mismatch: expected {len(gt.get('fn_callers', []))}, got {live_gt['unique_caller_count']}"
        )
    if set(gt.get("test_modules", [])) != set(live_gt["test_modules"]):
        problems.append(
            f"test_modules mismatch: expected {len(gt.get('test_modules', []))}, got {live_gt['test_module_count']}"
        )
    return problems


def _validate_graph_central(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate a ``graph_central`` task: top-N most-imported modules (:func:`_central_via_ast`).

    Args:
        task: Task dict; reads ``ground_truth.top`` (default 10) and ``exclude_tests`` (default True).
        sq: Path to scan-query (unused — GT is AST-only).
        index: Path to codemap index (unused).
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason).
    """
    del sq, index
    gt = task.get("ground_truth", {})
    top = int(gt.get("top", 10))
    exclude_tests = bool(gt.get("exclude_tests", True))
    ranked = _central_via_ast(repo, top=top, exclude_tests=exclude_tests)
    modules = [mod for mod, _count in ranked]
    live_gt: dict[str, Any] = {
        "top": top,
        "exclude_tests": exclude_tests,
        "central_modules": modules,
        "central_ranked": [[mod, count] for mod, count in ranked],
        "gt_source": "ast-central-oracle",
        "gt_pending": False,
    }
    if _gt_is_pending(task):
        return False, live_gt, "gt_pending: computed oracle GT (pass --update to write)"
    if set(gt.get("central_modules", [])) != set(modules):
        return (
            False,
            live_gt,
            f"central_modules mismatch: expected {gt.get('central_modules', [])[:3]}, got {modules[:3]}",
        )
    return True, live_gt, ""


def _validate_graph_path(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate a ``graph_path`` task: a *unique* shortest import path source→target.

    A path task's GT is well-defined only when the shortest path is unique (:func:`_shortest_path_is_unique`);
    the validator records both the path and its uniqueness so authors can pick unambiguous pairs. Ground
    truth is :func:`_import_path_via_ast` output.

    Args:
        task: Task dict; reads ``ground_truth.source`` / ``.target`` / ``exclude_tests`` (default True).
        sq: Path to scan-query (unused — GT is AST-only).
        index: Path to codemap index (unused).
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason).
    """
    del sq, index
    gt = task.get("ground_truth", {})
    source = gt.get("source", "")
    target = gt.get("target", "")
    exclude_tests = bool(gt.get("exclude_tests", True))
    if not source or not target:
        return False, None, "graph_path task needs ground_truth.source and .target module names"
    path = _import_path_via_ast(repo, source, target, exclude_tests=exclude_tests)
    unique = _shortest_path_is_unique(repo, source, target, exclude_tests=exclude_tests)
    live_gt: dict[str, Any] = {
        "source": source,
        "target": target,
        "exclude_tests": exclude_tests,
        "import_path": path,
        "path_is_unique": unique,
        "gt_source": "ast-path-oracle",
        "gt_pending": False,
    }
    if _gt_is_pending(task):
        return False, live_gt, "gt_pending: computed oracle GT (pass --update to write)"
    if gt.get("import_path") != path:
        return False, live_gt, f"import_path mismatch: expected {gt.get('import_path')}, got {path}"
    return True, live_gt, ""


def _validate_graph_fn_blast(task: dict, sq: Path, index: Path, repo: Path) -> tuple[bool, dict[str, Any] | None, str]:
    """Validate a ``graph_fn_blast`` task: transitive caller closure to depth-N (:func:`_fn_blast_via_ast`).

    Args:
        task: Task dict; reads ``primary_fn`` and ``ground_truth.depth`` (default 2).
        sq: Path to scan-query (unused — GT is AST-only).
        index: Path to codemap index (unused).
        repo: Repo root directory.

    Returns:
        (ok, live_ground_truth, failure_reason).
    """
    del sq, index
    gt = task.get("ground_truth", {})
    primary_fn = task.get("primary_fn", "")
    depth = int(gt.get("depth", 2))
    if not primary_fn or "::" not in primary_fn:
        return False, None, "graph_fn_blast task needs a `primary_fn` of the form module::qualname"
    blast, berr = _fn_blast_via_ast(primary_fn, repo, depth=depth)
    if berr is not None:
        return False, None, f"fn-blast oracle failed: {berr}"
    blast_list = sorted(blast)
    live_gt: dict[str, Any] = {
        "depth": depth,
        "blast_callers": blast_list,
        "blast_count": len(blast_list),
        "gt_source": "ast-fn-blast-oracle",
        "gt_pending": False,
    }
    if _gt_is_pending(task):
        return False, live_gt, "gt_pending: computed oracle GT (pass --update to write)"
    if set(gt.get("blast_callers", [])) != set(blast_list):
        return (
            False,
            live_gt,
            f"blast_callers mismatch: expected {len(gt.get('blast_callers', []))}, got {len(blast_list)}",
        )
    return True, live_gt, ""


VALIDATORS = {
    "symbol_extraction": _validate_symbol,
    "fn_call_graph": _validate_fn,
    "review_assistance": _validate_rv,
    "code_quality": _validate_oss,
    "develop_blast_radius": _validate_fn,
    "diff_impact": _validate_diff_impact,
    "graph_central": _validate_graph_central,
    "graph_path": _validate_graph_path,
    "graph_fn_blast": _validate_graph_fn_blast,
}


# ---- GROUND TRUTH UPDATER ----


def _build_updated_ground_truth(task_type: str, live_gt: dict[str, Any], existing_gt: dict) -> dict:
    """Merge live computed values into the existing ground_truth dict.

    Args:
        task_type: One of "symbol_extraction", "fn_call_graph", "develop_blast_radius",
            "review_assistance", "code_quality", "diff_impact", "graph_central", "graph_path",
            or "graph_fn_blast".
        live_gt: Computed ground truth (scan-query output for legacy types; AST oracle for the
            diff-impact / graph series).
        existing_gt: Existing ground_truth from the task file (for fields not recomputed).

    Returns:
        Updated ground_truth dict.
    """
    if task_type == "symbol_extraction":
        return {**existing_gt, **live_gt}
    if task_type in ("fn_call_graph", "develop_blast_radius"):
        return {**existing_gt, **live_gt}
    if task_type in ("diff_impact", "graph_central", "graph_path", "graph_fn_blast"):
        # AST-oracle-only GT (review DI/GR); live_gt already carries the cleared gt_pending flag.
        return {**existing_gt, **live_gt}
    if task_type == "review_assistance":
        # live_gt is {sq_id: {count: N} | {symbols: [...]}}
        return live_gt  # caller updates sub_questions in place
    if task_type == "code_quality":
        return {**existing_gt, **live_gt}
    return existing_gt


# Task types whose refreshed ground truth comes from an INDEPENDENT oracle (AST), not from
# scan-query (the tool under test). Only these may be refreshed under a plain --update; every
# other type is scan-query-derived (circular) and requires --update-from-tool (review C-3).
# The diff-impact / graph series (review DI/GR) are AST-oracle-only by construction — their GT never
# touches scan-query — so they refresh under a plain --update alongside the caller-graph types.
_ORACLE_BACKED_TYPES: frozenset[str] = frozenset(
    {
        "fn_call_graph",
        "develop_blast_radius",
        "diff_impact",
        "graph_central",
        "graph_path",
        "graph_fn_blast",
    }
)

# code_quality checks with a dedicated independent AST oracle (review C-2 / C-2 remainder).
_ORACLE_BACKED_CQ_CHECKS: frozenset[str] = frozenset({"undocumented", "uncovered"})


def _update_is_oracle_backed(task: dict) -> bool:
    """Return True when this task's refreshed ground truth is AST-oracle-derived, not circular.

    Oracle-backed: fn_call_graph / develop_blast_radius (qualified AST caller oracle) and the
    ``undocumented`` (AST docstring oracle) and ``uncovered`` (AST test-reference oracle) code_quality
    checks. Everything else — symbol line ranges, review_assistance, coupled / xrefs_broken /
    combined_health — is refreshed from scan-query output and is therefore circular (review C-3).

    Examples:
        >>> _update_is_oracle_backed({"type": "fn_call_graph"})
        True
        >>> _update_is_oracle_backed({"type": "code_quality", "ground_truth": {"check": "undocumented"}})
        True
        >>> _update_is_oracle_backed({"type": "code_quality", "ground_truth": {"check": "uncovered"}})
        True
        >>> _update_is_oracle_backed({"type": "code_quality", "ground_truth": {"check": "xrefs_broken"}})
        False
        >>> _update_is_oracle_backed({"type": "review_assistance"})
        False
    """
    ttype = task.get("type", "")
    if ttype in _ORACLE_BACKED_TYPES:
        return True
    return ttype == "code_quality" and task.get("ground_truth", {}).get("check") in _ORACLE_BACKED_CQ_CHECKS


def _warn_circular_update(task_id: str, existing_gt: dict, live_gt: dict) -> None:
    """Print a loud circularity warning and the existing→live diff before a tool-derived write.

    Args:
        task_id: Task identifier for the banner.
        existing_gt: Ground truth currently stored in the task file.
        live_gt: Scan-query-derived values about to overwrite it.
    """
    bar = "!" * 72
    print(bar)
    print(f"! CIRCULAR UPDATE [{task_id}] — refreshing ground truth from scan-query (the tool under test)")
    for key in sorted(set(existing_gt) | set(live_gt)):
        if existing_gt.get(key) != live_gt.get(key):
            print(f"!   {key}: {existing_gt.get(key)!r} -> {live_gt.get(key)!r}")
    print(bar)


def _merge_rv_sub_questions(task: dict, live_gt: dict) -> list[dict]:
    """Return review_assistance sub_questions with ground_truth refreshed from ``live_gt``.

    Args:
        task: The review_assistance task dict.
        live_gt: Mapping of sub-question id → refreshed ground_truth dict.

    Returns:
        New sub_questions list; unchanged entries preserved, matched entries refreshed.
    """
    new_sqs: list[dict] = []
    for sq_item in task.get("sub_questions", []):
        sq_id = sq_item["id"]
        if sq_id in live_gt:
            new_sqs.append({**sq_item, "ground_truth": live_gt[sq_id]})
        else:
            new_sqs.append(sq_item)
    return new_sqs


def _refresh_task_gt(task: dict, live_gt: dict, update_from_tool: bool) -> tuple[dict, str]:
    """Build the updated task dict for --update, gating scan-query-derived (circular) refresh.

    Oracle-backed types (:func:`_update_is_oracle_backed`) refresh under a plain --update.
    Scan-query-derived types refresh only when ``update_from_tool`` is True, after a loud
    circularity warning and an existing→live diff (review C-3).

    Args:
        task: Task dict being refreshed.
        live_gt: Live computed ground truth from the validator.
        update_from_tool: When True, allow refreshing scan-query-derived (circular) fields.

    Returns:
        (task_to_store, status_message) — when a circular refresh is skipped, the original
        task is returned unchanged with a SKIP status.
    """
    task_type = task.get("type", "")
    if not _update_is_oracle_backed(task):
        if not update_from_tool:
            return task, "SKIP UPDATE (scan-query-derived; circular — pass --update-from-tool to force)"
        _warn_circular_update(task.get("id", "?"), task.get("ground_truth", {}), live_gt)
    updated_task = dict(task)
    if task_type == "review_assistance":
        updated_task["sub_questions"] = _merge_rv_sub_questions(task, live_gt)
    else:
        updated_task["ground_truth"] = _build_updated_ground_truth(task_type, live_gt, task.get("ground_truth", {}))
    return updated_task, "UPDATED"


# ---- MAIN ----


def main(
    repo_path: str = None,
    index_path: str = None,
    task: str = None,
    update: bool = False,
    update_from_tool: bool = False,
    verbose: bool = False,
) -> None:
    """Entry point: validate or update tasks-bench.json ground truth.

    Args:
        repo_path: Path to the target repository clone.
        index_path: Path to pre-built index JSON.
        task: Validate only this task ID (e.g. SE-01).
        update: Refresh ground truth from independent (AST) oracles only. fn_call_graph /
            develop_blast_radius and the ``undocumented`` / ``uncovered`` code_quality checks refresh;
            scan-query-derived types (symbol lines, review_assistance, coupled / xrefs_broken /
            combined_health) are skipped unless ``update_from_tool`` is also set.
        update_from_tool: Also refresh scan-query-derived ground truth (circular — the tool
            under test grades itself). Prints a loud circularity warning and an existing→live
            diff per task before writing. Use only for deliberate re-baselining (review C-3).
        verbose: Print live ground truth on failure.
    """

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
    if repo_path:
        repo_path = Path(repo_path)
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
        print("ERROR: scan-query not found on PATH or in plugins/codemap-py/bin/")
        sys.exit(1)

    index_path = resolve_index_path(index_path, repo_path)
    if not index_path.exists():
        print(f"ERROR: index not found at {index_path}. Run scan-index first.")
        sys.exit(1)

    if task:
        tasks = [t for t in tasks if t.get("id") == task]
        if not tasks:
            print(f"ERROR: task {task!r} not found in {TASKS_FILE.name}")
            sys.exit(1)

    # Validate each task
    failed: list[str] = []
    updated_tasks: list[dict] = []

    # Loop variable is `entry`, NOT `task` — `task` holds the --task filter (a str | None) and
    # must survive the loop for the write-back guard below (`if task is None`). Rebinding it here
    # would leave it pointing at the last task dict, making the full-file write-back unreachable.
    for entry in tasks:
        task_id = entry.get("id", "?")
        task_type = entry.get("type", "")
        validator = VALIDATORS.get(task_type)

        if validator is None:
            print(f"  SKIP  {task_id}: unknown type {task_type!r}")
            updated_tasks.append(entry)
            continue

        ok, live_gt, reason = validator(entry, sq, index_path, repo_path)

        if ok:
            print(f"  PASS  {task_id}")
            updated_tasks.append(entry)
        else:
            print(f"  FAIL  {task_id}: {reason}")
            failed.append(task_id)
            if verbose and live_gt is not None:
                print(f"         live_gt = {json.dumps(live_gt, indent=2)}")

            if update and live_gt is not None:
                # Circular refresh (scan-query-derived GT) is gated behind --update-from-tool (review C-3).
                stored_task, status = _refresh_task_gt(entry, live_gt, update_from_tool)
                updated_tasks.append(stored_task)
                print(f"         {status}")
            else:
                updated_tasks.append(entry)

    if update:
        # Only write the full file when no --task filter was given (`task` is the filter, str | None).
        if task is None:
            with TASKS_FILE.open("w") as f:
                if _tasks_wrapper is not None:
                    out = {**_tasks_wrapper, "tasks": updated_tasks}
                    json.dump(out, f, indent=2, sort_keys=True)
                else:
                    json.dump(updated_tasks, f, indent=2, sort_keys=True)
                f.write("\n")
            print(f"\nWrote updated ground truth to {TASKS_FILE.name}")
        else:
            print(f"\nSingle-task mode: updated task {task!r} not written (omit --task to write full file)")

    total = len(tasks)
    passed = total - len(failed)
    print(f"\n{passed}/{total} passed")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        if not update:
            sys.exit(1)


if __name__ == "__main__":
    fire.Fire(main)
