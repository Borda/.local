# Benchmark Instructions

Root `AGENTS.md` applies here and is not restated: benchmark isolation, the test/lint workflow, multi-OS executables, and Markdown no-wrap. Below is benchmark-specific only.

- Use Fire for every Python CLI. Add a study to an existing provider runner when it shares transport or isolation; keep stage-specific contracts and scorers in focused modules rather than creating a second launcher.
- Interactive A/B/C result rows are a CLI contract: persist plain rows to a stage run log when that stage has one, and always route terminal output through the existing shared Rich arm renderer. Do not add direct `print()` paths for arm rows; redirected output must remain ANSI-free. Add a focused renderer-forwarding regression for every new stage or rescore path.
- Never run paid models. Give the user the exact command emitted by a fresh dry run with its 16-character `--paid-approval` token; retain the complete SHA-256 in benchmark provenance, then analyze only the artifact they provide.
- Treat task suites, manifests, frozen repositories, indexes, and input snapshots as immutable benchmark coordinates. Regenerate generated manifests after contract or consumer changes; do not edit result artifacts.
- Keep A/B/C arms symmetric except for the documented treatment supplement. State Codemap's static-graph boundary: use it for compact symbol/dependency/importer/caller facts, not runtime validation, test execution, or edits.
- Treat A_plain versus C_strict as the decision-grade comparison. B_auto is an optional-use canary: if it costs more than A_plain, recommend the installed integration rather than treating that as a failure of the strict treatment.
- Executable tasks require benchmark-owned disposable worktrees, canonical diff capture, a second clean scoring worktree, ordinary patch application, independent behavior oracle, and verified cleanup. `--recount` is diagnostic-only.
- For a changed runner execute its relevant `--dry-run` and scope-resolution command; no-model checks may be run by Codex.
