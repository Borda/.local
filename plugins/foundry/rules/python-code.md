---
description: Python coding standards — docstrings, deprecation, version policy, library API awareness, PyTorch AMP
paths:
  - '**/*.py'
---

## Docstring Style

- **Google style (Napoleon)** — no exceptions unless user explicitly requests otherwise
- Never switch NumPy style based on project type, existing code, or own judgement
- Every public function/class/module needs docstring; at least one `Examples` section per public function
  - Omit only when user **explicitly says skip examples** (e.g., "no examples needed", "skip the Examples section")
  - Brevity request or "minimal" docstring does NOT qualify

## Deprecation

**Version check first**: before generating any deprecation code:

- Agentic/tool context: `python -c "import deprecate; print(deprecate.__version__)"` via Bash
- In conversation context: output command for user to run, wait for confirmation before proceeding

If installed version differs, read `help(deprecate)` or project CHANGELOG before generating code — don't assume Claude knows latest API. Do **not** upgrade pyDeprecate on projects where older version works fine.

**Never use `warnings.warn` for deprecation** — use `pyDeprecate` exclusively. Import from `deprecate`, not `pyDeprecate`:

**Deprecation lifecycle**: deprecate in minor release → keep ≥1 minor cycle → remove in next major.

```python
from deprecate import deprecated  # correct
```

If `pyDeprecate` not installed, add it — don't fall back to `warnings.warn`.

### Function / method deprecation

Both parts required — decorator alone incomplete:

```python
from deprecate import deprecated


@deprecated(target=new_fn, deprecated_in="X.Y", remove_in="Z.W")
def old_fn(*args, **kwargs):
    """One-line summary.

    Args:
        ...

    Examples:
        ...
    """
    ...
```

### Class deprecation — use `deprecated_class` (v0.6.0+) <!-- verified: 2026-04-06; re-verify if pyDeprecate is upgraded past 0.6.x -->

**Don't apply `@deprecated` directly to class** — use `deprecated_class`. Applying `@deprecated` to class emits `UserWarning` and silently delegates, but `deprecated_class` is explicit, correct API for Enum, dataclass, plain classes.

```python
from deprecate import deprecated_class


@deprecated_class(target=NewClass, deprecated_in="X.Y", remove_in="Z.W")
class OldClass: ...
```

`deprecated_class` wraps class in transparent proxy — attribute access, method calls, `isinstance()`, instantiation all forward to `NewClass` with `FutureWarning`.

**Version conflict resolution**: If installed pyDeprecate below v0.6.0 and upgrading prohibited (stable project, pinned deps), don't use `deprecated_class` — instead apply `@deprecated` to thin subclass wrapper:

```python
from deprecate import deprecated


class ModelWrapper: ...  # new class


class _OldModelWrapperImpl(ModelWrapper):
    """Transitional subclass — do not use directly."""

    ...


@deprecated(target=ModelWrapper, deprecated_in="X.Y", remove_in="Z.W")
def OldModelWrapper(*args, **kwargs):  # noqa: N802
    return _OldModelWrapperImpl(*args, **kwargs)
```

Ask user whether upgrading pyDeprecate acceptable before proceeding. Never silently recommend upgrade.

### Instance deprecation — use `deprecated_instance` (v0.6.0+) <!-- verified: 2026-04-06; re-verify if pyDeprecate is upgraded past 0.6.x -->

```python
from deprecate import deprecated_instance

old_obj = deprecated_instance(new_obj, deprecated_in="X.Y", remove_in="Z.W")
```

## Python Version Policy

- Python 3.10 reaches EOL Oct 2026 — minimum for new projects is **3.11** (Python 3.11 reaches EOL Oct 2027; check [endoflife.date/python](https://endoflife.date/python) <!-- verified: 2026-04-08 --> for current schedule) <!-- re-verify: when Python 3.11 reaches EOL (Oct 2027) — bump minimum to 3.12 -->
- **Before writing any Python code**: read `pyproject.toml` (or `setup.cfg`/`setup.py`) to find `requires-python`; use only syntax/APIs available in that minimum version
- Version-gated features — **read pyproject.toml first if any of these requested**:
  - `match` statement (3.10+)
  - `TypeAlias` (3.10+)
  - `typing.ParamSpec` (3.10+)
  - `tomllib` (3.11+) — use `tomli` backport if requires-python < 3.11
  - `ExceptionGroup` (3.11+)
  - `Self` type (3.11+)
- Use `target-version = "py311"` in ruff/mypy configs for new projects

## Library API Awareness

Claude training data has fixed cutoff — any library released or substantially updated after that point may have APIs Claude doesn't know.

**Before using any third-party library feature**:

1. Check installed version: `python -c "import <pkg>; print(<pkg>.__version__)"` or `pip show <pkg>`
2. Compare against Claude training: Claude's training cutoff noted in system context; any library with active development after that date may have new or changed APIs
3. If installed version newer than Claude's training snapshot: read library's CHANGELOG or online docs first; `python -c "import <pkg>; help(<pkg>)"` fallback for offline inspection
4. Use API matching **installed** version — don't assume Claude's training knowledge current

**Never suggest upgrading library** solely because Claude doesn't recognise newer API. Project has version pinned for a reason — learn that version's API from docs; don't force updates on stable/stale projects.

## PyTorch AMP

- `torch.cuda.amp.autocast` deprecated since PyTorch 2.4 — use `torch.amp.autocast('cuda', ...)` instead
- `torch.cuda.amp.GradScaler` deprecated since PyTorch 2.4 — use `torch.amp.GradScaler('cuda')` instead
- Verify current stable release at pytorch.org when citing specific version numbers <!-- verified: 2026-04-06 -->

## Security

- `pickle.load` / `torch.load` on external data require `weights_only=True`

## Code Quality Rules

- Type annotations on all public interfaces
- No mutable default arguments
- No broad `except:` without re-raising or logging
- No `import *` — always explicit imports
- No global mutable state — use dependency injection
- `__all__` in `__init__.py` to define public API surface
- Prefer composition over deep inheritance

## Complexity Thresholds

Enforce via ruff `C901` + `PLR` rules (see `foundry:linting-expert` for config). Hard limits per function:

| Metric | Limit | ruff rule | Refactor signal |
| --- | --- | --- | --- |
| Cyclomatic complexity (McCabe) | ≤12 | `C901` | extract sub-functions, guard clauses |
| Required arguments (no default) | ≤7 | style rule | primary rule — enforced in review; more than 7 required = introduce config dataclass |
| All arguments (incl. kwargs w/ defaults) | ≤12 | `PLR0913` | blunt ruff gate — kwargs with defaults may exceed 7 freely; ≤12 catches extreme cases |
| Branches (`if`/`elif`/`match`) | ≤12 | `PLR0912` | dispatch table, strategy pattern |
| Statements | ≤50 | `PLR0915` | split responsibility |
| Return points | ≤6 | `PLR0911` | consolidate early-return paths |

When a function exceeds any limit: **refactor first**. Adding `# noqa: PLR...` allowed only when refactoring genuinely impossible (generated code, parser output, protocol-mandated signature) — always add inline comment explaining why.
