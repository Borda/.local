#!/usr/bin/env python3
"""dev_parse_args.py — parse develop-skill flags from $ARGUMENTS.

Two calling conventions:

1. **Spec-driven (legacy)** — caller declares flag specs explicitly; script prints
   shell-eval-safe ``KEY=VALUE`` lines on stdout, intended for ``eval "$(...)"``.

   Example::

       eval "$(python dev_parse_args.py "$ARGUMENTS" \\
           --neg-bool no-challenge CHALLENGE_ENABLED true \\
           --bool semble SEMBLE_ENABLED false \\
           --codemap CODEMAP_RAW auto)"

2. **Skill-driven with file writes** — caller passes ``--skill <name>
   --write-files <arguments>``; script looks up the per-skill flag set
   internally and writes each resulting value to a per-flag temp file
   under ``${TMPDIR:-/tmp}/`` (no ``eval`` required by the caller).

   Example::

       python dev_parse_args.py --skill feature --write-files "$ARGUMENTS"
       # Now read: $(cat ${TMPDIR:-/tmp}/dev-feature-codemap)

   Two files are written for every variable: a *per-skill* path
   (``dev-<skill>-<flag>``) for the modern convention and a *legacy*
   path (e.g. ``dev-team-mode``) so existing downstream blocks that
   read the legacy names keep working without a flag-day rename.

Flag spec types (each occupies 3 positional tokens after the type keyword):

    --bool FLAG VAR DEFAULT     --FLAG present → VAR=true;  absent → VAR=DEFAULT
    --neg-bool FLAG VAR DEFAULT --FLAG present → VAR=false; absent → VAR=DEFAULT
    --codemap VAR DEFAULT       --codemap/--no-codemap → strict/off/auto with
                                double-condition guard (--no-codemap wins on conflict)
    --int FLAG VAR DEFAULT      --FLAG N or --FLAG=N → VAR=N (integer)
    --str FLAG VAR DEFAULT      --FLAG VAL or --FLAG=VAL → VAR=VAL (string)

Exit codes:
    0 — success
    1 — malformed spec, unknown skill, or missing ``--write-files`` argument
    2 — --int flag received a non-integer value
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------


SpecType = Literal["bool", "neg-bool", "codemap", "int", "str"]

_TYPE_ARITIES: dict[str, int] = {
    "--bool": 3,
    "--neg-bool": 3,
    "--codemap": 2,  # VAR DEFAULT (no FLAG — always --codemap/--no-codemap)
    "--int": 3,
    "--str": 3,
}


@dataclass
class FlagSpec:
    """Parsed declaration of a single flag (or flag pair for codemap)."""

    kind: SpecType
    flag: str  # e.g. "no-challenge"; empty string for codemap kind
    var: str  # shell variable name to emit
    default: str  # string representation of default value


def parse_specs(tokens: list[str]) -> list[FlagSpec]:
    """Parse the flag-spec token list into FlagSpec objects.

    Args:
        tokens: everything after the ARGUMENTS string on the command line.

    Returns:
        List of FlagSpec instances in declaration order.

    Raises:
        SystemExit(1): on malformed spec (wrong token count).

    Examples:
        >>> parse_specs(['--bool', 'semble', 'SEMBLE_ENABLED', 'false'])
        [FlagSpec(kind='bool', flag='semble', var='SEMBLE_ENABLED', default='false')]
        >>> parse_specs(['--codemap', 'CODEMAP_RAW', 'auto'])
        [FlagSpec(kind='codemap', flag='', var='CODEMAP_RAW', default='auto')]
    """
    specs: list[FlagSpec] = []
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok not in _TYPE_ARITIES:
            print(f"dev_parse_args: unknown spec keyword '{tok}'", file=sys.stderr)
            sys.exit(1)
        arity = _TYPE_ARITIES[tok]
        rest = tokens[idx + 1 : idx + 1 + arity]
        if len(rest) < arity:
            print(
                f"dev_parse_args: '{tok}' needs {arity} tokens, got {len(rest)}",
                file=sys.stderr,
            )
            sys.exit(1)
        kind: SpecType = tok.lstrip("-")  # type: ignore[assignment]
        if kind == "codemap":
            var, default = rest
            specs.append(FlagSpec(kind=kind, flag="", var=var, default=default))
        else:
            flag, var, default = rest
            specs.append(FlagSpec(kind=kind, flag=flag, var=var, default=default))
        idx += 1 + arity
    return specs


# ---------------------------------------------------------------------------
# Flag extraction
# ---------------------------------------------------------------------------


def _shell_quote(value: str) -> str:
    """Return a shell-safe single-quoted representation of value.

    Examples:
        >>> _shell_quote("hello world")
        "'hello world'"
        >>> _shell_quote("it's")
        "'it'\\\\''s'"
        >>> _shell_quote("")
        "''"
    """
    return "'" + value.replace("'", "'\\''") + "'"


def _extract_value_flag(flag: str, args: str) -> tuple[str | None, str]:
    """Extract --flag VALUE or --flag=VALUE from args.

    Returns (value_or_None, args_with_flag_and_value_stripped).

    Examples:
        >>> _extract_value_flag("max-depth", "--max-depth 5 target.py")
        ('5', 'target.py')
        >>> _extract_value_flag("plan", "--plan=path/to/file.md fix issue")
        ('path/to/file.md', 'fix issue')
        >>> _extract_value_flag("plan", "fix issue")
        (None, 'fix issue')
    """
    # --flag=VALUE form. Require a full flag-token match so --planets does not
    # satisfy --plan, and preserve the historical non-whitespace value contract.
    eq_pattern = re.compile(r"(?<!\S)--" + re.escape(flag) + r"=(\S+)")
    m = eq_pattern.search(args)
    if m:
        return m.group(1), eq_pattern.sub("", args).strip()

    # --flag VALUE form (value = next non-flag, non-whitespace token).
    space_pattern = re.compile(r"(?<!\S)--" + re.escape(flag) + r"\s+(?!--)(\S+)")
    m = space_pattern.search(args)
    if m:
        full_match = m.group(0)
        return m.group(1), args.replace(full_match, "", 1).strip()

    return None, args


def extract_flags(arguments: str, specs: list[FlagSpec]) -> tuple[dict[str, str], str]:
    """Extract all declared flags from arguments string.

    Args:
        arguments: raw $ARGUMENTS string.
        specs: parsed flag specs.

    Returns:
        Tuple of (var_to_value dict, clean_args string).

    Examples:
        >>> specs = parse_specs(['--bool', 'semble', 'SEMBLE_ENABLED', 'false'])
        >>> extract_flags('--semble do the thing', specs)
        ({'SEMBLE_ENABLED': 'true'}, 'do the thing')
        >>> extract_flags('do the thing', specs)
        ({'SEMBLE_ENABLED': 'false'}, 'do the thing')
    """
    result: dict[str, str] = {}
    clean = arguments

    for spec in specs:
        if spec.kind == "bool":
            token = f"--{spec.flag}"
            token_pattern = re.compile(r"(?<!\S)" + re.escape(token) + r"(?![A-Za-z0-9_-])")
            if token_pattern.search(clean):
                result[spec.var] = "true"
                clean = token_pattern.sub("", clean)
            else:
                result[spec.var] = spec.default

        elif spec.kind == "neg-bool":
            token = f"--{spec.flag}"
            token_pattern = re.compile(r"(?<!\S)" + re.escape(token) + r"(?![A-Za-z0-9_-])")
            if token_pattern.search(clean):
                result[spec.var] = "false"
                clean = token_pattern.sub("", clean)
            else:
                result[spec.var] = spec.default

        elif spec.kind == "codemap":
            # Double-condition guard: --no-codemap wins; --codemap only sets strict
            # when --no-codemap absent.
            no_pattern = re.compile(r"(?<!\S)--no-codemap(?![A-Za-z0-9_-])")
            yes_pattern = re.compile(r"(?<!\S)--codemap(?![A-Za-z0-9_-])")
            has_no = no_pattern.search(clean) is not None
            has_yes = yes_pattern.search(clean) is not None
            if has_no:
                result[spec.var] = "off"
                clean = no_pattern.sub("", clean)
                clean = yes_pattern.sub("", clean)
            elif has_yes:
                result[spec.var] = "strict"
                clean = yes_pattern.sub("", clean)
            else:
                result[spec.var] = spec.default

        elif spec.kind == "int":
            val, clean = _extract_value_flag(spec.flag, clean)
            if val is not None:
                try:
                    int(val)
                except ValueError:
                    print(
                        f"dev_parse_args: --{spec.flag} expects integer, got '{val}'",
                        file=sys.stderr,
                    )
                    sys.exit(2)
                result[spec.var] = val
            else:
                result[spec.var] = spec.default

        elif spec.kind == "str":
            val, clean = _extract_value_flag(spec.flag, clean)
            result[spec.var] = val if val is not None else spec.default

    # Normalise whitespace in clean args
    clean = " ".join(clean.split())
    return result, clean


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(arguments: str, spec_tokens: list[str]) -> str:
    """Parse flags and return the eval-able shell assignment block.

    Args:
        arguments: raw $ARGUMENTS string.
        spec_tokens: everything after the arguments string on the CLI.

    Returns:
        Multi-line string of shell KEY=VALUE assignments ending with CLEAN_ARGS.

    Examples:
        >>> out = run('--semble fix auth.py', ['--bool', 'semble', 'SEMBLE_ENABLED', 'false'])
        >>> "SEMBLE_ENABLED='true'" in out
        True
        >>> "CLEAN_ARGS='fix auth.py'" in out
        True
    """
    specs = parse_specs(spec_tokens)
    values, clean_args = extract_flags(arguments, specs)
    lines = [f"{var}={_shell_quote(val)}" for var, val in values.items()]
    lines.append(f"CLEAN_ARGS={_shell_quote(clean_args)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill registry (used by --skill <name> --write-files)
# ---------------------------------------------------------------------------


def _spec(kind: SpecType, flag: str, var: str, default: str) -> FlagSpec:
    """Tiny helper so the registry table below stays compact and readable."""
    return FlagSpec(kind=kind, flag=flag, var=var, default=default)


# Per-skill flag declarations. Keep in sync with each skill's SKILL.md.
# Each entry: (FlagSpec, legacy_filename_or_None).
#
# ``legacy_filename`` preserves the original temp-file paths the existing
# downstream Bash() blocks read (e.g. ``dev-team-mode``, ``dev-upstream``),
# so the surgical replacement of the eval block in each SKILL.md does not
# need to touch any later block.  ``None`` means no legacy path was written
# before (e.g. a newly registered flag).
SKILL_SPECS: dict[str, list[tuple[FlagSpec, str | None]]] = {
    "feature": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-challenge-enabled"),
        (_spec("bool", "challenge", "CHALLENGE_FORCED", "false"), "dev-challenge-forced"),
        (_spec("bool", "semble", "SEMBLE_ENABLED", "false"), "dev-semble-enabled"),
        (_spec("bool", "team", "TEAM_MODE", "false"), "dev-team-mode"),
        (_spec("bool", "accept-no-plan", "ACCEPT_NO_PLAN", "false"), "dev-accept-no-plan"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-codemap-raw"),
        (_spec("str", "repo", "REPO_NAME", ""), "dev-upstream"),
    ],
    "fix": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-challenge-enabled"),
        (_spec("bool", "challenge", "CHALLENGE_FORCED", "false"), "dev-challenge-forced"),
        (_spec("bool", "accept-no-plan", "ACCEPT_NO_PLAN", "false"), "dev-accept-no-plan"),
        (_spec("bool", "semble", "SEMBLE_ENABLED", "false"), "dev-semble-enabled"),
        (_spec("bool", "team", "TEAM_MODE", "false"), "dev-team-mode"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-codemap-raw"),
        (_spec("str", "repo", "REPO_NAME", ""), "dev-upstream"),
    ],
    "debug": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-challenge-enabled"),
        (_spec("bool", "challenge", "CHALLENGE_FORCED", "false"), "dev-challenge-forced"),
        (_spec("bool", "team", "TEAM_MODE", "false"), "dev-team-mode"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-codemap-raw"),
        (_spec("str", "ci-run", "CI_RUN_ID", ""), "dev-ci-run-id"),
        (_spec("str", "repo", "REPO_NAME", ""), "dev-upstream"),
    ],
    "refactor": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-challenge-enabled"),
        (_spec("bool", "challenge", "CHALLENGE_FORCED", "false"), "dev-challenge-forced"),
        (_spec("bool", "semble", "SEMBLE_ENABLED", "false"), "dev-semble-enabled"),
        (_spec("bool", "team", "TEAM_MODE", "false"), "dev-team-mode"),
        (_spec("bool", "accept-no-plan", "ACCEPT_NO_PLAN", "false"), "dev-accept-no-plan"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-codemap-raw"),
        (_spec("str", "repo", "REPO_NAME", ""), "dev-upstream"),
    ],
    "plan": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-challenge-enabled"),
        (_spec("bool", "semble", "SEMBLE_ENABLED", "false"), "dev-semble-enabled"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-codemap-raw"),
        (_spec("int", "max-depth", "MAX_DEPTH", "3"), None),
    ],
    "review": [
        (_spec("neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"), "dev-review-challenge-enabled"),
        (_spec("bool", "challenge", "CHALLENGE_FORCED", "false"), "dev-review-challenge-forced"),
        (_spec("bool", "semble", "SEMBLE_ENABLED", "false"), "dev-review-semble-enabled"),
        (_spec("codemap", "", "CODEMAP_RAW", "auto"), "dev-review-codemap-enabled"),
    ],
}


def _per_skill_filename(skill: str, spec: FlagSpec) -> str:
    """Compose the per-skill temp filename for a given spec.

    For codemap (no ``flag`` token) the key is the literal string ``codemap``.

    Examples:
        >>> _per_skill_filename("feature", FlagSpec(kind="bool", flag="team", var="TEAM_MODE", default="false"))
        'dev-feature-team'
        >>> _per_skill_filename("debug", FlagSpec(kind="codemap", flag="", var="CODEMAP_RAW", default="auto"))
        'dev-debug-codemap'
    """
    key = spec.flag or ("codemap" if spec.kind == "codemap" else spec.var.lower())
    return f"dev-{skill}-{key}"


def _tmp_dir() -> Path:
    """Return the directory temp files are written to (mirrors shell ``${TMPDIR:-/tmp}``)."""
    return Path(os.environ.get("TMPDIR", "/tmp"))


def write_skill_files(skill: str, arguments: str, tmp_dir: Path | None = None) -> dict[str, str]:
    """Parse arguments using the registered ``skill`` specs and persist values to temp files.

    Writes two files per variable when a legacy path is registered:

    * Per-skill: ``${TMPDIR}/dev-<skill>-<flag>`` — modern convention used by callers
      that read flags back with explicit per-skill paths.
    * Legacy: ``${TMPDIR}/<legacy-name>`` — preserves backward compatibility with
      downstream Bash() blocks that read shared paths like ``dev-team-mode``.

    Args:
        skill: registered skill name (key of ``SKILL_SPECS``).
        arguments: raw ``$ARGUMENTS`` string.
        tmp_dir: override for the temp directory (defaults to ``${TMPDIR:-/tmp}``).

    Returns:
        Dict mapping each declared shell variable name to its resolved string value.

    Raises:
        SystemExit(1): if ``skill`` is not a registered key.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as d:
        ...     vals = write_skill_files("feature", "--semble fix auth.py", tmp_dir=Path(d))
        ...     vals["SEMBLE_ENABLED"]
        ...     (Path(d) / "dev-feature-semble").read_text()
        ...     (Path(d) / "dev-semble-enabled").read_text()
        'true'
        'true'
        'true'
    """
    if skill not in SKILL_SPECS:
        known = ", ".join(sorted(SKILL_SPECS))
        print(
            f"dev_parse_args: unknown skill '{skill}' (registered: {known})",
            file=sys.stderr,
        )
        sys.exit(1)

    target_dir = tmp_dir if tmp_dir is not None else _tmp_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    entries = SKILL_SPECS[skill]
    specs = [spec for spec, _ in entries]
    values, _clean = extract_flags(arguments, specs)

    for spec, legacy in entries:
        value = values[spec.var]
        (target_dir / _per_skill_filename(skill, spec)).write_text(value)
        if legacy is not None:
            (target_dir / legacy).write_text(value)
    # Write CLEAN_ARGS (flags stripped) to a per-skill file so callers avoid eval
    (target_dir / f"dev-{skill}-clean-args").write_text(_clean)
    return values


def main() -> None:
    """CLI entry point.

    Two invocation forms:

    * ``dev_parse_args.py ARGUMENTS [SPEC...]`` — print eval-able shell block on stdout
      (legacy form used by ``eval "$(...)"`` callers).
    * ``dev_parse_args.py --skill <name> --write-files ARGUMENTS`` — parse using the
      registered skill specs and write each value to a temp file under ``${TMPDIR:-/tmp}``.
    """
    argv = sys.argv[1:]
    if not argv:
        print(
            "usage:\n"
            "  dev_parse_args.py ARGUMENTS [SPEC...]\n"
            "  dev_parse_args.py --skill <name> --write-files ARGUMENTS",
            file=sys.stderr,
        )
        sys.exit(1)

    if "--skill" in argv:
        # Skill-driven write-files invocation
        try:
            skill_idx = argv.index("--skill")
            skill_name = argv[skill_idx + 1]
        except (ValueError, IndexError):
            print("dev_parse_args: --skill requires a name argument", file=sys.stderr)
            sys.exit(1)
        if "--write-files" not in argv:
            print(
                "dev_parse_args: --skill requires --write-files (only mode supported)",
                file=sys.stderr,
            )
            sys.exit(1)
        # Remaining positional after stripping both flag pairs is the ARGUMENTS string
        remaining = [
            tok for i, tok in enumerate(argv) if i not in {skill_idx, skill_idx + 1} and tok != "--write-files"
        ]
        if not remaining:
            print("dev_parse_args: --skill mode needs the ARGUMENTS string", file=sys.stderr)
            sys.exit(1)
        arguments = remaining[0]
        write_skill_files(skill_name, arguments)
        return

    # Legacy spec-driven invocation
    arguments = argv[0]
    spec_tokens = argv[1:]
    print(run(arguments, spec_tokens))


if __name__ == "__main__":
    main()
