#!/usr/bin/env python
"""symlink_with_guard.py — foundry-init symlink cleanup and conflict scan.

Encapsulates Phase 1 (obsolete-cleanup) and Phase 2 (conflict-scan) from the
init/SKILL.md symlinking flow. Phase 4 (the actual replacement that depends on
interactive user choices) stays inline in SKILL.md.

Two modes, both consume the same input:

* ``cleanup`` — remove foundry-managed symlinks whose targets no longer exist
  in the current plugin version. Side-effect: deletes stale symlinks. Prints
  ``removed obsolete: <name>`` lines to stdout for each removal. Also purges
  any foundry-managed symlinks lingering under ``~/.claude/agents/`` — agents
  are dispatched directly from the plugin namespace and never need a symlink
  there, so every foundry-managed entry there is by definition obsolete.
* ``scan`` — identify symlink/file entries needing user confirmation. Prints
  one conflict descriptor per line to stdout (ready for bash array consumption
  via ``mapfile -t LINK_CONFLICTS < <(... scan ...)``).

Three iteration patterns are evaluated by both modes (cleanup adds a fourth
agent-purge scope):

1. ``<plugin>/rules/*.md`` ↔ ``$HOME/.claude/rules/*.md``
2. ``<plugin>/TEAM_PROTOCOL.md`` ↔ ``$HOME/.claude/TEAM_PROTOCOL.md`` (single file)
3. ``<plugin>/skills/*/`` ↔ ``$HOME/.claude/skills/*/`` (subdir entries)
4. (cleanup only) ``$HOME/.claude/agents/`` — purge any foundry-managed symlink

Foundry-management is detected by substring match on the readlink target:
default marker ``borda-ai-rig/foundry/``.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/symlink_with_guard.py" cleanup --plugin-root <path> [--home <path>] [--marker <str>]
    python "${CLAUDE_PLUGIN_ROOT}/bin/symlink_with_guard.py" scan    --plugin-root <path> [--home <path>] [--marker <str>]

Exit codes:
    0   success (no failures)
    1   irrecoverable error (missing plugin root, write failure)
    2   argument error
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_MARKER = "borda-ai-rig/foundry/"


@dataclass(frozen=True)
class _Entry:
    """One (source, dest, kind) triple to evaluate.

    Attributes:
        source: Absolute path inside the plugin tree (file or directory).
        dest: Absolute path inside ``$HOME/.claude/`` (symlink target on disk).
        kind: ``"file"`` for files, ``"dir"`` for directories — drives the
            stat predicate used for real-entry detection.
    """

    source: Path
    dest: Path
    kind: str


def _readlink(path: Path) -> str | None:
    """Return ``readlink(path)`` as a string, or ``None`` if not a symlink.

    Args:
        path: Filesystem path to inspect.

    Returns:
        The link target text (not resolved) when ``path`` is a symlink,
        otherwise ``None``.

    Examples:
        >>> _readlink(Path("/nonexistent/path"))
    """
    if not path.is_symlink():
        return None
    try:
        return os.readlink(path)
    except OSError:
        return None


def _is_foundry_managed(target: str, marker: str) -> bool:
    """True when the readlink target contains the foundry marker substring.

    Args:
        target: ``readlink`` output (link's stored target, not resolved).
        marker: Substring identifying foundry-owned paths.

    Returns:
        True iff ``marker`` appears in ``target``.

    Examples:
        >>> _is_foundry_managed("/home/x/.claude/plugins/cache/borda-ai-rig/foundry/0.17.0/rules/x.md", "borda-ai-rig/foundry/")
        True
        >>> _is_foundry_managed("/home/x/local/file.md", "borda-ai-rig/foundry/")
        False
    """
    return marker in target


def _is_current(target: str, plugin_root: Path) -> bool:
    """True when the readlink target lives inside the current plugin root.

    Performs a proper path-prefix comparison (``Path.is_relative_to``) instead
    of a substring match, so a plugin root like ``…/foundry/0.1`` doesn't
    spuriously match a target under ``…/foundry/0.10``. Falls back to the
    substring check when the resolution itself fails (e.g. unresolvable
    symlink target on a foreign filesystem) so the cleanup pass is no more
    aggressive than the legacy behaviour.

    Args:
        target: ``readlink`` output.
        plugin_root: Absolute path of the currently-installed plugin version.

    Returns:
        True iff ``target`` resolves to a path under ``plugin_root``.

    Examples:
        >>> _is_current("/old/0.17.0/rules/a.md", Path("/new/0.18.0"))
        False
    """
    try:
        resolved = Path(os.path.realpath(target) if not os.path.isabs(target) else target)
        return resolved.is_relative_to(plugin_root.resolve())
    except (ValueError, OSError):
        return str(plugin_root) in target  # fallback if resolution fails


def _list_rule_files(plugin_root: Path) -> list[Path]:
    """List ``*.md`` files in ``<plugin_root>/rules``.

    Args:
        plugin_root: Plugin install root.

    Returns:
        Sorted list of rule-file paths (empty when ``rules/`` is absent).
    """
    rules_dir = plugin_root / "rules"
    if not rules_dir.is_dir():
        return []
    return sorted(p for p in rules_dir.iterdir() if p.is_file() and p.suffix == ".md")


def _list_skill_dirs(plugin_root: Path) -> list[Path]:
    """List subdirectories in ``<plugin_root>/skills``.

    Args:
        plugin_root: Plugin install root.

    Returns:
        Sorted list of skill directory paths (empty when ``skills/`` is absent).
    """
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p for p in skills_dir.iterdir() if p.is_dir())


def _build_entries(plugin_root: Path, home: Path) -> list[_Entry]:
    """Build the union of (source, dest, kind) triples for current plugin contents.

    Agents are intentionally absent from this list — they are dispatched
    directly from the plugin's installed namespace (``foundry:sw-engineer``)
    and require no ``~/.claude/agents/`` entry. Stale agent symlinks from
    pre-design installs are purged separately by :func:`cleanup` and are
    therefore never re-created here.

    Args:
        plugin_root: Plugin install root.
        home: Value of ``$HOME``.

    Returns:
        Triples covering rules ``*.md``, ``TEAM_PROTOCOL.md`` (when present in
        the plugin), and skills ``*/`` subdirectories.
    """
    entries: list[_Entry] = []
    rules_target = home / ".claude" / "rules"
    for rule in _list_rule_files(plugin_root):
        entries.append(_Entry(source=rule, dest=rules_target / rule.name, kind="file"))

    team_src = plugin_root / "TEAM_PROTOCOL.md"
    if team_src.is_file():
        entries.append(
            _Entry(source=team_src, dest=home / ".claude" / "TEAM_PROTOCOL.md", kind="file"),
        )

    skills_target = home / ".claude" / "skills"
    for skill_dir in _list_skill_dirs(plugin_root):
        entries.append(_Entry(source=skill_dir, dest=skills_target / skill_dir.name, kind="dir"))
    return entries


def _conflict_label(entry: _Entry, target: str | None) -> str:
    """Render a conflict descriptor consistent with the legacy bash format.

    Format examples (preserved verbatim for back-compat with existing prose):

    * ``rules/foo.md → /other/path/foo.md``
    * ``rules/foo.md  (real file)``
    * ``TEAM_PROTOCOL.md → /other/...``
    * ``skills/curator → /other/...``
    * ``skills/curator  (real entry)``

    Args:
        entry: Triple being labelled.
        target: ``readlink`` output, or ``None`` when the dest is a real file.

    Returns:
        Single conflict line matching the legacy SKILL.md format.

    Examples:
        >>> e = _Entry(Path("/p/rules/foo.md"), Path("/d/rules/foo.md"), "file")
        >>> _conflict_label(e, "/elsewhere/foo.md")
        'rules/foo.md → /elsewhere/foo.md'
        >>> _conflict_label(e, None)
        'rules/foo.md  (real file)'
        >>> ts = _Entry(Path("/p/TEAM_PROTOCOL.md"), Path("/d/TEAM_PROTOCOL.md"), "file")
        >>> _conflict_label(ts, "/elsewhere/team.md")
        'TEAM_PROTOCOL.md → /elsewhere/team.md'
        >>> sk = _Entry(Path("/p/skills/curator"), Path("/d/skills/curator"), "dir")
        >>> _conflict_label(sk, None)
        'skills/curator  (real entry)'
    """
    name = entry.source.name
    if entry.dest.name == "TEAM_PROTOCOL.md":
        prefix = "TEAM_PROTOCOL.md"
    elif entry.kind == "dir":
        prefix = f"skills/{name}"
    else:
        prefix = f"rules/{name}"

    if target is None:
        real_kind = "real entry" if entry.kind == "dir" else "real file"
        return f"{prefix}  ({real_kind})"
    return f"{prefix} → {target}"


def _existing_dest_symlinks(target_dir: Path) -> list[Path]:
    """Yield all symlinks directly under ``target_dir`` (non-recursive).

    Args:
        target_dir: Directory to scan; missing dirs return an empty list.

    Returns:
        Sorted list of symlink paths.
    """
    if not target_dir.is_dir():
        return []
    return sorted(p for p in target_dir.iterdir() if p.is_symlink())


def cleanup(plugin_root: Path, home: Path, marker: str) -> list[str]:
    """Remove foundry-managed symlinks whose source no longer exists.

    Four scopes evaluated. Three are conditional (rules files, TEAM_PROTOCOL.md,
    skill dirs) — the link is removed only when ALL three predicates hold:

    * the readlink target contains the foundry ``marker`` substring,
    * the readlink target does NOT resolve under ``plugin_root`` (stale, not current),
    * the matching source does not exist in the current plugin tree.

    The fourth scope (``~/.claude/agents/``) is unconditional: every foundry-managed
    symlink there is obsolete by design. Agents are dispatched directly from the
    plugin namespace and never need an entry under ``~/.claude/agents/``; any
    such symlink is left over from an earlier install flow and is purged on
    every cleanup pass with no source-existence check.

    Args:
        plugin_root: Currently-installed plugin root.
        home: Value of ``$HOME``.
        marker: Substring identifying foundry-managed targets.

    Returns:
        List of ``"removed obsolete: <name>"`` / ``"removed obsolete skill: <name>"``
        / ``"removed obsolete agent: <name>"`` log lines (also implies stdout
        side-effect when invoked via :func:`main`).
    """
    log: list[str] = []
    rules_dest = home / ".claude" / "rules"
    skills_dest = home / ".claude" / "skills"
    agents_dest = home / ".claude" / "agents"
    team_dest = home / ".claude" / "TEAM_PROTOCOL.md"

    # --- rules/*.md ---
    for link_path in _existing_dest_symlinks(rules_dest):
        target = _readlink(link_path)
        if target is None or not _is_foundry_managed(target, marker):
            continue
        if _is_current(target, plugin_root):
            continue
        if not (plugin_root / "rules" / link_path.name).is_file():
            try:
                link_path.unlink()
            except OSError:
                continue
            log.append(f"removed obsolete: {link_path.name}")

    # --- TEAM_PROTOCOL.md ---
    if team_dest.is_symlink():
        target = _readlink(team_dest)
        if target is not None and _is_foundry_managed(target, marker) and not _is_current(target, plugin_root):
            if not (plugin_root / "TEAM_PROTOCOL.md").is_file():
                try:
                    team_dest.unlink()
                    log.append("removed obsolete: TEAM_PROTOCOL.md")
                except OSError:
                    pass

    # --- skills/*/ ---
    for link_path in _existing_dest_symlinks(skills_dest):
        target = _readlink(link_path)
        if target is None or not _is_foundry_managed(target, marker):
            continue
        if _is_current(target, plugin_root):
            continue
        if not (plugin_root / "skills" / link_path.name).is_dir():
            try:
                link_path.unlink()
            except OSError:
                continue
            log.append(f"removed obsolete skill: {link_path.name}")

    # --- agents/ (unconditional purge) ---
    # No source-existence check — agents are dispatched from the plugin
    # namespace and are never (re-)created in ~/.claude/agents/. Any
    # foundry-managed symlink lingering here is by definition obsolete.
    for link_path in _existing_dest_symlinks(agents_dest):
        target = _readlink(link_path)
        if target is None or not _is_foundry_managed(target, marker):
            continue
        if _is_current(target, plugin_root):
            # A symlink under the current plugin root would still be obsolete
            # by design — we never create them — but leaving it gives a clear
            # signal that something outside init is staging it. Skip removal
            # so the operator can investigate.
            continue
        try:
            link_path.unlink()
        except OSError:
            continue
        log.append(f"removed obsolete agent: {link_path.name}")

    return log


def scan(plugin_root: Path, home: Path, marker: str) -> list[str]:
    """Identify dest entries needing user confirmation before symlink replacement.

    Stale foundry symlinks are auto-replaced in Phase 4 without prompting; only
    these states surface as conflicts:

    * dest is a real file (not a symlink),
    * dest is a symlink whose target is not foundry-managed.

    Args:
        plugin_root: Currently-installed plugin root.
        home: Value of ``$HOME``.
        marker: Substring identifying foundry-managed targets.

    Returns:
        Sorted list of conflict descriptor strings, one per affected dest.
    """
    conflicts: list[str] = []
    for entry in _build_entries(plugin_root, home):
        if entry.dest.is_symlink():
            target = _readlink(entry.dest)
            if target is None:
                continue
            if _is_current(target, plugin_root):
                continue
            if _is_foundry_managed(target, marker):
                # stale foundry version — auto-replace in Phase 4 (no prompt)
                continue
            conflicts.append(_conflict_label(entry, target))
        elif entry.dest.exists():
            conflicts.append(_conflict_label(entry, None))
    return conflicts


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns process exit code."""
    parser = argparse.ArgumentParser(
        prog="symlink_with_guard",
        description="foundry-init symlink cleanup and conflict scan (Phases 1 + 2).",
    )
    parser.add_argument(
        "mode",
        choices=("cleanup", "scan"),
        help="`cleanup` removes obsolete foundry-managed symlinks; `scan` prints conflicts.",
    )
    parser.add_argument(
        "--plugin-root",
        required=True,
        metavar="PATH",
        help="Absolute path of the currently-installed foundry plugin version.",
    )
    parser.add_argument(
        "--home",
        default=None,
        metavar="PATH",
        help="Override $HOME (default: value from environment).",
    )
    parser.add_argument(
        "--marker",
        default=_DEFAULT_MARKER,
        metavar="STR",
        help=f"Substring identifying foundry-managed symlink targets (default: {_DEFAULT_MARKER!r}).",
    )
    args = parser.parse_args(argv)

    if not args.marker:
        print("symlink_with_guard: --marker cannot be empty", file=sys.stderr)
        return 2

    plugin_root = Path(args.plugin_root)
    if not plugin_root.is_dir():
        print(
            f"error: --plugin-root {args.plugin_root!r} is not a directory",
            file=sys.stderr,
        )
        return 1

    home = Path(args.home) if args.home else Path(os.path.expanduser("~"))
    if not home.is_dir():
        print(f"error: home directory {str(home)!r} is not a directory", file=sys.stderr)
        return 1

    if args.mode == "cleanup":
        for line in cleanup(plugin_root, home, args.marker):
            print(f"  {line}")
        return 0

    # mode == "scan"
    for conflict in scan(plugin_root, home, args.marker):
        print(conflict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
