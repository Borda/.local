#!/usr/bin/env python3
"""Validate the Codex Rig plugin-only package contract and payload closure."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = PACKAGE_ROOT / "scripts" / "build_package.py"
EXPECTED_SKILLS = {
    "analyse",
    "audit",
    "calibrate",
    "code-remediate",
    "code-review",
    "develop",
    "investigate",
    "kaggle",
    "manage",
    "optimize",
    "release",
    "research",
    "sync",
}
EXPECTED_ROLES = {
    "challenger",
    "cicd-steward",
    "curator",
    "data-steward",
    "delegation-lead",
    "doc-scribe",
    "linting-expert",
    "oss-shepherd",
    "qa-specialist",
    "scientist",
    "security-auditor",
    "solution-architect",
    "squeezer",
    "sw-engineer",
    "web-explorer",
}
PRIVATE_PATH_PATTERN = re.compile(rb"/(?:Users|home)/[^/\s]+")
PRIVATE_KEY_MARKER = b"BEGIN " + b"PRIVATE KEY"


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object for semantic validation."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object: {path.relative_to(PACKAGE_ROOT)}")
    return payload


def validate_semantics() -> None:
    """Validate feature boundaries and exact public rosters."""
    manifest = load_json(PACKAGE_ROOT / "package-manifest.json")
    plugin = load_json(PACKAGE_ROOT / ".codex-plugin" / "plugin.json")
    skill_ids = {item["id"] for item in manifest.get("skills", [])}
    role_ids = {item["id"] for item in manifest.get("roles", [])}
    if skill_ids != EXPECTED_SKILLS or role_ids != EXPECTED_ROLES:
        raise ValueError("public roster mismatch")
    if manifest.get("version") != plugin.get("version") or manifest.get("release_profile") != "plugin-only":
        raise ValueError("plugin identity mismatch")
    if manifest.get("features") != {"manager": False, "hooks": False, "mcp": False, "generated_shims": False}:
        raise ValueError("plugin-only feature boundary mismatch")
    forbidden = (
        PACKAGE_ROOT / "skills" / "agent-shims",
        PACKAGE_ROOT / "hooks",
        PACKAGE_ROOT / ".mcp.json",
    )
    if any(path.exists() for path in forbidden):
        raise ValueError("future lifecycle payload present in plugin-only package")
    if any((PACKAGE_ROOT / "skills" / name).exists() for name in ("review", "resolve")):
        raise ValueError("retired skill present")


def validate_publication_payload() -> None:
    """Reject machine-local paths and obvious credential material in runtime payloads."""
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or "tests" in path.parts or "__pycache__" in path.parts:
            continue
        payload = path.read_bytes()
        if PRIVATE_PATH_PATTERN.search(payload) or PRIVATE_KEY_MARKER in payload:
            raise ValueError(f"private material in payload: {path.relative_to(PACKAGE_ROOT)}")


def parse_args() -> argparse.Namespace:
    """Parse package validation arguments."""
    return argparse.ArgumentParser(description=__doc__).parse_args()


def main() -> None:
    """Run deterministic and semantic package validation."""
    parse_args()
    generated = subprocess.run([sys.executable, str(BUILD_SCRIPT), "--check"], check=False)
    if generated.returncode != 0:
        raise SystemExit(generated.returncode)
    try:
        validate_semantics()
        validate_publication_payload()
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"package-validation-error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    print(f"Package validation passed: {PACKAGE_ROOT}")


if __name__ == "__main__":
    main()
