# 🏗️ `scripts/` — package and install verification tooling

These scripts are maintainer-facing. They build a deterministic codemap-py package, validate its payload, and optionally exercise the real Claude Code and Codex plugin-install paths. They are not the day-to-day query CLI; see [`../bin/README.md`](../bin/README.md) for that surface.

The builder is derived from the tracked plugin payload rather than the whole checkout: source caches, tests, untracked files under included directories, and host-specific timestamps do not silently enter a package. The probes build from a disposable source copy, preserve the tracked executable-mode map, and delete that source before runtime proof so a passing install cannot accidentally import from the checkout.

<details>
<summary><strong>Contents</strong></summary>

- [Package build and validation](#-package-build-and-validation)
- [Install probes](#-install-probes)
- [CLI entrypoint and compatibility shim](#-cli-entrypoint-and-compatibility-shim)
- [Maintainer boundaries](#-maintainer-boundaries)

</details>

## 🧪 Package build and validation

Run the builder, then validate the resulting directory before treating it as a release candidate:

```bash
python plugins/codemap-py/scripts/build_package.py --out <package-dir>
python plugins/codemap-py/scripts/validate_package.py --package <package-dir>
```

The scripts accept Python 3.10+ source syntax. The packaged runtime itself still requires CPython `>=3.11,<3.15`.

### `build_package.py`

Builds a package from the tracked plugin payload. It reads name and version from `.claude-plugin/plugin.json`, includes both runtime manifests, both six-skill rosters, hooks, `bin/`, `scripts/`, and required product documents, and writes a `package-manifest.json` with stable ordering, SHA-256 bytes, and executable-mode metadata. Tests and caches are excluded. Untracked files under included directories are not silently added to the payload.

```text
python build_package.py --out DIR [--check] [--mode-map PATH]
```

`--check` rebuilds and compares package bytes and executable modes. `--mode-map` supplies the authoritative `{relative_posix_path: bool}` executable map when building from a disposable source copy. Exit `0` means success, `1` a determinism or mode mismatch, and `2` usage or payload-closure failure.

The deterministic manifest records stable relative POSIX paths, SHA-256 content hashes, and executable-mode metadata. A clean `--check` therefore proves byte and mode reproducibility for the selected source tree; it does not prove that a native marketplace CLI is available or that a model can use the installed skills correctly.

### `validate_package.py`

Checks a builder output against its manifest. Validation covers inventory hashes and extra files, relative portable paths, symlinks and case collisions, source/home/secret-byte leaks, required documents and manifests, exact Claude/Codex six-skill roster closure, hook references, and executable modes where the host exposes them.

```text
python validate_package.py --package DIR
```

Exit `0` is clean, `1` reports named findings, and `2` is a usage error.

Validation is fail-closed for extra files, missing manifest entries, symlinks, case-folding collisions, absolute or parent-escaping paths, source/home/secret-byte leaks, missing product documents, Claude/Codex roster drift, hook references, and executable-mode mismatches where the host exposes file modes.

<details>
<summary><strong>Install probes</strong></summary>

## 🧪 Install probes

The probes are optional release-acceptance checks. They require the corresponding native CLI and use disposable configuration and source locations; they do not modify a user's normal plugin home. A missing native CLI is reported as a prerequisite limitation, not as evidence that the package is broken.

### `probe_claude_install.py`

Builds from a disposable source copy, registers a local Claude marketplace, runs the native marketplace/install commands, verifies the installed Claude manifest and six-skill roster, removes the source copy, and runs `doctor`, `index`, and `query` through the shipped launcher under a scrubbed environment.

```text
python probe_claude_install.py [--report PATH]
```

Exit `0` means the probe and source-independent runtime proof passed; `1` means the probe ran and found a failure; `2` means a named prerequisite such as the builder or `claude` CLI is unavailable.

### `probe_codex_install.py`

The Codex counterpart stages a disposable package, creates a local Codex marketplace manifest, runs native Codex marketplace/add operations, verifies the `./codex-skills/` source and six-skill roster, removes the source copy, and runs the same launcher-based runtime proof.

```text
python probe_codex_install.py [--report PATH]
```

Exit meanings match the Claude probe. The Codex manifest intentionally declares no hooks; the probe checks that the Claude roster is not used as the Codex source.

### `_probe_runtime.py`

Shared implementation for the two probes. It stages source, captures executable modes from the real tracked tree, builds the candidate, deletes the source copy, scrubs `PYTHONPATH`, plugin-root variables, and `CODEMAP_*` variables except a controlled interpreter override, and verifies `doctor`, `index`, and `query` through the installed launcher. Import it from a probe; it has no standalone CLI.

</details>

<details>
<summary><strong>Builder and validator closure details</strong></summary>

`build_package.py` derives its payload from the Git-tracked plugin set. The include roots are the two runtime manifests, `bin/`, `scripts/`, both six-skill rosters, hooks, and the required product documents. It reads name/version from `.claude-plugin/plugin.json`; it does not infer identity from a directory name or include tests, caches, source-checkout metadata, or untracked files. The optional `--mode-map PATH` is the authoritative `{relative_posix_path: executable}` map when a disposable source copy has no trustworthy Git index.

The manifest is deterministic: paths are relative POSIX paths, entries are stable-sorted, file bytes are LF-stable where generated, hashes are SHA-256, executable mode is explicit, and timestamps are absent. `--check` compares both bytes and executable flags against a fresh rebuild. A clean check proves reproducible packaging for the selected source tree; it does not prove marketplace installation or runtime/model behavior.

`validate_package.py` is fail-closed. It checks manifest inventory and hashes, extra files, absolute/parent-escaping paths, symlinks, case-fold collisions, source/home/secret-byte leaks, required manifests and documents, Claude/Codex roster parity and closure, hook references, and executable modes where the host exposes them. It reports named findings rather than repairing a package. Run it after every build and before a release candidate is handed to a native install probe.

The pair intentionally keeps release decisions outside these scripts: neither builds a remote marketplace, publishes an artifact, pushes Git, approves an integration plan, nor deletes a user installation. The release workflow owns those actions.

</details>

<details>
<summary><strong>Install-probe source independence and reports</strong></summary>

Each install probe builds from a disposable source copy and preserves the real tracked executable-mode map. It registers a local marketplace using the native runtime CLI, verifies the installed manifest and runtime-specific six-skill source, deletes the disposable source, scrubs `PYTHONPATH`, plugin-root variables, and `CODEMAP_*` variables except a controlled interpreter override, then runs `doctor`, `index`, and `query` through the installed launcher bytes. This proves the candidate does not accidentally import from the checkout; it does not prove an external marketplace or model session.

`probe_claude_install.py [--report PATH]` uses a disposable `CLAUDE_CONFIG_DIR`, checks the Claude manifest and `claude-skills/` roster, and reports missing native `claude` CLI as a prerequisite limitation. `probe_codex_install.py [--report PATH]` uses a disposable `CODEX_HOME`, checks the Codex object-form marketplace manifest and `codex-skills/` roster, and reports missing native `codex` CLI similarly. Both return 0 for source-independent runtime proof, 1 for a probe-detected failure, and 2 for a named prerequisite or usage failure.

`_probe_runtime.py` is import-only. Its supported helpers are `stage_disposable_source`, `write_real_mode_map`, `build_from_checkout`, and `runtime_proof`; changing staging, mode-map, scrubbed environment, or launcher selection requires running both probes. A non-executable launcher is a probe failure, not a reason to fall back to the Python entrypoint.

</details>

## 🧰 CLI entrypoint and compatibility shim

### `codemap_py_entry.py`

The Python entrypoint used by both platform launchers. It validates CPython `>=3.11,<3.15` before importing `codemap_py`, adds the installed `src/` directory to `sys.path`, and delegates to the CLI dispatcher. It performs no installation, download, or cache setup.

```text
python codemap_py_entry.py doctor --json
```

### `codemap_py_cli.py`

Compatibility shim for code that historically imported the bare `codemap_py_cli` module after adding `scripts/` to `sys.path`. New code should import `codemap_py.cli` directly. The shim has no separate command surface.

## 🧭 Maintainer boundaries

These scripts do not publish releases, push Git, mutate a remote marketplace, or approve integration plans. They build and inspect local artifacts; release policy and remote publication remain in the human release workflow. Keep examples pointed at explicit scratch directories and use the host's temporary-directory facilities rather than hard-coded platform paths.
