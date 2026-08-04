#!/usr/bin/env python
"""release_append_marker.py — persist and resolve the /oss:release notes --append baseline.

``--append`` needs to know where the *previous* ``notes``/``prepare`` run left
off, so the next invocation only re-classifies commits landed since then
instead of re-deriving the full ``$LAST_TAG..HEAD`` range. The marker is a
single commit SHA per branch, stored under the project's ``.temp/`` dir
rather than a git-tracked path — losing it degrades safely to the existing
non-append behaviour (full range, full DRAFT.md overwrite), never to a
broken or duplicated draft.

Marker location: ``.temp/release-last-processed-<branch>`` — deliberately
*not* date-stamped like this skill's other ``.temp/release-*-$BRANCH-$DATE``
artifacts, since it must survive across days/sessions, not just one run.
``.temp/`` is gitignored (see plugins/CLAUDE.md "Contributor email privacy"
convention already used by this skill) and is documented TTL-managed at
~30 days; on loss, ``resolve`` falls back to ``$LAST_TAG..HEAD`` and the
caller treats it as a fresh append baseline (see SKILL.md ``--append`` flag
docs) — a graceful reset, not data loss, so a git-tracked location (e.g.
``releases/.last-processed-<branch>``) was not required here.

**Two invalidation checks, both required for "valid"**:

1. **Reachability** (``_is_valid_commit``) — ``git merge-base --is-ancestor
   <sha> HEAD``, not ``git cat-file -e``. The latter only tests object-database
   existence; a commit orphaned by rebase/force-push stays reflog-protected
   (~90 days by default) and would still report "exists", silently
   re-including already-drafted rewritten-SHA commits in the "incremental"
   range instead of falling back to full-overwrite.
2. **Tag supersession** (``_tag_advanced_past``) — a release tag cut between
   two ``--append`` runs (via ``prepare`` or external ``git tag``) makes an
   otherwise-reachable marker stale: ``<marker>..HEAD`` would straddle the tag
   boundary and re-draft already-released commits. When the tag lands at or
   after the marker, fall back to ``<last_tag>..HEAD`` instead.

Subcommands:
    is-valid  Print "true"/"false" — does a marker exist, resolve to a
              commit still an ancestor of HEAD, AND sit at/after ``--last-tag``
              (not superseded by a later release cut)?
    resolve   Print the RANGE to use for --append (marker..HEAD when valid per
              both checks above, else <last-tag>..HEAD); prints an info/warn
              note to stderr.
    write     Persist the current HEAD sha as the new marker (call after a
              successful notes-mode write, append or full).

Usage:
    release_append_marker.py is-valid --branch <branch> --last-tag <tag>
    release_append_marker.py resolve --branch <branch> --last-tag <tag>
    release_append_marker.py write --branch <branch> --sha <sha>

Exit codes:
    0 — always (caller branches on stdout content, not exit code)
    2 — bad/missing required argument (argparse default)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from shutil import which


def _marker_path(branch: str, marker_dir: str | None) -> Path:
    """Resolve the marker file path for a branch.

    Args:
        branch: Branch slug (already ``/`` → ``-`` normalized by the caller).
        marker_dir: Override directory (tests / non-default layouts); defaults
            to ``.temp`` under the current working directory.

    Examples:
        >>> _marker_path("main", "/tmp/x").as_posix()
        '/tmp/x/release-last-processed-main'
    """
    base = Path(marker_dir) if marker_dir else Path(".temp")
    return base / f"release-last-processed-{branch}"


def _is_valid_commit(sha: str) -> bool:
    """Return True when ``sha`` is an ancestor of HEAD in this repo.

    Uses ``git merge-base --is-ancestor`` (reachability from HEAD), not
    ``git cat-file -e`` (mere object-database existence) — a rebased/reset-away
    commit stays reflog-protected (~90 days by default ``gc.reflogExpire``) so
    ``cat-file -e`` would report it "valid" long after it stopped being real
    history, silently re-including already-drafted rewritten-SHA commits in
    the "incremental" range instead of falling back to full-overwrite.

    Args:
        sha: Candidate commit SHA read from the marker file.

    Returns:
        False for an empty/blank sha, when git is unavailable, or when ``sha``
        is not (or no longer) an ancestor of HEAD (e.g. after a force-push or
        rebase rewrote history and orphaned it).
    """
    if not sha:
        return False
    git = which("git")
    if git is None:
        return False
    result = subprocess.run(  # noqa: S603
        [git, "merge-base", "--is-ancestor", sha, "HEAD"],
        capture_output=True,
        check=False,
        timeout=5,
    )
    return result.returncode == 0


def _tag_advanced_past(marker_sha: str, last_tag: str) -> bool:
    """Return True when ``last_tag`` was cut at or after ``marker_sha``.

    A release tag landing between two ``--append`` runs (via ``prepare`` or
    external ``git tag``) makes a still-valid marker stale: trusting it would
    compute ``<marker>..HEAD``, which straddles the tag boundary and re-drafts
    commits that already shipped in that release. When the marker is at or
    behind the tag, the caller should prefer ``<last_tag>..HEAD`` instead.

    Args:
        marker_sha: The stored marker commit.
        last_tag: Tag ref/name (or any revision git can resolve) to compare against.

    Returns:
        True when ``marker_sha`` is an ancestor of (or equal to) ``last_tag``
        — a release was cut at/after the marker. False when ``last_tag`` is
        empty, git is unavailable, ``last_tag`` doesn't resolve (e.g. no
        stable tags yet), or ``last_tag`` predates the marker (the normal,
        safe case — nothing to do).
    """
    if not marker_sha or not last_tag:
        return False
    git = which("git")
    if git is None:
        return False
    result = subprocess.run(  # noqa: S603
        [git, "merge-base", "--is-ancestor", marker_sha, last_tag],
        capture_output=True,
        check=False,
        timeout=5,
    )
    return result.returncode == 0


def _read_marker(branch: str, marker_dir: str | None) -> str:
    """Read the stored marker sha for a branch, or "" if absent/unreadable.

    Args:
        branch: Branch slug.
        marker_dir: Override directory (see :func:`_marker_path`).

    Returns:
        Stripped sha string, or "" when the marker file is missing/unreadable.
    """
    try:
        return _marker_path(branch, marker_dir).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def cmd_is_valid(args: argparse.Namespace) -> int:
    """Print "true"/"false" for whether a usable marker exists.

    Requires ``--last-tag`` too (not just ancestor-of-HEAD) so this agrees
    with ``resolve``'s RANGE computation — a marker superseded by a later tag
    must report "false" here as well, or the Write-release-draft phase would
    merge-mode a DRAFT.md whose Gather-changes phase actually used the full
    ``$LAST_TAG..HEAD`` range (mismatch between what was gathered and how it
    gets written).

    Args:
        args: Namespace with ``branch``, ``last_tag``, ``marker_dir``.

    Returns:
        Always 0.
    """
    sha = _read_marker(args.branch, args.marker_dir)
    valid = _is_valid_commit(sha) and not _tag_advanced_past(sha, args.last_tag)
    print("true" if valid else "false")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    """Print the --append RANGE to stdout; print an info/warn note to stderr.

    Args:
        args: Namespace with ``branch``, ``last_tag``, ``marker_dir``.

    Returns:
        Always 0.
    """
    sha = _read_marker(args.branch, args.marker_dir)
    valid = _is_valid_commit(sha)
    superseded = valid and _tag_advanced_past(sha, args.last_tag)
    if valid and not superseded:
        print(f"ℹ append: resuming from marker {sha[:12]} (incremental range)", file=sys.stderr)
        print(f"{sha}..HEAD")
        return 0
    if superseded:
        print(
            f"⚠ append: {args.last_tag} was cut at/after marker {sha[:12]} — falling back to "
            f"{args.last_tag}..HEAD (marker superseded by a release tag)",
            file=sys.stderr,
        )
    elif sha:
        print(
            f"⚠ append: marker sha {sha[:12]} not found in history (rebase/force-push?)"
            f" — falling back to {args.last_tag}..HEAD",
            file=sys.stderr,
        )
    else:
        print(
            f"ℹ append: no prior marker — establishing first append baseline from {args.last_tag}..HEAD",
            file=sys.stderr,
        )
    print(f"{args.last_tag}..HEAD")
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    """Persist ``--sha`` as the new marker for ``--branch``.

    Args:
        args: Namespace with ``branch``, ``sha``, ``marker_dir``.

    Returns:
        Always 0.
    """
    path = _marker_path(args.branch, args.marker_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(args.sha.strip() + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the requested subcommand.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code (always 0; argparse exits 2 on bad/missing args).
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        prog="release_append_marker.py",
        description="Persist and resolve the /oss:release notes --append baseline marker.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_valid = sub.add_parser("is-valid", help="Print true/false for whether a usable, non-superseded marker exists.")
    p_valid.add_argument("--branch", required=True)
    p_valid.add_argument("--last-tag", required=True)
    p_valid.add_argument("--marker-dir", default=None)

    p_resolve = sub.add_parser("resolve", help="Print the --append RANGE (marker..HEAD or last-tag..HEAD).")
    p_resolve.add_argument("--branch", required=True)
    p_resolve.add_argument("--last-tag", required=True)
    p_resolve.add_argument("--marker-dir", default=None)

    p_write = sub.add_parser("write", help="Persist the current HEAD sha as the new marker.")
    p_write.add_argument("--branch", required=True)
    p_write.add_argument("--sha", required=True)
    p_write.add_argument("--marker-dir", default=None)

    args = parser.parse_args(argv)
    if args.command == "is-valid":
        return cmd_is_valid(args)
    if args.command == "resolve":
        return cmd_resolve(args)
    return cmd_write(args)


if __name__ == "__main__":
    sys.exit(main())
