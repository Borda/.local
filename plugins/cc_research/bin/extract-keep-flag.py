#!/usr/bin/env python3
"""extract-keep-flag.py — initialise a skill's compaction-contract state from its arguments.

Python rather than a shell regex on purpose: the inline twin of this parse used `[[ =~ ]]` +
${BASH_REMATCH[1]}, and zsh — the harness shell — populates $match instead, so every
`--keep "..."` silently resolved to the empty string.

Usage: python extract-keep-flag.py <sentinel-slug> "$ARGUMENTS"
  <sentinel-slug> is the sentinel's own slug, not the skill name (research:run writes
  `research-run-keep-items`, so it passes `research-run`).
Side effects: clears a stale .temp/state/skill-contract.md left by a crashed prior run
  (compaction-contract.md §Lifecycle) and writes the keep value to
  ${TMPDIR:-/tmp}/<sentinel-slug>-keep-items-${CSID}. Also prints it (may be empty).
Requires: CSID exported by the caller — a child's own parent process id is the calling shell,
  not the Claude Code process, so deriving it here would name a different sentinel.
Exit codes: 0 = ok · 2 = missing <sentinel-slug> or CSID unset
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

# [[:space:]]+ (not a single literal space) so `--keep  "a, b"` parses too — superset of the
# inline form it replaces, never a narrower match.
_KEEP_RE = re.compile(r'--keep[ \t\r\f\v]+"([^"]+)"')

# CWD-relative, exactly as the shell original: the contract belongs to the project the skill
# is running in, which is the caller's working directory, not this script's location.
_CONTRACT = Path(".temp/state/skill-contract.md")


def main(argv: list[str]) -> int:
    slug = argv[1] if len(argv) > 1 else ""
    args = argv[2] if len(argv) > 2 else ""
    if not slug:
        print("extract-keep-flag: missing <sentinel-slug> argument", file=sys.stderr)
        return 2
    # No "shared" fallback here, unlike the other bin/ scripts: this script's contract is
    # that an unset CSID is a caller bug, and its callers gate on the exit-2.
    csid = os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if not csid:
        print("extract-keep-flag: CSID not exported by caller", file=sys.stderr)
        return 2

    match = _KEEP_RE.search(args)
    keep_items = match.group(1) if match else ""

    try:
        _CONTRACT.unlink(missing_ok=True)
    except OSError as exc:
        print(f"extract-keep-flag: cannot clear {_CONTRACT}: {exc}", file=sys.stderr)
        return 1

    tmp = Path(os.environ.get("TMPDIR") or tempfile.gettempdir())
    sentinel = tmp / f"{slug}-keep-items-{csid}"
    try:
        sentinel.write_text(keep_items + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"extract-keep-flag: cannot write {sentinel}: {exc}", file=sys.stderr)
        return 1

    print(keep_items)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
