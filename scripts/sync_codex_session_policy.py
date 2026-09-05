#!/usr/bin/env python3
"""Synchronize the repository's normal-session model policy into Codex home.

Updates only ``model`` and ``review_model`` in ``CODEX_HOME/config.toml``.

Maintains one authenticated personal-policy block in ``CODEX_HOME/AGENTS.md``. All unrelated configuration and
instructions remain user-owned.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import tempfile
from pathlib import Path


BEGIN_PREFIX = "<!-- borda-local:session-model-policy begin sha256="
END_MARKER = "<!-- borda-local:session-model-policy end -->\n"
BEGIN_PATTERN = re.compile(r"<!-- borda-local:session-model-policy begin sha256=([0-9a-f]{64}) -->\n")
MODEL_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<spelling>model|review_model|"
    '"model"|"review_model"|'
    "'model'|'review_model')"
    r"(?P<separator>\s*=\s*)(?P<value>"
    r'"(?:[^"\\]|\\.)*"'
    r"|'[^']*')(?P<suffix>\s*(?:#.*)?)$"
)
MODEL_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?:model|review_model|"
    '"model"|"review_model"|'
    "'model'|'review_model')"
    r"\s*="
)
TABLE_PATTERN = re.compile(r"^\s*\[")
MANAGED_KEYS = frozenset({"model", "review_model"})


class SyncError(ValueError):
    """Report a configuration state unsafe to update automatically."""


def _sha256(payload: str) -> str:
    """Return the SHA-256 digest for UTF-8 text."""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_text(path: Path, label: str) -> str:
    """Read one ordinary UTF-8 file with a bounded ownership check."""
    if path.is_symlink() or not path.is_file():
        raise SyncError(f"{label} must be an ordinary file: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise SyncError(f"{label} must be UTF-8: {path}") from error


def _source_models(path: Path) -> dict[str, str]:
    """Extract the two root model assignments from the repository config."""
    models: dict[str, str] = {}
    in_table = False
    for line in _read_text(path, "source config").splitlines():
        if TABLE_PATTERN.match(line):
            in_table = True
        if in_table:
            continue
        match = MODEL_PATTERN.fullmatch(line)
        if match is None:
            if MODEL_ASSIGNMENT_PATTERN.match(line):
                raise SyncError("source config has an unsupported model string assignment")
            continue
        key = match.group("spelling").strip("\"'")
        value = match.group("value")
        if key in models:
            raise SyncError(f"source config has duplicate {key} assignments")
        models[key] = value
    if models.keys() != MANAGED_KEYS:
        raise SyncError("source config must define exactly one model and review_model assignment")
    return models


def _replace_models(existing: str, models: dict[str, str]) -> str:
    """Replace managed root settings while preserving table settings and comments.

    Values in ``models`` must already be quoted TOML string literals. Insert
    missing managed keys before the first table, or at the end of a table-free
    document. Raise ``SyncError`` for duplicate or unsupported root assignments.
    Return new text without reading or writing any files.

    Examples:
        >>> models = {"model": '"primary"', "review_model": '"reviewer"'}
        >>> print(_replace_models("[profile]\\nmodel = 'custom'\\n", models))
        model = "primary"
        review_model = "reviewer"
        [profile]
        model = 'custom'
        <BLANKLINE>
    """
    seen: set[str] = set()
    lines: list[str] = []
    insertion_index: int | None = None
    in_table = False
    for line in existing.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body) :]
        if TABLE_PATTERN.match(body):
            in_table = True
            if insertion_index is None:
                insertion_index = len(lines)
        if in_table:
            lines.append(line)
            continue
        match = MODEL_PATTERN.fullmatch(body)
        if match is None:
            if MODEL_ASSIGNMENT_PATTERN.match(body):
                raise SyncError("target config has an unsupported model string assignment")
            lines.append(line)
            continue
        key = match.group("spelling").strip("\"'")
        if key in seen:
            raise SyncError(f"target config has duplicate {key} assignments")
        seen.add(key)
        line_ending = ending or "\n"
        lines.append(
            f"{match.group('indent')}{match.group('spelling')}{match.group('separator')}"
            f"{models[key]}{match.group('suffix')}{line_ending}"
        )
    missing = [f"{key} = {models[key]}\n" for key in sorted(MANAGED_KEYS - seen)]
    if missing:
        index = insertion_index if insertion_index is not None else len(lines)
        if index and not lines[index - 1].endswith("\n"):
            lines[index - 1] += "\n"
        lines[index:index] = missing
    return "".join(lines)


def _policy_block(policy: str) -> str:
    """Wrap policy text in checksum-bearing ownership markers.

    Ensure a trailing newline before computing the UTF-8 digest. Reject nested
    ownership markers with ``SyncError``; the checksum detects changed content
    but does not authenticate its author.

    Examples:
        >>> _policy_block("Example policy") == _policy_block("Example policy\\n")
        True
        >>> _policy_block("Example policy").endswith(END_MARKER)
        True
    """
    body = policy if policy.endswith("\n") else f"{policy}\n"
    if BEGIN_PREFIX in body or END_MARKER.rstrip("\n") in body:
        raise SyncError("source policy must not contain ownership markers")
    return f"{BEGIN_PREFIX}{_sha256(body)} -->\n{body}{END_MARKER}"


def _replace_policy(existing: str, policy: str, block: str) -> str:
    """Merge one verified personal policy block without touching other instructions."""
    begins = existing.count(BEGIN_PREFIX)
    ends = existing.count(END_MARKER.rstrip("\n"))
    if begins == 0 and ends == 0:
        if existing.endswith(policy):
            return f"{existing[: -len(policy)]}{block}"
        separator = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
        return f"{existing}{separator}{block}"
    if begins != 1 or ends != 1:
        raise SyncError("personal policy markers are malformed or duplicated")
    match = BEGIN_PATTERN.search(existing)
    if match is None:
        raise SyncError("personal policy marker is malformed")
    end = existing.find(END_MARKER, match.end())
    if end < 0:
        raise SyncError("personal policy end marker is missing")
    body = existing[match.end() : end]
    if _sha256(body) != match.group(1):
        raise SyncError("personal policy block was modified; refusing overwrite")
    return f"{existing[: match.start()]}{block}{existing[end + len(END_MARKER) :]}"


def _atomic_write(path: Path, content: str, existing: str | None) -> None:
    """Atomically replace a user file after checking it did not change."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.borda-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600)
        if existing is None:
            if path.exists():
                raise SyncError(f"target appeared during update: {path}")
        elif path.is_symlink() or not path.is_file() or _read_text(path, "target") != existing:
            raise SyncError(f"target changed during update: {path}")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def sync(source_config: Path, source_policy: Path, codex_home: Path, *, install_policy: bool = True) -> None:
    """Apply repository model defaults and the optional personal advisory policy."""
    models = _source_models(source_config)
    codex_home.mkdir(parents=True, exist_ok=True)

    config = codex_home / "config.toml"
    existing_config = _read_text(config, "target config") if config.exists() else ""
    desired_config = _replace_models(existing_config, models)

    if not install_policy:
        _atomic_write(config, desired_config, existing_config if config.exists() else None)
        return

    policy = _read_text(source_policy, "source policy")
    policy = policy if policy.endswith("\n") else f"{policy}\n"
    agents = codex_home / "AGENTS.md"
    existing_agents = _read_text(agents, "target instructions") if agents.exists() else ""

    # Validate both targets before modifying either one so a malformed policy
    # cannot leave a partially synchronized configuration behind.
    desired_agents = _replace_policy(existing_agents, policy, _policy_block(policy))
    _atomic_write(config, desired_config, existing_config if config.exists() else None)
    _atomic_write(agents, desired_agents, existing_agents if agents.exists() else None)


def parse_args() -> argparse.Namespace:
    """Parse the explicitly scoped source and Codex-home paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--source-policy", type=Path, required=True)
    parser.add_argument("--codex-home", type=Path, required=True)
    parser.add_argument("--skip-policy", action="store_true", help="update model defaults without changing AGENTS.md")
    return parser.parse_args()


def main() -> int:
    """Synchronize the requested Codex-home model policy."""
    args = parse_args()
    try:
        sync(args.source_config, args.source_policy, args.codex_home, install_policy=not args.skip_policy)
    except (OSError, SyncError) as error:
        print(f"codex-home-sync-error: {error}", file=sys.stderr)
        return 2
    print(f"[ok] synced normal-session model policy to {args.codex_home}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
