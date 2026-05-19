# bin/ Authoring Guide

Reference from any skill or scaffolding step that needs to decide whether to write a `bin/` script vs keep code inline, which language to use, and how to structure it.

Two audiences:

1. **Check 33 auto-fix** — when a HIGH verdict is reached, reference this doc for how to perform the extraction
2. **`foundry:manage create skill`** — reference when scaffolding any new skill that needs code blocks, to prevent inline blocks that will later need extraction

---

## Language Policy (canonical — reproduced verbatim from `plugins/CLAUDE.md`)

- `bin/` — optional: standalone executables (`.sh`, `.py`) auto-added to Bash `PATH` by Claude Code; invoked via `${CLAUDE_PLUGIN_ROOT}/bin/<script>` inside skills
  - **Language policy — `bin/`**: Python default (minimum 3.10); bash only for enumerated cases: (1) plugin install-path resolution, (2) `$ARGUMENTS` parsing where bash regex shorter and quoting-safe, (3) `find | sort | head` pipelines with no business logic
    - Python scripts: type hints, module docstring, `if __name__ == "__main__"` guard; ruff-format 120-char line length (pre-commit enforced); aggregate related print output into single `print()` using `\n`/`\t`; pure functions (no I/O, no subprocess, no env-var reads) → `doctest` in docstring; anything with I/O/subprocess/argv → `pytest` with `capsys`/`monkeypatch` in `tests/` alongside `bin/`
    - bin/ scope: deterministic transforms only (parse args, resolve paths, compute one value); decision flow, branching prompts, agent-dispatch logic stays in SKILL.md prose
    - **Complexity escalation (bin/ scripts only — not inline blocks)**: existing or new `bin/` bash script that hits any trigger → convert to Python (see **Complexity Escalation** section); triggers: (1) 3+ `if/elif` branches, (2) nested conditionals, (3) loop with conditional body, (4) multiple `sed`/`awk` patterns in one pipeline, (5) multiple distinct error-handling paths
    - Reference design: `plugins/codemap/bin/` (typed, docstrings, `__name__` guards, dataclass serialization boundaries)
  - **Language policy — inline blocks in SKILL.md**: bash default; Python only when bash version requires JSON parsing, multi-line string manipulation, or numeric computation (and note: `Bash(python:*)` not in allow list — inline Python triggers approval prompt every invocation)

---

## Extraction Gate

Before writing ANY inline code block, apply this gate. All three must pass — if any fails, stay inline.

**Gate conditions (all three must pass):**

- **G1 (Size)**: block > 100 tokens — else overhead ≥ savings
- **G2 (Independence)**: no branch on prior LLM decision that cannot become an explicit arg
- **G3 (Identity)**: has computational meaning outside orchestration prose

**Score — sum applicable weights when gate passes:**

| Dimension | Weight |
| --- | --- |
| Testable (deterministic I/O, writable pytest/shellcheck test) | +2 |
| Reuse (same logic used in 2+ `.md` files) | +2 |
| Token drain (block > 300 tokens) | +2 |
| Lintable (shellcheck/ruff directly applicable) | +1 |
| Run frequency (executes >1× per skill invocation) | +1 |
| Standalone debuggable (runnable with no SKILL.md context) | +1 |

**Verdict:**

| Score | Verdict | Action |
| --- | --- | --- |
| Any gate fails | HOLD | Inline is correct choice |
| 0–1 | LOW | Inline acceptable |
| 2–3 | MEDIUM | Prefer bin/ script |
| ≥4 | HIGH | Write as bin/ script — do NOT write inline |

---

## Decision Flowchart

1. Writing a code block in SKILL.md? Apply gate (G1/G2/G3).
2. Any gate fails? Inline is correct — stop here.
3. Gate passes. Score positive dimensions.
4. Score < 2? Inline acceptable — stop here.
5. Score 2–3? Prefer bin/ (MEDIUM verdict); use language policy to pick bash vs Python.
6. Score ≥ 4? bin/ required (HIGH verdict); use language policy; write tests.
7. Wire into consumer — before commit: edit consumer SKILL.md, replace inline twin with `"${CLAUDE_PLUGIN_ROOT}/bin/<script>" …`; run `python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_orphaned_bin.py"`; must exit 0. Cross-plugin consumer (script in plugin A, called from plugin B)? Add `<!-- file: <basename> — consumers: <plugin> skills/<name> -->` doc header in any `.md` in the owning plugin (e.g. this guide); the detector now searches all plugins, so the script won't be flagged. Known cross-plugin utilities: `resolve-shared-path.sh` (foundry bin/ → oss skills/review, resolve, release), `find-polluter.py` (foundry bin/ → develop skills/debug).

---

## Caller Pattern

How to invoke bin/ scripts from `.md` files:

