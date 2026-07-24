#!/usr/bin/env python3
"""propagate_shared.py — keep byte-identical cross-plugin shared files in sync.

Some files must be identical across plugins because each plugin ships its own
copy of a shared mechanism (a plugin cannot depend on another being installed —
see plugins/CLAUDE.md "Fallback / Resilience Infrastructure"). The canonical
copy lives in one plugin; the others must track it byte-for-byte. Without
enforcement these copies drift silently (verified: the `agent-router.js`
fallback hook had three stale 168-line copies against foundry's 400-line
canonical).

This tool has a single source of truth — MANIFEST — mapping each canonical file
to the copies that must equal it.

- ``--check`` (default): report every copy that differs from its canonical;
  exit 1 if any differ. Wire into pre-commit / CI.
- ``--apply``: overwrite each copy with its canonical.

Only files that are MEANT to be byte-identical belong in MANIFEST. Files that
legitimately vary per plugin (e.g. `agent-resolution.md` fallback tables,
per-plugin `rules/quality-gates.md`) must NOT be listed here.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Each entry: the canonical file, and the copies that must equal it byte-for-byte.
MANIFEST: list[dict[str, object]] = [
    {
        "canonical": "plugins/cc_foundry/hooks/agent-router.js",
        "copies": [
            "plugins/cc_oss/hooks/agent-router.js",
            "plugins/cc_develop/hooks/agent-router.js",
            "plugins/cc_research/hooks/agent-router.js",
        ],
    },
    {
        # Every plugin ships the blueprint auto-allow hook so a standalone
        # install (e.g. cc_oss alone) still covers its own SKILL.md idioms.
        "canonical": "plugins/cc_foundry/hooks/sentinel-read-allow.js",
        "copies": [
            "plugins/cc_oss/hooks/sentinel-read-allow.js",
            "plugins/cc_develop/hooks/sentinel-read-allow.js",
            "plugins/cc_research/hooks/sentinel-read-allow.js",
            # codemap-py intentionally ships no copy: its hook helpers are
            # Python-only by contract, and the cc_foundry canonical covers all
            # Bash calls session-wide whenever cc_foundry is installed.
        ],
    },
]


def _differs(a: Path, b: Path) -> bool:
    """Return True if files differ or either is unreadable/missing.

    Args:
        a: First file path.
        b: Second file path.

    Returns:
        True when the two files are not byte-identical.

    Examples:
        >>> _differs(Path("/nonexistent-a"), Path("/nonexistent-b"))
        True
    """
    try:
        return a.read_bytes() != b.read_bytes()
    except OSError:
        return True


def check(root: Path, manifest: list[dict[str, object]]) -> list[str]:
    """Return a list of drift findings (empty when all copies match canonical).

    Args:
        root: Repository root the manifest paths are relative to.
        manifest: List of ``{"canonical": str, "copies": [str, ...]}`` entries.

    Returns:
        Human-readable finding strings, one per drifted or missing copy.
    """
    findings: list[str] = []
    for entry in manifest:
        canonical = root / str(entry["canonical"])
        if not canonical.is_file():
            findings.append(f"canonical missing: {entry['canonical']}")
            continue
        for rel in entry["copies"]:  # type: ignore[union-attr]
            copy = root / str(rel)
            if _differs(canonical, copy):
                findings.append(f"{rel} differs from canonical {entry['canonical']}")
    return findings


def apply(root: Path, manifest: list[dict[str, object]]) -> list[str]:
    """Copy each canonical over its copies; return the list of paths updated.

    Args:
        root: Repository root the manifest paths are relative to.
        manifest: List of ``{"canonical": str, "copies": [str, ...]}`` entries.

    Returns:
        Relative paths of copies that were rewritten.
    """
    updated: list[str] = []
    for entry in manifest:
        canonical = root / str(entry["canonical"])
        if not canonical.is_file():
            continue
        for rel in entry["copies"]:  # type: ignore[union-attr]
            copy = root / str(rel)
            if _differs(canonical, copy):
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(canonical, copy)
                updated.append(str(rel))
    return updated


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code (0 clean, 1 drift in --check)."""
    parser = argparse.ArgumentParser(description="Sync byte-identical cross-plugin shared files")
    parser.add_argument("--apply", action="store_true", help="overwrite copies with canonical (default: check only)")
    parser.add_argument("--root", default=".", help="repository root (default: cwd)")
    args = parser.parse_args(argv)
    root = Path(args.root)

    if args.apply:
        updated = apply(root, MANIFEST)
        if updated:
            print("\n".join(f"PROPAGATED: {u}" for u in updated))
        else:
            print("✓: all shared copies already in sync")
        return 0

    findings = check(root, MANIFEST)
    if findings:
        print("\n".join(f"SHARED-DRIFT: {f}" for f in findings))
        print("  fix: run `python plugins/cc_foundry/bin/propagate_shared.py --apply`")
        return 1
    print("✓: cross-plugin shared files in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
