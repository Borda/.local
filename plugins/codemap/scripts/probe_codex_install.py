#!/usr/bin/env python3
"""Non-interactive Codex install probe for the disposable codemap-py candidate.

Feasibility probe, not a CI test: it drives the real ``codex`` CLI against a
throwaway ``CODEX_HOME`` to prove the built candidate installs and exposes exactly one
Codex skill. It never touches the user's real ``~/.codex`` — every mutation is scoped
to a fresh temporary home that is removed on exit.

Flow (all inside the disposable home):

1. Build the candidate via ``build_package.py --out <root>/plugins/codemap-py``.
2. Write a local marketplace at ``<root>/.agents/plugins/marketplace.json`` whose one
   entry points at the candidate with a ``./``-relative ``source.path``.
3. ``codex plugin marketplace add <root>`` then ``codex plugin add codemap-py@<mkt> --json``.
4. Statically verify the installed bytes: a ``codex-skills/`` directory holding exactly
   one skill, a ``.codex-plugin/plugin.json`` with the expected name/version, and a
   ``skills`` manifest field that points at ``./codex-skills/`` — never at any bundled
   ``claude-skills/`` (which may ship in the payload but must not be a Codex skills source).

Exit codes: 0 = installed and verified; 2 = a named prerequisite is absent (the builder
has not landed yet, or the ``codex`` CLI is not installed) — a recorded limitation, not a
failure; 1 = the probe ran but installation or verification failed.

The probe writes its JSON result to stdout, and to ``--report <path>`` when given.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_THIS = Path(__file__).resolve()
_SCRIPTS = _THIS.parent
_BUILDER = _SCRIPTS / "build_package.py"

MKT_NAME = "codemap-py-probe-mkt"
PLUGIN_NAME = "codemap-py"
EXPECTED_VERSION = "0.25.0-rc1"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_SKIP = 2


def codex_marketplace_manifest(rel_path: str) -> dict:
    """Return the Codex local-marketplace manifest for the candidate.

    ``rel_path`` is the candidate location relative to the marketplace root, ``./``-prefixed
    and kept inside the root, as Codex requires. The ``source.source`` discriminator must be
    present — without it Codex registers the marketplace but parses zero plugins.

    Examples:
        >>> m = codex_marketplace_manifest("./plugins/codemap-py")
        >>> m["plugins"][0]["source"]
        {'source': 'local', 'path': './plugins/codemap-py'}
        >>> m["plugins"][0]["name"]
        'codemap-py'
    """
    return {
        "name": MKT_NAME,
        "interface": {"displayName": "codemap-py probe marketplace"},
        "plugins": [
            {
                "name": PLUGIN_NAME,
                "source": {"source": "local", "path": rel_path},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }


def verify_codex_install(installed_path: Path) -> dict:
    """Statically check the installed Codex plugin bytes; return a checks/issues report.

    Verifies the manifest identity, that ``codex-skills/`` holds exactly one skill, and
    that the manifest's ``skills`` source is ``codex-skills`` rather than any bundled
    ``claude-skills`` directory.

    Examples:
        >>> verify_codex_install(Path("/nonexistent"))["ok"]
        False
    """
    checks: dict[str, bool] = {}
    issues: list[str] = []

    manifest_path = installed_path / ".codex-plugin" / "plugin.json"
    checks["manifest_present"] = manifest_path.is_file()
    manifest: dict = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"manifest unreadable: {exc}")
    else:
        issues.append("missing .codex-plugin/plugin.json")

    checks["name_matches"] = manifest.get("name") == PLUGIN_NAME
    if not checks["name_matches"]:
        issues.append(f"manifest name {manifest.get('name')!r} != {PLUGIN_NAME!r}")
    checks["version_present"] = bool(manifest.get("version"))
    if not checks["version_present"]:
        issues.append("manifest version missing")

    skills_dir = installed_path / "codex-skills"
    checks["codex_skills_present"] = skills_dir.is_dir()
    skill_dirs = sorted(p.name for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() else []
    checks["exactly_one_skill"] = len(skill_dirs) == 1
    if not checks["exactly_one_skill"]:
        issues.append(f"expected 1 codex skill dir, found {skill_dirs}")

    skills_field = manifest.get("skills")
    checks["skills_field_is_codex"] = isinstance(skills_field, str) and "codex-skills" in skills_field
    checks["claude_skills_not_registered"] = not (isinstance(skills_field, str) and "claude-skills" in skills_field)
    if not checks["claude_skills_not_registered"]:
        issues.append(f"claude-skills registered as codex skills source: {skills_field!r}")

    return {
        "ok": all(checks.values()),
        "checks": checks,
        "issues": issues,
        "skill_dirs": skill_dirs,
        "manifest": {"name": manifest.get("name"), "version": manifest.get("version"), "skills": skills_field},
    }


def _codex_version() -> str | None:
    try:
        out = subprocess.run(["codex", "--version"], capture_output=True, text=True, timeout=15, check=False)
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or out.stderr.strip() or None


def _run(cmd: list[str], home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env={**os.environ, "CODEX_HOME": str(home)},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _build_candidate(dest: Path) -> tuple[bool, str]:
    """Invoke the builder to assemble the candidate at *dest*; return (ok, detail)."""
    proc = subprocess.run(
        [sys.executable, str(_BUILDER), "--out", str(dest)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()
    return True, "built"


def run_probe() -> dict:
    """Drive the full disposable install and return a JSON-able result envelope."""
    codex_version = _codex_version()
    if codex_version is None:
        return {"probe": "codex", "status": "codex-cli-not-present", "codex_version": None}
    if not _BUILDER.is_file():
        return {
            "probe": "codex",
            "status": "builder-not-yet-present",
            "codex_version": codex_version,
            "detail": f"missing {_BUILDER}",
        }

    workdir = Path(tempfile.mkdtemp(prefix="codemap-py-codex-probe-"))
    home = workdir / "codex-home"
    home.mkdir()
    mkt_root = workdir / "mkt"
    candidate = mkt_root / "plugins" / PLUGIN_NAME
    candidate.mkdir(parents=True)
    mkt_manifest = mkt_root / ".agents" / "plugins" / "marketplace.json"
    mkt_manifest.parent.mkdir(parents=True)

    result: dict = {"probe": "codex", "codex_version": codex_version}
    try:
        built_ok, detail = _build_candidate(candidate)
        if not built_ok:
            return {**result, "status": "builder-failed", "detail": detail}

        mkt_manifest.write_text(json.dumps(codex_marketplace_manifest(f"./plugins/{PLUGIN_NAME}"), indent=2))

        add = _run(["codex", "plugin", "marketplace", "add", str(mkt_root), "--json"], home)
        if add.returncode != 0:
            return {**result, "status": "marketplace-add-failed", "detail": add.stderr.strip()}
        install = _run(["codex", "plugin", "add", f"{PLUGIN_NAME}@{MKT_NAME}", "--json"], home)
        if install.returncode != 0:
            return {**result, "status": "plugin-add-failed", "detail": install.stderr.strip()}
        installed_path = Path(json.loads(install.stdout)["installedPath"])

        verification = verify_codex_install(installed_path)
        return {
            **result,
            "status": "ok" if verification["ok"] else "verification-failed",
            "installed_path": str(installed_path),
            "verification": verification,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Non-interactive Codex install probe for codemap-py.")
    parser.add_argument("--report", type=Path, help="Write the JSON result to this path in addition to stdout.")
    args = parser.parse_args(argv)

    result = run_probe()
    payload = json.dumps(result, indent=2)
    print(payload)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload)

    if result["status"] == "ok":
        return EXIT_OK
    if result["status"] in {"builder-not-yet-present", "codex-cli-not-present"}:
        return EXIT_SKIP
    return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
