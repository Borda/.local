#!/usr/bin/env python3
"""Create one portable timestamped Codex Rig artifact directory."""

from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path


SKILL_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


def parse_args() -> argparse.Namespace:
    """Parse the run-directory creation contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, help="Canonical lowercase skill identifier")
    parser.add_argument("--root", type=Path, default=Path(".reports") / "codex", help="Artifact root")
    arguments = parser.parse_args()
    if SKILL_ID.fullmatch(arguments.skill) is None:
        parser.error("invalid skill id")
    return arguments


def main() -> int:
    """Create the directory and print its path for later explicit arguments."""
    arguments = parse_args()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-%fZ")
    run_directory = arguments.root / arguments.skill / timestamp
    run_directory.mkdir(parents=True, exist_ok=False)
    print(run_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
