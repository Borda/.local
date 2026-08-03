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


def _fixture_files(tmp_path: Path, expected_sha256: str, *, scan_version: int = 12) -> tuple[Path, Path, Path, bytes]:
    """Create one environment-dependent scan and its locked manifest oracle."""
    source_root = tmp_path / "fresh-target"
    source_root.mkdir(exist_ok=True)
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "scan_version": scan_version,
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
        "scan_version": scan_version,
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
                    "scan_version": scan_version,
                    "scan_root": locked_payload["scan_root"],
                    "project": locked_payload["project"],
                    "scanned_at": locked_payload["scanned_at"],
                }
            }
        ),
        encoding="utf-8",
    )
    return index_path, source_root, manifest_path, locked_bytes


def _schema_file(tmp_path: Path, scan_version: int) -> Path:
    """Write a minimal scanner schema source for version-compatibility tests."""
    path = tmp_path / "schema.py"
    path.write_text(f"SCAN_VERSION: int = {scan_version}\n", encoding="utf-8")
    return path


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


def test_old_lock_was_accepted_without_schema_context_but_fails_against_current_schema(tmp_path: Path) -> None:
    """An archived v11 lock remains reproducible only outside the active v12 contract."""
    module = _load_script()
    expected_payload = _fixture_files(tmp_path, "placeholder", scan_version=11)[-1]
    expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
    index_path, source_root, manifest_path, _locked_bytes = _fixture_files(tmp_path, expected_sha256, scan_version=11)

    assert module.prepare_index(index_path, source_root, manifest_path) == expected_sha256
    with pytest.raises(ValueError, match="does not match current Codemap schema"):
        module.index_contract(manifest_path, schema_path=_schema_file(tmp_path, 12))


def test_current_v12_lock_and_index_pass_schema_contract(tmp_path: Path) -> None:
    """The active v12 scan is accepted when manifest, bytes, and scanner agree."""
    module = _load_script()
    expected_payload = _fixture_files(tmp_path, "placeholder", scan_version=12)[-1]
    expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
    index_path, source_root, manifest_path, locked_bytes = _fixture_files(tmp_path, expected_sha256, scan_version=12)
    schema_path = _schema_file(tmp_path, 12)

    assert module.index_contract(manifest_path, schema_path=schema_path)["scan_version"] == 12
    assert module.verify_index(index_path, manifest_path, schema_path=schema_path) is None
    assert module.prepare_index(index_path, source_root, manifest_path, schema_path=schema_path) == expected_sha256
    assert index_path.read_bytes() == locked_bytes


def test_verify_index_rejects_wrong_bytes_with_current_schema(tmp_path: Path) -> None:
    """A structurally valid v12 graph still requires the exact locked bytes."""
    module = _load_script()
    expected_payload = _fixture_files(tmp_path, "placeholder", scan_version=12)[-1]
    expected_sha256 = hashlib.sha256(expected_payload).hexdigest()
    index_path, _source_root, manifest_path, _locked_bytes = _fixture_files(tmp_path, expected_sha256, scan_version=12)
    index_path.write_text(json.dumps({"scan_version": 12, "modules": [{"wrong": True}]}), encoding="utf-8")

    with pytest.raises(ValueError, match="index SHA-256 mismatch"):
        module.verify_index(manifest_path=manifest_path, index_path=index_path, require_hash=True)


def _paired_manifests(tmp_path: Path, *, source_manifest: object) -> tuple[Path, Path, Path]:
    """Create a Codex manifest and provider-neutral source with one shared index lock."""
    methodology_path = tmp_path / "provider-parity-methodology.json"
    methodology_path.write_text(
        json.dumps(
            {
                "index": {
                    "raw_sha256": "0" * 64,
                    "scan_version": 12,
                    "project": "fixture",
                    "scan_root": "/fixture",
                    "scanned_at": "now",
                }
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "codex-integration.json"
    manifest_path.write_text(
        json.dumps({"index": json.loads(methodology_path.read_text())["index"], "source_manifest": source_manifest}),
        encoding="utf-8",
    )
    return manifest_path, methodology_path, _schema_file(tmp_path, 12)


def test_index_contract_requires_source_manifest_metadata(tmp_path: Path) -> None:
    """Codex must identify the exact provider-neutral methodology bytes."""
    module = _load_script()
    manifest_path, methodology_path, schema_path = _paired_manifests(tmp_path, source_manifest=None)

    with pytest.raises(ValueError, match="missing source_manifest"):
        module.index_contract(manifest_path, methodology_path=methodology_path, schema_path=schema_path)


def test_index_contract_rejects_tampered_source_manifest_metadata(tmp_path: Path) -> None:
    """A stale or tampered methodology source cannot supply an index lock."""
    module = _load_script()
    manifest_path, methodology_path, schema_path = _paired_manifests(
        tmp_path,
        source_manifest={"path": str(tmp_path / "provider-parity-methodology.json"), "sha256": "f" * 64},
    )

    with pytest.raises(ValueError, match="source_manifest SHA-256"):
        module.index_contract(manifest_path, methodology_path=methodology_path, schema_path=schema_path)
