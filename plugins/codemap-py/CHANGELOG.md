# Changelog

`codemap-py` is the renamed, direct successor to the `codemap` plugin. The maintained
product and its SemVer history continue across the rename; only the plugin identity,
repository directory, and skill namespace change. Pre-`0.25.0` history was recorded as
`codemap` under `plugins/codemap/` — see the repository git history for that line; it is
not reproduced here.

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
