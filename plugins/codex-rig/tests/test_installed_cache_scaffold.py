"""Acceptance checks for the representative installed-cache scaffold."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


WINDOWS_POSIX_SKIP_REASON = "requires POSIX filesystem modes, links, and executable semantics"
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_POSIX_SKIP_REASON)
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_ROOT.parents[1]
CARD_SEPARATOR = b"--- codex-rig-role-card ---\n"


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for one file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_scaffold_has_stable_role_card_release_identity() -> None:
    """Prevent installed-cache identity and declared boundaries from drifting."""
    manifest = json.loads((PLUGIN_ROOT / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))

    assert manifest["name"] == "codex-rig"
    assert manifest["version"] == "0.2.3"
    assert manifest["author"]["name"] == "Jiri Borovec"
    assert "hooks" not in manifest
    assert "mcpServers" not in manifest
    assert len(manifest["interface"]["defaultPrompt"]) <= 3
    assert all("agent-shims" not in prompt for prompt in manifest["interface"]["defaultPrompt"])
    assert {"codex-rig:develop", "codex-rig:code-review", "codex-rig:research"} == {
        prompt.split()[2] for prompt in manifest["interface"]["defaultPrompt"]
    }


def test_repository_marketplace_contract() -> None:
    """Validate repository catalog metadata only when its source root exists."""
    marketplace_path = REPO_ROOT / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_path.exists():
        pytest.skip("repository marketplace is intentionally outside installed plugin cache")
    marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))

    assert marketplace["name"] == "borda-ai-rig"
    assert marketplace["plugins"][0]["source"]["path"] == "./plugins/codex-rig"


def test_representative_skill_and_role_are_cache_portable() -> None:
    """Prevent representative payloads from depending on the source checkout."""
    skill = (PLUGIN_ROOT / "skills" / "analyse" / "SKILL.md").read_text(encoding="utf-8")
    role = (PLUGIN_ROOT / "roles" / "challenger" / "ROLE.md").read_text(encoding="utf-8")

    assert "../../shared/" in skill
    assert "../_shared/" not in skill
    for required in (
        "role_id: challenger",
        "model: gpt-5.6-terra",
        "model_reasoning_effort: high",
        "approval_policy: on-request",
        "sandbox_mode: read-only",
        "fallback_modes:",
        "## Trigger and skip boundaries",
        "## Evidence ownership",
        "## Execution constraints",
        "## Handover contract",
        "## Confidence contract",
    ):
        assert required in role
    assert "/Users/" not in skill + role
    assert "/home/" not in skill + role
    assert "plugins/codex-rig" not in skill + role

    package_manifest = json.loads((PLUGIN_ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    role_entry = package_manifest["roles"][0]
    assert role_entry["runtime"] == {
        "model": "gpt-5.6-terra",
        "model_reasoning_effort": "high",
        "approval_policy": "on-request",
        "sandbox_mode": "read-only",
    }


@POSIX_ONLY
def test_package_manifest_covers_regular_payloads_and_modes() -> None:
    """Prevent duplicate, linked, unverified, or mode-drifted package files."""
    manifest = json.loads((PLUGIN_ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    records = manifest["files"]
    recorded_paths = [item["path"] for item in records]
    assert len(recorded_paths) == len(set(recorded_paths))
    assert len(recorded_paths) == len({path.casefold() for path in recorded_paths})

    recorded = {item["path"]: (item["sha256"], int(item["mode"], 8)) for item in records}
    discovered: dict[str, tuple[str, int]] = {}
    for path in PLUGIN_ROOT.rglob("*"):
        if path.name in {".coverage", "package-manifest.json"} or any(
            part in {"__pycache__", ".pytest_cache"} for part in path.parts
        ):
            continue
        assert not path.is_symlink()
        if path.is_file():
            relative = path.relative_to(PLUGIN_ROOT).as_posix()
            assert ".." not in Path(relative).parts
            discovered[relative] = (sha256(path), stat.S_IMODE(path.stat().st_mode))
    assert recorded == discovered


def write_fake_codex(path: Path, version: str, *, installed: bool = True, enabled: bool = True) -> None:
    """Write an absolute executable that returns one bounded plugin-list fixture."""
    entries = []
    if installed:
        entries.append(
            {
                "pluginId": "codex-rig@borda-ai-rig",
                "name": "codex-rig",
                "marketplaceName": "borda-ai-rig",
                "version": version,
                "installed": True,
                "enabled": enabled,
            }
        )
    payload = json.dumps({"installed": entries}, separators=(",", ":"))
    path.write_text(f"#!/bin/sh\nprintf '%s\\n' '{payload}'\n", encoding="utf-8")
    path.chmod(0o755)


def installed_fixture(
    tmp_path: Path,
    *,
    installed: bool = True,
    enabled: bool = True,
    stale_cache: bool = False,
    missing_card: bool = False,
) -> tuple[Path, Path, Path]:
    """Copy a source-independent package snapshot into an isolated cache."""
    manifest = json.loads((PLUGIN_ROOT / "package-manifest.json").read_text(encoding="utf-8"))
    version = manifest["version"]
    cache_version = "0.0.0-retained" if stale_cache else version
    home = tmp_path / "codex-home"
    installed_root = home / "plugins" / "cache" / "borda-ai-rig" / "codex-rig" / cache_version
    shutil.copytree(
        PLUGIN_ROOT,
        installed_root,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".coverage"),
    )
    if missing_card:
        (installed_root / "roles" / "challenger" / "ROLE.md").unlink()
    codex_binary = tmp_path / "codex-runtime"
    write_fake_codex(codex_binary, version, installed=installed, enabled=enabled)
    return home, installed_root, codex_binary


def run_verifier(
    home: Path,
    installed_root: Path,
    codex_binary: Path,
    *,
    role_sha256: str | None = None,
    helper_sha256: str | None = None,
    manifest_sha256: str | None = None,
    path_override: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run the installed verifier with exact bound identity arguments."""
    role_path = installed_root / "roles" / "challenger" / "ROLE.md"
    verifier = installed_root / "scripts" / "verify_role_link.py"
    manifest_path = installed_root / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded_role_digest = next(item["sha256"] for item in manifest["roles"] if item["id"] == "challenger")
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    if path_override is not None:
        env["PATH"] = path_override
    return subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--plugin-root",
            str(installed_root),
            "--role",
            "challenger",
            "--role-sha256",
            role_sha256 or (sha256(role_path) if role_path.exists() else recorded_role_digest),
            "--manifest-sha256",
            manifest_sha256 or sha256(manifest_path),
            "--helper-sha256",
            helper_sha256 or sha256(verifier),
            "--codex-binary",
            str(codex_binary),
            "--codex-sha256",
            sha256(codex_binary),
        ],
        check=False,
        capture_output=True,
        env=env,
    )


