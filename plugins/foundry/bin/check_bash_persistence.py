#!/usr/bin/env python
"""check_bash_persistence.py — Detect shell variables referenced across Bash tool call boundaries.

Variables assigned in one ```bash block are NOT available in later bash blocks —
each Bash tool call runs in a fresh shell. Cross-block references silently expand
to empty string, corrupting paths, conditionals, and spawn prompts without any
error message.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_bash_persistence.py" [files...]
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_bash_persistence.py" --scan-dir plugins/

Output (stdout):
    One finding line per violation with prefix "C41-CRITICAL:", or a single pass line.

Exit codes:
    0   all files pass
    1   one or more violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Variables that persist across bash calls (env vars, skill runner context, common loop vars)
_SKIP_VARS: frozenset[str] = frozenset(
    {
        "HOME",
        "PATH",
        "USER",
        "SHELL",
        "TMPDIR",
        "PWD",
        "OLDPWD",
        "IFS",
        "PIPESTATUS",
        "BASH_VERSION",
        "SECONDS",
        "RANDOM",
        "UID",
        "EUID",
        "ARGUMENTS",
        "CLAUDE_PLUGIN_ROOT",
        "LANG",
        "LC_ALL",
        "TERM",
        "LOCAL_MODE",
        "AUDIT_TPL",
        "RUN_DIR",
        "REPORT_DIR",
        "SKIP_GATE",
        # common short loop/counter vars unlikely to cause real persistence bugs
        "f",
        "i",
        "j",
        "k",
        "n",
        "b",
        "s",
        "v",
        "c",
        "dir",
        "file",
        "found",
        "var",
        "out",
        "err",
        "rc",
        "ret",
        "line",
        "name",
        "key",
        "val",
        "base",
        "dest",
        "src",
        "arg",
    }
)

_BASH_OPEN = re.compile(r"^```bash\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")
_ASSIGN = re.compile(r"^[ \t]*(?:export[ \t]+|local[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=")
_REF = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]+)\}?")


def extract_bash_blocks(text: str) -> list[str]:
    """Return bash fenced block bodies in document order.

    Args:
        text: full content of a SKILL.md file.

    Returns:
        List of block body strings, one per ```bash...``` fence.

    Examples:
        >>> extract_bash_blocks("```bash\\nFOO=1\\n```\\n")
        ['FOO=1\\n']
        >>> extract_bash_blocks("no fences here")
        []
        >>> len(extract_bash_blocks("```bash\\nA=1\\n```\\n```bash\\nB=2\\n```\\n"))
        2
    """
    blocks: list[str] = []
    buf: list[str] = []
    in_bash = False
    for line in text.splitlines(keepends=True):
        if not in_bash and _BASH_OPEN.match(line):
            in_bash = True
            buf = []
        elif in_bash and _FENCE_CLOSE.match(line):
            in_bash = False
            blocks.append("".join(buf))
        elif in_bash:
            buf.append(line)
    return blocks


def assigned_vars(block: str) -> frozenset[str]:
    """Return variable names assigned in a bash block.

    Only matches bare assignments at the start of a line (after optional
    whitespace and optional export/local prefix). Comment lines are skipped.

    Args:
        block: bash block body text.

    Returns:
        Frozenset of assigned variable names (no $ prefix).

    Examples:
        >>> sorted(assigned_vars("FOO=1\\nBAR=$(cmd)\\n  BAZ=x\\n"))
        ['BAR', 'BAZ', 'FOO']
        >>> assigned_vars("# FOO=1\\n")
        frozenset()
        >>> sorted(assigned_vars("export QUX=y\\nlocal QUZ=z\\n"))
        ['QUX', 'QUZ']
    """
    names: set[str] = set()
    for line in block.splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = _ASSIGN.match(line)
        if m:
            names.add(m.group(1))
    return frozenset(names)


def referenced_vars(block: str) -> frozenset[str]:
    """Return variable names referenced via $VAR or ${VAR} in a bash block.

    Filters out known-safe env vars, single-char names, and pure-digit refs.

    Args:
        block: bash block body text.

    Returns:
        Frozenset of referenced variable names (no $ prefix).

    Examples:
        >>> sorted(referenced_vars("echo $FOO ${BAR_BAZ}\\n"))
        ['BAR_BAZ', 'FOO']
        >>> referenced_vars("echo $HOME $1\\n")
        frozenset()
        >>> referenced_vars("")
        frozenset()
    """
    names: set[str] = set()
    for m in _REF.finditer(block):
        v = m.group(1)
        if v in _SKIP_VARS or len(v) <= 1:
            continue
        names.add(v)
    return frozenset(names)


def check_file(path: Path) -> list[str]:
    """Return C41 violation strings for one SKILL.md file.

    Args:
        path: path to SKILL.md to analyse.

    Returns:
        List of finding strings; empty list = no violations.

    Examples:
        >>> import os, tempfile
        >>> content = "```bash\\nFOO=bar\\n```\\n```bash\\necho $FOO\\n```\\n"
        >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        ...     _ = f.write(content); name = f.name
        >>> findings = check_file(Path(name)); os.unlink(name)
        >>> any("C41" in x and "FOO" in x for x in findings)
        True
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    blocks = extract_bash_blocks(text)
    if len(blocks) < 2:
        return []
    assigns = [assigned_vars(b) for b in blocks]
    findings: list[str] = []
    for i in range(1, len(blocks)):
        refs = referenced_vars(blocks[i])
        for var in sorted(refs):
            if var in assigns[i]:
                continue
            for j in range(i):
                if var in assigns[j]:
                    findings.append(
                        f"C41-CRITICAL: {path}: ${var} assigned in bash block {j + 1},"
                        f" referenced in block {i + 1} — variable lost across Bash calls"
                    )
                    break
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point — scan files and print findings.

    Args:
        argv: argument list (defaults to sys.argv[1:]).

    Returns:
        Exit code: 0 = all pass, 1 = violations found.
    """
    parser = argparse.ArgumentParser(description="Detect shell variable persistence issues in SKILL.md files")
    parser.add_argument("files", nargs="*", help="SKILL.md files to check")
    parser.add_argument("--scan-dir", metavar="DIR", help="recursively scan DIR for SKILL.md files")
    parser.add_argument("--timeout", type=int, help="ignored — accepted for CLI compatibility")
    args = parser.parse_args(argv)

    paths: list[Path] = []
    if args.scan_dir:
        paths.extend(Path(args.scan_dir).rglob("*/skills/*/SKILL.md"))
    paths.extend(Path(f) for f in args.files)
    if not paths:
        paths.extend(Path(".").rglob("*/skills/*/SKILL.md"))

    all_findings: list[str] = []
    for p in sorted(set(paths)):
        all_findings.extend(check_file(p))

    if all_findings:
        print("\n".join(all_findings))
        return 1
    print("✓: Check 41 — no cross-bash-call variable persistence issues found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
