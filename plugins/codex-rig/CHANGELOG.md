# Changelog

## 0.2.3

- Add intent-first target-merge conflict resolution to PR remediation, with explicit merge-commit authorization and fail-closed completion evidence.
- Add scoped `sync.sh clear` teardown for Claude and Codex plugins plus authenticated removal of the managed global-instructions block.
- Keep package identity, release documentation, and acceptance checks synchronized with the plugin version.

## 0.2.2

- Make Codex Rig the canonical source for workflows, role cards, lifecycle contracts, calibration, and public product documentation.
- Document exact blank-agent role injection, inline fallback, model-control limits, lifecycle behavior, and lessons learned from the original named-agent design.
- Replace repository-to-home `.codex` copying with public GitHub plugin installation.
- Follow the GitHub default branch by default while retaining an optional immutable release-tag pin.
- Ship generic Codex guidance as inert `assets/AGENTS.md`; repository sync installs or updates its backup-protected managed block by default whenever Codex scope is active, with `--no-codex-global-agents` opt-out. Direct plugin installation and Claude-only sync leave global and project instructions untouched.
- Require exact, explicit authorization before any amend, rebase, reset, squash, fixup, or equivalent history rewrite.

## 0.2.1

- Package 13 Codex-native workflow skills, one experimental shim manager, and 15 canonical specialist role cards.
- Support parallel blank-agent role-card injection with inline fallback when spawning is unavailable.
- Preserve transactional, exact-approval diagnosis and cleanup for prior thin user-agent shims on supported POSIX local filesystems; block new installation until runtime selection is verifiable.
- Add a trust-gated, read-only SessionStart shim-health diagnostic.
- Keep MCP and native plugin-bundled agent registration out of scope.

Known limit: standalone shim installation proves ownership and link integrity, not selection by the active
collaboration interface. Runtimes without an explicit custom-agent selector use blank-agent role injection.

## 0.1.0

- Establish the Apache-2.0 Codex plugin package, deterministic inventory, portable workflows, and canonical role cards.
- Define the thin-shim safety contract, authenticated installed state, and reversible transaction foundation.
- Introduce role-card fallback routing while native custom-agent selection remained unverified.