```bash
# Bash script — Claude Code annotation enforces timeout
RESULT=$("${CLAUDE_PLUGIN_ROOT}/bin/script-name.sh" arg1 arg2 2>/dev/null || echo "fallback-value")  # timeout: 5000

# Python script — timeout enforced inside the script via --timeout default
RESULT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/script-name.py" arg1 arg2)
```

---

## Timeout Policy

Every bin/ executable called from a SKILL.md with a `# timeout: N` comment must enforce that timeout at runtime — not just as a hint to Claude Code's Bash tool:

**Bash scripts** — use `# timeout: N` annotation; do NOT wrap with `timeout S` shell command:

```bash
# ✓ — Claude Code kills the Bash tool after N ms; annotation is the correct mechanism
RESULT=$("${CLAUDE_PLUGIN_ROOT}/bin/script.sh" args 2>/dev/null || echo "fallback")  # timeout: 5000

# ✗ — timeout S inside $() is redundant with # timeout: N and adds risk:
#     (1) timeout not in Claude Code allow list — future permission prompt exposure
#     (2) both fire at same threshold; inner timeout adds only subprocess fork overhead
RESULT=$(timeout 5 "${CLAUDE_PLUGIN_ROOT}/bin/script.sh" args 2>/dev/null || echo "fallback")  # timeout: 5000
```

Note: `timeout S` IS valid for scripts invoked outside Claude Code (CI pipelines, standalone shell, pytest helpers). In SKILL.md context only: use `# timeout: N`.

**Python scripts** — add `--timeout SECS` argparse argument; scripts doing subprocess or network I/O must pass it to every blocking call. The `--timeout` parameter is optional at the call site — default value must equal N ÷ 1000 (from the calling SKILL.md `# timeout: N` annotation). Shell `timeout S` wrapper is not required for Python scripts; the argparse default enforces the budget internally:

```bash
# ✓ — timeout enforced by --timeout default inside the script; no shell wrapper needed
RESULT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/script.py" args)  # timeout: 5000

# ✓ — explicit override also valid when caller needs a different budget
RESULT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/script.py" --timeout 30 args)  # timeout: 30000
```

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(...)
    # default= must match # timeout: N at the call site (N ÷ 1000)
    parser.add_argument("--timeout", type=int, default=5,
                        help="Max subprocess wait in seconds (default: 5).")
    args = parser.parse_args(argv)
    result = _subprocess_call(timeout=args.timeout)
    ...

def _subprocess_call(timeout: int = 5) -> str:
    try:
        return subprocess.check_output([...], timeout=timeout, ...)
    except subprocess.TimeoutExpired:
        return ""  # or raise, depending on caller contract
```

**Pure-transform scripts** (arg parsers, path resolvers without subprocess) — no timeout parameter needed; they cannot block.

**ms → s reference** (for `--timeout` arg in Python scripts): 5000 ms = 5 s; 6000 ms = 6 s; 15000 ms = 15 s; 600000 ms = 600 s.

---

## Python Script Skeleton

Minimum required structure for any new Python bin/ script:

```python
#!/usr/bin/env python
"""script-name.py — one-line description.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/script-name.py" <required-arg> [--flag]
"""
from __future__ import annotations
import argparse
import sys
# ... imports


def pure_function(x: str) -> str:
    """One-line summary.

    Args:
        x: description.

    Returns:
        description.

    Examples:
        >>> pure_function("input")
        'output'
    """
    ...


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = argparse.ArgumentParser(...)
    ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Tests go in `<plugin-root>/tests/test_<script-name>.py` — alongside `bin/`, not inside it. No `__init__.py`. Plugin layout:

```
plugins/foundry/
  bin/
    script_name.py        ← underscore names (see naming rule below)
  tests/
    test_script_name.py   ← here, not bin/tests/
```

**Naming rule — use underscores, not hyphens.** Python cannot import hyphenated filenames via `import` statement; `script-name.py` requires `importlib` boilerplate. Underscore names (`script_name.py`) allow direct import — simpler tests, no extra machinery.

**conftest.py** (one per plugin `tests/` directory — centralises `bin/` path setup for all test files in that plugin):

```python
"""Pytest configuration — adds bin/ to sys.path for all tests."""
from __future__ import annotations

import sys
from pathlib import Path

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
if str(_BIN_DIR) not in sys.path:
    sys.path.insert(0, str(_BIN_DIR))
```

- `.resolve()` — resolves symlinks; path is absolute and canonical
- Guard `if str(_BIN_DIR) not in sys.path` — prevents duplicate entries when pytest reimports conftest

**Individual test files** — import directly, no `sys.path` manipulation needed:

```python
import script_name  # bin/ already on sys.path via conftest.py
from script_name import pure_function
```

---

