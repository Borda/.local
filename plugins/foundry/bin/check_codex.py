#!/usr/bin/env python
"""check_codex.py — detect whether the ``codex`` plugin is available AND enabled.

Detection order:
1. If ``enabledPlugins.codex@openai-codex`` is explicitly ``false`` in settings
   (local ``.claude/settings.json`` wins over global ``~/.claude/settings.json``)
   → return ``false`` immediately (opt-out design; installed-but-disabled = unavailable).
2. Otherwise check installed state: ``installed_plugins.json`` manifest, filesystem
   scan of ``~/.claude/plugins/cache`` for ``codex*`` dirs, ``codex`` on PATH.

Prints ``true`` if codex is enabled and installed, ``false`` otherwise.
Always exits 0 — callers branch on stdout, never on exit code.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_codex.py"
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _manifest_has_codex(manifest_path: Path) -> bool:
    """Return True when ``manifest_path`` is a JSON object with any key containing 'codex'.

    Silent on missing file, parse failure, or unexpected JSON shape — the
    fallback chain handles negative cases.

    Args:
        manifest_path: Path to ``installed_plugins.json``.

    Returns:
        True only if a parseable JSON object exposes a 'codex'-bearing key.
    """
    if not manifest_path.is_file():
        return False
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return any("codex" in key for key in data)


def _cache_has_codex(cache_dir: Path) -> bool:
    """Return True if any ``codex*`` directory exists under ``cache_dir``.

    Searches up to depth 4 to match the original ``find -maxdepth 4`` behaviour
    while keeping the scan bounded.

    Args:
        cache_dir: Plugin cache root (typically ``~/.claude/plugins/cache``).

    Returns:
        True when at least one matching directory is found.
    """
    if not cache_dir.is_dir():
        return False
    # Depths 1..4 inclusive; ``Path.glob`` patterns are explicit per depth.
    patterns = ("codex*", "*/codex*", "*/*/codex*", "*/*/*/codex*")
    for pattern in patterns:
        for match in cache_dir.glob(pattern):
            if match.is_dir():
                return True
    return False


def _settings_explicitly_disabled(home: Path, project_root: Path | None = None) -> bool:
    """Return True when settings explicitly opt out of codex (always-on opt-out design).

    Reads global ``~/.claude/settings.json`` then merges local ``.claude/settings.json``
    (local wins on conflict).  Returns True only when the merged result has
    ``enabledPlugins.codex@openai-codex == False``.  Missing file, missing key, or
    parse error all return False (default = enabled).

    Args:
        home: User home directory.
        project_root: Project root for local settings lookup; defaults to CWD.

    Returns:
        True only when codex is explicitly disabled in merged settings.
    """

    def _load(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            return {}

    root = project_root or Path(".")
    global_cfg = _load(home / ".claude" / "settings.json")
    local_cfg = _load(root / ".claude" / "settings.json")
    merged: dict = {**global_cfg.get("enabledPlugins", {}), **local_cfg.get("enabledPlugins", {})}
    return merged.get("codex@openai-codex", True) is False


def codex_available(home: Path, project_root: Path | None = None) -> bool:
    """Return True when codex plugin is enabled in settings and installed.

    Args:
        home: User home directory (allows tests to inject a tmp_path).
        project_root: Project root for local settings lookup; defaults to CWD.

    Returns:
        True if codex is enabled (not opted out) and detectable, False otherwise.
    """
    if _settings_explicitly_disabled(home, project_root):
        return False

    manifest = home / ".claude" / "plugins" / "installed_plugins.json"
    if _manifest_has_codex(manifest):
        return True

    cache_dir = home / ".claude" / "plugins" / "cache"
    if _cache_has_codex(cache_dir):
        return True

    return shutil.which("codex") is not None


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Unused; accepted for parity with the bin/ skeleton.

    Returns:
        Always 0 — stdout carries the boolean answer.
    """
    del argv  # interface parity; no flags accepted
    print("true" if codex_available(Path.home(), Path(".")) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
