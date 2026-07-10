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

from _injection_block import (
    BLOCK_VERSION,
    SCAN_QUERY_MARKER,
    load_integration_sites,
    parse_block_version,
)

# Default canonical injection-site list for the borda-ai-rig distribution — used when those plugins
# are present and no per-project ``integration.json`` record overrides it. Patterns match relative
# cache paths; ``.*`` stands in for the plugin-version directory. cicd-steward and shepherd are
# agents (agents/*.md), not skills — no SKILL.md to check; omitted intentionally.
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

# Injection marker sourced from the single-source-of-truth block module so init and check never drift.
SKILL_INJECTION_MARKER = SCAN_QUERY_MARKER
AGENT_INJECTION_MARKER = "Structural context (codemap"
DEFAULT_CACHE_GLOB = "borda-ai-rig/codemap/*"
MAX_AUDIT_FILE_SIZE = 1_000_000  # 1 MB — skip oversized files in marker scan (SEC-M8: DoS guard)

FN_RDEPS_MARKER = "fn-rdeps"

GATE_WIRING_MARKER = "codemap-gates.md"
GATE_WIRING_INLINE_MARKER = "Gate A — missing index"


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


def classify_block_version(path: Path) -> str:
    """Return ``"current"`` or ``"outdated"`` for the injected block in ``path``.

    Compares the file's ``codemap-block: vN`` stamp against :data:`BLOCK_VERSION`. A file with the
    injection marker but no parseable stamp is treated as ``"outdated"`` (a legacy, pre-versioning
    block that a re-inject should refresh).

    Args:
        path: an injected SKILL.md file.

    Returns:
        ``"current"`` when the stamp equals the shipped block version, else ``"outdated"``.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "outdated"
    return "current" if parse_block_version(content) == BLOCK_VERSION else "outdated"


def audit_recorded_sites(sites: list[str], base_dir: Path) -> list[str]:
    """Return per-site PASS/OUTDATED/MISSING status lines for init-recorded injection sites.

    Each recorded site is a path (absolute, or relative to ``base_dir`` — typically the project root)
    checked directly rather than via the plugin-cache scan, so personal skills under ``.claude/skills``
    or ``.claude/agents`` are audited by name. A recorded file that no longer carries the injection
    marker reports MISSING (e.g. after a plugin update wiped a cache target); a marker present but
    version-stamped below :data:`BLOCK_VERSION` reports OUTDATED.

    Args:
        sites: recorded site paths from ``integration.json``.
        base_dir: directory recorded relative paths resolve against.

    Returns:
        Status lines (no trailing newlines), one per recorded site.
    """
    lines: list[str] = []
    for site in sites:
        path = Path(site) if Path(site).is_absolute() else base_dir / site
        if not _file_has_marker(path, SCAN_QUERY_MARKER):
            lines.append(f"  ⚠ MISSING injection: {site} — run /codemap:integration init to (re)inject")
        elif classify_block_version(path) == "outdated":
            lines.append(f"  ⟳ OUTDATED block (v{BLOCK_VERSION} available): {site} — re-inject via init")
        else:
            lines.append(f"  ✓ {site}")
    return lines


def borda_default_sites(cache: Path) -> tuple[str, ...]:
    """Return the borda-ai-rig canonical site patterns when those plugins are present in ``cache``.

    Args:
        cache: plugin cache root being audited.

    Returns:
        :data:`CANONICAL_INJECTION_SITES` when any of develop/oss/research is installed, else ``()``.
    """
    if any((cache / plugin).is_dir() for plugin in ("develop", "oss", "research")):
        return CANONICAL_INJECTION_SITES
    return ()


def _file_has_marker(path: Path, *markers: str) -> bool:
    """Return True when ``path`` is readable and contains any of ``markers``.

    Args:
        path: file to read.
        markers: one or more literal substrings; any match suffices.

    Returns:
        True when the file is readable, within size limit, and contains at least one marker.
    """
    try:
        if path.stat().st_size > MAX_AUDIT_FILE_SIZE:
            return False
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(m in content for m in markers)


def check_fn_rdeps_wiring(skill_files: list[Path]) -> list[Path]:
    """Return injected review-skill files that lack fn-rdeps wiring.

    Filters ``skill_files`` to those whose immediate parent directory name
    contains ``"review"`` (content-agnostic heuristic that works for any plugin
    layout, not just borda-ai-rig).

    Args:
        skill_files: SKILL.md paths that already contain the codemap injection marker.

    Returns:
        Paths from ``skill_files`` that match the review heuristic but lack fn-rdeps wiring.

    Examples:
        >>> check_fn_rdeps_wiring([])
        []
    """
    return [p for p in skill_files if "review" in p.parent.name and not _file_has_marker(p, FN_RDEPS_MARKER)]


def check_gate_wiring(skill_files: list[Path]) -> list[Path]:
    """Return injected SKILL.md files that lack Gate A/B wiring.

    Every file with the codemap injection marker must also have gate wiring —
    either via the shared ``codemap-gates.md`` load directive or inline gate text.
    Works for any plugin layout; no hardcoded plugin-name assumptions.

    Args:
        skill_files: SKILL.md paths that already contain the codemap injection marker.

    Returns:
        Paths from ``skill_files`` that lack gate wiring.

    Examples:
        >>> check_gate_wiring([])
        []
    """
    return [p for p in skill_files if not _file_has_marker(p, GATE_WIRING_MARKER, GATE_WIRING_INLINE_MARKER)]


def _skill_status_lines(skill_files: list[Path], cache_prefix: str) -> list[str]:
    """Return the per-file PASS/OUTDATED status lines for injected skill files.

    Each injected file is classified by :func:`classify_block_version`: a current block prints ``✓``,
    an outdated block prints ``⟳`` with a re-inject hint (distinct from the MISSING case handled by
    :func:`missing_canonical_sites`).

    Args:
        skill_files: SKILL.md paths carrying the injection marker.
        cache_prefix: cache-root prefix to strip for display.

    Returns:
        Status lines (no trailing newlines).
    """
    if not skill_files:
        return [
            "⚠ 0 SKILL.md files have injection block — codemap not integrated into any skill",
            "  → Run /codemap:integration init to add injection",
        ]
    outdated = [p for p in skill_files if classify_block_version(p) == "outdated"]
    lines = [f"✓ {len(skill_files)} SKILL.md file(s) have the injection block:"]
    for p in skill_files:
        rel = p.as_posix().removeprefix(cache_prefix)
        mark = "⟳ OUTDATED" if p in outdated else "✓ current"
        lines.append(f"  • {rel} — {mark}")
    if outdated:
        lines.append(f"  ⟳ {len(outdated)} block(s) OUTDATED (block v{BLOCK_VERSION} available)")
        lines.append("  → Run /codemap:integration init to re-inject the current block")
    return lines


def _canonical_site_lines(cache: Path, integration_dir: Path | None, relative: list[str]) -> list[str]:
    """Return the canonical-site audit lines, preferring the per-project ``integration.json`` record.

    When ``integration_dir`` holds a recorded site list, each recorded site is audited directly by
    path (personal ``.claude/skills`` targets included). Otherwise the borda default patterns are
    matched against the cache-relative ``relative`` paths of injected files.

    Args:
        cache: plugin cache root being audited.
        integration_dir: project cache dir (``.cache/codemap``) that may hold ``integration.json``.
        relative: cache-relative paths of injected skill files (borda-default path).

    Returns:
        Status lines (no trailing newlines).
    """
    recorded = load_integration_sites(integration_dir) if integration_dir is not None else None
    if recorded:
        base_dir = integration_dir.parent.parent  # <root>/.cache/codemap → <root>
        header = [f"  (canonical sites from {integration_dir.as_posix()}/integration.json)"]
        return header + audit_recorded_sites(recorded, base_dir)
    return [
        f"  ⚠ missing injection in: {missing}/SKILL.md"
        for missing in missing_canonical_sites(relative, borda_default_sites(cache))
    ]


def build_audit_lines(cache: Path, integration_dir: Path | None = None) -> list[str]:
    """Produce the ordered status lines for an audit of ``cache``.

    Args:
        cache: cache root directory (contains plugin-name/version subtrees).
        integration_dir: optional project cache dir (``.cache/codemap``) holding ``integration.json``;
            when present its recorded sites drive the canonical-site check instead of the borda default.

    Returns:
        Status lines (no trailing newlines) in display order.
    """
    lines: list[str] = ["", f"--- Skill injection audit (cache: {cache}) ---"]

    skill_files = find_files_with_marker(cache, "SKILL.md", SKILL_INJECTION_MARKER)
    cache_prefix = f"{cache.as_posix()}/"
    relative = [p.as_posix().removeprefix(cache_prefix) for p in skill_files]

    lines.extend(_skill_status_lines(skill_files, cache_prefix))
    lines.extend(_canonical_site_lines(cache, integration_dir, relative))

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
            lines.append(f"  ✗ fn-rdeps missing: {p.as_posix().removeprefix(cache_prefix)}")
    else:
        lines.append("  ✓ fn-rdeps wiring present in all injected review skill files")

    lines.append("")
    lines.append("--- Gate A/B wiring audit ---")
    gate_missing = check_gate_wiring(skill_files)
    if gate_missing:
        for p in gate_missing:
            lines.append(f"  ✗ Gate A/B missing: {p.as_posix().removeprefix(cache_prefix)}")
    else:
        lines.append("  ✓ Gate A/B wiring present in all injected skill files")

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


def _resolve_integration_dir(explicit: str | None) -> Path | None:
    """Return the project cache dir holding ``integration.json``, or ``None``.

    Uses the explicit value when given; otherwise honours ``CODEMAP_INDEX_DIR`` and finally falls
    back to ``<cwd>/.cache/codemap``. The path is only returned when it exists as a directory so the
    audit silently ignores a stranger project that never ran init.

    Args:
        explicit: caller-supplied path to the project cache dir (may be empty/``None``).

    Returns:
        Existing project cache dir, or ``None`` when none is present.
    """
    if explicit:
        candidate = Path(explicit).expanduser()
    else:
        env_dir = os.environ.get("CODEMAP_INDEX_DIR")
        candidate = Path(env_dir) if env_dir else Path.cwd() / ".cache" / "codemap"
    return candidate if candidate.is_dir() else None


def run_audit(
    plugin_root_arg: str | None,
    cache_root_override: str | None = None,
    integration_dir_arg: str | None = None,
) -> AuditResult:
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
        integration_dir_arg: caller-supplied project cache dir holding ``integration.json``;
            when absent it is resolved from ``CODEMAP_INDEX_DIR`` or ``<cwd>/.cache/codemap``.

    Returns:
        ``AuditResult`` capturing exit code and output lines.

    Raises:
        ValueError: If ``cache_root_override`` resolves outside ``$HOME`` or is not
            a plausible plugin directory.
    """
    integration_dir = _resolve_integration_dir(integration_dir_arg)
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
        return AuditResult(exit_code=0, lines=tuple(build_audit_lines(cache, integration_dir)))

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
    return AuditResult(exit_code=0, lines=tuple(build_audit_lines(cache, integration_dir)))


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
    parser.add_argument(
        "--integration-dir",
        default="",
        metavar="PATH",
        help=(
            "Project cache dir holding integration.json (default: $CODEMAP_INDEX_DIR or "
            "<cwd>/.cache/codemap). When present, its recorded sites drive the canonical-site check."
        ),
    )
    args = parser.parse_args(argv)

    try:
        result = run_audit(
            args.plugin_root or None,
            cache_root_override=args.cache_root or None,
            integration_dir_arg=args.integration_dir or None,
        )
    except ValueError as exc:
        sys.stderr.write(f"! {exc}\n")
        return 1
    sys.stdout.write("\n".join(result.lines) + "\n")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
