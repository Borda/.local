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
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Score contributions — see _score_content. Threshold: >=2 inject, ==1 manual suggestion, 0 skip.
HIGH_SCORE_THRESHOLD = 2
MEDIUM_SCORE_THRESHOLD = 1

PYTHON_MARKERS: tuple[str, ...] = (".py", "import", "pyproject.toml")
BASH_BLOCK_MARKER = "```bash"
SOURCE_OP_MARKERS: tuple[str, ...] = ("Read(", "Edit(", "grep", "find")
INTEGRATION_MARKERS: tuple[str, ...] = ("scan-query", "codemap")

# Matches the first "## Step 1" or "### Step 1" heading at the start of a line.
STEP_HEADING_RE = re.compile(r"^#{2,3}\s+Step\s+1\b", re.MULTILINE)

INJECTION_BLOCK = """## Codemap context (optional — skip if index absent)

```bash
_CM_SQ=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/locate_scan_query.py" 2>/dev/null || echo "")
if [ -n "$_CM_SQ" ]; then
  "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/scan-index" --incremental 2>/dev/null || true
fi
```

> If codemap index available, use `/codemap:query-code` for symbol definitions and call graphs.

"""


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
    """Return ``content`` with ``block`` inserted before the first step heading (or appended).

    Args:
        content: original SKILL.md text.
        block: injection block to insert (defaults to the codemap context block).

    Returns:
        New file text with the block inserted before the first ``## Step 1``/``### Step 1`` heading,
        or appended (with a separating blank line) when no step heading exists.

    Examples:
        >>> inject_block("intro\\n## Step 1\\ndo it\\n", "BLOCK\\n").splitlines()[1]
        'BLOCK'
        >>> inject_block("intro only\\n", "BLOCK\\n").rstrip().endswith("BLOCK")
        True
    """
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


def build_report(plugin_root: Path, apply: bool) -> dict[str, object]:
    """Discover, score, and (optionally) inject candidates, returning the JSON-serialisable report.

    Args:
        plugin_root: resolved plugin root directory.
        apply: when True, inject into High-score candidates; otherwise dry-run only.

    Returns:
        Dict with ``mode``, ``candidates`` (list of dicts), and a ``summary`` count breakdown.
    """
    allowed_root = plugin_root.resolve()
    candidates = [evaluate_candidate(p, apply, allowed_root=allowed_root) for p in discover_candidates(plugin_root)]
    summary = {
        "high": sum(c.action == "inject" for c in candidates),
        "medium": sum(c.action == "manual" for c in candidates),
        "skip": sum(c.action == "skip" for c in candidates),
        "applied": sum(c.injected for c in candidates),
    }
    return {
        "mode": "apply" if apply else "dry-run",
        "candidates": [asdict(c) for c in candidates],
        "summary": summary,
    }


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

    apply = args.apply and not args.dry_run
    report = build_report(plugin_root, apply)

    if args.verbose:
        for candidate in report["candidates"]:  # type: ignore[union-attr]
            sys.stderr.write(f"[{candidate['action']}] score={candidate['score']} {candidate['path']}\n")

    sys.stdout.write(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