## Bash Script Skeleton

For the three allowed cases only (see language policy above):

```bash
#!/usr/bin/env bash
# script-name.sh — one-line description.
# Usage: script-name.sh [arg]
# Exit codes: 0 = success, 1 = not found
set -euo pipefail
...
```

---

## Complexity Escalation

Applies to `bin/` scripts only — inline SKILL.md blocks stay bash (inline Python triggers approval prompt every invocation). When an extracted `bin/` bash script grows past a simple linear transform, convert to Python before complexity compounds.

**Escalation triggers** — any one fires → convert:

| Trigger | Example |
| --- | --- |
| 3+ `if/elif` branches | `if [[ $x == a ]]; then ... elif [[ $x == b ]]; ...` (3rd branch = trigger) |
| Nested conditionals | `if ...; then if ...; fi; fi` |
| Loop with conditional body | `for f in ...; do if ...; then ...; fi; done` |
| Multiple `sed`/`awk` patterns | `sed -e 's/a/b/' -e 's/c/d/'` — 2nd `-e` is trigger |
| Multiple distinct error paths | 2+ separate `exit N` calls at different failure points |

**Conversion steps:**

1. Identify bash script in `bin/` meeting a trigger
2. Rewrite as Python using the Python Script Skeleton above — preserve CLI interface (arg names, exit codes, stdout contract)
3. Add `pytest` test file in `tests/test_<script_name>.py` — cover all branches that triggered escalation plus happy path
4. Replace invocation in source SKILL.md (Bash block or prose reference) with `python "${CLAUDE_PLUGIN_ROOT}/bin/<script_name>.py" ...`
5. Delete old `.sh` file
6. Delegate to **foundry:linting-expert** (ruff + mypy) and **foundry:qa-specialist** (edge-case matrix) per Quality Agents section

**Check 33 / `--efficiency` mode**: Phase A bin/-extraction check raises complexity-escalation findings as **medium** severity when trigger conditions detected in an existing `bin/` bash script. HIGH or MEDIUM verdict triggers conversion, not just extraction.

---

## Quality Agents

After writing any `bin/` script, delegate to these agents:

**`foundry:linting-expert`** — after implementation, before handover:
- `ruff check` + `ruff format` — style, imports, security, 120-char lines
- `mypy` — type annotation correctness
- `shellcheck bin/<name>.sh` for bash scripts
- Note: `bin/` scripts use `print()` for output — intentional, not stray. Add `"bin/**" = ["T20"]` to `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`

**`foundry:qa-specialist`** — for test coverage review and edge-case matrix:
- Public API surface: `main()`, all exported pure functions
- Edge cases: empty input, bad args, missing files, unsupported markers
- Parametrize where 3+ cases share same structure

---

## Resilience Replication Marker

Blocks replicating across files by design (per-plugin resilience, cross-plugin fallbacks) must be marked to suppress Check 33 / `--efficiency` false positives.

**Canonical marker** — first line of the fenced block content:

```bash
# audit-skip: resilience-replication
```

Marker must appear as the first content line inside the fence (not preceding it). Curator and Check 33 Phase 2 recognize both this structured marker and prose annotations matching "intentional resilience replication" — the structured form is a conventional token (not yet wired into bash quick-scans; recognized by curator prompt).

Example:

```bash
# audit-skip: resilience-replication
MONITOR_INTERVAL=${MONITOR_INTERVAL:-300}
HARD_CUTOFF=${HARD_CUTOFF:-900}
```

**When to use**: block appears in 2+ plugin files with only constant differences AND is not a bin/ extraction candidate — e.g. health-monitoring constants, plugin-availability checks, unsupported-flag resilience boilerplate. See `plugins/CLAUDE.md` §Fallback / Resilience Infrastructure for design rationale.

---

## Integration with `foundry:manage create skill`

When `foundry:manage create skill <name>` scaffolds a new SKILL.md, include this instruction:

> Before writing any fenced code block, read `$_FOUNDRY_SHARED/bin-authoring-guide.md` and apply the extraction gate. Write bin/ script directly if verdict is MEDIUM or HIGH.

---

## Integration with Check 33 Auto-Fix

When Check 33 surfaces HIGH findings, reference this doc for:

- Language choice (bash vs Python) — see Language Policy section
- Caller pattern to replace the inline block with — see Caller Pattern section
- Test location (`bin/tests/`)

**Surgical edit constraint** — when replacing an inline block in a source `.md` file, modify ONLY the target block. Do NOT edit surrounding prose, frontmatter, other code blocks, check tables, or any other content. If incidental issues are noticed, record them in the extraction summary — do not fix them inline. After each file edit, run `git diff HEAD -- <file>` and verify only target-block lines appear in the diff; revert and re-apply if non-target lines changed.
