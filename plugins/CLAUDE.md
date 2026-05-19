# Plugin Authoring Rules

Plugins under `plugins/`. See `README.md` for user-facing detail.

## Writing Style

Use `/caveman` compression for all agent, skill, rule file edits — drop articles, filler, hedging; keep full technical substance.

## File Layout

- `.claude-plugin/plugin.json` — version + metadata
- `agents/`, `skills/`, `README.md`, `CLAUDE.md` (optional)
- `bin/` — optional: standalone executables (`.sh`, `.py`) auto-added to Bash `PATH` by Claude Code; invoked via `${CLAUDE_PLUGIN_ROOT}/bin/<script>` inside skills
  - **Language policy — `bin/`**: Python default (minimum 3.10); bash only for enumerated cases: (1) plugin install-path resolution, (2) `$ARGUMENTS` parsing where bash regex shorter and quoting-safe, (3) `find | sort | head` pipelines with no business logic
    - Python scripts: type hints, module docstring, `if __name__ == "__main__"` guard; ruff-format 120-char line length (pre-commit enforced); aggregate related print output into single `print()` using `\n`/`\t`; pure functions (no I/O, no subprocess, no env-var reads) → `doctest` in docstring; anything with I/O/subprocess/argv → `pytest` with `capsys`/`monkeypatch` in `tests/` alongside `bin/`
    - bin/ scope: deterministic transforms only (parse args, resolve paths, compute one value); decision flow, branching prompts, agent-dispatch logic stays in SKILL.md prose
    - Reference design: `plugins/codemap/bin/` (typed, docstrings, `__name__` guards, dataclass serialization boundaries)
  - **Language policy — inline blocks in SKILL.md**: bash default; Python only when bash version requires JSON parsing, multi-line string manipulation, or numeric computation (and note: `Bash(python:*)` not in allow list — inline Python triggers approval prompt every invocation)
- `rules/`, `hooks/` — foundry only

## Shared File Authoring Rule (modes/, templates/, _shared/)

Every file added to `plugins/*/skills/*/modes/`, `plugins/*/skills/*/templates/`, or `plugins/*/skills/_shared/` **must** satisfy at least one of:

1. Its **basename appears as a literal string** in at least one consumer `.md` file (SKILL.md, agent `.md`, or another shared file) — e.g. `# loads: upgrade.md` or inline in prose
2. The file itself contains a `<!-- file: <basename> — consumers: ... -->` header declaring cross-plugin consumers (use when all consumers are in a different plugin)

**Why**: grep-based orphan checks find zero hits → agent concludes file is dead → deletes it. This has happened to `adversarial.md`, `upgrade.md`, `vitality-calibration.md`. A single comment line prevents deletion. Check R2 (`/foundry:audit plugins`) detects violations.

**At authoring time**: before writing the file, identify its consumer SKILL.md and add the `# loads:` comment there first, then create the file. If consumer is in a different plugin, add the `<!-- file: ... -->` header to the file itself.

## Installability

- Every file must be installable via `claude plugin install <name>@borda-ai-rig`
- No file depend on source tree — assume installed path only
- No hardcoded paths to sibling plugins or `plugins/<name>/` directories
- Validate: after `claude plugin install`, all agents/skills/rules/hooks resolve without local `plugins/` tree
- **Bare `plugins/` path = only valid as final fallback** after cache-path resolution: `VAR="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/_shared 2>/dev/null | head -1)"; [ -z "$VAR" ] && VAR="plugins/<plugin>/skills/_shared"`. Never use bare `plugins/` as primary path. Check C32 flags violations.
- **Health monitoring mandatory for background agents**: any skill spawning `Agent(..., run_in_background=true)` must implement CLAUDE.md §8 (sentinel + 5-min poll + 15-min cutoff). Reference `_FOUNDRY_SHARED/agent-spawn-protocol.md` rather than reproducing inline. Check C35 flags violations.

## Naming

- Plugin-prefixed refs always: `foundry:sw-engineer`, `oss:review` — never bare names
- Agent `subagent_type` must match filename (e.g. `sw-engineer.md` → `foundry:sw-engineer`)

## Cross-References

- `description` field = routing signal; calibrated threshold `routing accuracy ≥90%`
- NOT-for lines mandatory in every agent; `/audit` Check 16 flags ≥40% overlap
- **Independent instances** — each plugin is independent install; treat as if source tree absent
  - Never cross-ref via local/relative path (e.g. `../foundry/agents/foo.md`) — breaks after install
  - Reference only via installed plugin-prefixed name (e.g. `foundry:sw-engineer`)
- **Opt-in gating required** — plugins opt-in; user may have only subset installed
  - Any cross-plugin usage **must** check availability first
  - Degrade gracefully if dependency plugin absent
  - Unchecked cross-plugin call = broken UX for users without that plugin
