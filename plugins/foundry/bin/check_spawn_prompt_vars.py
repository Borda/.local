#!/usr/bin/env python
"""check_spawn_prompt_vars.py — Detect $VAR references inside markdown spawn prompt templates.

Variables written as $VAR or ${VAR} inside ```markdown fenced blocks are passed
literally to spawned agents. The agent receives the dollar-sign string, not the
resolved value. Read tool calls on paths like "$_FOUNDRY_SHARED/foo.md" then fail
silently — no error surfaced at runtime.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_spawn_prompt_vars.py" [files...]
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_spawn_prompt_vars.py" --scan-dir plugins/

Output (stdout):
    One finding line per violation with prefix "C42-CRITICAL:", or a single pass line.

Exit codes:
    0   all files pass
    1   one or more violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Variables that callers explicitly substitute into the prompt string before dispatch
_CALLER_SUBSTITUTED: frozenset[str] = frozenset(
    {
        "ARGUMENTS",
        "RUN_DIR",
        "AUDIT_TPL",
        "REPORT_DIR",
        "SCOPE",
        "SKILL_DIR",
        "PLUGIN",
        "NAME",
        "DIRECTIVE",
    }
)

_MD_OPEN = re.compile(r"^```markdown\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")
_VAR_REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]+)\}?")


def check_file(path: Path) -> list[str]:
    """Return C42 violation strings for one SKILL.md or template file.

    Args:
        path: path to file to analyse.

    Returns:
        List of finding strings; empty list = no violations.

    Examples:
        >>> import os, tempfile
        >>> content = "```markdown\\nRead $_FOUNDRY_SHARED/foo.md\\n```\\n"
        >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        ...     _ = f.write(content); name = f.name
        >>> findings = check_file(Path(name)); os.unlink(name)
        >>> any("C42" in x and "_FOUNDRY_SHARED" in x for x in findings)
        True
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    findings: list[str] = []
    in_md = False
    block_num = 0
    reported: set[tuple[int, str]] = set()

    for line in text.splitlines():
        if not in_md and _MD_OPEN.match(line):
            in_md = True
            block_num += 1
            continue
        if in_md and _FENCE_CLOSE.match(line):
            in_md = False
            continue
        if not in_md:
            continue
        for m in _VAR_REF.finditer(line):
            var = m.group(1)
            if var in _CALLER_SUBSTITUTED or len(var) <= 1:
                continue
            key = (block_num, var)
            if key in reported:
                continue
            reported.add(key)
            findings.append(
                f"C42-CRITICAL: {path} (markdown block {block_num}):"
                f" ${var} unexpanded — variable reaches spawned agent as literal string"
            )

    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — scan files and print findings.

    Args:
        argv: argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 = all pass, 1 = violations found.
    """
    parser = argparse.ArgumentParser(description="Detect unexpanded $VAR in markdown spawn prompt blocks")
    parser.add_argument("files", nargs="*", help="files to check")
    parser.add_argument("--scan-dir", metavar="DIR", help="recursively scan DIR for SKILL.md and template .md files")
    parser.add_argument("--timeout", type=int, help="ignored — accepted for CLI compatibility")
    args = parser.parse_args(argv)

    paths: list[Path] = []
    if args.scan_dir:
        root = Path(args.scan_dir)
        paths.extend(root.rglob("*/skills/*/SKILL.md"))
        paths.extend(root.rglob("*/skills/*/templates/*.md"))
    paths.extend(Path(f) for f in args.files)
    if not paths:
        root = Path(".")
        paths.extend(root.rglob("*/skills/*/SKILL.md"))
        paths.extend(root.rglob("*/skills/*/templates/*.md"))

    all_findings: list[str] = []
    for p in sorted(set(paths)):
        all_findings.extend(check_file(p))

    if all_findings:
        print("\n".join(all_findings))
        return 1
    print("✓: Check 42 — no unexpanded variables in spawn prompt markdown blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
