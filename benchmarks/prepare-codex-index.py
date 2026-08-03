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
        --manifest-path benchmarks/manifests/codex-integration.json \
        --methodology-path benchmarks/manifests/provider-parity-methodology.json \
        --schema-path plugins/codemap-py/src/codemap_py/schema.py
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    """Load one manifest object and reject malformed/non-object JSON."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"manifest root must be an object: {path}")
    return value


def _scanner_scan_version(schema_path: Path) -> int:
    """Read the persisted-index schema version from the checked-out scanner source."""
    try:
        tree = ast.parse(schema_path.read_text(encoding="utf-8"), filename=str(schema_path))
    except (OSError, SyntaxError) as exc:
        raise ValueError(f"cannot read Codemap schema version from {schema_path}: {exc}") from exc
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name, value = node.target.id, node.value
        else:
            continue
        if name == "SCAN_VERSION" and isinstance(value, ast.Constant) and isinstance(value.value, int):
            if isinstance(value.value, bool) or value.value < 1:
                break
            return value.value
    raise ValueError(f"Codemap schema does not declare a valid SCAN_VERSION: {schema_path}")


def index_contract(
    manifest_path: Path,
    *,
    methodology_path: Path | None = None,
    schema_path: Path | None = None,
) -> dict[str, Any]:
    """Return and validate the active index lock and scanner schema identity.

    The Codex manifest must carry the same index identity as the provider-neutral
    methodology source. When the schema source is supplied, an older manifest
    lock is rejected even if an old index's bytes still match that lock.
    """
    manifest = _load_json(manifest_path)
    expected = manifest.get("index")
    if not isinstance(expected, dict):
        raise ValueError(f"active manifest has no index contract: {manifest_path}")
    raw_sha = expected.get("raw_sha256")
    scan_version = expected.get("scan_version")
    if not isinstance(raw_sha, str) or len(raw_sha) != 64 or any(char not in "0123456789abcdef" for char in raw_sha):
        raise ValueError("active index contract requires a 64-character raw_sha256")
    if not isinstance(scan_version, int) or isinstance(scan_version, bool):
        raise ValueError("active index contract requires an integer scan_version")

    if methodology_path is not None:
        methodology = _load_json(methodology_path)
        methodology_index = methodology.get("index")
        if not isinstance(methodology_index, dict):
            raise ValueError(f"provider-neutral methodology has no index contract: {methodology_path}")
        if expected != methodology_index:
            raise ValueError(
                "Codex/index lock disagrees with provider-neutral methodology; regenerate both manifests "
                f"(codex={expected.get('raw_sha256')}, methodology={methodology_index.get('raw_sha256')})"
            )
        source = manifest.get("source_manifest")
        if not isinstance(source, dict):
            raise ValueError("Codex manifest is missing source_manifest metadata")
        source_sha = source.get("sha256")
        actual_sha = hashlib.sha256(methodology_path.read_bytes()).hexdigest()
        root = Path(__file__).resolve().parents[1]
        try:
            relative_methodology = methodology_path.resolve().relative_to(root).as_posix()
        except ValueError:
            relative_methodology = ""
        if source.get("path") not in {str(methodology_path), relative_methodology}:
            raise ValueError("Codex source_manifest path does not identify the active methodology")
        if source_sha != actual_sha:
            raise ValueError("Codex source_manifest SHA-256 does not match the active methodology")

    if schema_path is not None:
        current_version = _scanner_scan_version(schema_path)
        if scan_version != current_version:
            raise ValueError(
                f"active index scan_version {scan_version} does not match current Codemap schema {current_version}; "
                "rebuild and relock the index before running the benchmark"
            )
    return expected


def verify_index(
    index_path: Path,
    manifest_path: Path,
    *,
    methodology_path: Path | None = None,
    schema_path: Path | None = None,
    require_hash: bool = False,
) -> None:
    """Fail closed unless an index has the active lock's schema metadata."""
    expected = index_contract(manifest_path, methodology_path=methodology_path, schema_path=schema_path)
    try:
        payload = _load_json(index_path)
    except ValueError as exc:
        raise ValueError(f"index is not valid JSON: {index_path}: {exc}") from exc
    if payload.get("scan_version") != expected["scan_version"]:
        raise ValueError(
            f"index scan_version mismatch: expected {expected['scan_version']}, got {payload.get('scan_version')!r}"
        )
    if not isinstance(payload.get("modules"), list):
        raise ValueError("index schema mismatch: modules must be a list")
    if require_hash:
        actual_sha = hashlib.sha256(index_path.read_bytes()).hexdigest()
        if actual_sha != expected["raw_sha256"]:
            raise ValueError(f"index SHA-256 mismatch: expected {expected['raw_sha256']}, got {actual_sha}")


def _replace_root(value: Any, source_root: str, locked_root: str) -> Any:
    """Replace scanner-root prefixes recursively without changing structure."""
    if isinstance(value, str):
        return value.replace(source_root, locked_root)
    if isinstance(value, list):
        return [_replace_root(item, source_root, locked_root) for item in value]
    if isinstance(value, dict):
        return {key: _replace_root(item, source_root, locked_root) for key, item in value.items()}
    return value


def prepare_index(
    index_path: Path,
    source_root: Path,
    manifest_path: Path,
    *,
    methodology_path: Path | None = None,
    schema_path: Path | None = None,
) -> str:
    """Normalize one new scan and atomically install it only on an exact hash match."""
    expected = index_contract(manifest_path, methodology_path=methodology_path, schema_path=schema_path)
    locked_root = str(expected["scan_root"])
    payload = _load_json(index_path)
    if payload.get("scan_version") != expected["scan_version"]:
        raise ValueError(
            "fresh index schema mismatch: "
            f"expected scan_version {expected['scan_version']}, got {payload.get('scan_version')!r}"
        )
    if not isinstance(payload.get("modules"), list):
        raise ValueError("fresh index schema mismatch: modules must be a list")
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
    parser.add_argument("--index-path", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--methodology-path", type=Path)
    parser.add_argument("--schema-path", type=Path)
    parser.add_argument("--verify", action="store_true", help="verify index schema against the active lock")
    parser.add_argument("--require-hash", action="store_true", help="require exact manifest-locked index bytes")
    parser.add_argument("--print-contract", action="store_true", help="print the validated index contract as JSON")
    args = parser.parse_args()
    if args.print_contract:
        print(
            json.dumps(
                index_contract(
                    args.manifest_path,
                    methodology_path=args.methodology_path,
                    schema_path=args.schema_path,
                ),
                sort_keys=True,
            )
        )
        return
    if args.verify:
        if args.index_path is None:
            parser.error("--index-path is required with --verify")
        verify_index(
            args.index_path,
            args.manifest_path,
            methodology_path=args.methodology_path,
            schema_path=args.schema_path,
            require_hash=args.require_hash,
        )
        print(f"verified: {args.index_path}")
        return
    if args.index_path is None or args.source_root is None:
        parser.error("--index-path and --source-root are required unless --print-contract is used")
    print(
        prepare_index(
            args.index_path,
            args.source_root,
            args.manifest_path,
            methodology_path=args.methodology_path,
            schema_path=args.schema_path,
        )
    )


if __name__ == "__main__":
    main()
