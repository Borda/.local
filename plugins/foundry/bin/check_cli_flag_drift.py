#!/usr/bin/env python
"""check_cli_flag_drift.py — detect SKILL.md flags that drifted from a bin/ script's argparse.

For every ``bin/*.py`` script that defines an ``argparse`` parser, extract the exact
set of option strings it registers (via static AST parsing — the target script is
never imported or executed). Then scan every ``skills/*/SKILL.md`` for a literal
``python .../bin/<script>.py`` invocation and collect the ``--long-flag`` tokens on
that same shell command (following ``\`` line-continuations, stopping at a
pipe/``;``/``&&``/``$(`` boundary). A documented ``--long-flag`` that the script's
argparse does NOT define is a finding: the doc drifted (flag renamed, removed, or
typo'd). This is a flag-ACCURACY check, not an enumeration-completeness one — a real
flag the docs never mention is fine.

Only ``--long-flag`` tokens are checked. Single-dash short options (``-f``, ``-z``)
are ignored because they collide with bash test operators and other shell short flags
that legitimately share a script's command line.

Only literal invocation syntax anchors a flag to a script — a bare basename mention in
prose (e.g. a backtick reference) contributes nothing, and a skill's own CLI flags
(documented in ``argument-hint``, prose bullets, or flag tables, never inside a
``python .../bin/<script>.py`` command) are structurally excluded.

Scripts with no ``add_argument`` calls (not yet argparse-converted, or module-only
helpers) are skipped. Underscore-prefixed scripts are skipped (private modules).

Usage:
    check_cli_flag_drift.py [--plugins-dir DIR]

Output (stdout):
    One finding line per drifted flag + hint line, or a single pass line.

Exit codes:
    0 — every documented flag matches a real argparse flag
    1 — one or more documented flags drifted from the script's argparse
    2 — bad/missing required argument (argparse default) or invalid --plugins-dir
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Guard against pathological inputs that would exhaust heap memory when read in one
# shot. 10 MB is well above any realistic Markdown / Python source file.
_MAX_FILE_SIZE = 10 * 1024 * 1024
# A --long-flag token within a command. Single-dash short options (-f, -z, -n) are
# deliberately NOT matched: they collide with bash test operators ([ -z "$X" ]) and
# other shell short flags that legitimately appear on a script's command line, so
# treating them as documented CLI flags produces false positives. Drift on a renamed
# short option is rare and not worth that noise; long flags carry the real signal.
_FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*\b")
# Shell boundaries that end the command owning the flags — a piped/chained command
# (grep, printf, git) past one of these contributes its own flags, not the script's.
_CMD_BOUNDARY_RE = re.compile(r"\||;|&&|\|\||\$\(|`|>&|2>")
_DEFAULT_PLUGINS_DIR = "plugins"


@dataclass
class DriftFinding:
    """A SKILL.md flag near a script basename that the script's argparse does not define."""

    skill_md: str
    script: str
    flag: str


def _accepts_passthrough(node: ast.Call) -> bool:
    """Return True if an ``add_argument`` call declares a flag-swallowing positional.

    A ``nargs=argparse.REMAINDER`` or ``nargs="..."`` positional captures arbitrary
    trailing tokens including ``--flags``, so any flag documented for such a script is
    validly handled and must not be reported as drift.

    Args:
        node: An ``add_argument`` Call node.

    Returns:
        True when the call sets ``nargs`` to REMAINDER / ``"..."``.
    """
    for kw in node.keywords:
        if kw.arg != "nargs":
            continue
        val = kw.value
        if isinstance(val, ast.Attribute) and val.attr == "REMAINDER":
            return True
        if isinstance(val, ast.Constant) and val.value == "...":
            return True
    return False


