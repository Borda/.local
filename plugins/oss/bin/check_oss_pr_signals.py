#!/usr/bin/env python
"""check_oss_pr_signals.py — collect OSS-relevant signals from a PR diff.

Runs four read-only git/gh checks against a GitHub PR and emits a JSON
document summarising findings:

1. **Dependency changes** — diff against ``pyproject.toml`` / ``requirements*.txt``
   (license-compatibility surface).
2. **Possible secrets** — grep added ``.py`` lines for password/secret/api_key/
   token/private_key/auth_token assignments with values 8+ chars long.
3. **API stability — removed exports** — exports removed from
   ``src/**/__init__.py``; flagged as ``DEPRECATION_NEEDED`` when the symbol
   was present in the latest release tag, else ``UNRELEASED_REMOVAL``. No tag
   resolvable → ``NO_RELEASE_TAG``.
4. **CHANGELOG diff** — ``CHANGELOG.md`` / ``CHANGES.md`` changes (presence of
   release-notes update).

Usage:
    check_oss_pr_signals.py --clean-args <PR#> [--latest-tag <tag>] \\
                            [--output-file <path>] [--timeout <seconds>]

Default ``--timeout`` is 30 s — matches the longest subprocess inside the
loop (``git show`` per removed export). When ``--latest-tag`` is omitted the
script resolves it via ``git describe --tags --abbrev=0``; empty result is
treated as "no release tag".

Exit codes:
    0 — JSON written (empty/missing data is non-fatal)
    1 — bad argv (missing --clean-args) or invalid CLEAN_ARGS value
    2 — gh/git binary not on PATH
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from shutil import which


# CLEAN_ARGS is a numeric PR identifier — accept digits only to guard against
# argv injection into the gh diff path glob. Mirrors Step 1 PR-number validation.
_PR_NUMBER_RE = re.compile(r"^[0-9]+$")

# Secret-pattern grep — same as the original SKILL.md inline regex; case-insensitive,
# matches `key=value` or `key: value` with a quoted/unquoted value of 8+ chars.
_SECRET_RE = re.compile(
    r"(password|secret|api_key|token|private_key|auth_token)\s*[=:]\s*['\"]?[A-Za-z0-9+/._\-]{8,}['\"]?",
    re.IGNORECASE,
)

# Identifier extractor — picks up Python symbol names from removed diff lines.
_IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")


@dataclass(slots=True)
class OssSignals:
    """Aggregated PR signals — serialised to JSON by ``main()``.

    Attributes:
        deps_diff: Raw ``gh pr diff`` output for dependency files (str).
        secret_matches: Lines from ``.py`` diff matching the secrets regex.
        removed_exports: Symbol names removed from ``src/**/__init__.py``.
        deprecation_findings: Per-symbol verdict for removed exports.
        latest_tag: Tag used for the deprecation check (``""`` if unresolved).
        changelog_diff: Raw diff for ``CHANGELOG.md`` / ``CHANGES.md``.
    """

    deps_diff: str = ""
    secret_matches: list[str] = field(default_factory=list)
    removed_exports: list[str] = field(default_factory=list)
    deprecation_findings: list[str] = field(default_factory=list)
    latest_tag: str = ""
    changelog_diff: str = ""


def _resolve(cmd: str) -> str:
    """Resolve a CLI tool to its absolute path.

    Args:
        cmd: Bare executable name (e.g. ``"gh"``).

    Returns:
        Absolute path to the executable.

    Raises:
        FileNotFoundError: If ``cmd`` is not on ``PATH``.

    Examples:
        >>> import shutil
        >>> _resolve("python") == shutil.which("python")
        True
    """
    p = which(cmd)
    if p is None:
        raise FileNotFoundError(f"executable not found on PATH: {cmd}")
    return p


def _run(cmd: list[str], timeout: int) -> str:
    """Run a subprocess, return stdout — never raises on non-zero.

    Args:
        cmd: Command argv (first element is absolute path).
        timeout: Per-call timeout in seconds.

    Returns:
        Stdout (decoded). Empty string on non-zero exit or timeout.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ""
    return proc.stdout


