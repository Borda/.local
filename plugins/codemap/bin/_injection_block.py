#!/usr/bin/env python
"""_injection_block.py — single source of truth for the codemap injection block.

Every consumer that reads, writes, or audits the codemap context block imports its constants
from here so ``inject``, ``check``, the integration SKILL, and the README never drift apart:

    * :data:`BEGIN_SENTINEL` / :data:`END_SENTINEL` — mark the re-injectable region so a
      later re-inject can replace only the block while preserving user text outside it.
    * :data:`BLOCK_VERSION` — integer version stamp carried inside the block; ``check`` compares
      the stamp found on disk against this value to distinguish PASS from OUTDATED.
    * :data:`MARKER` — stable substring identifying an already-injected block (idempotency guard).
    * :data:`SCAN_QUERY_MARKER` — the ``command -v scan-query`` probe token the audit scanner keys on.
    * :data:`BLOCK` — the full markdown block, version-stamped, running real queries and emitting a
      ``codemap_evidence:`` line, with one reference line pointing at the shared context contract.

The block is a *loader* from day one: short inline queries plus a reference to
``skills/_shared/codemap-context.md`` for the full query map, which later contract work enriches.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Relative location (from the project git root or ``CODEMAP_INDEX_DIR``) of the persisted record of
# injection sites discovered at init time. ``check`` reads it to audit exactly those sites, so a
# stranger project with only personal skills is audited by name instead of the borda default list.
INTEGRATION_RECORD_NAME = "integration.json"
INTEGRATION_SCHEMA_VERSION = 1

# Version stamp carried inside the block. Bump when the block's query set or contract changes;
# ``check_injection`` reports OUTDATED for any injected block whose stamp differs from this value.
BLOCK_VERSION = 1

# Sentinels bounding the re-injectable region. Re-inject replaces everything between them
# (inclusive) and leaves any user-authored text outside the sentinels untouched.
BEGIN_SENTINEL = "<!-- codemap:begin -->"
END_SENTINEL = "<!-- codemap:end -->"

# Version-stamp line format. The audit and re-inject logic parse the integer back out of this line.
VERSION_STAMP_PREFIX = "codemap-block: v"

# ``check_injection`` scans installed files for this literal token to decide a file is wired.
SCAN_QUERY_MARKER = "command -v scan-query"

# Idempotency marker: a stable substring present in every injected block. Keyed on the begin
# sentinel so a re-run detects prior injection regardless of the surrounding heading text.
MARKER = BEGIN_SENTINEL

# Heading the block renders under; kept out of the sentinel-bounded region so surrounding
# markdown structure is human-legible when the block is viewed in a rendered file.
BLOCK_HEADING = "## Codemap context (optional — skip if index absent)"


def _render_block(version: int) -> str:
    """Return the full injection block markdown for a given version stamp.

    Args:
        version: integer version stamp to embed via :data:`VERSION_STAMP_PREFIX`.

    Returns:
        The complete block text, terminated with a trailing newline, with the version-stamped,
        sentinel-bounded region carrying the runnable bash and the ``codemap_evidence:`` line.

    Examples:
        >>> block = _render_block(7)
        >>> BEGIN_SENTINEL in block and END_SENTINEL in block
        True
        >>> "codemap-block: v7" in block
        True
        >>> "command -v scan-query" in block
        True
    """
    return f"""{BLOCK_HEADING}

{BEGIN_SENTINEL} {VERSION_STAMP_PREFIX}{version}

```bash
# Structural context (codemap — Python projects only; silent skip if index absent).
# Full query map: skills/_shared/codemap-context.md
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
_CM_IDX="${{CODEMAP_INDEX_DIR:-.cache/codemap}}"
if command -v scan-query >/dev/null 2>&1 && [ -f "${{_CM_IDX}}/${{PROJ}}.json" ]; then
    _CM_N=0 _CM_H=0
    _cm_q() {{
        _CM_N=$((_CM_N+1))
        _out=$(scan-query --timeout 5 "$@" 2>/dev/null)
        case "$_out" in *'"error"'*|'') ;; *) _CM_H=$((_CM_H+1)); printf '%s\\n' "$_out" ;; esac
    }}
    _cm_q central --top 3
    [ -n "$TARGET_FN" ]     && _cm_q fn-rdeps "${{TARGET_MODULE}}::${{TARGET_FN}}"
    [ -z "$TARGET_FN" ] && [ -n "$TARGET_MODULE" ] && _cm_q rdeps "$TARGET_MODULE"
    if [ "$_CM_H" -eq 0 ]; then _CM_COMPL="unknown"; else _CM_COMPL="exhaustive"; fi
    echo "codemap_evidence: queries_run=${{_CM_N}} hits=${{_CM_H}} completeness=${{_CM_COMPL}}"
fi
```

