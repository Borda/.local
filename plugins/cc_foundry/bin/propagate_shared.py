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

Check mode is the default and takes no flag — there is no ``--check`` option, and
passing one exits 2 (``unrecognized arguments: --check``). ``--apply`` is the only
mode flag.

- no mode flag (default): report every copy that differs from its canonical;
  exit 1 if any differ. This is the form pre-commit / CI run.
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
        # Table-format detector consumed by all six enforce-*-header.js
        # hooks. Each caller requires it in a try/catch and fails open, so a
        # standalone plugin install missing its copy never breaks the
        # existing file-existence gate — but a stale copy would silently
        # drift the detection logic (MIN_TABLE_ROWS, boundary detection)
        # across plugins, so it still belongs in MANIFEST.
        "canonical": "plugins/cc_foundry/hooks/report-header-table.js",
        "copies": [
            "plugins/cc_oss/hooks/report-header-table.js",
            "plugins/cc_develop/hooks/report-header-table.js",
            "plugins/cc_research/hooks/report-header-table.js",
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
    # --- Self-contained _shared (plugins/CLAUDE.md §Self-Contained _shared) ---
    # These six docs were previously READ OUT OF FOUNDRY'S TREE by sibling plugins
    # (via `resolve_shared_path.py foundry`, `dev_shared_resolve.py --foundry`, or
    # a $HOME/.claude/skills/_shared symlink). Every such reach-in made the feature
    # vanish on a standalone install — research lost R7 entirely that way. Each
    # consuming plugin now ships its own copy and resolves it with its OWN resolver;
    # these entries are what keep the copies byte-identical. Audit Check 27 fails
    # any new reach-in, so extend the copies list here instead of borrowing.
    {
        "canonical": "plugins/cc_foundry/skills/_shared/codex-delegation.md",
        "copies": [
            "plugins/cc_research/skills/_shared/codex-delegation.md",
            "plugins/cc_oss/skills/_shared/codex-delegation.md",
            "plugins/cc_develop/skills/_shared/codex-delegation.md",
        ],
    },
    {
        "canonical": "plugins/cc_foundry/skills/_shared/file-handoff-protocol.md",
        "copies": [
            "plugins/cc_oss/skills/_shared/file-handoff-protocol.md",
            "plugins/cc_develop/skills/_shared/file-handoff-protocol.md",
            "plugins/cc_research/skills/_shared/file-handoff-protocol.md",
        ],
    },
    {
        "canonical": "plugins/cc_foundry/skills/_shared/cross-validation-protocol.md",
        "copies": [
            "plugins/cc_oss/skills/_shared/cross-validation-protocol.md",
            "plugins/cc_develop/skills/_shared/cross-validation-protocol.md",
        ],
    },
    {
        "canonical": "plugins/cc_foundry/skills/_shared/terminal-summaries.md",
        "copies": [
            "plugins/cc_oss/skills/_shared/terminal-summaries.md",
        ],
    },
    {
        "canonical": "plugins/cc_foundry/skills/_shared/quality-stack.md",
        "copies": [
            "plugins/cc_develop/skills/_shared/quality-stack.md",
        ],
    },
    # No rules/*.md entries here, deliberately. Cross-cutting standards (python-code.md,
    # python-testing.md, git-commit.md) are single-homed in cc_foundry because rules reach
    # Claude only as symlinks in ~/.claude/rules/, created by foundry:setup — that flat
    # namespace means two plugins shipping the same rule filename would collide, and a copy
    # in a plugin with no installer is simply never loaded. Per-plugin rules/quality-gates.md
    # variants stay unmanifested for the separate reason that they legitimately differ.
    {
        "canonical": "plugins/cc_foundry/skills/_shared/codex-prepass.md",
        "copies": [
            "plugins/cc_develop/skills/_shared/codex-prepass.md",
        ],
    },
    {
        # oss shipped a byte-identical copy of this resolver that was never manifested,
        # so it silently inherited foundry-specific internals (it scanned FOUNDRY's cache
        # for get_plugin_install_path.py). Both copies now derive their own plugin from
        # __file__; manifesting them keeps that true.
        "canonical": "plugins/cc_foundry/bin/resolve_shared_path.py",
        "copies": [
            "plugins/cc_oss/bin/resolve_shared_path.py",
        ],
    },
    {
        "canonical": "plugins/cc_foundry/bin/get_plugin_install_path.py",
        "copies": [
            "plugins/cc_oss/bin/get_plugin_install_path.py",
        ],
    },
    {
        # Same rule applies to bin/ scripts: cc_develop/skills/debug used to invoke
        # this out of foundry's bin/ via a $_FOUNDRY_BIN path derived by stripping
        # `/skills/_shared` off the resolver output. Flaky-test isolation silently
        # disappeared without foundry installed.
        "canonical": "plugins/cc_foundry/bin/find-polluter.py",
        "copies": [
            "plugins/cc_develop/bin/find-polluter.py",
        ],
    },
    {
        # file -> canonical-module resolver, fed by `codemap-py query central`. Foundry's six
        # agent pre-flights need the same mapping oss:review already uses; re-implementing
        # match_module() in foundry would be a second copy of the exact drift this MANIFEST
        # exists to stop, and importing oss's copy is a forbidden cross-plugin runtime
        # dependency. Byte-identical copy is the only remaining shape.
        "canonical": "plugins/cc_oss/bin/resolve_centrality.py",
        "copies": [
            "plugins/cc_foundry/bin/resolve_centrality.py",
        ],
    },
    {
        # Consumer codemap gate resolver. Identical logic in both plugins; the only
        # per-plugin difference (the currency-sentinel name) is injected by each
        # plugin's own wrapper (dev_codemap_gate.py / codemap-flag.py) via
        # --currency-prefix, never by editing this file.
        "canonical": "plugins/cc_develop/bin/codemap_resolve.py",
        "copies": [
            "plugins/cc_research/bin/codemap_resolve.py",
        ],
    },
    {
        # Each of these three plugins ships a rules/ directory that no installed
        # workflow used to deliver, so those rules were inert. Every plugin now
        # installs its own via /<plugin>:setup, and the delivery mechanism must be
        # identical everywhere — an ownership bug fixed in one copy but not the
        # others would let a sibling plugin delete a user's link. The canonical
        # lives in cc_develop (which owns the only test suite for it); foundry
        # keeps its own delivery in symlink_with_guard.py and is NOT a copy.
        "canonical": "plugins/cc_develop/bin/sync_rules.py",
        "copies": [
            "plugins/cc_oss/bin/sync_rules.py",
            "plugins/cc_research/bin/sync_rules.py",
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
    """CLI entry point. Returns process exit code (0 clean, 1 drift in check mode)."""
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