def _resolve_latest_tag(git: str, timeout: int) -> str:
    """Return latest tag via ``git describe --tags --abbrev=0`` — ``""`` if none.

    Args:
        git: Absolute path to git.
        timeout: Subprocess timeout in seconds.

    Returns:
        Tag string (stripped) or ``""``.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    return _run([git, "describe", "--tags", "--abbrev=0"], timeout=timeout).strip()


def _grep_secrets(diff_text: str) -> list[str]:
    """Return lines from ``diff_text`` matching the secret regex.

    Args:
        diff_text: Concatenated ``gh pr diff`` output for ``.py`` files.

    Returns:
        List of matching lines (preserves order, deduplicated).

    Examples:
        >>> _grep_secrets("+password = 'hunter22hunter'\\n+x = 1\\n")
        ["+password = 'hunter22hunter'"]
        >>> _grep_secrets("+x = 1\\n")
        []
        >>> _grep_secrets("+API_KEY=abcdef12345")
        ['+API_KEY=abcdef12345']
    """
    seen: set[str] = set()
    out: list[str] = []
    for line in diff_text.splitlines():
        if _SECRET_RE.search(line) and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _extract_removed_exports(init_diff: str) -> list[str]:
    """Pull symbol names from removed (``^-``) lines of an ``__init__.py`` diff.

    Args:
        init_diff: Output of ``gh pr diff -- :(glob)src/**/__init__.py``.

    Returns:
        Sorted, deduplicated symbol names.

    Examples:
        >>> _extract_removed_exports("-from .x import Foo\\n-Bar = 1\\n+keep")
        ['Bar', 'Foo', 'from', 'import', 'x']
        >>> _extract_removed_exports("--- a/x\\n+++ b/x\\n+keep_me\\n")
        []
        >>> _extract_removed_exports("")
        []
    """
    syms: set[str] = set()
    for line in init_diff.splitlines():
        # Skip the diff header lines (---/+++) and unchanged context.
        if not line.startswith("-") or line.startswith("---"):
            continue
        # ``line[1:]`` strips the leading ``-``.
        syms.update(_IDENT_RE.findall(line[1:]))
    return sorted(syms)


def _check_deprecations(
    git: str,
    latest_tag: str,
    removed_exports: list[str],
    timeout: int,
) -> list[str]:
    """For each removed export, decide DEPRECATION_NEEDED vs UNRELEASED_REMOVAL.

    Args:
        git: Absolute path to git.
        latest_tag: Tag to inspect (``""`` → ``NO_RELEASE_TAG`` verdict).
        removed_exports: Symbol names removed from ``__init__.py``.
        timeout: Per-call subprocess timeout in seconds.

    Returns:
        One verdict line per removed export (or a single
        ``NO_RELEASE_TAG: ...`` line when ``latest_tag`` is empty).

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    if not latest_tag:
        return ["NO_RELEASE_TAG: cannot determine release history — skip deprecation check"]
    if not removed_exports:
        return []
    findings: list[str] = []
    for export in removed_exports:
        prior = _run(
            [git, "show", f"{latest_tag}", "--", ":(glob)src/**/__init__.py"],
            timeout=timeout,
        )
        if export in prior:
            findings.append(f"DEPRECATION_NEEDED: {export} (present in {latest_tag} — was released)")
        else:
            findings.append(
                f"UNRELEASED_REMOVAL: {export} (absent from {latest_tag} — clean removal OK, no deprecation needed)"
            )
    return findings


def collect_signals(
    clean_args: str,
    latest_tag: str,
    timeout: int,
    gh: str,
    git: str,
) -> OssSignals:
    """Run all four checks against the PR and return aggregated signals.

    Args:
        clean_args: Numeric PR identifier.
        latest_tag: Pre-resolved latest tag (``""`` → script will resolve via git).
        timeout: Per-subprocess timeout in seconds.
        gh: Absolute path to ``gh``.
        git: Absolute path to ``git``.

    Returns:
        Populated :class:`OssSignals` dataclass.

    Examples:
        No doctest — subprocess-dependent; covered by pytest with monkeypatch.
    """
    deps_diff = _run(
        [gh, "pr", "diff", clean_args, "--", "pyproject.toml", "requirements*.txt"],
        timeout=timeout,
    )
    py_diff = _run([gh, "pr", "diff", clean_args, "--", "*.py"], timeout=timeout)
    secrets = _grep_secrets(py_diff)
    init_diff = _run(
        [gh, "pr", "diff", clean_args, "--", ":(glob)src/**/__init__.py"],
        timeout=timeout,
    )
    removed = _extract_removed_exports(init_diff)
    effective_tag = latest_tag or _resolve_latest_tag(git, timeout=timeout)
    deprecations = _check_deprecations(git, effective_tag, removed, timeout=timeout)
    changelog_diff = _run(
        [gh, "pr", "diff", clean_args, "--", "CHANGELOG.md", "CHANGES.md"],
        timeout=timeout,
    )
    return OssSignals(
        deps_diff=deps_diff,
        secret_matches=secrets,
        removed_exports=removed,
        deprecation_findings=deprecations,
        latest_tag=effective_tag,
        changelog_diff=changelog_diff,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` on success, ``1`` on invalid argv, ``2`` on missing gh/git.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    parser = argparse.ArgumentParser(
        prog="check_oss_pr_signals.py",
        description="Collect OSS-relevant signals (deps, secrets, deprecations, CHANGELOG) from a PR diff.",
    )
    parser.add_argument("--clean-args", required=True, type=str, help="PR number (digits only).")
    parser.add_argument(
        "--latest-tag",
        type=str,
        default="",
        help="Latest release tag; if empty, resolved via 'git describe --tags --abbrev=0'.",
    )
    parser.add_argument(
        "--output-file",
        type=str,
        default="",
        help="Write JSON to this path; default empty → write to stdout.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Max subprocess wait in seconds (default: 30).",
    )
    args = parser.parse_args(argv)

    if not _PR_NUMBER_RE.match(args.clean_args):
        print(
            f"check_oss_pr_signals: --clean-args must be a numeric PR number, got {args.clean_args!r}",
            file=sys.stderr,
        )
        return 1

    try:
        gh = _resolve("gh")
        git = _resolve("git")
    except FileNotFoundError as exc:
        print(f"check_oss_pr_signals: {exc}", file=sys.stderr)
        return 2

    signals = collect_signals(
        clean_args=args.clean_args,
        latest_tag=args.latest_tag,
        timeout=args.timeout,
        gh=gh,
        git=git,
    )
    payload = json.dumps(asdict(signals), indent=2, sort_keys=True)
    if args.output_file:
        Path(args.output_file).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
