#!/usr/bin/env python3
"""check_readme_drift.py — detect README facts that have drifted from disk.

Deterministic, low-false-positive drift checks for a plugin's ``README.md``.
Two classes of fact are verified against ground truth on disk:

1. **Version marker** — a literal ``Current version: `X.Y.Z``` line must match the
   ``version`` field in the plugin's ``.claude-plugin/plugin.json``. Only this
   explicit marker is checked; arbitrary version-shaped strings (release
   examples like ``v2.1.0``, historical benchmark tags like ``v0.13.2``) are
   ignored to avoid false positives.
2. **bin/ script references** — any backtick token ending in ``.py`` or ``.sh``
   that appears either on a line mentioning ``bin/`` or as an explicit
   ``plugins/<plugin>/bin/<name>`` path must exist in the plugin's ``bin/``
   directory. Catches the sh→py migration drift where README kept the old names.

Usage:
    check_readme_drift.py plugins/research [plugins/oss ...]
    check_readme_drift.py --scan-dir plugins

Exit code 0 when clean, 1 when any drift is found, 2 on usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VERSION_MARKER = re.compile(r"Current version:\s*`(\d+\.\d+\.\d+)`")
BACKTICK_SCRIPT = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|sh))`")


def _plugin_version(plugin_dir: Path) -> str | None:
    """Return the ``version`` string from a plugin's manifest, or None if absent.

    Args:
        plugin_dir: Path to a plugin directory (containing ``.claude-plugin/``).

    Returns:
        The version string, or None if the manifest is missing or malformed.

    Examples:
        >>> _plugin_version(Path("/nonexistent")) is None
        True
    """
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (json.JSONDecodeError, OSError):
        return None


def _referenced_scripts(readme_text: str, plugin_name: str) -> set[str]:
    """Extract bin/ script basenames a README refers to.

    A token is treated as a bin/ reference when it ends in ``.py``/``.sh`` and
    either appears on a line mentioning ``bin/`` or is written as an explicit
    ``plugins/<plugin>/bin/<name>`` path.

    Args:
        readme_text: Full README contents.
        plugin_name: The plugin directory name (for explicit-path matching).

    Returns:
        Set of referenced script basenames (e.g. ``{"resolve_shared.py"}``).

    Examples:
        >>> _referenced_scripts("see `foo.py` in bin/ here", "research")
        {'foo.py'}
        >>> _referenced_scripts("`plugins/oss/bin/bar.sh`", "oss")
        {'bar.sh'}
        >>> _referenced_scripts("unrelated `train.py` example", "research")
        set()
    """
    found: set[str] = set()
    explicit_path = f"plugins/{plugin_name}/bin/"
    for line in readme_text.splitlines():
        line_flags_bin = "bin/" in line
        for token in BACKTICK_SCRIPT.findall(line):
            if explicit_path in line or line_flags_bin:
                found.add(Path(token).name)
    return found


def check_plugin(plugin_dir: Path) -> list[str]:
    """Check one plugin's README for version and bin/ reference drift.

    Args:
        plugin_dir: Path to the plugin directory.

    Returns:
        List of human-readable drift findings (empty when clean).

    Examples:
        >>> check_plugin(Path("/nonexistent"))
        []
    """
    readme = plugin_dir / "README.md"
    if not readme.is_file():
        return []
    text = readme.read_text(encoding="utf-8")
    findings: list[str] = []

    version = _plugin_version(plugin_dir)
    marker = VERSION_MARKER.search(text)
    if marker and version and marker.group(1) != version:
        findings.append(f"{readme}: 'Current version: `{marker.group(1)}`' != plugin.json `{version}`")

    # Existence is checked plugin-wide (not just bin/): a referenced script may
    # legitimately live in tests/ or a skill dir. Drift = referenced nowhere.
    existing = {p.name for p in plugin_dir.rglob("*.py") if "__pycache__" not in p.parts}
    existing |= {p.name for p in plugin_dir.rglob("*.sh")}
    for script in sorted(_referenced_scripts(text, plugin_dir.name)):
        if script not in existing:
            findings.append(f"{readme}: references script `{script}` — not found anywhere in {plugin_dir}")
    return findings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list (defaults to sys.argv[1:] when None).

    Returns:
        Process exit code: 0 clean, 1 drift found.
    """
    parser = argparse.ArgumentParser(description="Detect README drift from disk (version + bin/ refs)")
    parser.add_argument("plugins", nargs="*", help="plugin directories to check")
    parser.add_argument("--scan-dir", metavar="DIR", help="check every immediate subdir of DIR that has a README.md")
    args = parser.parse_args(argv)

    targets: list[Path] = [Path(p) for p in args.plugins]
    if args.scan_dir:
        targets += [d for d in sorted(Path(args.scan_dir).iterdir()) if (d / "README.md").is_file()]
    if not targets:
        parser.error("no plugin directories given (pass paths or --scan-dir)")

    all_findings: list[str] = []
    for plugin_dir in targets:
        all_findings.extend(check_plugin(plugin_dir))

    if all_findings:
        print("\n".join(f"README-DRIFT: {f}" for f in all_findings))
        return 1
    print("✓: README drift — version markers and bin/ references match disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
