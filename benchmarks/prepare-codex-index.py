#!/usr/bin/env python3
"""Normalize a fresh Codemap scan to the manifest-locked benchmark bytes.

The scanner's timestamp and absolute root are environment-dependent even when
the indexed repository is identical. This utility rewrites only those declared
metadata values and embedded root prefixes, then replaces the new scan only if
its complete SHA-256 matches the reviewed manifest.

Usage:
    python3 benchmarks/prepare-codex-index.py \
        --index-path /private/tmp/codemap-provider-parity-pl-2.6.5/.cache/codemap/codemap-provider-parity-pl-2.6.5.json \
        --source-root /private/tmp/codemap-provider-parity-pl-2.6.5 \
        --manifest-path benchmarks/manifests/codex-integration.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _replace_root(value: Any, source_root: str, locked_root: str) -> Any:
    """Replace scanner-root prefixes recursively without changing structure."""
    if isinstance(value, str):
        return value.replace(source_root, locked_root)
    if isinstance(value, list):
        return [_replace_root(item, source_root, locked_root) for item in value]
    if isinstance(value, dict):
        return {key: _replace_root(item, source_root, locked_root) for key, item in value.items()}
    return value


def prepare_index(index_path: Path, source_root: Path, manifest_path: Path) -> str:
    """Normalize one new scan and atomically install it only on an exact hash match."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["index"]
    locked_root = str(expected["scan_root"])
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    payload = _replace_root(payload, str(source_root.resolve()), locked_root)
    payload.update(
        project=expected["project"],
        scan_root=locked_root,
        scanned_at=expected["scanned_at"],
    )
    normalized = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(normalized).hexdigest()
    if digest != expected["raw_sha256"]:
        raise ValueError(f"normalized index SHA-256 mismatch: expected {expected['raw_sha256']}, got {digest}")

    with tempfile.NamedTemporaryFile(dir=index_path.parent, prefix=f".{index_path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(normalized)
    try:
        os.replace(temporary, index_path)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def main() -> None:
    """Parse CLI arguments and prepare one manifest-locked index."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--index-path", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    args = parser.parse_args()
    print(prepare_index(args.index_path, args.source_root, args.manifest_path))


if __name__ == "__main__":
    main()