def failure_payload(result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    """Decode one exact unavailable bootstrap envelope."""
    assert result.returncode == 4
    assert result.stderr == b""
    assert result.stdout.count(b"\n") == 1
    payload = json.loads(result.stdout)
    assert payload["protocol"] == 1
    assert payload["role_id"] == "challenger"
    assert payload["status"] == "codex-rig-role-unavailable"
    return payload


@POSIX_ONLY
def test_verifier_emits_exact_installed_card_bytes(tmp_path: Path) -> None:
    """Prove the active cache copy emits its verified bytes without source fallback."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    result = run_verifier(home, installed_root, codex_binary)
    card = (installed_root / "roles" / "challenger" / "ROLE.md").read_bytes()
    first_line, separator, emitted_card = result.stdout.partition(CARD_SEPARATOR)

    assert installed_root != PLUGIN_ROOT
    assert result.returncode == 0
    assert result.stderr == b""
    assert separator == CARD_SEPARATOR
    assert json.loads(first_line) == {
        "protocol": 1,
        "role_id": "challenger",
        "role_sha256": sha256(installed_root / "roles" / "challenger" / "ROLE.md"),
        "status": "ok",
    }
    assert emitted_card == card


@pytest.mark.parametrize("hooks", [False, True], ids=["without-hook", "with-hook"])
@POSIX_ONLY
def test_verifier_accepts_exact_manager_profile(tmp_path: Path, hooks: bool) -> None:
    """Keep linked bootstrap valid for both declared manager package variants."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    manifest_path = installed_root / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["release_profile"] = "shim-enabled"
    manifest["features"] = {"manager": True, "hooks": hooks, "mcp": False, "generated_shims": True}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_verifier(home, installed_root, codex_binary)

    assert result.returncode == 0, result.stdout
    assert CARD_SEPARATOR in result.stdout


@POSIX_ONLY
def test_verifier_rejects_plugin_manifest_content_not_bound_by_package_manifest(tmp_path: Path) -> None:
    """Prevent same-version plugin metadata tampering from emitting a role card."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    plugin_manifest_path = installed_root / ".codex-plugin" / "plugin.json"
    plugin_manifest = json.loads(plugin_manifest_path.read_text(encoding="utf-8"))
    plugin_manifest["description"] = "tampered but same identity"
    plugin_manifest_path.write_text(json.dumps(plugin_manifest), encoding="utf-8")

    result = run_verifier(home, installed_root, codex_binary)

    assert failure_payload(result)["reason"] == "package-identity-mismatch"
    assert CARD_SEPARATOR not in result.stdout


@pytest.mark.parametrize("schema", [None, 2], ids=["missing", "future"])
@POSIX_ONLY
def test_verifier_rejects_unsupported_package_schema(tmp_path: Path, schema: int | None) -> None:
    """Prevent missing or future package schemas from entering the trust chain."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    manifest_path = installed_root / "package-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if schema is None:
        manifest.pop("schema")
    else:
        manifest["schema"] = schema
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run_verifier(home, installed_root, codex_binary)

    assert failure_payload(result)["reason"] == "manifest-invalid"
    assert CARD_SEPARATOR not in result.stdout


@POSIX_ONLY
def test_verifier_bounds_invalid_role_envelope(tmp_path: Path) -> None:
    """Prevent malformed role arguments from expanding or injecting diagnostics."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    verifier = installed_root / "scripts" / "verify_role_link.py"
    result = subprocess.run(
        [sys.executable, str(verifier), "--role", "bad\n" + "x" * 1000],
        check=False,
        capture_output=True,
        env={**os.environ, "CODEX_HOME": str(home)},
    )

    assert result.returncode == 4
    assert result.stderr == b""
    assert json.loads(result.stdout) == {
        "protocol": 1,
        "reason": "invalid-arguments",
        "role_id": "unknown",
        "status": "codex-rig-role-unavailable",
    }
    assert len(result.stdout) < 160


@POSIX_ONLY
def test_verifier_stops_oversized_oracle_output(tmp_path: Path) -> None:
    """Prevent an oversized runtime response from being buffered or trusted."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    codex_binary.write_text("#!/bin/sh\nyes x\n", encoding="utf-8")
    codex_binary.chmod(0o755)

    result = run_verifier(home, installed_root, codex_binary)

    assert failure_payload(result)["reason"] == "active-package-oracle-oversized"
    assert CARD_SEPARATOR not in result.stdout


@pytest.mark.parametrize(
    ("fixture_options", "overrides", "reason"),
    [
        ({"enabled": False}, {}, "active-package-mismatch"),
        ({"installed": False}, {}, "active-package-mismatch"),
        ({"missing_card": True}, {}, "verification-error"),
        ({"stale_cache": True}, {}, "active-package-mismatch"),
        ({}, {"role_sha256": "0" * 64}, "role-manifest-mismatch"),
        ({}, {"helper_sha256": "0" * 64}, "helper-hash-mismatch"),
        ({}, {"manifest_sha256": "0" * 64}, "manifest-hash-mismatch"),
    ],
    ids=["disabled", "removed", "missing-card", "retained-old-cache", "role-hash", "helper-hash", "manifest-hash"],
)
@POSIX_ONLY
def test_verifier_rejects_negative_link_states(
    tmp_path: Path, fixture_options: dict[str, bool], overrides: dict[str, str], reason: str
) -> None:
    """Prevent inactive or inconsistent links from emitting role instructions."""
    home, installed_root, codex_binary = installed_fixture(tmp_path, **fixture_options)
    result = run_verifier(home, installed_root, codex_binary, **overrides)

    assert failure_payload(result)["reason"] == reason
    assert b"Treat every important claim" not in result.stdout


@POSIX_ONLY
def test_verifier_ignores_hostile_path_lookup(tmp_path: Path) -> None:
    """Prevent inherited PATH from substituting the active-package oracle."""
    home, installed_root, codex_binary = installed_fixture(tmp_path)
    hostile_bin = tmp_path / "hostile-bin"
    hostile_bin.mkdir()
    marker = tmp_path / "hostile-codex-ran"
    hostile_codex = hostile_bin / "codex"
    hostile_codex.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    hostile_codex.chmod(0o755)

    result = run_verifier(home, installed_root, codex_binary, path_override=str(hostile_bin))

    assert result.returncode == 0
    assert not marker.exists()


def test_committed_runtime_payload_has_no_private_machine_paths() -> None:
    """Prevent local cache paths and obvious secret material from publication."""
    for path in PLUGIN_ROOT.rglob("*"):
        if not path.is_file() or "tests" in path.parts or "__pycache__" in path.parts:
            continue
        payload = path.read_bytes()
        assert b"/Users/" not in payload
        assert b"/home/" not in payload
        assert b"BEGIN " + b"PRIVATE KEY" not in payload
