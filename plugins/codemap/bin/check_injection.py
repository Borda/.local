#!/usr/bin/env python
"""check_injection.py — audit which installed SKILL.md and agent .md files contain the codemap injection block.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/check_injection.py" [<claude_plugin_root>]

Output:
    Human-readable ✓/⚠ status lines listing injected files and missing canonical injection sites.

Exit codes:
    0 — audit produced output (success or warnings).
    1 — could not resolve plugin cache root.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Canonical injection-site list — keep in sync with develop, oss, and research plugin skill directories.
# Patterns match relative cache paths; ``.*`` stands in for the plugin-version directory.
# cicd-steward and shepherd are agents (agents/*.md), not skills — no SKILL.md to check; omitted intentionally.
CANONICAL_INJECTION_SITES: tuple[str, ...] = (
    "develop/.*/skills/fix",
    "develop/.*/skills/feature",
    "develop/.*/skills/refactor",
    "develop/.*/skills/plan",
    "develop/.*/skills/review",
    "develop/.*/skills/debug",
    "oss/.*/skills/review",
    "oss/.*/skills/resolve",
    "oss/.*/skills/analyse",
    "oss/.*/skills/release",
    "research/.*/skills/run",
    "research/.*/skills/topic",
)

SKILL_INJECTION_MARKER = "command -v scan-query"
AGENT_INJECTION_MARKER = "Structural context (codemap"
DEFAULT_CACHE_GLOB = "borda-ai-rig/codemap/*"
MAX_AUDIT_FILE_SIZE = 1_000_000  # 1 MB — skip oversized files in marker scan (SEC-M8: DoS guard)

FN_RDEPS_MARKER = "fn-rdeps"
# Skills that must have fn-rdeps in their query block (not just scan-query marker)
FN_RDEPS_REQUIRED_PATTERNS = [
    "plugins/develop/skills/review/SKILL.md",
    "plugins/oss/skills/review/SKILL.md",
    "plugins/develop/skills/_shared/codemap-context.md",
]


@dataclass(frozen=True)
class AuditResult:
    """Outcome of a single injection audit run.

    Attributes:
        exit_code: 0 on success, 1 when cache root could not be resolved.
        lines: status lines to print, in order, each without trailing newline.
    """

    exit_code: int
    lines: tuple[str, ...]


def _is_plausible_plugin_dir(path: Path) -> bool:
    """Return True when ``path`` looks like a real plugin directory.

    A safe plugin directory must (a) exist as a directory, (b) not be ``/`` or
    ``$HOME``, (c) contain at least one plugin marker (``plugin.json``,
    ``.claude-plugin/plugin.json``, ``agents/``, or ``skills/``). This guards
    against unbounded ``rglob`` traversal across the home or root filesystem.
    """
    if not path.is_dir():
        return False
    resolved = path.resolve()
    home = Path(os.path.expanduser("~")).resolve()
    if resolved == Path("/") or resolved == home:
        return False
    markers = (
        resolved / "plugin.json",
        resolved / ".claude-plugin" / "plugin.json",
        resolved / "agents",
        resolved / "skills",
    )
    return any(m.exists() for m in markers)


def resolve_plugin_root(explicit: str | None) -> Path | None:
    """Resolve the codemap plugin install root.

    Falls back to the most recently modified entry under
    ``~/.claude/plugins/cache/borda-ai-rig/codemap/*/skills/integration``.

    The caller-supplied value is canonicalised with :meth:`Path.resolve` and must
    pass :func:`_is_plausible_plugin_dir` — paths resolving outside expected
    plugin directories (e.g. ``/``, ``$HOME``, arbitrary system dirs) are
    rejected and the auto-discovery fallback is used instead (CWE-22).

    Args:
        explicit: caller-supplied path (may be empty/``None``).

    Returns:
        Resolved ``Path`` or ``None`` if neither argument nor fallback succeeded.
    """
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if _is_plausible_plugin_dir(candidate):
            return candidate
        # Reject silently → fall through to auto-discovery (preserves prior UX for missing paths).
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    candidates = sorted(
        home.joinpath(".claude/plugins/cache").glob(DEFAULT_CACHE_GLOB),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    return candidates[0] if candidates else None


def derive_cache_root(plugin_root: Path) -> Path:
    """Return ``CACHE`` directory — parent-of-parent of the resolved plugin root.

    Mirrors the bash ``$(dirname "$(dirname "$PLUGIN_ROOT")")`` two-level walk.

    Args:
        plugin_root: resolved plugin root path.

    Returns:
        Cache directory containing all installed plugin versions.

    Examples:
        >>> from pathlib import Path
        >>> derive_cache_root(Path("/a/b/c/d/e")).as_posix()
        '/a/b/c'
    """
    return plugin_root.parent.parent


def find_files_with_marker(
    root: Path, filename_pattern: str, marker: str, path_substr: str | None = None
) -> list[Path]:
    """Return sorted list of files under ``root`` matching ``filename_pattern`` containing ``marker``.

    Args:
        root: directory to walk.
        filename_pattern: glob filename (e.g. ``"SKILL.md"`` or ``"*.md"``).
        marker: literal substring required inside the file.
        path_substr: optional substring that must appear in the file's path (e.g. ``"/agents/"``).

    Returns:
        Sorted list of matching ``Path`` objects.
    """
    matches: list[Path] = []
    for candidate in root.rglob(filename_pattern):
        if not candidate.is_file():
            continue
        if path_substr is not None and path_substr not in candidate.as_posix():
            continue
        # DoS guard (SEC-M8): skip oversized files; markdown SKILL.md / agent .md files are well under 1 MB.
        try:
            if candidate.stat().st_size > MAX_AUDIT_FILE_SIZE:
                continue
        except OSError:
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker in content:
            matches.append(candidate)
    return sorted(matches)


def missing_canonical_sites(
    relative_paths: list[str], patterns: tuple[str, ...] = CANONICAL_INJECTION_SITES
) -> list[str]:
    """Return the canonical site patterns not represented in ``relative_paths``.

    Args:
        relative_paths: cache-relative paths of injected files (e.g. ``"develop/0.1.0/skills/fix/SKILL.md"``).
        patterns: regex patterns describing required injection sites.

    Returns:
        Patterns that did not match any provided path.

    Examples:
        >>> missing_canonical_sites(
        ...     ["develop/0.1/skills/fix/SKILL.md", "develop/0.1/skills/feature/SKILL.md"],
        ...     ("develop/.*/skills/fix", "develop/.*/skills/feature", "develop/.*/skills/refactor"),
        ... )
        ['develop/.*/skills/refactor']
        >>> missing_canonical_sites([], ("oss/.*/skills/review",))
        ['oss/.*/skills/review']
    """
    compiled = [(pat, re.compile(pat)) for pat in patterns]
    missing: list[str] = []
    for raw, regex in compiled:
        if not any(regex.search(path) for path in relative_paths):
            missing.append(raw)
    return missing


def check_fn_rdeps_wiring(skill_files: list[str]) -> list[str]:
    """Return paths that have scan-query injection but lack fn-rdeps wiring.

    Args:
        skill_files: unused — retained for API symmetry with other audit helpers.

    Returns:
        List of paths from ``FN_RDEPS_REQUIRED_PATTERNS`` that contain the
        scan-query injection marker but do not contain the fn-rdeps marker.

    Examples:
        >>> check_fn_rdeps_wiring([])  # no required files present → empty list
        []
    """
    missing = []
    for path in FN_RDEPS_REQUIRED_PATTERNS:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            continue
        has_injection = SKILL_INJECTION_MARKER in content
        has_fn_rdeps = FN_RDEPS_MARKER in content
        if has_injection and not has_fn_rdeps:
            missing.append(path)
    return missing


def build_audit_lines(cache: Path) -> list[str]:
    """Produce the ordered status lines for an audit of ``cache``.

    Args:
        cache: cache root directory (contains plugin-name/version subtrees).

    Returns:
        Status lines (no trailing newlines) in display order.
    """
    lines: list[str] = ["", f"--- Skill injection audit (cache: {cache}) ---"]

    skill_files = find_files_with_marker(cache, "SKILL.md", SKILL_INJECTION_MARKER)
    cache_prefix = f"{cache.as_posix()}/"
    relative = [p.as_posix().removeprefix(cache_prefix) for p in skill_files]

    if not skill_files:
        lines.append("⚠ 0 SKILL.md files have injection block — codemap not integrated into any skill")
        lines.append("  → Run /codemap:integration init to add injection")
    else:
        lines.append(f"✓ {len(skill_files)} SKILL.md file(s) have the injection block:")
        lines.extend(f"  • {rel}" for rel in relative)

    for missing in missing_canonical_sites(relative):
        lines.append(f"  ⚠ missing injection in: {missing}/SKILL.md")

    agent_files = find_files_with_marker(cache, "*.md", AGENT_INJECTION_MARKER, path_substr="/agents/")
    if not agent_files:
        lines.append("  ⚠ 0 agent .md files have codemap injection block")
    else:
        lines.append(f"✓ {len(agent_files)} agent file(s) have codemap injection block")

    lines.append("")
    lines.append("--- fn-rdeps wiring audit ---")
    fn_rdeps_missing = check_fn_rdeps_wiring(skill_files)
    if fn_rdeps_missing:
        for p in fn_rdeps_missing:
            lines.append(f"  ✗ fn-rdeps missing: {p}")
    else:
        lines.append("  ✓ fn-rdeps wiring present in all required files")

    lines.extend(
        [
            "",
            "--- check complete ---",
            "If any check failed:",
            "  • /codemap:scan-codebase    — build or refresh the index",
            "  • /codemap:integration init — add injection to more skills/agents",
            "  • /codemap:integration check — re-run after fixes",
        ]
    )
    return lines


def run_audit(plugin_root_arg: str | None, cache_root_override: str | None = None) -> AuditResult:
    """Run the audit and return its result (lines + exit code).

    Args:
        plugin_root_arg: caller-supplied plugin root (may be empty).
        cache_root_override: when provided, scan this directory directly as the cache root
            instead of deriving it from ``plugin_root_arg``. Useful for non-standard
            cache locations (e.g. a custom plugin registry). Traversal guards enforced
            here (not only in ``main``) so direct API callers cannot bypass them: the
            resolved path must be an existing directory, must reside within ``$HOME``
            (SEC-M2: blocks unbounded ``rglob`` from ``/``), and must pass
            :func:`_is_plausible_plugin_dir` (SEC-M3).

    Returns:
        ``AuditResult`` capturing exit code and output lines.

    Raises:
        ValueError: If ``cache_root_override`` resolves outside ``$HOME`` or is not
            a plausible plugin directory.
    """
    if cache_root_override:
        cache = Path(cache_root_override).expanduser().resolve()
        if not cache.is_dir():
            return AuditResult(
                exit_code=1,
                lines=(f"✗ --cache-root path not found or not a directory: {cache}",),
            )
        home = Path(os.environ.get("HOME") or os.path.expanduser("~")).resolve()
        try:
            cache.relative_to(home)
        except ValueError as exc:
            raise ValueError(f"cache_root_override {cache} is outside $HOME — refusing to scan") from exc
        if not _is_plausible_plugin_dir(cache):
            raise ValueError(f"cache_root_override {cache} is not a plausible plugin directory — refusing to scan")
        return AuditResult(exit_code=0, lines=tuple(build_audit_lines(cache)))

    plugin_root = resolve_plugin_root(plugin_root_arg)
    if plugin_root is None:
        return AuditResult(
            exit_code=1,
            lines=(
                "✗ Could not locate codemap plugin — injection audit skipped. "
                "Run: claude plugin install codemap@borda-ai-rig",
            ),
        )
    cache = derive_cache_root(plugin_root)
    return AuditResult(exit_code=0, lines=tuple(build_audit_lines(cache)))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: optional argv override for testing.

    Returns:
        Process exit code (0 = success, 1 = could not resolve plugin root).
    """
    parser = argparse.ArgumentParser(
        description="Audit which installed SKILL.md and agent .md files contain the codemap injection block.",
    )
    parser.add_argument(
        "plugin_root",
        nargs="?",
        default="",
        help="Optional path to the codemap plugin install root (auto-discovers if empty).",
    )
    parser.add_argument(
        "--cache-root",
        default="",
        metavar="PATH",
        help=(
            "Explicit path to the plugin cache root directory to scan (e.g. "
            "~/.claude/plugins/cache/borda-ai-rig). "
            "Bypasses plugin-root auto-discovery and the default borda-ai-rig scope; "
            "useful for non-standard cache locations or auditing a custom plugin registry."
        ),
    )
    args = parser.parse_args(argv)

    try:
        result = run_audit(args.plugin_root or None, cache_root_override=args.cache_root or None)
    except ValueError as exc:
        sys.stderr.write(f"! {exc}\n")
        return 1
    sys.stdout.write("\n".join(result.lines) + "\n")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