def extract_argparse_flags(source: str) -> set[str] | None:
    """Return the set of flag strings registered by ``add_argument`` calls, or None.

    Statically walks the AST for ``*.add_argument("--foo", "-f", ...)`` calls and
    collects every string literal argument that starts with ``-`` (the option strings).
    Returns None when the source has no ``add_argument`` call at all — signalling the
    script is not argparse-based and should be skipped, distinct from an empty set.
    Also returns None when a ``nargs=argparse.REMAINDER`` passthrough positional is
    present, since such a script accepts arbitrary trailing flags and cannot drift.

    Args:
        source: Python source text of a bin/ script.

    Returns:
        Set of registered flag strings (e.g. ``{"--foo", "-f"}``), or None if the
        script registers no arguments or accepts arbitrary passthrough flags.

    Examples:
        >>> src = 'p.add_argument("--foo"); p.add_argument("-b", "--bar")'
        >>> sorted(extract_argparse_flags(src))
        ['--bar', '--foo', '-b']
        >>> extract_argparse_flags("x = 1") is None
        True
        >>> extract_argparse_flags('p.add_argument("x", nargs=argparse.REMAINDER)') is None
        True
        >>> sorted(extract_argparse_flags('p.add_argument("pos"); p.add_argument("--f")'))
        ['--f']
    """
    tree = ast.parse(source)
    flags: set[str] = set()
    saw_add_argument = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument":
            continue
        saw_add_argument = True
        if _accepts_passthrough(node):
            return None
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("-"):
                flags.add(arg.value)
    return flags if saw_add_argument else None


def iter_argparse_scripts(plugins_dir: Path) -> dict[str, set[str]]:
    """Map each argparse-based bin/ script basename to its registered flag set.

    Discovers ``plugins/*/bin/*.py`` scripts, skipping underscore-prefixed private
    modules. Each script is read and AST-parsed (never imported/executed). Scripts
    that register no argparse arguments are omitted from the result.

    Args:
        plugins_dir: Root directory containing plugin subdirectories.

    Returns:
        Mapping of ``script_basename -> {flags}`` for every argparse-based script.
        Basenames are stored without extension collision handling — duplicates across
        plugins merge their flag sets (a doc flag matching any is accepted).

    No doctest — filesystem-dependent; covered by pytest with tmp_path.
    """
    scripts: dict[str, set[str]] = {}
    for plugin_dir in sorted(plugins_dir.iterdir()):
        bin_dir = plugin_dir / "bin"
        if not (plugin_dir.is_dir() and bin_dir.is_dir()):
            continue
        for script in sorted(bin_dir.iterdir()):
            if script.suffix != ".py" or script.name.startswith("_") or not script.is_file():
                continue
            if script.stat().st_size > _MAX_FILE_SIZE:
                continue
            try:
                flags = extract_argparse_flags(script.read_text(encoding="utf-8", errors="replace"))
            except (OSError, SyntaxError):
                continue
            if flags is not None:
                scripts.setdefault(script.name, set()).update(flags)
    return scripts


def _invocation_pattern(script: str) -> re.Pattern[str]:
    """Return a regex matching a literal ``python .../bin/<script>`` invocation.

    Anchors on the ``bin/`` path segment so a bare backtick prose mention (no path
    prefix) never matches — only an actual command invocation does.

    Args:
        script: Script basename with ``.py`` (e.g. ``resolve_preflight.py``).

    Returns:
        Compiled pattern that matches at the end of the invocation token.

    Examples:
        >>> p = _invocation_pattern("foo.py")
        >>> bool(p.search('python "${CLAUDE_PLUGIN_ROOT}/bin/foo.py" --x'))
        True
        >>> bool(p.search("`foo.py` delegates to bar"))
        False
        >>> bool(p.search("python bin/barfoo.py --x"))
        False
    """
    return re.compile(rf"/bin/{re.escape(script)}(?![\w.-])")


def command_scope(lines: list[str], start_idx: int, match_end: int) -> str:
    """Return the shell-command text owning the flags after an invocation match.

    Starts at ``match_end`` on line ``start_idx`` and follows ``\\`` line-continuations
    onto subsequent lines. Truncates at the first shell boundary (pipe, ``;``, ``&&``,
    ``$(``, backtick, redirect) so flags from a chained command are not captured.

    Args:
        lines: All lines of the SKILL.md.
        start_idx: Index of the line where the invocation matched.
        match_end: Character offset just past the matched invocation token.

    Returns:
        The joined command text from the invocation to its shell boundary or end.

    Examples:
        >>> command_scope(['x --a \\\\', '  --b | grep --c'], 0, 1)
        ' --a    --b '
        >>> command_scope(['x --a', 'unrelated --b'], 0, 1)
        ' --a'
    """
    segments: list[str] = []
    idx = start_idx
    tail = lines[idx][match_end:]
    while True:
        continued = tail.rstrip().endswith("\\")
        body = tail.rstrip()[:-1] if continued else tail
        boundary = _CMD_BOUNDARY_RE.search(body)
        if boundary:
            segments.append(body[: boundary.start()])
            break
        segments.append(body)
        if not continued or idx + 1 >= len(lines):
            break
        idx += 1
        tail = lines[idx]
    return " ".join(segments) if len(segments) > 1 else segments[0]


