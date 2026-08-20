# Changelog

All notable changes to `bridge_CC-Codex` are documented here.

## 0.2.1

- Compress Claude- and Codex-side skill instructions while preserving explicit effort selection, caller-selected arguments, host-bound workspace/session authority, recursion refusal, detached-job lifecycle, compact-envelope/transcript boundaries, and paid live-probe consent.
- Retain Codex-side characterization coverage and validate Claude-side compression through exact executable-literal preservation plus full plugin and packaged-shape gates.

## 0.2.0

- Set the user-facing brand to `bridge_CC-Codex` across both host manifest descriptions and the Codex display metadata, while the installed plugin name, skill namespaces, and marketplace registrations stay `bridge` for consistency with the other plugins.
- Advertise the MCP server under the same `bridge` name the plugin already installs as, so the transport identifier no longer differs from the plugin identifier.
- Accept the task from a file via `--task-file`, mutually exclusive with `--task`, so a caller forwarding text it did not author never has to embed that text in a command line; both a missing and an ambiguous task source fail as the same parseable JSON error envelope every other failure uses.

## 0.1.0

- Add independently installable Claude Code and Codex halves for bounded `implement`, read-only `advise`, and adversarial `review` calls.
- Add caller-selected model and effort, task-tier normalization, per-verb soft budgets, hard cutoffs, bounded read-only retry, and recursion-depth protection.
- Return compact validated envelopes instead of forwarding raw host transcripts into the caller's context.
- Keep decision-critical fields and observed metadata in the public envelope while retaining bounded peer `details` in workspace-relative transcript artifacts and compact incident records.
- Route read-only reviews through a general Codex execution with an explicit adversarial-review prompt rather than relying on the native review subcommand.
- Add detached-job status, result, and cancellation controls, project-local transcript/job artifacts, sanitized incidents, and rolling health/cost records.
- Add static CLI drift diagnostics and an opt-in live setup probe for host availability, authentication, structured-output compatibility, and envelope behavior.
- Add repository marketplace registrations for Claude Code and Codex, disjoint host skill surfaces, and complete architecture, security, operations, and development documentation.
