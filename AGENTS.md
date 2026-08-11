# Repository Agent Instructions

<!-- policy-sibling-sync: AGENTS.md, plugins/AGENTS.md, plugins/CLAUDE.md -->

Any policy change in one listed instruction file must trigger a relevance review of the other two before completion. Synchronize applicable shared policy in either direction; preserve intentional agent-specific differences and record when no counterpart change is needed.

## Core Principles

Simplicity and reliability come first. Understand the affected flow and root cause, then prefer the smallest clear, reversible solution that satisfies the verified contract. Prefer established project patterns, standard tools, and deletion over new abstractions, dependencies, configuration, or layers; add complexity only when current evidence proves it necessary.

Verification is part of implementation. Work is not complete until relevant checks pass and failures, residual risks, and deliberately deferred scope are reported accurately.

## Benchmark Isolation

Benchmark task IDs, target repositories, prompt wording, expected answers, and task-specific source or symbol examples are test evidence, not production content. Never copy them into shipped plugins, Skills, templates, or user-facing docs; use neutral generic examples and encode the generalized contract in a regression test instead.

## Focused Delegation

Use the lowest-cost capable subagent for small, well-defined support work when the task splits into independent bounded workstreams and the expected time or cost saving exceeds coordination overhead. Give each subagent narrow file or evidence ownership, only the context it needs, and explicit acceptance gates; parallelize disjoint work and never assign duplicate investigation or overlapping edits.

Keep indivisible or very small work in the main agent. The main agent owns integration, reviews every handoff against its gates, resolves conflicts, and retains final acceptance for behavior-changing or executable results.

## Markdown Policy

Never hard-wrap prose in any Markdown file. Keep each prose paragraph on one physical line; preserve intentional structural breaks in headings, lists, tables, blockquotes, links, HTML `<details>` blocks, and fenced code. Do not blindly unwrap or reflow a whole file; edit only the intended prose and retain its surrounding structure.

Plugin-specific authoring, installability, cross-reference, versioning, and verification rules live in [plugins/AGENTS.md](plugins/AGENTS.md).

## Project Workflow

- Python minimum: 3.10. The repository root is an environment anchor, not an installable package.
- Bootstrap test tooling with `uv sync --only-group test`; benchmark-only dependencies use `uv sync --only-group bench`.
- Run focused tests with `.venv/bin/python -m pytest <paths>` and broaden to the affected suite before completion.
- Run `.venv/bin/ruff check <changed-python-paths>` and `.venv/bin/ruff format --check <changed-python-paths>` for Python edits.
- Use `pre-commit run --all-files` only when the task requires the repository-wide gate; preserve unrelated working-tree changes.
- Release and build entry points are plugin-specific; follow `plugins/AGENTS.md` and the owning plugin's scripts and README. Remote publication remains human-owned.
