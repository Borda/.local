<!-- R3: placeholder paths below (e.g. /Users/<name>/, /path/to/) are illustrative examples, not hardcoded user paths — Check R3 false positives -->
# bin/ Authoring Guide

Reference from any skill or scaffolding step that needs to decide whether to write a `bin/` script vs keep code inline, which language to use, and how to structure it.

Two audiences:

1. **Check 33 auto-fix** — when a HIGH verdict is reached, reference this doc for how to perform the extraction
2. **`foundry:manage create skill`** — reference when scaffolding any new skill that needs code blocks, to prevent inline blocks that will later need extraction

See also: [bin/ Script Principles](../../README.md#bin-script-principles) in plugins/README.md for the authoring motivations behind these rules.

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

## Cross-OS Compatibility

`bin/` scripts run on macOS, Linux, and Windows (WSL/git-bash). Python scripts are preferred over bash for any logic beyond the three allowed bash cases — Python is portable by design; bash is not.

**Bash: banned constructs** (GNU-only or platform-divergent):

| Construct | Problem | Use instead |
| --- | --- | --- |
| `grep -P` | PCRE — GNU only; macOS BSD grep rejects | `grep -E` or Python `re` |
| `sed -i` (no arg) | GNU accepts; BSD requires `sed -i ''` | Python `pathlib.write_text` |
| `readlink -f` | BSD lacks `-f` | Python `Path.resolve()` |
| `date -d` | GNU only | Python `datetime` |
| `find -printf` | GNU only | Python `os.walk` |
| `sort -V` (version sort) | GNU/recent BSD only | Python `packaging.version` |

**Python: portability rules**:
- Use `pathlib.Path` for all path operations — never `os.path.sep` string surgery
- Never `os.system()` — use `subprocess.run(..., check=True)`
- Add `LC_ALL=C` to subprocess env when calling `sort`/`grep` for stable locale-independent output
- Test with `tmp_path` fixture (pytest) — never hard-code `/tmp/` or `C:\Temp`

---

## Extraction Gate

Before writing ANY inline code block, first apply the Prose check (§Prose over Code, Case 3). If prose is precision-equivalent and shorter — write prose and stop. Otherwise apply this gate. All three must pass — if any fails, stay inline.

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
| Reasoning complexity (3+ conditional branches, nested conditionals, or non-trivial regex/arithmetic) | +2 |

**Verdict:**

| Score | Verdict | Action |
| --- | --- | --- |
| Any gate fails | HOLD | Inline is correct choice |
| 0–1 | LOW | Inline acceptable |
| 2–3 | MEDIUM | Prefer bin/ script |
| ≥4 | HIGH | Write as bin/ script — do NOT write inline |

---

## Prose over Code (Token Compression)

Prefer plain language, a table, or a schema over a code block when prose is **precision-equivalent** and shorter in tokens. Applies at authoring time and retrospectively.

**Exempt** (fenced code blocks in `.md` files): examples, templates, and blocks whose purpose is to carry exact syntax for copy-paste or reproducible execution.

**Precision-equivalent** means the prose expresses the logic with **100% precision and 100% reproducibility**: every input produces the same output from the prose description as from the code, with no ambiguity. This holds for: routing/switch logic with a fixed, bounded, enumerable input set (e.g. mode flags, classification labels, small enum dispatch). It does NOT hold for: free-form inputs, numeric ranges, regex pattern matching, file-system state checks, or any logic where edge cases cannot be fully enumerated in plain language. When uncertain, keep code.

Tests and linting on a bin/ script are anti-regression tools — they are NOT a reason to keep a script that is fully replaceable with plain language. Delete the script and the tests with it when precision-equivalent prose is possible.

### Case 1 — inline fenced code block in any `.md` file

Replace with prose/table/schema when all REPLACE conditions apply AND no KEEP condition applies:

| Condition | REPLACE | KEEP |
| --- | --- | --- |
| Variable only referenced in prose conditions (never in a later shell command) | ✓ | — |
| Variable consumed by a later shell command or drives file I/O / cache state | — | ✓ |
| Cases bounded, mutually exclusive, no shell/subshell semantics | ✓ | — |
| Prose form is precision-equivalent (see definition above) | ✓ | — |

Token test (apply only when all REPLACE conditions hold): `tokens(block) > tokens(prose/table/schema)` → replace.

**Replace**: `manage/SKILL.md` `EDIT_TRIVIAL` classifier — only in prose conditions, no shell consumer → 2-row table.

**Keep**: `STALE=$([ ! -f "$INDEX" ] || [ -n "$(find "$INDEX" -mmin +60 -print 2>/dev/null)" ] && echo true || echo false)` — `STALE` consumed by downstream shell command; `find -mmin` + `2>/dev/null` not precision-equivalent in prose.

### Case 2 — existing `bin/` script

`bin/` scripts enforce reproducibility and stay as executables. Deletion candidate only when ALL hold:

- Logic is precision-equivalent (see definition above) — routing/switch with bounded input set; NOT free-form or range inputs
- If a test file exists (`tests/test_<name>.py` or `tests/test_<name>_sh.py`): the test file is evidence that precision was non-obvious at authoring time. Before deleting, verify the prose covers every non-happy-path test scenario — if any test case produces an ambiguous prose answer, keep the script. Delete the test file only after this verification passes.
- No cross-plugin consumers (not listed in `Known cross-plugin utilities` or any `<!-- file: ... consumers: ... -->` header)
- Single consumer — called from exactly one `.md` file within the plugin; verify with `grep -rn "<script-basename>" plugins/*/skills/ plugins/*/agents/`
- Token test: `tokens(call-site description in .md) > tokens(equivalent prose in .md)` — strict savings required

Linting on the script is not a blocker. Tests are not a veto — but they document the precision cases the author considered non-obvious. Verify prose covers every test scenario before deleting. Delete the test file together with the script after verification.

When all hold: delete script (and its test file if present), replace call-site with prose, run `check_orphaned_bin.py` (must exit 0).

### Case 3 — new code at authoring time

**Prose check runs first, before the Extraction Gate.** Ask: would one sentence, a table, or a schema express this with equal precision and fewer tokens? Yes → write prose; stop. No → proceed to Extraction Gate (G1/G2/G3).

---

## Decision Flowchart

0. **Prose check first**: would one sentence, a table, or a schema express this with precision-equivalent content and fewer tokens? Yes → write prose; stop here. No → continue.
1. Writing a code block in SKILL.md? Apply gate (G1/G2/G3).
2. Any gate fails? Inline is correct — stop here.
3. Gate passes. Score positive dimensions.
4. Score < 2? Inline acceptable — stop here.
5. Score 2–3? Prefer bin/ (MEDIUM verdict); use language policy to pick bash vs Python.
6. Score ≥ 4? bin/ required (HIGH verdict); use language policy; write tests.
7. Wire into consumer — before commit: edit consumer SKILL.md, replace inline twin with `"${CLAUDE_PLUGIN_ROOT}/bin/<script>" …`; run `python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_orphaned_bin.py"`; must exit 0. Cross-plugin consumer (script in plugin A, called from plugin B)? Add `<!-- file: <basename> — consumers: <plugin> skills/<name> -->` doc header in any `.md` in the owning plugin (e.g. this guide); the detector now searches all plugins, so the script won't be flagged. Known cross-plugin utilities: `resolve-shared-path.sh` (foundry bin/ → oss skills/review, resolve, release), `find-polluter.py` (foundry bin/ → develop skills/debug), `get_plugin_install_path.py` (foundry bin/ → consumed by `find-foundry-shared.sh` and `resolve-shared-path.sh` for registry-authoritative install-path lookup).

---

## Caller Pattern

How to invoke bin/ scripts from `.md` files:

```bash
# timeout enforced via annotation
RESULT=$("${CLAUDE_PLUGIN_ROOT}/bin/script-name.sh" arg1 arg2 2>/dev/null || echo "fallback-value")  # timeout: 5000

# timeout enforced by --timeout default inside script
RESULT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/script-name.py" arg1 arg2)
```

---

## Script Output Routing

**Rule: match output channel to downstream consumer.**

| Output needed for | Script writes | Skill reads via |
| --- | --- | --- |
| Shell command arg (`"$VAR"`) | `${TMPDIR:-/tmp}/<skill>-<name>` file | `VAR=$(cat "${TMPDIR:-/tmp}/<skill>-<name>")` |
| Prose condition / display only | `${TMPDIR:-/tmp}/<skill>-<name>` file | Read tool or plain prose |
| Single value, same bash block | stdout | `VAR=$(python script.py ...)` |
| Several values across later blocks | `bin/state.py set <ns> K=V …` | `eval "$(python … bin/state.py load <ns>)"` |

**Multi-value DATA output: write to TMPDIR files — never `eval` stdout.**

Shell variables set in one Bash tool call do not persist to the next separate Bash tool call — they only survive within a single invocation. TMPDIR files survive across all invocations. Any script returning 2+ values (e.g. `PROJ` + `INDEX`) must write each to its own file and exit 0/1. The skill checks exit code; downstream steps `cat` what they need.

**Preferred idiom for cross-block persistence: `bin/state.py`.** Instead of hand-rolling a per-skill temp file + reload, use the tested helper — `python "${CLAUDE_PLUGIN_ROOT}/bin/state.py" set <namespace> RUN_DIR="$RUN_DIR" SCOPE="$SCOPE"` in the producing block, then `eval "$(python "${CLAUDE_PLUGIN_ROOT}/bin/state.py" load <namespace>)"` at the top of each consuming block. Values are single-quote-escaped so `eval` is injection-safe. Include a run-unique component in `<namespace>` (timestamp / run-id) when concurrent sessions of the same skill could collide. This is what `check_bash_persistence` recognizes as a valid reload — the `eval "$(…)"` form suppresses the cross-block-loss finding.

> **Scope**: this rule applies to DATA output (returning computed values to the skill). Shell-setup eval — e.g. `eval "$(python health_sentinel.py ...)"` that injects `SENTINEL=...` into the calling shell for health monitoring — is a different pattern and remains valid.

**Naming convention**: `${TMPDIR:-/tmp}/<plugin>-<script-slug>-<value-name>`. When a script has more than one consumer (e.g. a shared `resolve-shared.py`), the calling skill passes a unique prefix: `--out-prefix <skill>-<run-id>`; the script writes `<prefix>-proj`, `<prefix>-index`. Never hardcode a prefix in a shared script — consumers will collide.

```python
# script — owns output routing; prefix passed by caller when multi-consumer
import os, sys
from pathlib import Path
tmpdir = os.environ.get("TMPDIR", "/tmp")
prefix = sys.argv[1]  # e.g. "codemap-integration"
Path(f"{tmpdir}/{prefix}-proj").write_text(proj)
Path(f"{tmpdir}/{prefix}-index").write_text(index)
sys.exit(0)
```

```bash
# skill — exit-code check only; no parsing
python "${CLAUDE_PLUGIN_ROOT:-plugins/myplugin}/bin/resolve.py" "myplugin-resolve" ...  # timeout: 5000
```

```bash
# only when value feeds shell command
INDEX=$(cat "${TMPDIR:-/tmp}/myplugin-resolve-index")
python scan.py --index "$INDEX"  # timeout: 30000
```

```text
# downstream prose — when value used only for display or condition
Read ${TMPDIR:-/tmp}/myplugin-resolve-index. If empty: print ✗ and stop.
```

**Anti-patterns — data output:**

```bash
# ✗ eval for data — fragile; shlex discipline required;
#   vars die at next Bash tool call anyway
eval "$(python resolve.py ...)"

# ✗ tab-delimited read — vars die at next Bash tool call
IFS=$'\t' read -r PROJ INDEX < <(python resolve.py ...)

# non-atomic anti-pattern (separate concern): two calls may see different state
# even with TMPDIR routing, one invocation writes both files
# ✗ two calls — non-atomic
PROJ=$(python resolve.py --field proj)
INDEX=$(python resolve.py --field index)
```

---

## Timeout Policy

Every bin/ executable called from a SKILL.md with a `# timeout: N` comment must enforce that timeout at runtime — not just as a hint to Claude Code's Bash tool:

**Bash scripts** — use `# timeout: N` annotation; do NOT wrap with `timeout S` shell command:

```bash
# ✓ — Claude Code kills Bash tool after N ms; annotation is correct
RESULT=$("${CLAUDE_PLUGIN_ROOT}/bin/script.sh" args 2>/dev/null || echo "fallback")  # timeout: 5000

# ✗ — timeout S inside $() is redundant with # timeout: N and adds risk:
#     (1) not in allow list — future permission prompt
#     (2) same threshold; adds only subprocess fork overhead
RESULT=$(timeout 5 "${CLAUDE_PLUGIN_ROOT}/bin/script.sh" args 2>/dev/null || echo "fallback")  # timeout: 5000
```

Note: `timeout S` IS valid for scripts invoked outside Claude Code (CI pipelines, standalone shell, pytest helpers). In SKILL.md context only: use `# timeout: N`.

**Python scripts** — add `--timeout SECS` argparse argument; scripts doing subprocess or network I/O must pass it to every blocking call. The `--timeout` parameter is optional at the call site — default value must equal N ÷ 1000 (from the calling SKILL.md `# timeout: N` annotation). Shell `timeout S` wrapper is not required for Python scripts; the argparse default enforces the budget internally:

```bash
# ✓ — --timeout default enforces budget; no shell wrapper needed
RESULT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/script.py" args)  # timeout: 5000

# ✓ — explicit override for different budget
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

## Bash Script Testing

Naming: `test_<basename_normalized>_sh.py` in `tests/` alongside `bin/`. Normalize: dashes → underscores, drop `.sh`, append `_sh` suffix. `_sh` suffix permanently distinguishes bash tests from Python tests with same base name.

Example: `resolve-shared-path.sh` → `test_resolve_shared_path_sh.py`.

**Self-contained helper** — each test file defines own `SCRIPT` path and `sh()` helper; no `conftest.py` changes needed for bash tests:

```python
import os, subprocess
from pathlib import Path
import pytest

SCRIPT = Path(__file__).parent.parent / "bin" / "script-name.sh"

def sh(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    e = {**os.environ, **(env or {})}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e, cwd=cwd)
```

**Three mandatory tests per script:**

- Missing/wrong args → non-zero exit
- Invalid input (path traversal `..`, special chars, non-integer where integer expected) → exit 2 + stderr message
- Happy path with isolated `HOME` via `tmp_path` (prevents cache-dir reads from real `~`)

Template:

```python
def test_missing_args() -> None:
    assert sh().returncode != 0

def test_invalid_input_traversal() -> None:
    r = sh("../evil", "skills/_shared")
    assert r.returncode == 2
    assert "invalid" in r.stderr

def test_happy_path(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path)}
    r = sh("foundry", "skills/_shared", env=env)
    assert r.returncode == 0
    assert "skills/_shared" in r.stdout
