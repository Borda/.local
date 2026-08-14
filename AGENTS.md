# Repository Agent Instructions

<!-- policy-sibling-sync: CLAUDE.md, AGENTS.md, plugins/AGENTS.md, plugins/CLAUDE.md -->

Any policy change in one listed instruction file must trigger a relevance review of every other listed file before completion. Synchronize applicable shared policy in either direction; preserve intentional agent-specific differences and record when no counterpart change is needed.

## Edit Scope

All edits stay inside this project directory. Never edit `$CODEX_HOME` or `~/.claude/` directly — both are install targets populated from this checkout, and a hand-edit there is overwritten on the next sync.

- Permitted roots: `.codex/` (Codex config, skills, session policy), `.claude/settings.json` and `.claude/settings.local.json`, `plugins/*/{agents,skills,rules,hooks,bin}/`.
- `sync.sh` installs from the pushed GitHub remote, not the local working tree: commit and push first, then `bash sync.sh [claude|codex]`. Running it against uncommitted work silently installs the previous state.
- Never initiate propagation mid-task; it is a deliberate human-triggered step.

## Core Principles

Simplicity and reliability come first. Understand the affected flow and root cause, then prefer the smallest clear, reversible solution that satisfies the verified contract. Prefer established project patterns, standard tools, and deletion over new abstractions, dependencies, configuration, or layers; add complexity only when current evidence proves it necessary.

Verification is part of implementation. Work is not complete until relevant checks pass and failures, residual risks, and deliberately deferred scope are reported accurately.

## Multi-OS Executables

Scripts, hooks, `bin/` entry points, and CI steps all run on Linux, macOS, and native Windows. A POSIX-only assumption is a defect to fix at the source, never a reason to skip the platform.

- `pathlib`; `Path(p).is_absolute()` not a leading-slash check; `PurePath(p).as_posix()` before hashing, serializing, or comparing a path — native separators change the digest.
- POSIX-absolute literals are not portable fixtures: `/host/x` resolves to `D:\host\x` on Windows.
- Byte-asserted or hashed writes use `newline="\n"` or bytes; text mode emits CRLF on Windows.
- Sanitized subprocess `env=` keeps `SystemRoot`, `SYSTEMROOT`, `COMSPEC`, `PATHEXT`, `TEMP`, `TMP` on win32, else the child Python aborts before running; temp dirs via `os.environ.get("TMPDIR") or tempfile.gettempdir()`, never `/tmp`.
- A workflow `run:` step invoking `.sh` needs explicit `shell: bash` — the Windows default shell dot-sources it and exits zero, a false green.
- Symlinks, file modes, and uid checks are capabilities: degrade in production code first.
- Skips are the last resort: never a blanket `skipif(sys.platform == "win32")`, always a capability probe skipping on `OSError`, with each surviving skip documented and re-audited.
- Test skips must be collection-time decorators (`pytest.mark.skipif`, `pytest.mark.skip`, or parametrized marks); never call `pytest.skip()` from a test or fixture body.
- Green macOS is absence of regression, not Windows support: prove Windows semantics with `PureWindowsPath` or `ntpath`, since monkeypatching `os.name` does not change `pathlib`.

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
- Lint/format edits via the pinned pre-commit hooks, never the bare tool: `pre-commit run ruff-check --files <changed-python-paths>`, `pre-commit run ruff-format --files <changed-python-paths>`, and `pre-commit run mdformat --files <changed-markdown-paths>`; direct `ruff` or `mdformat` invocation drifts from the version/config pinned in `.pre-commit-config.yaml`.
- Use `pre-commit run --all-files` only when the task requires the repository-wide gate; preserve unrelated working-tree changes.
- Release and build entry points are plugin-specific; follow `plugins/AGENTS.md` and the owning plugin's scripts and README. Remote publication remains human-owned.
