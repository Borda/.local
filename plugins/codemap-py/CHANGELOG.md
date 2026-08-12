# Changelog

`codemap-py` is the renamed, direct successor to the `codemap` plugin. The maintained product and its SemVer history continue across the rename; only the plugin identity, repository directory, and skill namespace change. Pre-`0.25.0` history was recorded as `codemap` under `plugins/codemap/` — see the repository git history for that line; it is not reproduced here.

## 0.29.1

- Keep structural queries in the caller's current repository, define returned relative paths against that repository rather than the installed Skill directory, and stop redundant query/source verification after `query_complete: true`; Claude prefers the literal PATH-resolved `codemap-py query` command so headless permission matching does not reject environment expansion, while the installed absolute launcher remains an interactive fallback and query-code permits only those query commands plus the documented Read/Write rendering path.

## 0.29.0

- Route direct callers and same-name implementation candidates to task-fit compact queries, while requiring source verification for inheritance claims.
- Skip structural retrieval for fully localized edits with no unresolved graph or source-slice fact, while preserving explicit tool requirements and the smallest relevant query for uncertain scope.

## 0.28.8

- Repair structural query routing for multi-query diff-impact evidence and broken Sphinx cross-references while preserving compact managed-run evidence boundaries.

## 0.28.7

- Replace closed integration, query, schema, scanner, and wrapper option strings with Python 3.10-compatible string enums without changing CLI or JSON wire values.

## 0.28.6

- Preserve static reverse-import edges for relative imports and known `from package import submodule` forms without adding false module edges for symbol imports.

## 0.28.5

- Harden cross-platform test isolation and publish synchronized structural and agentic benchmark evidence.

## 0.28.4

- Harden runtime state handling, temporary-file safety, path containment, and cross-runtime skill guidance after the plugin audit.

## 0.28.3

- Add actionable hints for invalid query commands and align mirrored production-importer, feature-scaffolding, and symbol-routing guidance with the supported CLI contracts.

## 0.28.2

- Improve structural query fidelity for source-root aliases, centrality, direct-import routes, and compact coverage results.

## 0.28.1

- Correct Codex and Claude query-skill guidance for direct-import routes used by structural validation.

## 0.28.0

- Add alias-aware import and symbol resolution across scanning, graph construction, structural queries, and integration probes.

## 0.27.3

- Clarify query command contracts and improve structural-query discoverability for Codex.

## 0.27.2

- Streamline all six Codex skills around the native plugin-root integration contract.

## 0.27.1

- Harden frozen structural queries and compact coverage output while preserving complete-result metadata.

## 0.27.0

- Port all six Claude hooks to stdlib-only Python: session seeding, exhaustive-query recording, redundant-scan guard, preamble injection, skill-start telemetry, and tool-use telemetry. The guard and recorder retain their shared per-session sentinel contract. The preamble uses an atomic exclusive refresh lock and a platform-specific detached spawn; its Windows process-group branch is acceptance-tested. Claude hook wiring now launches Python helpers; Codex still declares no hook.
- Remove the retired installed-cache injection implementation and its audit/tests. The integration engine is the sole source-wiring path: `build_plan`/`apply_plan` write authenticated blocks only at finalized checked-in targets. Migration utilities for plugin-root and dual-identity detection now live in `codemap_py.index_paths`; the legacy post-commit installer is removed, while `resolve_proj_index.py` and `smoke_test_index.py` remain live skill dependencies.
- Finalize the engine target map: oss writes `skills/_shared/codemap-gates.md`; foundry, develop, and research write `skills/_shared/codemap-context.md`; codex-rig writes `shared/codemap-py-integration.md`. Root `sync.sh` stays the whole-repo aggregate installer; retiring it to a `codemap-py integrate` exec adapter is deferred to a follow-up, since `integrate` covers only the codemap-integration set, not sync.sh's full install scope.

## 0.26.0

