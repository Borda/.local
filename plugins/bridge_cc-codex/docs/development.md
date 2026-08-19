# Development and release verification

`bridge_CC-Codex` is a standalone Python 3.10+ plugin package. Its normalized plugin identifier is `bridge`; both manifests must keep that name and the same version. Its Claude Code manifest is `.claude-plugin/plugin.json`; its Codex manifest is `.codex-plugin/plugin.json`; its reverse transport declaration is `.mcp.json`. The current release is `0.2.0`.

## Source layout

- `bin/bridge_call.py` owns request normalization, peer command construction, supervision, compact-result validation, artifacts, and health logging. Implement requests are write-capable; review requests use read-only general Codex execution with an explicit adversarial-review prompt rather than Codex's native review subcommand.
- `bin/bridge_mcp.py` owns the stdio MCP protocol and the three Codex-facing tools `bridge_implement`, `bridge_advise`, and `bridge_review`.
- `bin/bridge_diagnose.py` owns static host-surface checks and optional live diagnosis. The baseline is deliberately flag-only — it pins no CLI version number, because a depended-on flag disappearing from `--help` is the failure that actually breaks dispatch — and the free static check reports without appending health records; only completed bridge requests write `health.jsonl` lines.
- `schemas/` contains the model-core, harness-envelope, and MCP input contracts.
- `rules/` contains the effort, prompting, recursion, envelope, and recovery policies used by both host integrations.
- `claude-skills/` contains Claude Code commands; `codex-skills/` contains Codex commands. Both host trees expose `implement`, `advise`, and `review`.
- `tests/` proves runtime, contract, cross-platform, and install-shaped package behavior.

Keep public names, schemas, manifests, skills, and README examples synchronized when a user-facing behavior changes. Do not make the package depend on a source checkout, another plugin, or a private workspace path.

## Local checks

Run the focused plugin suite:

```bash
python -m pytest -q plugins/bridge_cc-codex
```

Format and lint changed Markdown through the pinned pre-commit hook:

```bash
pre-commit run mdformat --files plugins/bridge_cc-codex/docs/architecture.md plugins/bridge_cc-codex/docs/security.md plugins/bridge_cc-codex/docs/operations.md plugins/bridge_cc-codex/docs/development.md
```

Check whitespace and build an install-shaped package outside the source tree on Linux or macOS:

```bash
git diff --check -- plugins/bridge_cc-codex
disposable_parent_directory="$(mktemp -d)"
python plugins/bridge_cc-codex/scripts/build_package.py --output "$disposable_parent_directory/bridge"
python plugins/bridge_cc-codex/scripts/validate_package.py "$disposable_parent_directory/bridge"
```

Use the native PowerShell equivalents on Windows:

```powershell
git diff --check -- plugins/bridge_cc-codex
$disposableParentDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("bridge-" + [System.Guid]::NewGuid())
New-Item -ItemType Directory -Path $disposableParentDirectory | Out-Null
$disposablePackageDirectory = Join-Path $disposableParentDirectory "bridge"
& python plugins/bridge_cc-codex/scripts/build_package.py --output $disposablePackageDirectory
& python plugins/bridge_cc-codex/scripts/validate_package.py $disposablePackageDirectory
```

The package validator rejects symlinks, private artifact directories, private absolute paths, malformed JSON, missing runtime closure, unresolved manifest paths, and version mismatches. The disposable build excludes tests, caches, `.DS_Store`, and temporary bridge state. The public envelope must remain compact: decisions, blockers, and remaining work belong in public fields, while bounded peer `details` belong only in the raw transcript with workspace-relative transcript and incident references returned as metadata.

## Behavioral verification

When changing the bridge runtime, add or update a public-contract test that would fail under a plausible incorrect implementation, then run the complete plugin suite. Exercise both directions where the change affects transport, and inspect the compact returned envelope plus `.temp/bridge` artifacts for timeout, refusal, authentication, and partial-result behavior. Live setup probes are optional and require explicit operator approval because they invoke authenticated provider inference; static setup alone does not verify provider or schema compatibility.

Before a release, verify both host manifests, the `.mcp.json` `${PLUGIN_ROOT}` path, the three MCP tool schemas, the version in `CHANGELOG.md`, and the install-shaped package. Remote marketplace publication and host installation remain operator-owned actions after these local gates pass.
