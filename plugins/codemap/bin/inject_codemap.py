#!/usr/bin/env python
"""inject_codemap.py — discover and inject the codemap context block into candidate SKILL.md files.

Scans ``<plugin-root>/skills/*/SKILL.md``, scores each candidate for codemap relevance, and (with
``--apply``) injects an optional codemap-context block before the first step heading. A ``.bak`` backup is
created before any write, and restored on write failure.

Usage:
    python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/inject_codemap.py" \
        --plugin-root <path> [--apply] [--dry-run] [--verbose]

Output:
    A JSON report (stdout) describing each candidate's score, action, and (in apply mode) write outcome.

Exit codes:
    0 — report produced (dry-run or apply, including no-candidate case).
    1 — plugin root not found or not a directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _injection_block import (
    BLOCK as INJECTION_BLOCK,
)
from _injection_block import (
    BLOCK_VERSION,
)
from _injection_block import (
    MARKER as INJECTION_MARKER,
)
from _injection_block import (
    parse_block_version,
    replace_block_region,
    save_integration_sites,
)

# Score contributions — see _score_content. Threshold: >=2 inject, ==1 manual suggestion, 0 skip.
HIGH_SCORE_THRESHOLD = 2
MEDIUM_SCORE_THRESHOLD = 1

PYTHON_MARKERS: tuple[str, ...] = (".py", "import", "pyproject.toml")
BASH_BLOCK_MARKER = "```bash"
SOURCE_OP_MARKERS: tuple[str, ...] = ("Read(", "Edit(", "grep", "find")
INTEGRATION_MARKERS: tuple[str, ...] = ("scan-query", "codemap")

# Matches the first "## Step 1" or "### Step 1" heading at the start of a line.
STEP_HEADING_RE = re.compile(r"^#{2,3}\s+Step\s+1\b", re.MULTILINE)


@dataclass
class Candidate:
    """Scored injection candidate.

    Attributes:
        path: SKILL.md path, relative to the current working directory when possible.
        score: relevance score in the range 0–4.
        action: ``"inject"`` (score >= 2), ``"manual"`` (score == 1), or ``"skip"`` (score == 0).
        backed_up: whether a ``.bak`` backup was written (apply mode only).
        injected: whether the block was written into the file (apply mode only).
        error: error message when an apply-mode write failed, else ``None``.
    """

    path: str
    score: int
    action: str
    backed_up: bool = False
    injected: bool = False
    error: str | None = None


def _score_content(content: str) -> int:
    """Return the codemap relevance score (0–4) for SKILL.md ``content``.

    Args:
        content: full text of a SKILL.md file.

    Returns:
        Integer score: +1 Python reference, +1 bash block, +1 source-file op, +1 not already integrated.

    Examples:
        >>> _score_content("import os\\n```bash\\nls\\n```\\nRead(file)")
        4
        >>> _score_content("uses scan-query already\\nimport os")
        1
        >>> _score_content("plain prose with no markers")
        1
    """
    score = 0
    if any(marker in content for marker in PYTHON_MARKERS):
        score += 1
    if BASH_BLOCK_MARKER in content:
        score += 1
    if any(marker in content for marker in SOURCE_OP_MARKERS):
        score += 1
    if not any(marker in content for marker in INTEGRATION_MARKERS):
        score += 1
    return score


def _action_for_score(score: int) -> str:
    """Map a score to its action label.

    Args:
        score: relevance score (0–4).

    Returns:
        ``"inject"`` for score >= 2, ``"manual"`` for score == 1, ``"skip"`` otherwise.

    Examples:
        >>> _action_for_score(3)
        'inject'
        >>> _action_for_score(1)
        'manual'
        >>> _action_for_score(0)
        'skip'
    """
    if score >= HIGH_SCORE_THRESHOLD:
        return "inject"
    if score == MEDIUM_SCORE_THRESHOLD:
        return "manual"
    return "skip"


def inject_block(content: str, block: str = INJECTION_BLOCK) -> str:
    """Return ``content`` with the current ``block`` present, inserting or refreshing as needed.

    Version-aware and idempotent:

    * Block absent → insert ``block`` before the first ``## Step 1``/``### Step 1`` heading, or
      append it (with a separating blank line) when no step heading exists.
    * Block present and current (its ``codemap-block: vN`` stamp equals :data:`BLOCK_VERSION`) →
      return ``content`` unchanged.
    * Block present but outdated (stamp differs from :data:`BLOCK_VERSION`) → replace only the
      sentinel-bounded region with ``block``, preserving any user text outside the sentinels.

    Args:
        content: original SKILL.md text.
        block: injection block to insert (defaults to the current codemap context block).

    Returns:
        New file text with the up-to-date block present exactly once.

    Examples:
        >>> inject_block("intro only\\n").count(INJECTION_MARKER)
        1
        >>> already = inject_block("intro only\\n")
        >>> inject_block(already) == already  # current block → no-op
        True
    """
    if INJECTION_MARKER in content:
        found_version = parse_block_version(content)
        if found_version == BLOCK_VERSION:
            return content
        return replace_block_region(content, block)
    match = STEP_HEADING_RE.search(content)
    if match is None:
        separator = "" if content.endswith("\n") else "\n"
        return f"{content}{separator}\n{block}"
    head = content[: match.start()]
    tail = content[match.start() :]
    return f"{head}{block}{tail}"


def _relative_path(path: Path) -> str:
    """Return ``path`` relative to the current working directory when possible, else its posix form.

    Args:
        path: filesystem path to render.

    Returns:
        A forward-slash path string suitable for JSON output.
    """
    try:
        return path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def discover_candidates(plugin_root: Path) -> list[Path]:
    """Return sorted SKILL.md paths under ``<plugin_root>/skills/*/SKILL.md``.

    Args:
        plugin_root: resolved plugin root directory.

    Returns:
        Sorted list of existing SKILL.md file paths (one level under ``skills/``).
    """
    skills_dir = plugin_root / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(p for p in skills_dir.glob("*/SKILL.md") if p.is_file())


