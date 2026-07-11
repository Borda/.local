#!/usr/bin/env python3
"""Select a local Git remote that matches an authoritative repository URL."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    """Represent a normalized Git host and owner/repository path."""

    host: str
    repository: str


def parse_repository_url(raw_url: str) -> RepositoryIdentity:
    """Parse Git, SSH, or pull-request URLs into a repository identity."""
    value = raw_url.strip()
    scp_match = re.fullmatch(r"(?:[^@]+@)?([^:]+):(.+)", value)
    if scp_match and "://" not in value:
        host, path = scp_match.groups()
    else:
        parsed = urlparse(value)
        host = parsed.hostname or ""
        path = parsed.path
    parts = [part for part in path.strip("/").split("/") if part]
    if "pull" in parts:
        parts = parts[: parts.index("pull")]
    if len(parts) < 2 or not host:
        raise ValueError(f"unrecognized-repository-url:{raw_url}")
    repository = "/".join(parts[:2])
    if repository.endswith(".git"):
        repository = repository[:-4]
    return RepositoryIdentity(host=host.lower(), repository=repository.lower())


def read_remotes(cwd: Path) -> dict[str, list[str]]:
    """Read every configured fetch URL without contacting a remote service."""
    names = subprocess.run(
        ["git", "remote"],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    remotes: dict[str, list[str]] = {}
    for name in names:
        urls = subprocess.run(
            ["git", "remote", "get-url", "--all", name],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        remotes[name] = [url for url in urls if url]
    return remotes


def select_remote(expected_url: str, remotes: dict[str, list[str]]) -> dict[str, object]:
    """Select a deterministic remote whose normalized identity matches expected."""
    expected = parse_repository_url(expected_url)
    matches: list[tuple[str, str]] = []
    rejected: dict[str, list[str]] = {}
    for name, urls in remotes.items():
        for url in urls:
            try:
                identity = parse_repository_url(url)
            except ValueError:
                rejected.setdefault(name, []).append(url)
                continue
            if identity == expected:
                matches.append((name, url))
    matches.sort(key=lambda item: (item[0] != "origin", item[0], item[1]))
    if not matches:
        raise ValueError(f"no-matching-remote:{expected.host}/{expected.repository}")
    selected_name, selected_url = matches[0]
    return {
        "expected": asdict(expected),
        "remote": selected_name,
        "remote_url": selected_url,
        "matching_remotes": [{"name": name, "url": url} for name, url in matches],
        "unparseable_urls": rejected,
    }


def main() -> int:
    """Parse arguments and emit the selected matching remote as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-url", required=True, help="Authoritative GitHub PR or repository URL.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Local repository used for remote matching.")
    parser.add_argument(
        "--identity-only", action="store_true", help="Return normalized host/repository identity without Git lookup."
    )
    args = parser.parse_args()
    try:
        if args.identity_only:
            payload = asdict(parse_repository_url(args.expected_url))
        else:
            payload = select_remote(args.expected_url, read_remotes(args.cwd))
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
