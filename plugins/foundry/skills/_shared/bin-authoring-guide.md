# bin/ Authoring Guide

Reference from any skill or scaffolding step that needs to decide whether to write a `bin/` script vs keep code inline, which language to use, and how to structure it.

Two audiences:

1. **Check 33 auto-fix** — when an EXTRACT verdict is reached, reference this doc for how to perform the extraction
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
| Any gate fails | SKIP | Inline is correct choice |
| 0–1 | OPTIONAL | Inline acceptable |
| 2–3 | RECOMMENDED | Prefer bin/ script |
| ≥4 | EXTRACT | Write as bin/ script — do NOT write inline |

---

## Decision Flowchart

1. Writing a code block in SKILL.md? Apply gate (G1/G2/G3).
2. Any gate fails? Inline is correct — stop here.
3. Gate passes. Score positive dimensions.
4. Score < 2? Inline acceptable — stop here.
5. Score 2–3? Prefer bin/; use language policy to pick bash vs Python.
6. Score ≥ 4? bin/ required; use language policy; write tests.

---

## Caller Pattern

How to invoke bin/ scripts from `.md` files:

```bash
# Bash script — with fallback
RESULT=$( "${CLAUDE_PLUGIN_ROOT}/bin/script-name.sh" arg1 arg2 2>/dev/null || echo "fallback-value" )

# Python script
RESULT=$( python3 "${CLAUDE_PLUGIN_ROOT}/bin/script-name.py" arg1 arg2 )
```

---

## Python Script Skeleton

Minimum required structure for any new Python bin/ script:

```python
#!/usr/bin/env python3
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

**Naming rule — use underscores, not hyphens.** Python cannot import hyphenated filenames via `import` statement; `script-name.py` requires `importlib` boilerplate. Underscore names (`script_name.py`) allow direct import after `sys.path.insert` — simpler tests, no extra machinery.

Test file header (standard pattern):

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "bin"))

import script_name  # or: from script_name import specific_function
```

That's all that's needed — `sys.path.insert` + direct `import`.

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
4. Replace invocation in source SKILL.md (Bash block or prose reference) with `python3 "${CLAUDE_PLUGIN_ROOT}/bin/<script_name>.py" ...`
5. Delete old `.sh` file
6. Delegate to **foundry:linting-expert** (ruff + mypy) and **foundry:qa-specialist** (edge-case matrix) per Quality Agents section

**Check 33 / `--efficiency` mode**: Phase A bin/-extraction check raises complexity-escalation findings as **medium** severity when trigger conditions detected in an existing `bin/` bash script. Extraction gate answer (a) or (b) triggers conversion, not just extraction.

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

## Integration with `foundry:manage create skill`

When `foundry:manage create skill <name>` scaffolds a new SKILL.md, include this instruction:

> Before writing any fenced code block, read `$_FOUNDRY_SHARED/bin-authoring-guide.md` and apply the extraction gate. Write bin/ script directly if verdict is RECOMMENDED or EXTRACT.

---

## Integration with Check 33 Auto-Fix

When Check 33 surfaces EXTRACT findings, reference this doc for:

- Language choice (bash vs Python) — see Language Policy section
- Caller pattern to replace the inline block with — see Caller Pattern section
- Test location (`bin/tests/`)
