# scripts/ — build, validation, and install-probe tooling

This directory holds the maintainer-facing tooling that turns the tracked `codemap-py` plugin source tree into a shippable package, checks that package for closure and portability, and proves the package actually installs into a real Claude Code or Codex CLI. None of these scripts are part of the runtime CLI surface a project author interacts with day to day (that lives in `bin/`, documented separately) — everything here runs at release-engineering time, or from a test suite that exercises the release pipeline.

## Contents

- [Package build and validation](#package-build-and-validation) — `build_package.py`, `validate_package.py`
- [Install probes](#install-probes) — `probe_claude_install.py`, `probe_codex_install.py`, `_probe_runtime.py`
- [CLI entrypoint and compatibility shim](#cli-entrypoint-and-compatibility-shim) — `codemap_py_entry.py`, `codemap_py_cli.py`

## Package build and validation

`build_package.py` and `validate_package.py` are a matched pair: the first assembles a package, the second checks it. Every release (and every install probe, which builds a disposable candidate first) runs `build_package.py` and should follow it with `validate_package.py` before trusting the result.

### `build_package.py`

**Purpose.** Assembles the deterministic `codemap-py` distribution package from the REAL tracked plugin tree — both runtime manifest directories, every `bin/` executable and support module, the `scripts/` entrypoints, the Claude and Codex skill rosters, hook wiring, and the top-level product documents (`README.md`, `LICENSE`, `NOTICE`, `CHANGELOG.md`). Name and version are read from `.claude-plugin/plugin.json` at build time, never hardcoded. The package is git-tracked-set derived: `_INCLUDE_DIRS` membership is drawn from the same `{relative_posix_path: is_executable}` map used for the executable-bit metadata (by default `git ls-files --stage` on `source_root`), so an untracked file under an include directory is simply invisible to the payload rather than a build error. Determinism guarantees: stable file order, LF-terminated manifest, fixed on-disk modes, no timestamps, and an exec flag taken from git's tracked mode rather than the build host's `st_mode` — a Windows and a POSIX build of the same commit therefore produce a byte-identical `package-manifest.json`.

**Usage.**

```
python plugins/codemap-py/scripts/build_package.py --out <dir> [--check] [--mode-map <path>]
```

- `--out <dir>` (required) — package output directory; cleared and recreated on each build.
- `--check` — rebuild to a temporary directory and byte-compare against `--out` (or against a fresh second build when `--out` is empty), also verifying on-disk executable modes agree with the manifest.
- `--mode-map <path>` — JSON `{relative_posix_path: bool}` file overriding `source_root`'s own git-derived exec modes; used by the install probes, which build from a disposable copy whose own synthesized git index is not authoritative.

Exit `0` on success, `1` on a `--check` mismatch, `2` on a usage or payload-closure error (missing required document, symlink, case collision, missing mode-map entry).

**How-to.**

```bash
python plugins/codemap-py/scripts/build_package.py --out /tmp/codemap-py-pkg
python plugins/codemap-py/scripts/build_package.py --out /tmp/codemap-py-pkg --check
```

**When-to-use.** At release build time, to produce the artifact that gets distributed through a marketplace, and in CI with `--check` to catch a non-deterministic build (e.g. a file whose executable bit disagrees between hosts) before it ships.

### `validate_package.py`

**Purpose.** Validates a directory produced by `build_package.py` against its own `package-manifest.json` and a set of closure rules, asserting that the package is a closed, self-contained, portable artifact. It checks: inventory identity (every manifest entry exists on disk with a matching SHA-256, no un-manifested extra file); portability (no symlinks, no case-folding collisions, no absolute or parent-escaping manifest paths); hygiene (no source-checkout or personal-home path bytes, no obvious secret material such as private-key headers or provider token prefixes, in the payload); closure (both runtime manifests and all required product documents present, no default `skills/` directory or `hooks/hooks.json` leaking in); declared-component closure (the Claude skill roster matches the on-disk `SKILL.md` directories exactly, every referenced hook helper exists and is inventoried, and the Codex manifest declares the same six-skill roster as Claude); and executable modes (on POSIX, each file's on-disk executable bit matches its manifest `exec` flag — informational only on Windows).

**Usage.**

```
python plugins/codemap-py/scripts/validate_package.py --package <dir>
```

- `--package <dir>` (required) — a directory previously produced by `build_package.py`.

Exit `0` when clean, `1` with named findings on stderr, `2` on a usage error (missing manifest or directory).

**How-to.**

```bash
python plugins/codemap-py/scripts/validate_package.py --package /tmp/codemap-py-pkg
```

**When-to-use.** Immediately after `build_package.py`, before tagging or shipping a release — build then validate is the standard two-step release gate. Also useful any time a package directory's integrity is in question (e.g. after a manual edit) since it re-derives every closure guarantee from first principles rather than trusting the manifest blindly.

## Install probes

`probe_claude_install.py` and `probe_codex_install.py` are feasibility probes, not CI unit tests: each drives the real `claude` or `codex` CLI against a throwaway config directory to prove a freshly built candidate package actually installs and exposes the roster it declares. Neither ever touches the user's real `~/.claude` or `~/.codex` — every mutation is scoped to a fresh temporary directory removed on exit. Both share their staging and runtime-proof logic through `_probe_runtime.py`.

### `probe_claude_install.py`

**Purpose.** Copies the plugin working tree into a disposable checkout, builds a candidate package from that copy (using a mode map captured from the REAL repository's git index beforehand, since the copy's own synthesized index is never authoritative), registers a local Claude marketplace pointing at the candidate, and runs `claude plugin marketplace add` + `claude plugin install codemap-py@<mkt> --scope user` against a scratch `CLAUDE_CONFIG_DIR`. It then statically verifies the installed bytes (Claude skill roster matches `package-manifest.json`, no `codex-skills/` registered as a Claude skills source), deletes the entire disposable source tree, and finally proves source-independent runtime execution — `doctor`/`index`/`query` run from the installed cache bytes through the shipped launcher under a scrubbed environment, asserting no forbidden path leaks via env, argv, or installed bytes.

**Usage.**

```
python plugins/codemap-py/scripts/probe_claude_install.py [--report <path>]
```

- `--report <path>` — also write the JSON result to this path (always printed to stdout).

Exit `0` = installed and verified; `2` = a named prerequisite is absent (`build_package.py` not yet present, or the `claude` CLI is not installed) — a recorded limitation, not a failure; `1` = the probe ran but installation or verification failed.

**How-to.**

```bash
python plugins/codemap-py/scripts/probe_claude_install.py --report /tmp/claude-probe.json
```

**When-to-use.** As a release-acceptance check that the package actually installs cleanly through Claude Code's real plugin-install path — run it whenever the package layout, manifest fields, or skill roster change, and as part of the pre-release checklist.

### `probe_codex_install.py`

**Purpose.** The Codex-side mirror of `probe_claude_install.py`: stages a disposable copy, builds a candidate, writes a local Codex marketplace manifest (`.agents/plugins/marketplace.json`, using Codex's object-form `source` discriminator), and runs `codex plugin marketplace add` + `codex plugin add codemap-py@<mkt> --json` against a scratch `CODEX_HOME`. It verifies a Codex skill source referencing `codex-skills/`, a non-empty installed Codex roster, and that `claude-skills/` is not registered as the Codex source. Package validation separately requires the shipped `./codex-skills/` source and the six-skill Claude/Codex parity. The probe then deletes the disposable source and proves `doctor`/`index`/`query` run only from installed cache bytes under a scrubbed environment.

**Usage.**

```
python plugins/codemap-py/scripts/probe_codex_install.py [--report <path>]
```

- `--report <path>` — also write the JSON result to this path (always printed to stdout).

Exit `0` = installed and verified; `2` = a named prerequisite is absent (builder not present, or the `codex` CLI is not installed); `1` = the probe ran but installation or verification failed.

**How-to.**

```bash
python plugins/codemap-py/scripts/probe_codex_install.py --report /tmp/codex-probe.json
```

**When-to-use.** Same release-acceptance role as `probe_claude_install.py`, for the Codex Rig install path. Run both probes together before a release — they exercise different marketplace manifest shapes and different roster contracts.

### `_probe_runtime.py`

**Purpose.** Shared helper module backing both install probes — not a standalone CLI. Implements the disposable-source-copy runtime proof: capture the authoritative exec-mode map from the real repository's git index, `shutil.copytree` the plugin working tree into a temp checkout outside the repo (minus caches/tests/junk), build the candidate from that copy via `build_package.py --mode-map`, delete the entire temp source tree, then execute `doctor`/`index`/`query` from the installed cache bytes strictly through the shipped launcher (`bin/codemap-py`; there is deliberately no Python-entry fallback — a non-executable launcher is a probe failure, not a silent reroute) under an environment scrubbed of `PYTHONPATH`, `CLAUDE_PLUGIN_*`, and `CODEMAP_*` variables (except a controlled `CODEMAP_PYTHON`), scanning env, argv, and installed bytes for any reference to a forbidden root.

**Usage.** Imported only — `from _probe_runtime import build_from_checkout, runtime_proof, stage_disposable_source, write_real_mode_map`. It has no `__main__` block and is never invoked from the command line.

**How-to.** Not directly runnable; to exercise its logic, run `probe_claude_install.py` or `probe_codex_install.py`, both of which call into it.

**When-to-use.** Internal shim — not invoked directly. Anyone changing its staging, mode-map, or scrubbed-env logic should re-run both install probes afterward, since they are its only callers and the sole way to observe a regression here.

## CLI entrypoint and compatibility shim

### `codemap_py_entry.py`

**Purpose.** The single Python entrypoint shared by the POSIX launcher (`bin/codemap-py`), the Windows launcher (`bin/codemap-py.cmd`), an editable developer install, and runtime skills. It validates the running interpreter against the supported bound (CPython 3.11 up to, but excluding, 3.15) BEFORE importing anything from `codemap_py`, then prepends `<plugin-root>/src` to its own process import path and hands control to `codemap_py.cli.main` without remapping arguments. It performs no install, download, cache mutation, or dependency setup — it is a pure dispatcher.

**Usage.**

```
python3 scripts/codemap_py_entry.py <codemap-py-subcommand> [args...]
```

On interpreter rejection, stdout stays empty and a single diagnostic is written to stderr; exit code `127`. Otherwise the exit code is whatever `codemap_py.cli.main` returns for the given subcommand.

**How-to.**

```bash
python3 plugins/codemap-py/scripts/codemap_py_entry.py doctor --json
```

**When-to-use.** This is what `bin/codemap-py` and `bin/codemap-py.cmd` `exec` into after they have located an eligible interpreter — it is rarely invoked by name directly, but doing so is useful when debugging interpreter resolution or when working from a source checkout without an installed launcher.

### `codemap_py_cli.py`

**Purpose.** A compatibility shim for `codemap_py.cli`. `codemap_py_entry.py` already imports `codemap_py.cli` directly; this shim exists only so consumers that import the bare `codemap_py_cli` name after inserting `scripts/` onto their own `sys.path` (tests, an editable checkout) keep working. It prepends `<plugin-root>/src` to `sys.path`, then replaces its own entry in `sys.modules` with the real package module so every attribute access — including `is_supported`, `candidate_interpreters`, and `resolve_interpreter`, which tests exercise directly — reaches the one authoritative implementation.

**Usage.** Imported only, as a bare module name after a `sys.path.insert` of `scripts/`: `import codemap_py_cli`. It has no CLI surface of its own.

**How-to.** Not run directly; a test file that needs it does:

```python
import sys

sys.path.insert(0, "plugins/codemap-py/scripts")
import codemap_py_cli
```

**When-to-use.** Internal shim — not invoked directly. It is a transitional compatibility layer kept for test and editable-checkout imports; new code should import `codemap_py.cli` directly instead.