> Set `TARGET_MODULE` (dotted) and `TARGET_FN` (bare name) before this block when a target is known;
> both empty runs only the `central` baseline. Prepend returned results as a
> `## Structural Context (codemap)` section to any agent spawn prompt. Codemap is the primary
> navigation tool — do not grep to re-verify what it returns when `completeness=exhaustive`.

{END_SENTINEL}

"""


BLOCK = _render_block(BLOCK_VERSION)

# Matches the version integer inside an injected block's stamp line, e.g. ``codemap-block: v3``.
VERSION_STAMP_RE = re.compile(re.escape(VERSION_STAMP_PREFIX) + r"(\d+)")


def parse_block_version(content: str) -> int | None:
    """Return the injected block's version stamp found in ``content``, or ``None`` if absent.

    Args:
        content: full text of a file that may contain an injected block.

    Returns:
        The integer version from the first ``codemap-block: vN`` stamp, or ``None`` when the
        file carries no version-stamped block.

    Examples:
        >>> parse_block_version("prose\\ncodemap-block: v4\\nmore")
        4
        >>> parse_block_version("no block here") is None
        True
    """
    match = VERSION_STAMP_RE.search(content)
    return int(match.group(1)) if match else None


def replace_block_region(content: str, new_block: str = BLOCK) -> str:
    """Replace the sentinel-bounded block region in ``content`` with ``new_block``.

    Only the region from :data:`BEGIN_SENTINEL` through :data:`END_SENTINEL` (inclusive), plus the
    heading immediately preceding it, is replaced; any user-authored text outside the sentinels is
    preserved. When ``content`` has no sentinel region, it is returned unchanged (callers detect
    this via equality and fall back to a fresh insert).

    Args:
        content: original file text (expected to contain a prior injected block).
        new_block: replacement block (defaults to the current :data:`BLOCK`).

    Returns:
        ``content`` with its old block region swapped for ``new_block``, or unchanged text when no
        sentinel region is present.

    Examples:
        >>> old = "intro\\n" + _render_block(1) + "outro\\n"
        >>> updated = replace_block_region(old, _render_block(9))
        >>> "codemap-block: v9" in updated and "codemap-block: v1" not in updated
        True
        >>> updated.startswith("intro") and updated.rstrip().endswith("outro")
        True
        >>> replace_block_region("no sentinels here") == "no sentinels here"
        True
    """
    begin = content.find(BEGIN_SENTINEL)
    end = content.find(END_SENTINEL)
    if begin == -1 or end == -1 or end < begin:
        return content
    # Extend the replaced span back over the heading (and its trailing blank line) so the whole
    # rendered block is swapped as a unit rather than leaving a stale orphaned heading.
    head_start = content.rfind(BLOCK_HEADING, 0, begin)
    region_start = head_start if head_start != -1 else begin
    region_end = end + len(END_SENTINEL)
    # Consume a single trailing newline after the end sentinel to avoid accumulating blank lines
    # across repeated re-injects.
    if content[region_end : region_end + 1] == "\n":
        region_end += 1
    replacement = new_block if new_block.endswith("\n") else new_block + "\n"
    return content[:region_start] + replacement + content[region_end:]


def save_integration_sites(cache_dir: Path, sites: list[str]) -> Path:
    """Persist the injection ``sites`` discovered at init time under ``cache_dir``.

    Writes ``<cache_dir>/integration.json`` recording the schema version and the sorted, de-duplicated
    site paths. ``check`` later reads this file so a project with only personal skills is audited by
    the sites actually wired, not a hardcoded plugin list.

    Args:
        cache_dir: codemap cache directory (created if absent), typically ``<root>/.cache/codemap``.
        sites: injection-site paths discovered at init (any order; duplicates tolerated).

    Returns:
        The path to the written record file.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    record = {"schema": INTEGRATION_SCHEMA_VERSION, "block_version": BLOCK_VERSION, "sites": sorted(set(sites))}
    path = cache_dir / INTEGRATION_RECORD_NAME
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def load_integration_sites(cache_dir: Path) -> list[str] | None:
    """Return the persisted injection-site list from ``cache_dir``, or ``None`` if unavailable.

    Args:
        cache_dir: codemap cache directory to read ``integration.json`` from.

    Returns:
        The recorded ``sites`` list, or ``None`` when the record is absent, unreadable, or malformed
        (callers then fall back to their default canonical-site list).
    """
    path = cache_dir / INTEGRATION_RECORD_NAME
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sites = record.get("sites") if isinstance(record, dict) else None
    if not isinstance(sites, list) or not all(isinstance(s, str) for s in sites):
        return None
    return sites
