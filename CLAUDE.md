## Edit Scope — Hard Constraint

**ALL edits must stay within this project directory.** Never directly edit `~/.claude/` (cache, settings, hooks, or any file under the user home).

**Permitted edit roots** (project-local):

- `.claude/agents/`, `.claude/skills/`, `.claude/rules/`, `settings.json` — project config
- `plugins/*/hooks/`, `plugins/*/agents/`, `plugins/*/skills/` — plugin source

**Propagation to live cache** at `~/.claude/plugins/cache/`:

- Use `bash sync.sh claude` only — cache is managed by plugin install, never hand-edited
- Never suggest or initiate propagation mid-workflow
- Applies to all skills — no skill auto-syncs

## Memory Policy

Nothing to auto-memory (`~/.claude/projects/.../memory/`). Learnings → skills, agents, rules, plugin files (versioned, distributed with plugin).

- New rule/guideline → edit `plugins/*/skills/*/SKILL.md`, `plugins/*/agents/*.md`, or `plugins/*/rules/*.md`
- Lesson/correction → update governing skill/agent/rule
- Never write to MEMORY.md or create memory files
