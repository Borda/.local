# Changelog

`codemap-py` is the renamed, direct successor to the `codemap` plugin. The maintained
product and its SemVer history continue across the rename; only the plugin identity,
repository directory, and skill namespace change. Pre-`0.25.0` history was recorded as
`codemap` under `plugins/codemap/` — see the repository git history for that line; it is
not reproduced here.

## 0.25.1

- Extracted the two monolithic `bin/` executables into an importable
  `src/codemap_py/` package: `scanner` (Python-file discovery and single-file AST
  parsing), `graph` (import/call/test/fixture/docstring graph, coverage, and
  test-impact construction plus scan orchestration), `query` (query dispatch and
  rendering), `cli` (the shared dispatcher), and the schema/index-path/read-write-gate/
  logging/telemetry cores. `bin/scan-index` and `bin/scan-query` are now thin launchers
  over the package; `python -m codemap_py` reaches the same dispatcher. The legacy
  `bin/_*.py` module names remain as compatibility shims, so existing imports and
  monkeypatches keep working unchanged. No CLI behavior, output bytes, or exit codes
  changed — the move is byte-for-byte parity-tested against the pre-extraction bytes.
- **`.pyi` type stubs now participate in analysis** (plan §2.1 scope extension). A
  sibling `module.py` stays authoritative and its `module.pyi` is recorded as a
  shadowed stub rather than indexed twice; a `module.pyi` with no implementation is
  indexed once as a stub-only module contributing declarations and imports but no call
  edges; `package/__init__.pyi` follows the same precedence rule; case-fold path
  collisions fail closed identically on every OS. Editing a `.pyi` now invalidates the
  index. The first scan after upgrading rebuilds each index once (new discovery set),
  then reuse is stable; the on-disk index schema and `.cache/codemap/` path are
  unchanged.
- Reorganized the test suite into subsystem subfolders with shared fixtures under
  `tests/data/` (test-only; nothing ships in the package).

## 0.25.0

- **Renamed the product and plugin identity**: `codemap` → `codemap-py`, directory
  `plugins/codemap/` → `plugins/codemap-py/`. **! BREAKING**: the Claude skill namespace
  changed from `/codemap:*` to `/codemap-py:*` — renaming one plugin manifest cannot keep
  a second namespace alive, so every saved prompt, alias, or automation invoking the old
  triggers must move to the new namespace. `scan-index`/`scan-query` compatibility
  aliases, the `.cache/codemap/` project cache, and every `CODEMAP_*` environment variable
  are unaffected and keep working exactly as before.
- Added a dual-runtime package layout: a Claude Code manifest (`.claude-plugin/plugin.json`)
  alongside a new Codex manifest (`.codex-plugin/plugin.json`). The Codex manifest ships
  with **no skill roster yet** — Codex skill parity lands in a later `0.25.x` release.
  Both manifests share the same product identity and SemVer version.
- Carried forward the `codemap-py` CLI (`codemap-py index` / `codemap-py query` /
  `codemap-py doctor`), the process-safe shared-index read/write gate, and the
  runtime-neutral index-identity resolver introduced under `codemap` `0.24.1`, now
  packaged under the renamed identity.
- Removed `hooks/sentinel-read-allow.js` from the shipped payload. That shared auto-allow
  hook is canonical to, and now lives only in, the `cc_foundry` plugin; installs without
  `cc_foundry` see an ordinary Bash permission prompt for sentinel-read compounds instead
  of auto-allow — a UX difference only, never a correctness one.
- Added `LICENSE` (Apache-2.0) and `NOTICE` to the package payload.

## Predecessor

Continuity note: `codemap-py` `0.25.0` succeeds `codemap` `0.24.0`/`0.24.1` directly — same
maintained product and release train, not a new `0.1.0` line and not yet a `1.0.0` stable
line. See [Upgrading from codemap](README.md#upgrading-from-codemap) for the migration and
rollback procedure.