```

**HOME isolation** — always pass `HOME=str(tmp_path)` for scripts doing cache lookups. Never rely on real `~/.claude/` in tests.

**Integration marking** — scripts requiring real git repo with history, `gh` auth, or network calls use module-level `pytestmark`:

```python
pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_INTEGRATION"),
    reason="requires real git/gh env — set RUN_INTEGRATION=1"
)
```

Apply at module level for fully-integration files; on individual tests for mixed files (arg-validation unit + happy-path integration).

Integration-requiring conditions: `git describe`, `git log` on real history, `gh` auth/API, network calls.

**Audit enforcement** — Check 34 (`/audit plugins`) verifies every `bin/*.sh` has corresponding `tests/test_<name>_sh.py`. Missing test files flagged as MEDIUM severity.

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

> Before writing any fenced code block, read `$_FOUNDRY_SHARED/bin-authoring-guide.md` and apply the extraction gate. Write bin/ script directly if verdict is MEDIUM or HIGH. For any bin/ script returning 2+ values: apply §Script Output Routing — write each value to `${TMPDIR:-/tmp}/<skill>-<name>` file; never `eval` stdout.

---

## Integration with Check 33 Auto-Fix

When Check 33 surfaces HIGH findings, reference this doc for:

- Language choice (bash vs Python) — see Language Policy section
- Caller pattern to replace the inline block with — see Caller Pattern section
- Test location (`bin/tests/`)

**Surgical edit constraint** — when replacing an inline block in a source `.md` file, modify ONLY the target block. Do NOT edit surrounding prose, frontmatter, other code blocks, check tables, or any other content. If incidental issues are noticed, record them in the extraction summary — do not fix them inline. After each file edit, run `git diff HEAD -- <file>` and verify only target-block lines appear in the diff; revert and re-apply if non-target lines changed.