# Personal-skill / agent discovery globs, resolved relative to a base directory. Personal skills and
# agents authored outside any plugin are durable by nature (they live in the project or user home, not
# the wipe-on-update plugin cache), so init prefers them as injection targets.
_PERSONAL_GLOBS: tuple[str, ...] = (
    ".claude/skills/*/SKILL.md",
    ".claude/agents/*.md",
)
_USER_GLOBS: tuple[str, ...] = (
    ".claude/skills/*/SKILL.md",
    ".claude/agents/*.md",
)


def discover_personal_candidates(project_root: Path, home: Path | None = None) -> list[Path]:
    """Return sorted personal-skill and agent files discovered outside any plugin cache.

    Globs ``project_root/.claude/skills/*/SKILL.md``, ``project_root/.claude/agents/*.md`` and the
    same patterns under the user home (``~/.claude/...``). These targets are durable — they survive
    ``claude plugin install`` because they are not part of the wipe-on-update plugin cache.

    Args:
        project_root: project root (typically the git root) to scan under ``.claude``.
        home: user home to scan under ``.claude`` (defaults to :meth:`Path.home`).

    Returns:
        Sorted, de-duplicated list of existing personal SKILL.md / agent .md paths.
    """
    home = home if home is not None else Path.home()
    found: set[Path] = set()
    for pattern in _PERSONAL_GLOBS:
        found.update(p for p in project_root.glob(pattern) if p.is_file())
    for pattern in _USER_GLOBS:
        found.update(p for p in home.glob(pattern) if p.is_file())
    return sorted(found)


def _check_path_within_root(path: Path, allowed_root: Path) -> bool:
    """Return True when ``path`` resolves inside ``allowed_root`` (SEC-M1: CWE-22).

    Args:
        path: Candidate path to validate (will be resolved).
        allowed_root: Allowed root directory (already resolved).

    Returns:
        True if ``path`` resolves to ``allowed_root`` or a descendant; False otherwise.

    Examples:
        >>> _check_path_within_root(Path("/a/b/c.bak"), Path("/a/b"))
        True
        >>> _check_path_within_root(Path("/a/x/c.bak"), Path("/a/b"))
        False
    """
    try:
        path.resolve().relative_to(allowed_root.resolve())
        return True
    except ValueError:
        return False


