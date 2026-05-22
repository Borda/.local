#!/usr/bin/env python
"""fetch_gh_data_group1.py — Group 1 parallel gh API data fetch for oss:gh-scraper.

Fetches all GitHub REST + GraphQL data sources with no inter-dependency
(issues, PRs, releases, commits, contributor stats, security alerts,
forks, stargazers, workflows, etc.). Writes one JSON file per dataset
under the output directory; downstream scorers treat missing files as
"data unavailable".

Individual fetch failures are non-fatal — printed to stderr with a
warning prefix; the empty file signals "tried, failed" to scorers.

Usage:
    fetch_gh_data_group1.py --repo <owner/repo> --output-dir <path>
                            [--cutoff-3y <YYYY-MM-DD>]
                            [--cutoff-90d <iso>]
                            [--cutoff-180d <iso>]

Exit: 0 on success (warnings on individual failures); 1 on bad args.
"""

from __future__ import annotations

import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import which

# GitHub allows owner and repo names matching [A-Za-z0-9._-]; we enforce the
# combined ``owner/repo`` shape strictly to defuse URL-path injection (A03:2021).
_REPO_RE = re.compile(r"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$")

_DISCUSSIONS_QUERY = (
    "query($owner:String!,$repo:String!){"
    "repository(owner:$owner,name:$repo){"
    "discussions(first:100,orderBy:{field:UPDATED_AT,direction:DESC}){"
    "nodes { number title closed createdAt }"
    "}}}"
)
_RESPONSIVENESS_QUERY = (
    "query($owner:String!,$repo:String!){"
    "repository(owner:$owner,name:$repo){"
    "issues(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:OPEN){"
    "nodes{number createdAt author{login} comments(first:1){nodes{createdAt author{login}}}}}"
    "pullRequests(first:20,orderBy:{field:CREATED_AT,direction:DESC},states:[OPEN,MERGED]){"
    "nodes{number createdAt author{login}"
    " reviews(states:[APPROVED,CHANGES_REQUESTED,COMMENTED],first:1){nodes{createdAt author{login}}}"
    " comments(first:1){nodes{createdAt author{login}}}}}}}"
)
_REVIEW_COVERAGE_QUERY = (
    "query($owner:String!,$repo:String!){"
    "repository(owner:$owner,name:$repo){"
    "pullRequests(last:30,states:MERGED,orderBy:{field:UPDATED_AT,direction:DESC}){"
    "nodes{number author{login} reviews(states:APPROVED){nodes{author{login}}}}}}}"
)


def _resolve(cmd: str) -> str:
    """Resolve a CLI tool to its absolute path.

    Args:
        cmd: Bare executable name (e.g. ``"gh"``).

    Returns:
        Absolute path to the executable.

    Raises:
        FileNotFoundError: If ``cmd`` is not present on ``PATH``.

    Examples:
        >>> import shutil
        >>> _resolve("gh") == shutil.which("gh") or shutil.which("gh") is None
        True
    """
    p = which(cmd)
    if p is None:
        raise FileNotFoundError(f"executable not found on PATH: {cmd}")
    return p


