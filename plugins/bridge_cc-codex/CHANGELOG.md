# Changelog

All notable changes to `bridge` are documented here.

## 0.1.0

- Add independently installable Claude Code and Codex halves for bounded `implement`, read-only `advise`, and adversarial `review` calls.
- Add caller-selected model and effort, task-tier normalization, per-verb soft budgets, hard cutoffs, bounded read-only retry, and recursion-depth protection.
- Return compact validated envelopes instead of forwarding raw host transcripts into the caller's context.
- Keep decision-critical fields and observed metadata in the public envelope while retaining bounded peer `details` in workspace-relative transcript artifacts and compact incident records.
- Route read-only reviews through a general Codex execution with an explicit adversarial-review prompt rather than relying on the native review subcommand.
- Add detached-job status, result, and cancellation controls, project-local transcript/job artifacts, sanitized incidents, and rolling health/cost records.
- Add static CLI drift diagnostics and an opt-in live setup probe for host availability, authentication, structured-output compatibility, and envelope behavior.
- Add repository marketplace registrations for Claude Code and Codex, disjoint host skill surfaces, and complete architecture, security, operations, and development documentation.
