<!-- policy-sibling-sync: CLAUDE.md, AGENTS.md, plugins/AGENTS.md, plugins/CLAUDE.md -->

Any policy change in one listed instruction file must trigger a relevance review of every other listed file before completion. Synchronize applicable shared policy in either direction; preserve intentional agent-specific differences and record when no counterpart change is needed.

## Edit Scope — Hard Constraint

**ALL edits must stay within this project directory.** Never directly edit `~/.claude/` or `$CODEX_HOME` (cache, settings, hooks, or any file under the user home).

**Permitted edit roots** (project-local):

- `.claude/settings.json`, `.claude/settings.local.json` — project Claude config
- `.codex/` — project Codex config, skills, session policy (mirrored to `$CODEX_HOME` by `sync.sh`, never edited there)
- `plugins/*/{agents,skills,rules,hooks,bin}/` — plugin source

**Propagation to live cache** at `~/.claude/plugins/cache/`:

- `sync.sh` installs from the pushed GitHub remote, not local working tree — commit and push first, then `bash sync.sh claude`
- Never run `sync.sh` against uncommitted/unpushed changes — cache will not reflect them
- Never suggest or initiate propagation mid-workflow
- Applies to all skills — no skill auto-syncs

## Lint/Format — Use pre-commit Hooks, Not Direct Tools

Repo pins lint/format tools via `.pre-commit-config.yaml` (ruff, eslint, mdformat, prettier, codespell, etc). **Never invoke these tools directly** (`ruff check`, `ruff format`, `eslint`, `mdformat`, ...) — version/config drift vs CI.

Invoke the specific hook instead:

```bash
pre-commit run <hook-id> --files <path>   # single hook, targeted files
pre-commit run --all-files                # full sweep
pre-commit run <hook-id> --all-files      # single hook, repo-wide
```

Hook ids (from `.pre-commit-config.yaml`): `ruff-check`, `ruff-format`, `eslint`, `mdformat`, `codespell`, `pyproject-fmt`, `validate-pyproject`, `end-of-file-fixer`, `trailing-whitespace`.

- Applies to ad-hoc checks during edits — not just the commit-time run
- If a hook is missing/needed and not yet in config, add it to `.pre-commit-config.yaml` rather than shelling out around it

## Test Workflow

- Python minimum 3.10. Repository root is an environment anchor, not an installable package.
- Bootstrap test tooling with `uv sync --only-group test`; benchmark-only dependencies use `uv sync --only-group bench`.
- Run tests with `.venv/bin/python -m pytest <paths>` — **not** `uv run pytest` or a bare `pytest`; the project venv is the pinned environment. Start focused, broaden to the affected suite before completion.

## Benchmark Isolation

Benchmark task IDs, target repositories, prompt wording, expected answers, and task-specific source or symbol examples are test evidence, not production content. Never copy them into shipped plugins, skills, templates, or user-facing docs; use neutral generic examples and encode the generalized contract in a regression test instead.

## Memory Policy

Nothing to auto-memory (`~/.claude/projects/.../memory/`). Learnings → skills, agents, rules, plugin files (versioned, distributed with plugin).

- New rule/guideline → edit `plugins/*/skills/*/SKILL.md`, `plugins/*/agents/*.md`, or `plugins/*/rules/*.md`
- Lesson/correction → update governing skill/agent/rule
- Never write to MEMORY.md or create memory files