def _apply_injection(path: Path, content: str, candidate: Candidate, allowed_root: Path) -> None:
    """Inject the block into ``path`` in place, with backup and rollback, recording outcome on ``candidate``.

    Creates ``<path>.bak`` before writing. The backup path is validated against ``allowed_root`` before
    creation (SEC-M1: CWE-22 — path traversal guard). On write failure, restores from the backup and
    records the error message on ``candidate``; the backup is removed only after a successful write.

    Args:
        path: SKILL.md file to modify.
        content: already-read original file content.
        candidate: candidate record to update with ``backed_up``/``injected``/``error``.
        allowed_root: Resolved plugin root; backup path must stay within this root.
    """
    backup = path.with_suffix(path.suffix + ".bak")
    # SEC-M1: verify the .bak path does not escape the plugin root via symlinks or traversal
    if not _check_path_within_root(backup, allowed_root):
        candidate.error = f"backup path escapes plugin root (path traversal guard): {backup}"
        return
    try:
        shutil.copy2(path, backup)
        candidate.backed_up = True
    except OSError as exc:
        candidate.error = f"backup failed: {exc}"
        return
    try:
        path.write_text(inject_block(content), encoding="utf-8")
        candidate.injected = True
        backup.unlink(missing_ok=True)
    except OSError as exc:
        candidate.error = f"write failed: {exc}"
        _restore_backup(backup, path, candidate)


def _restore_backup(backup: Path, path: Path, candidate: Candidate) -> None:
    """Restore ``path`` from ``backup`` after a failed write, appending any restore error to ``candidate``.

    Args:
        backup: backup file created before the write attempt.
        path: target file to restore.
        candidate: candidate record whose ``error`` is extended on restore failure.
    """
    try:
        shutil.move(str(backup), str(path))
        candidate.backed_up = False
    except OSError as restore_exc:
        candidate.error = f"{candidate.error}; restore failed: {restore_exc}"


