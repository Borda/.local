#!/usr/bin/env python3
"""write-skill-contract.py — write the compaction-boundary contract the PreCompact hook appends verbatim.

Only the skeleton is shared. `preserve` and `next` stay bespoke per boundary by design
(compaction.md §Verbatim-file principle) — this script parameterises the mkdir + write
around them, never the prose itself.

Usage: python write-skill-contract.py <skill> <phase> <run-dir> <preserve> <next>
  Callers keep their own sentinel reads: the `${_OUT}`-style values must expand in the
  caller's shell, while `<REFINE_ITER>`-style placeholders are literal fill-in tokens the
  orchestrator substitutes as prose. Both survive as-is through a double-quoted argument.
Exit codes: 0 = written · 2 = wrong argument count or empty <skill>
"""

from __future__ import annotations

import sys
from pathlib import Path

# CWD-relative, exactly as the shell original: the contract belongs to the project the
# skill is running in, which is the caller's working directory, not this script's location.
_CONTRACT = Path(".temp/state/skill-contract.md")


def main(argv: list[str]) -> int:
    args = argv[1:]
    if len(args) != 5:
        print(
            f"write-skill-contract: expected 5 args (skill phase run-dir preserve next), got {len(args)}",
            file=sys.stderr,
        )
        return 2

    skill, phase, run_dir, preserve, next_step = args
    if not skill:
        print("write-skill-contract: <skill> must not be empty", file=sys.stderr)
        return 2

    contract = (
        "## Active Skill Contract\n"
        f"- skill: {skill} · phase: {phase}\n"
        f"- run-dir: {run_dir}\n"
        f"- preserve: {preserve}\n"
        f"- next: {next_step}\n"
    )
    try:
        _CONTRACT.parent.mkdir(parents=True, exist_ok=True)
        _CONTRACT.write_text(contract, encoding="utf-8")
    except OSError as exc:
        print(f"write-skill-contract: cannot write {_CONTRACT}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
