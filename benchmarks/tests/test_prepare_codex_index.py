"""Regression tests for deterministic fresh-machine Codemap index preparation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "prepare-codex-index.py"


def _load_script() -> ModuleType:
    """Load the hyphenated index utility as a test module."""
    spec = importlib.util.spec_from_file_location("prepare_codex_index", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_files(tmp_path: Path, expected_sha256: str) -> tuple[Path, Path, Path, bytes]:
    """Create one environment-dependent scan and its locked manifest oracle."""
    source_root = tmp_path / "fresh-target"
    source_root.mkdir(exist_ok=True)
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "scan_version": 11,
                "scanned_at": "fresh",
                "project": "fresh-target",
                "scan_root": str(source_root),
                "modules": [{"mock_patches": [{"file": f"{source_root}/tests/test_demo.py"}]}],
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    locked_payload = {
        "scan_version": 11,
        "scanned_at": "2026-07-29T18:51:27.926212+00:00",
        "project": "codemap-provider-parity-pl-2.6.5",
        "scan_root": "/private/tmp/codemap-provider-parity-pl-2.6.5",
        "modules": [{"mock_patches": [{"file": "/private/tmp/codemap-provider-parity-pl-2.6.5/tests/test_demo.py"}]}],
    }
    locked_bytes = json.dumps(locked_payload, separators=(",", ":")).encode("utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "index": {
                    "raw_sha256": expected_sha256,
                    "scan_root": locked_payload["scan_root"],
                    "project": locked_payload["project"],
                    "scanned_at": locked_payload["scanned_at"],
                }
            }
        ),
        encoding="utf-8",
    )
    return index_path, source_root, manifest_path, locked_bytes


def test_prepare_index_rewrites_only_environment_metadata_to_exact_locked_bytes(tmp_path: Path) -> None:
    """A fresh scan becomes portable only when its complete normalized hash matches."""
    module = _load_script()
    expected_payload = _fixture_files(tmp_path, "placeholder")[-1]
    expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
    index_path, source_root, manifest_path, locked_bytes = _fixture_files(tmp_path, expected_sha256)

    digest = module.prepare_index(index_path, source_root, manifest_path)

    assert digest == expected_sha256
    assert index_path.read_bytes() == locked_bytes


def test_prepare_index_preserves_fresh_scan_when_normalized_graph_does_not_match(tmp_path: Path) -> None:
    """Metadata normalization must never conceal a changed graph or scanner result."""
    module = _load_script()
    index_path, source_root, manifest_path, _locked_bytes = _fixture_files(tmp_path, "0" * 64)
    original = index_path.read_bytes()

    with pytest.raises(ValueError, match="normalized index SHA-256 mismatch"):
        module.prepare_index(index_path, source_root, manifest_path)

    assert index_path.read_bytes() == original
