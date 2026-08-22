#!/usr/bin/env python3
"""check_plugin_version_sync.py — dual-host plugin manifests must agree on version.

A plugin shipped to both hosts carries two manifests: ``.claude-plugin/plugin.json``
(Claude Code) and ``.codex-plugin/plugin.json`` (Codex). A version bump applied to
one and not the other ships two installs that claim different releases of the same
code (observed: codemap-py bumped to 0.31.3 on the Claude side while the Codex
manifest stayed 0.31.2). This check is general: ANY directory under ``--scan-dir``
containing BOTH manifest directories is checked — no per-plugin list to maintain.

Single-host plugins (only one of the two manifest dirs present) are ignored; they
have nothing to desync.

Replaces the per-plugin hardcoded assertion that previously lived in
``plugins/bridge_cc-codex/tests/test_packaging.py`` (it pinned the literal version
string, so every legitimate bump broke the test, and it covered only bridge).

Usage:
    check_plugin_version_sync.py [--scan-dir DIR]

Exit codes:
    0 — every dual-manifest plugin agrees on ``version``.
    1 — at least one mismatch or unreadable/missing ``version`` field.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _read_version(manifest: Path) -> str | None:
    """Return the ``version`` string from a plugin manifest, or None if unreadable.

    Args:
        manifest: Path to a ``plugin.json`` file.

    Returns:
        The ``version`` value when the file parses and carries one, else None.
    """
    try:
        value = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None
    return value if isinstance(value, str) else None


def find_desyncs(scan_dir: Path) -> list[str]:
    """Return one finding line per dual-manifest plugin whose versions disagree.

    Args:
        scan_dir: Root to scan; every ``.claude-plugin`` directory found below it
            whose parent also holds a ``.codex-plugin`` directory is checked.

    Returns:
        Human-readable finding strings; empty when all pairs agree.
    """
    findings: list[str] = []
    for claude_dir in sorted(scan_dir.rglob(".claude-plugin")):
        plugin_root = claude_dir.parent
        codex_manifest = plugin_root / ".codex-plugin" / "plugin.json"
        claude_manifest = claude_dir / "plugin.json"
        if not codex_manifest.parent.is_dir():
            continue  # single-host plugin — nothing to desync
        claude_version = _read_version(claude_manifest)
        codex_version = _read_version(codex_manifest)
        rel = plugin_root.as_posix()
        if claude_version is None or codex_version is None:
            missing = ".claude-plugin" if claude_version is None else ".codex-plugin"
            findings.append(f"{rel}: unreadable or missing version in {missing}/plugin.json")
        elif claude_version != codex_version:
            findings.append(f"{rel}: .claude-plugin {claude_version} != .codex-plugin {codex_version}")
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns 0 when all dual-manifest versions agree, else 1."""
    parser = argparse.ArgumentParser(description="Check .claude-plugin/.codex-plugin version agreement")
    parser.add_argument("--scan-dir", default="plugins", help="directory to scan (default: plugins)")
    # pre-commit passes matched filenames; the scan is repo-shaped, so they are ignored
    parser.add_argument("files", nargs="*", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    findings = find_desyncs(Path(args.scan_dir))
    if findings:
        print("\n".join(f"VERSION-DESYNC: {f}" for f in findings))
        print("  fix: bump both manifests to the same version — they ship one release")
        return 1
    print("✓: dual-host plugin manifest versions in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
