#!/usr/bin/env python
"""parse-skill-flags.py — parse a skill's $ARGUMENTS blob, emit shell variable assignments for eval.

Generalizes the boolean anchored-token flag + ``--keep "<items>"`` extraction that
was independently re-implemented (regex + ``case``/``[[ ]]`` anchored-token match +
``sed``-based ``CLEAN_ARGS`` stripping) in ``resolve/SKILL.md``, ``analyse/SKILL.md``,
and ``review/SKILL.md``. Follows the eval-emit shape of ``parse-resolve-args.py``.

Usage (Claude Code plugin — ``CLAUDE_PLUGIN_ROOT`` set automatically)::

    eval "$(python "${CLAUDE_PLUGIN_ROOT}/bin/parse-skill-flags.py" --flags reply,no-challenge,worktree "$ARGUMENTS")"

Emits, for a ``--flags`` list of ``N`` comma-separated bare flag names (no leading
``--``):

- ``FLAG_<NAME>`` — one per requested flag, ``true``/``false``; ``<NAME>`` is the
  flag name uppercased with ``-`` replaced by ``_`` (e.g. ``no-challenge`` →
  ``FLAG_NO_CHALLENGE``). Detection is anchored-token (padded-space match), never
  bare substring — ``--reply`` does not false-fire on ``--reply-later`` or a repo
  name containing ``--reply-bot``.
- ``KEEP_ITEMS`` — value captured from ``--keep "<items>"`` (empty string if absent)
- ``CLEAN_ARGS`` — original blob with ``--keep "<items>"`` and every requested
  ``--<flag>`` token removed (anchored, same non-substring safety as detection),
  whitespace collapsed, one leading ``#`` stripped

Callers keep flag-specific semantics (name mapping, polarity inversion such as
``--no-challenge`` → ``CHALLENGE_ENABLED`` defaulting ``true``) in the consuming
``SKILL.md`` — this script extracts only the duplicated detection/stripping
mechanics, not per-skill variable naming or polarity.

Exit codes:
    0 — assignments emitted
    2 — invalid ``--flags`` value (empty list or a token failing name validation)

Note: like ``parse-resolve-args.py``, the ``$ARGUMENTS`` blob is forwarded
verbatim via ``parse_known_args`` — a blob starting with ``-`` (e.g. dash-leading
prose) is never misparsed as an option of this script.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
from typing import Final

_FLAG_NAME_RE: Final = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KEEP_RE: Final = re.compile(r'--keep\s+"([^"]+)"')


def _var_name(flag: str) -> str:
    """Convert a bare flag name to its emitted shell variable suffix.

    >>> _var_name("worktree")
    'WORKTREE'
    >>> _var_name("no-challenge")
    'NO_CHALLENGE'
    """
    return flag.upper().replace("-", "_")


def parse_skill_flags(arguments: str, flags: list[str]) -> dict[str, str]:
    """Parse a skill's ``$ARGUMENTS`` blob against a requested flag list.

    Args:
        arguments: Raw ``$ARGUMENTS`` blob (e.g. ``'42 --reply --keep "notes"'``).
        flags: Bare flag names to detect (no leading ``--``), e.g.
            ``["reply", "no-challenge", "worktree"]``.

    Returns:
        Dict with one ``FLAG_<NAME>`` key per requested flag plus ``KEEP_ITEMS``
        and ``CLEAN_ARGS``.

    Examples:
        >>> result = parse_skill_flags("42 --reply --keep \\"drop the typo fix\\"", ["reply", "worktree"])
        >>> result["FLAG_REPLY"]
        'true'
        >>> result["FLAG_WORKTREE"]
        'false'
        >>> result["KEEP_ITEMS"]
        'drop the typo fix'
        >>> result["CLEAN_ARGS"]
        '42'
        >>> parse_skill_flags("--reply-later fix the bug", ["reply"])["FLAG_REPLY"]
        'false'
        >>> parse_skill_flags("#42 --reply", ["reply"])["CLEAN_ARGS"]
        '42'
    """
    padded = f" {arguments} "
    keep_match = _KEEP_RE.search(arguments)
    keep_items = keep_match.group(1) if keep_match else ""

    result: dict[str, str] = {}
    clean = _KEEP_RE.sub("", padded)
    for flag in flags:
        present = f" --{flag} " in padded
        result[f"FLAG_{_var_name(flag)}"] = "true" if present else "false"
        clean = re.sub(rf"(?<=\s)--{re.escape(flag)}(?=\s)", "", clean)

    clean = re.sub(r"\s+", " ", clean).strip()
    if clean.startswith("#"):
        clean = clean[1:].strip()

    result["KEEP_ITEMS"] = keep_items
    result["CLEAN_ARGS"] = clean
    return result


def _validate_flags(raw: str) -> list[str]:
    """Split + validate the ``--flags`` CLI value.

    Args:
        raw: Comma-separated flag names as passed to ``--flags``.

    Returns:
        Validated list of bare flag names, order preserved.

    Raises:
        ValueError: ``raw`` is empty, or any token fails
            ``^[a-z0-9]+(-[a-z0-9]+)*$`` (lowercase, digits, single internal dashes).

    Examples:
        >>> _validate_flags("reply,no-challenge")
        ['reply', 'no-challenge']
        >>> _validate_flags("")
        Traceback (most recent call last):
            ...
        ValueError: --flags must list at least one flag name
        >>> _validate_flags("Reply")
        Traceback (most recent call last):
            ...
        ValueError: invalid flag name: 'Reply'
    """
    tokens = [t.strip() for t in raw.split(",") if t.strip()]
    if not tokens:
        raise ValueError("--flags must list at least one flag name")
    for token in tokens:
        if not _FLAG_NAME_RE.match(token):
            raise ValueError(f"invalid flag name: {token!r}")
    return tokens


def _emit(parsed: dict[str, str]) -> str:
    """Render parsed dict as newline-separated ``VAR=value`` shell assignments."""
    return "\n".join(f"{key}={shlex.quote(value)}" for key, value in parsed.items())


def main(argv: list[str]) -> int:
    """Parse ``--flags`` + the ``$ARGUMENTS`` blob, emit shell assignments.

    Args:
        argv: Raw argv tokens (``sys.argv[1:]``).

    Returns:
        ``0`` on success, ``2`` on invalid ``--flags`` value. Argparse itself
        exits ``2`` when ``-h``/``--help`` is the sole argument, or when
        ``--flags`` is missing entirely.

    Examples:
        No doctest — emits to stdout; covered by pytest via subprocess.
    """
    parser = argparse.ArgumentParser(
        prog="parse-skill-flags.py",
        description="Parse a skill's $ARGUMENTS blob for anchored-token flags + --keep, emit shell assignments for eval.",
    )
    parser.add_argument(
        "--flags",
        required=True,
        help="Comma-separated bare flag names, no leading --, e.g. reply,no-challenge,worktree",
    )
    ns, extra = parser.parse_known_args(argv)

    try:
        flags = _validate_flags(ns.flags)
    except ValueError as exc:
        print(f"parse-skill-flags: {exc}", file=sys.stderr)
        return 2

    arguments = " ".join(extra)
    parsed = parse_skill_flags(arguments, flags)
    print(_emit(parsed))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