def find_drift(plugins_dir: Path) -> list[DriftFinding]:
    """Return every SKILL.md flag on a script invocation that its argparse lacks.

    Args:
        plugins_dir: Root directory containing plugin subdirectories.

    Returns:
        List of DriftFinding objects (empty when all documented flags are accurate).

    No doctest — filesystem-dependent; covered by pytest with tmp_path.
    """
    scripts = iter_argparse_scripts(plugins_dir)
    patterns = {name: _invocation_pattern(name) for name in scripts}
    findings: list[DriftFinding] = []
    for skill_md in sorted(plugins_dir.glob("*/skills/*/SKILL.md")):
        try:
            lines = skill_md.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        findings.extend(_scan_skill_lines(lines, skill_md.as_posix(), scripts, patterns))
    return findings


def _scan_skill_lines(
    lines: list[str],
    skill_md: str,
    scripts: dict[str, set[str]],
    patterns: dict[str, re.Pattern[str]],
) -> list[DriftFinding]:
    """Scan one SKILL.md for invocation flags a script's argparse does not define.

    Args:
        lines: The SKILL.md content split into lines.
        skill_md: POSIX path of the SKILL.md (for finding attribution).
        scripts: Mapping of script basename to its real flag set.
        patterns: Mapping of script basename to its precompiled invocation regex.

    Returns:
        List of DriftFinding for this file (deduped per script+flag pair).

    No doctest — multi-arg orchestration; covered by pytest via find_drift.
    """
    findings: list[DriftFinding] = []
    seen: set[tuple[str, str]] = set()
    for idx, line in enumerate(lines):
        for name, pattern in patterns.items():
            match = pattern.search(line)
            if not match:
                continue
            command = command_scope(lines, idx, match.end())
            for flag in _FLAG_RE.findall(command):
                if flag in scripts[name] or (name, flag) in seen:
                    continue
                seen.add((name, flag))
                findings.append(DriftFinding(skill_md=skill_md, script=name, flag=flag))
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code.

    Args:
        argv: Optional argv override (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` when clean, ``1`` when drifted flags exist; argparse exits ``2`` on bad
        args and this returns ``2`` when --plugins-dir escapes or is not a directory.

    No doctest — argv/filesystem-dependent; covered by pytest with tmp_path.
    """
    parser = argparse.ArgumentParser(
        prog="check_cli_flag_drift.py",
        description="Detect SKILL.md flags that drifted from a bin/ script's argparse.",
    )
    parser.add_argument(
        "--plugins-dir",
        default=_DEFAULT_PLUGINS_DIR,
        metavar="DIR",
        help=f"Root dir containing plugin subdirs (default: {_DEFAULT_PLUGINS_DIR}/).",
    )
    args = parser.parse_args(argv)

    # SEC-M1: normalise --plugins-dir so ``..`` cannot escape the project tree (CWE-22 guard).
    plugins_dir = Path(args.plugins_dir).resolve()
    project_root = Path.cwd().resolve()
    try:
        plugins_dir.relative_to(project_root)
    except ValueError:
        print(f"! SECURITY: --plugins-dir must be within project root: {args.plugins_dir}", file=sys.stderr)
        return 2
    if not plugins_dir.is_dir():
        print(f"check_cli_flag_drift: {args.plugins_dir!r} is not a directory", file=sys.stderr)
        return 2

    findings = find_drift(plugins_dir)
    if findings:
        for f in findings:
            print(
                f"⚠ 42: {f.skill_md}"
                f" — documents {f.flag} near {f.script}, which its argparse does not define"
                f"\n  hint: fix the flag name in SKILL.md, or add {f.flag} to {f.script}'s parser"
            )
        return 1

    print("✓: Check 42 — all documented bin/ flags match their script's argparse")
    return 0


if __name__ == "__main__":
    sys.exit(main())