- Make the `integrate apply` engine byte-exact on Windows: `_atomic_write` now writes the managed block in binary mode so the on-disk bytes stay LF-only on every OS, matching the plan's expected post-state hash and the block's own embedded SHA-256 stamp (text-mode writes translated `\n` to `\r\n` on Windows, corrupting the self-authenticating marker and failing the post-write hash check); source-write rollback likewise restores the exact original bytes.
- Decode every `git`/native-CLI subprocess with `encoding="utf-8"` (`canonical_root`, `_git_dirty`, `_run_native`, and the JSON probe) so a project path containing non-ASCII characters resolves correctly on Windows instead of being mangled by the console code page and misrouting the dirty-overlap and identity checks.
- Seed the integration test fixtures LF-only and disable `core.autocrlf` in the disposable fixture repos so the suite is byte-deterministic across platforms; add a test asserting a freshly applied managed block contains no `\r\n`.
- **Dual-runtime skill parity.** `codemap-py` now ships a Codex skill roster under `codex-skills/` alongside the existing Claude roster under `claude-skills/`, and the Codex manifest points `skills` at `./codex-skills/`. Both runtimes expose the same six skills — `scan-codebase`, `query-code`, `test-impact`, `rename-refs`, `integration`, and `debrief-coding` — with identical truth-claims (inputs, outputs, exit codes, completeness metadata, caveats), differing only in runtime-specific invocation (Codex resolves an explicit plugin-root path and has no `bin/` PATH or `AskUserQuestion` tool). A shared capability contract (`shared/capability-contract.md`) is the single source of those truth-claims, and a parity test rejects missing skills, stale command names, unsupported cache paths, or contradictory limits. Codex still ships no hooks in this release — a documented automation limitation, not hidden parity.
- **Native `integrate` control plane** (`codemap-py integrate check|plan|apply|sync|demo`, surfaced as `/codemap-py:integration` and `$codemap-py:integration`). `check` is a read-only health report; `plan` persists an inspectable artifact (exact targets, before-state hashes, argv arrays, ordered operations, rollback identities) bound by a SHA-256; `apply` updates only sentinel-bounded managed blocks inside allowlisted consumer source files (marker `<!-- codemap-py:integration:begin v1 sha256=… -->`), preserving everything outside the block byte-for-byte and refusing foreign/modified markers, path escapes, symlinks, installed-cache roots, or dirty overlap; `sync` runs only the approved native plugin-manager argv and never mutates source or global instructions; `demo` records disposable evidence. Every mutation is dry-run-first, hash-approved, journaled with before-images, and rolled back on partial failure, ending `recovery-required` if a rollback cannot be verified. This replaces the retired installed-cache `init` injection model.
- The Claude `integration` skill was rewritten from the retired `check|init|demo` model to `check|plan|apply|sync|demo`; the legacy demo A/B measurement helper was removed. The package builder now ships `codex-skills/` and `shared/` and records the Codex skill roster in the manifest, and the package validator now enforces Codex six-skill parity in place of the former zero-roster rule. Both plugin manifests move to `0.26.0`.

## 0.25.1

- Extracted the two monolithic `bin/` executables into an importable `src/codemap_py/` package: `scanner` (Python-file discovery and single-file AST parsing), `graph` (import/call/test/fixture/docstring graph, coverage, and test-impact construction plus scan orchestration), `query` (query dispatch and rendering), `cli` (the shared dispatcher), and the schema/index-path/read-write-gate/ logging/telemetry cores. `bin/scan-index` and `bin/scan-query` are now thin launchers over the package; `python -m codemap_py` reaches the same dispatcher. The legacy `bin/_*.py` module names remain as compatibility shims, so existing imports and monkeypatches keep working unchanged. No CLI behavior, output bytes, or exit codes changed — the move is byte-for-byte parity-tested against the pre-extraction bytes.
- **`.pyi` type stubs now participate in analysis** (plan §2.1 scope extension). A sibling `module.py` stays authoritative and its `module.pyi` is recorded as a shadowed stub rather than indexed twice; a `module.pyi` with no implementation is indexed once as a stub-only module contributing declarations and imports but no call edges; `package/__init__.pyi` follows the same precedence rule; case-fold path collisions fail closed identically on every OS. Editing a `.pyi` now invalidates the index. The first scan after upgrading rebuilds each index once (new discovery set), then reuse is stable; the on-disk index schema and `.cache/codemap/` path are unchanged.
- Reorganized the test suite into subsystem subfolders with shared fixtures under `tests/data/` (test-only; nothing ships in the package).

## 0.25.0

- **Renamed the product and plugin identity**: `codemap` → `codemap-py`, directory `plugins/codemap/` → `plugins/codemap-py/`. **! BREAKING**: the Claude skill namespace changed from `/codemap:*` to `/codemap-py:*` — renaming one plugin manifest cannot keep a second namespace alive, so every saved prompt, alias, or automation invoking the old triggers must move to the new namespace. `scan-index`/`scan-query` compatibility aliases, the `.cache/codemap/` project cache, and every `CODEMAP_*` environment variable are unaffected and keep working exactly as before.
- Added a dual-runtime package layout: a Claude Code manifest (`.claude-plugin/plugin.json`) alongside a new Codex manifest (`.codex-plugin/plugin.json`). The Codex manifest ships with **no skill roster yet** — Codex skill parity lands in a later `0.25.x` release. Both manifests share the same product identity and SemVer version.
- Carried forward the `codemap-py` CLI (`codemap-py index` / `codemap-py query` / `codemap-py doctor`), the process-safe shared-index read/write gate, and the runtime-neutral index-identity resolver introduced under `codemap` `0.24.1`, now packaged under the renamed identity.
- Removed `hooks/sentinel-read-allow.js` from the shipped payload. That shared auto-allow hook is canonical to, and now lives only in, the `cc_foundry` plugin; installs without `cc_foundry` see an ordinary Bash permission prompt for sentinel-read compounds instead of auto-allow — a UX difference only, never a correctness one.
- Added `LICENSE` (Apache-2.0) and `NOTICE` to the package payload.

## Predecessor

Continuity note: `codemap-py` `0.25.0` succeeds `codemap` `0.24.0`/`0.24.1` directly — same maintained product and release train, not a new `0.1.0` line and not yet a `1.0.0` stable line. See [Upgrading from codemap](README.md#upgrading-from-codemap) for the migration and rollback procedure.