def _fetch_one(gh: str, name: str, cmd_args: list[str], output_dir: Path) -> tuple[str, bool]:
    """Run one gh command and write result to ``<output_dir>/<name>.json``.

    Args:
        gh: Absolute path to the gh binary.
        name: Dataset name (used as filename stem).
        cmd_args: Arguments passed after the gh binary.
        output_dir: Directory to write the output file.

    Returns:
        ``(name, True)`` on success; ``(name, False)`` on failure.

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    out_path = output_dir / f"{name}.json"
    result = subprocess.run(  # noqa: S603
        [gh, *cmd_args],
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
    )
    if result.returncode == 0:
        out_path.write_text(result.stdout, encoding="utf-8")
        return name, True
    out_path.write_text("", encoding="utf-8")
    print(f"⚠ fetch_gh_data_group1: {name} failed (non-fatal)", file=sys.stderr)
    return name, False


def _build_datasets(
    owner_repo: str,
    cutoff_3y: str,
    cutoff_90d: str,
    cutoff_180d: str,  # noqa: ARG001 — reserved for future axes
) -> list[tuple[str, list[str]]]:
    """Build the full list of ``(name, gh_command_args)`` for all datasets.

    Args:
        owner_repo: ``"owner/repo"`` string.
        cutoff_3y: ISO date string for 3-year lookback (``YYYY-MM-DD``).
        cutoff_90d: ISO datetime string for 90-day lookback.
        cutoff_180d: ISO datetime string for 180-day lookback (reserved).

    Returns:
        List of ``(name, cmd_args)`` tuples, one per dataset.

    Examples:
        >>> ds = _build_datasets("o/r", "2023-01-01", "2023-01-01T00:00:00Z", "2022-07-01T00:00:00Z")
        >>> len(ds) == 21
        True
        >>> ds[0][0]
        'open_issues'
    """
    owner, _, repo = owner_repo.partition("/")
    return [
        (
            "open_issues",
            [
                "issue",
                "list",
                "-R",
                owner_repo,
                "--state",
                "open",
                "--json",
                "number,title,createdAt,updatedAt,labels",
                "--limit",
                "501",
            ],
        ),
        (
            "closed_issues",
            [
                "issue",
                "list",
                "-R",
                owner_repo,
                "--state",
                "closed",
                "--search",
                f"closed:>={cutoff_3y}",
                "--json",
                "number,title,createdAt,closedAt",
                "--limit",
                "1001",
            ],
        ),
        (
            "open_prs",
            [
                "pr",
                "list",
                "-R",
                owner_repo,
                "--state",
                "open",
                "--json",
                "number,title,createdAt,updatedAt,reviews,statusCheckRollup",
                "--limit",
                "201",
            ],
        ),
        (
            "closed_prs",
            [
                "pr",
                "list",
                "-R",
                owner_repo,
                "--state",
                "closed",
                "--json",
                "number,title,createdAt,closedAt,mergedAt",
                "--limit",
                "201",
            ],
        ),
        (
            "commits",
            ["api", f"repos/{owner_repo}/commits?per_page=100", "--jq", "[.[].commit.author.date]"],
        ),
        (
            "releases",
            [
                "api",
                f"repos/{owner_repo}/releases?per_page=10",
                "--jq",
                "[.[] | {tag: .tag_name, published: .published_at, downloads: ([.assets[].download_count] | add // 0)}]",
            ],
        ),
        (
            "contributor_stats",
            [
                "api",
                f"repos/{owner_repo}/stats/contributors",
                "--jq",
                "[.[] | {author: .author.login, total: .total, weeks: .weeks}]",
            ],
        ),
        (
            "root_contents",
            ["api", f"repos/{owner_repo}/contents", "--jq", "[.[] | .name]"],
        ),
        (
            "repo_metadata",
            [
                "api",
                f"repos/{owner_repo}",
                "--jq",
                "{default_branch,has_issues,has_projects,allow_forking,stargazers_count,forks_count,subscribers_count,open_issues_count}",
            ],
        ),
        (
            "dependabot_alerts",
            ["api", f"repos/{owner_repo}/dependabot/alerts?state=open&per_page=100"],
        ),
        (
            "secret_scanning_alerts",
            ["api", f"repos/{owner_repo}/secret-scanning/alerts?state=open"],
        ),
        (
            "fork_dates",
            ["api", f"repos/{owner_repo}/forks?sort=newest&per_page=100", "--jq", "[.[] | .created_at]"],
        ),
        (
            "all_issues",
            [
                "issue",
                "list",
                "-R",
                owner_repo,
                "--state",
                "all",
                "--json",
                "number,title,state,labels,createdAt",
                "--limit",
                "200",
            ],
        ),
        (
            "all_prs",
            [
                "pr",
                "list",
                "-R",
                owner_repo,
                "--state",
                "all",
                "--json",
                "number,title,state,createdAt",
                "--limit",
                "100",
            ],
        ),
        (
            "discussions",
            ["api", "graphql", "-f", f"query={_DISCUSSIONS_QUERY}", "-f", f"owner={owner}", "-f", f"repo={repo}"],
        ),
        (
            "responsiveness_gql",
            ["api", "graphql", "-f", f"query={_RESPONSIVENESS_QUERY}", "-f", f"owner={owner}", "-f", f"repo={repo}"],
        ),
        (
            "review_coverage_gql",
            ["api", "graphql", "-f", f"query={_REVIEW_COVERAGE_QUERY}", "-f", f"owner={owner}", "-f", f"repo={repo}"],
        ),
        (
            "ci_workflows",
            [
                "api",
                f"repos/{owner_repo}/actions/workflows",
                "--jq",
                "{count: (.workflows | length), names: [.workflows[].name]}",
            ],
        ),
        (
            "ci_runs",
            [
                "api",
                f"repos/{owner_repo}/actions/runs?per_page=21",
                "--jq",
                "[.workflow_runs[] | {conclusion: .conclusion, name: .name}]",
            ],
        ),
        (
            "merged_prs_90d",
            [
                "pr",
                "list",
                "-R",
                owner_repo,
                "--state",
                "closed",
                "--search",
                f"merged:>={cutoff_90d}",
                "--json",
                "number,createdAt,mergedAt,author",
                "--limit",
                "201",
            ],
        ),
        (
            "commits_50",
            [
                "api",
                f"repos/{owner_repo}/commits?per_page=50",
                "--jq",
                '[.[] | {sha:.sha[:7], message:(.commit.message | split("\\n")[0]), author:(.author.login // .commit.author.name // "unknown"), date:.commit.author.date}]',
            ],
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    """Entry point — mirrors ``fetch_gh_data_group1.sh`` behaviour.

    Args:
        argv: Optional argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Exit code: 1 on bad args; 0 on success (individual failures non-fatal).

    Examples:
        No doctest — subprocess-dependent; covered by pytest.
    """
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")  # type: ignore[union-attr]
    args = list(sys.argv[1:] if argv is None else argv)

    owner_repo = ""
    output_dir = ""
    cutoff_3y = ""
    cutoff_90d = ""
    cutoff_180d = ""

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--repo":
            i += 1
            owner_repo = args[i] if i < len(args) else ""
        elif a == "--output-dir":
            i += 1
            output_dir = args[i] if i < len(args) else ""
        elif a == "--cutoff-3y":
            i += 1
            cutoff_3y = args[i] if i < len(args) else ""
        elif a == "--cutoff-90d":
            i += 1
            cutoff_90d = args[i] if i < len(args) else ""
        elif a == "--cutoff-180d":
            i += 1
            cutoff_180d = args[i] if i < len(args) else ""
        else:
            print(f"fetch_gh_data_group1: unknown arg '{a}'", file=sys.stderr)
            return 1
        i += 1

    if not owner_repo:
        print("fetch_gh_data_group1: --repo required", file=sys.stderr)
        return 1
    if not _REPO_RE.match(owner_repo):
        print(
            f"fetch_gh_data_group1: --repo must match 'owner/repo' (allowed chars: A-Za-z0-9._-), got: {owner_repo!r}",
            file=sys.stderr,
        )
        return 1
    if not output_dir:
        print("fetch_gh_data_group1: --output-dir required", file=sys.stderr)
        return 1

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    if not cutoff_3y:
        now = datetime.now(tz=timezone.utc)
        cutoff_3y = (now - timedelta(days=1095)).strftime("%Y-%m-%d")
        cutoff_90d = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cutoff_180d = (now - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%SZ")

    gh = _resolve("gh")
    datasets = _build_datasets(owner_repo, cutoff_3y, cutoff_90d, cutoff_180d)

    # Cap concurrency at 10 — running 21 simultaneous `gh api` calls easily
    # triggers GitHub's secondary rate limits (HTTP 403 "abuse detection")
    # which cause silent partial failures across the dataset.
    with ThreadPoolExecutor(max_workers=min(len(datasets), 10)) as executor:
        futures = {executor.submit(_fetch_one, gh, name, cmd_args, out_path): name for name, cmd_args in datasets}
        for future in as_completed(futures):
            future.result()

    count = sum(1 for f in out_path.iterdir() if f.suffix == ".json" and f.is_file())
    print(f"[fetch_gh_data_group1] wrote {count} dataset files → {output_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
