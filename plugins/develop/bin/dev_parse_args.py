#!/usr/bin/env python3
"""dev_parse_args.py — parse develop-skill flags from $ARGUMENTS.

Outputs shell-eval-safe KEY=VALUE lines.  CLEAN_ARGS is always emitted last —
$ARGUMENTS with all recognised flag tokens stripped and whitespace normalised.

Usage (inside SKILL.md bash block):

    eval "$(python "${CLAUDE_PLUGIN_ROOT:-plugins/develop}/bin/dev_parse_args.py" \\
        "$ARGUMENTS" \\
        --neg-bool no-challenge CHALLENGE_ENABLED true \\
        --bool semble SEMBLE_ENABLED false \\
        --codemap CODEMAP_RAW auto \\
        --int max-depth MAX_DEPTH 3 \\
        --str plan PLAN_FILE '' \\
    )"

Flag spec types (each occupies 3 positional tokens after the type keyword):

    --bool FLAG VAR DEFAULT     --FLAG present → VAR=true;  absent → VAR=DEFAULT
    --neg-bool FLAG VAR DEFAULT --FLAG present → VAR=false; absent → VAR=DEFAULT
    --codemap VAR DEFAULT       --codemap/--no-codemap → strict/off/auto with
                                double-condition guard (--no-codemap wins on conflict)
    --int FLAG VAR DEFAULT      --FLAG N or --FLAG=N → VAR=N (integer)
    --str FLAG VAR DEFAULT      --FLAG VAL or --FLAG=VAL → VAR=VAL (string)

Output format: one KEY=VALUE line per declared variable (shell-safe single-quoted
values where needed), then CLEAN_ARGS='...' on the final line.

Exit codes:
    0 — success
    1 — malformed spec (wrong number of tokens after type keyword)
    2 — --int flag received a non-integer value
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
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
        "'it'\\''s'"
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
    # --flag=VALUE form
    eq_pattern = re.compile(r"--" + re.escape(flag) + r"=(\S+)")
    m = eq_pattern.search(args)
    if m:
        return m.group(1), eq_pattern.sub("", args).strip()

    # --flag VALUE form (value = next non-whitespace token after the flag)
    space_pattern = re.compile(r"--" + re.escape(flag) + r"\s+(\S+)")
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
            if token in clean:
                result[spec.var] = "true"
                clean = clean.replace(token, "")
            else:
                result[spec.var] = spec.default

        elif spec.kind == "neg-bool":
            token = f"--{spec.flag}"
            if token in clean:
                result[spec.var] = "false"
                clean = clean.replace(token, "")
            else:
                result[spec.var] = spec.default

        elif spec.kind == "codemap":
            # Double-condition guard: --no-codemap wins; --codemap only sets strict
            # when --no-codemap absent.
            has_no = "--no-codemap" in clean
            has_yes = "--codemap" in clean
            if has_no:
                result[spec.var] = "off"
                clean = clean.replace("--no-codemap", "")
                clean = clean.replace("--codemap", "")
            elif has_yes:
                result[spec.var] = "strict"
                clean = clean.replace("--codemap", "")
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
        >>> 'SEMBLE_ENABLED=true' in out
        True
        >>> "CLEAN_ARGS='fix auth.py'" in out
        True
    """
    specs = parse_specs(spec_tokens)
    values, clean_args = extract_flags(arguments, specs)
    lines = [f"{var}={_shell_quote(val)}" for var, val in values.items()]
    lines.append(f"CLEAN_ARGS={_shell_quote(clean_args)}")
    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("usage: dev_parse_args.py ARGUMENTS [SPEC...]", file=sys.stderr)
        sys.exit(1)
    arguments = sys.argv[1]
    spec_tokens = sys.argv[2:]
    print(run(arguments, spec_tokens))


if __name__ == "__main__":
    main()
