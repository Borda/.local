#!/usr/bin/env python3
"""Create one portable timestamped artifact directory for a Codex Rig workflow.

## Purpose

Give each workflow invocation an isolated, predictable evidence location without requiring shell-specific timestamp handling. The generated directory is the handoff point that later helpers use for all run-scoped evidence and results.

## Scope

It validates a canonical skill identifier and creates one local directory; it neither writes a review result nor starts a workflow. Directory names use a UTC timestamp with microseconds, so separate invocations are not intentionally merged into one artifact run.

## Usage

Run ``python create_run.py --skill <canonical-skill-id>`` once and use the printed path literally in later commands. Pass ``--root`` when a workflow owns a different local artifact root; the skill ID remains the final path component under that root.

## Used by

Every artifact-producing workflow skill and portable workflow-helper tests use this creator. Downstream commands depend on its stdout path rather than recomputing timestamps or assuming a shell-specific date utility.

## Outputs

It prints the newly created artifact path, named by UTC timestamp beneath ``.reports/codex/<skill>/`` unless an explicit root is supplied. The directory is created with ``exist_ok=False`` so a collision cannot silently redirect two workflow invocations into the same run.

## Failure

An invalid canonical skill ID or an unwritable target directory exits non-zero before later workflow commands receive a path. Existing timestamp collisions and filesystem errors likewise propagate as failures, leaving callers responsible for deciding whether to retry with a new run.
"""

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