def evaluate_candidate(path: Path, apply: bool, allowed_root: Path) -> Candidate:
    """Score a single SKILL.md candidate and, in apply mode, inject when the score is High.

    Args:
        path: SKILL.md file to evaluate.
        apply: when True, write the injection block for inject-action candidates.
        allowed_root: Resolved plugin root; passed to :func:`_apply_injection` for path traversal guard.

    Returns:
        A populated :class:`Candidate` record.
    """
    rel = _relative_path(path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        return Candidate(path=rel, score=0, action="skip", error=f"read failed: {exc}")
    score = _score_content(content)
    candidate = Candidate(path=rel, score=score, action=_action_for_score(score))
    if apply and candidate.action == "inject":
        _apply_injection(path, content, candidate, allowed_root=allowed_root)
    return candidate


def _record_integration_sites(
    candidates: list[Candidate], project_root: Path, integration_dir: Path | None
) -> str | None:
    """Persist injected-candidate paths to ``integration.json`` under the project cache dir.

    Records project-relative paths for injected candidates so ``check_injection`` can audit exactly
    the sites init wired — including personal skills that live outside any plugin cache.

    Args:
        candidates: evaluated candidates (only those with ``injected`` set are recorded).
        project_root: project root recorded paths are made relative to when possible.
        integration_dir: project cache dir to write ``integration.json`` into (``None`` → skip).

    Returns:
        The written record path as a string, or ``None`` when nothing was persisted.
    """
    if integration_dir is None:
        return None
    injected = [c.path for c in candidates if c.injected]
    if not injected:
        return None
    sites = [_project_relative(Path(p), project_root) for p in injected]
    return save_integration_sites(integration_dir, sites).as_posix()


def _project_relative(path: Path, project_root: Path) -> str:
    """Return ``path`` relative to ``project_root`` when possible, else its posix form."""
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_report(
    plugin_root: Path,
    apply: bool,
    project_root: Path | None = None,
    integration_dir: Path | None = None,
    home: Path | None = None,
) -> dict[str, object]:
    """Discover, score, and (optionally) inject candidates, returning the JSON-serialisable report.

    Candidates are the plugin's own ``skills/*/SKILL.md`` plus any personal skills and agents under
    ``.claude`` (project and user home). In apply mode the injected site paths are persisted to
    ``integration.json`` so ``check_injection`` audits exactly the wired sites.

    Args:
        plugin_root: resolved plugin root directory.
        apply: when True, inject into High-score candidates; otherwise dry-run only.
        project_root: project root for personal-skill discovery and relative site recording
            (defaults to the current working directory).
        integration_dir: project cache dir to persist ``integration.json`` into (apply mode only).
        home: user home for personal-skill discovery (defaults to :meth:`Path.home`; injected in tests
            to keep discovery hermetic).

    Returns:
        Dict with ``mode``, ``candidates`` (list of dicts), a ``summary`` count breakdown, and (in
        apply mode) ``integration_record`` naming the persisted record path when one was written.
    """
    allowed_root = plugin_root.resolve()
    root = project_root if project_root is not None else Path.cwd()
    plugin_paths = [evaluate_candidate(p, apply, allowed_root=allowed_root) for p in discover_candidates(plugin_root)]
    # Personal skills/agents are durable — allow injection into their own tree, not just plugin_root.
    personal = [
        evaluate_candidate(p, apply, allowed_root=p.parent) for p in discover_personal_candidates(root, home=home)
    ]
    candidates = plugin_paths + personal
    summary = {
        "high": sum(c.action == "inject" for c in candidates),
        "medium": sum(c.action == "manual" for c in candidates),
        "skip": sum(c.action == "skip" for c in candidates),
        "applied": sum(c.injected for c in candidates),
    }
    report: dict[str, object] = {
        "mode": "apply" if apply else "dry-run",
        "candidates": [asdict(c) for c in candidates],
        "summary": summary,
    }
    if apply:
        record = _record_integration_sites(candidates, root, integration_dir)
        if record is not None:
            report["integration_record"] = record
    return report


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: optional argv override for testing.

    Returns:
        Parsed namespace with ``plugin_root``, ``apply``, ``dry_run``, and ``verbose`` attributes.
    """
    parser = argparse.ArgumentParser(
        description="Discover and inject the codemap context block into candidate SKILL.md files.",
    )
    parser.add_argument("--plugin-root", required=True, metavar="PATH", help="Path to the plugin root directory.")
    parser.add_argument("--apply", action="store_true", help="Write injections (default is dry-run).")
    parser.add_argument("--dry-run", action="store_true", help="Report only; never write (default behaviour).")
    parser.add_argument("--verbose", action="store_true", help="Emit per-candidate diagnostics on stderr.")
    parser.add_argument(
        "--project-root",
        default="",
        metavar="PATH",
        help="Project root for personal-skill discovery and relative site recording (default: cwd).",
    )
    parser.add_argument(
        "--integration-dir",
        default="",
        metavar="PATH",
        help="Cache dir to persist integration.json into on apply (default: <project-root>/.cache/codemap).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: optional argv override for testing.

    Returns:
        Process exit code (0 = report produced, 1 = plugin root not found).
    """
    args = _parse_args(argv)
    plugin_root = Path(args.plugin_root).expanduser().resolve()
    if not plugin_root.is_dir():
        sys.stderr.write(f"! --plugin-root not found or not a directory: {plugin_root}\n")
        return 1

    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else Path.cwd()
    integration_dir = (
        Path(args.integration_dir).expanduser() if args.integration_dir else project_root / ".cache" / "codemap"
    )
    apply = args.apply and not args.dry_run
    report = build_report(plugin_root, apply, project_root=project_root, integration_dir=integration_dir)

    if args.verbose:
        for candidate in report["candidates"]:  # type: ignore[union-attr]
            sys.stderr.write(f"[{candidate['action']}] score={candidate['score']} {candidate['path']}\n")

    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