- **Prose references too**: any mention of `/plugin:skill` in `<notes>`, follow-up chains, or documentation prose (not just dispatch calls) must include `(requires \`<plugin>\` plugin)` inline caveat. Check 28c flags unguarded prose refs.

## Fallback / Resilience Infrastructure

**The self-defeating plugin trap** — hook or skill whose job is "handle plugin `foo` being absent" cannot live inside plugin `foo`. If `foo` absent, hook never runs.

- **General rule: resilience code lives in plugin whose users need protecting, not plugin being protected against**
- Examples: fallback for missing `foundry` agents → cannot live in `foundry`; fallback for missing `oss` agents → cannot live in `oss`; same for any plugin pair

Correct placement: every plugin dispatching agents from others ships own fallback hook. Source of truth in one plugin; `sync.sh` copies to others at release.

No plugin dependency system in Claude Code — never propose "install `foo` as prerequisite" or "register globally via `foo` init" as solution to missing-plugin resilience. Circular: requires thing that might be absent.

## README Sync

**Edit agents/skills/rules/hooks → update plugin `README.md` before done.**

- Added/removed → update README table
- Changed trigger/scope/NOT-for/hook behaviour → update README description
- Changed user-facing API/usage patterns (flags, argument names, invocation syntax, skill modes) → revise affected README sections and propagate to all cross-plugin READMEs that reference the changed interface; search other plugin READMEs for any mention of the changed flag/argument before declaring done
- Changed model tier for an agent → update README agent entry's **Model** line and the agent-relationships model-tiering paragraph; update `curator.md` antipatterns table if the agent appears there
- Significant behaviour change (new phase, changed default, removed option) → add a note in the relevant README skill or agent section; if the change is breaking, mark with `! BREAKING` in the README change description

Unsynced change = incomplete.

## Versioning

> **Commit gate**: any `plugins/<name>/` file in `git diff HEAD` → run pre-bump checklist before `git add`. Each plugin touched gets its own independent bump. Baseline = HEAD every time — post-compaction sessions have no memory of prior bumps; always re-read HEAD version, never trust session recall.

Per-plugin version in `.claude-plugin/plugin.json`. Space: `0.X.Y`.

| Change type | Bump |
| --- | --- |
| Fix, wording, refactor, cleanup, or restoring behaviour to original design intent | `Y` |
| New capability, new agent/skill, new designed behaviour (not intended before) | `X` |

> **Rule**: Ask "was this *supposed* to work this way?" Yes + it didn't → `Y` (fix). No, new intent → `X` (feature). Internal restructuring always `Y` regardless of size or visibility.

**Bump at commit, not per edit** — single bump per commit, highest-magnitude change wins:

- Session has both `Y`- and `X`-class changes → bump `X` only, reset `Y` to `0`
- **Baseline = HEAD, not disk** — always get current version via:
  `git show HEAD:<plugin-path>/.claude-plugin/plugin.json | grep version`
- Bump `X` → reset `Y` to `0` (e.g. `0.2.3` → `0.3.0`)

**Example**: start `0.2.0`, session: wording fix + feature add → commit as `0.3.0` (not `0.2.1`).

**Pre-bump checklist** — run before writing any version change to disk:

1. Read HEAD baseline: `git show HEAD:<plugin-path>/.claude-plugin/plugin.json | grep version`
2. Classify highest-magnitude change in session (`X` or `Y`) — do NOT read on-disk version; disk may already differ from HEAD
3. Calculate new version from HEAD baseline: `X` → bump minor, reset patch to `0`; `Y` → bump patch only
4. Write calculated version to `<plugin-path>/.claude-plugin/plugin.json` — **if on-disk version already equals or exceeds calculated, skip write entirely; do not bump again**

**One bump per commit session** — after writing once, all further edits to that plugin in same uncommitted session must NOT bump again. On-disk version will already exceed HEAD baseline, triggering step 4 skip. Never treat on-disk bumped value as new baseline to increment from.

## Edit Quality Gate

Before any edit, delete, or addition to plugin files — self-challenge:

- **Best approach?** Simpler path exists → take it; no unnecessary complexity or speculative abstractions
- **No side effects?** Cross-refs still resolve, existing callers unaffected, no behavior regression introduced
- **Complete and clean?** No gaps/TODOs, no dead instructions, no orphaned cross-refs, no leftover stubs
- **Verified?** Every claim backed by code/disk evidence — no hypothesis or assumption stated as fact
- **bin/ scripts wired?** Created/edited a `bin/` script? Consumer `.md` references basename before commit (inline invocation or `<!-- file: ... consumers: ... -->` header in owning plugin). Run `check_orphaned_bin.py` — must exit 0.
