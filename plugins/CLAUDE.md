<!-- scope: project-local plugin authoring rules — not synced to ~/.claude/ -->

# Plugin Authoring Rules

Plugins under `plugins/`. See `README.md` for user-facing detail.

## Markdown Annotation Convention

In `.md` plugin files: prose annotations/notes/load directives → `>` blockquote. `#` only inside ` ```bash ``` ` or ` ```python ``` ` fences (valid comment there). `#` in plain text = H1 heading — corrupts hierarchy.

```
> loads: modes/resume.md   ✓    # loads: modes/resume.md   ✗ (H1)
```

**Code block comments — WHY vs example**:

- **Procedural code** (steps agent/skill executes): comments explain WHY only — non-obvious constraint, workaround, incident ref, safety rationale. Never WHAT or HOW (code shows that). Remove self-documenting comments (`# Create directory`, `# Check if exists`, `# Parse flags`).
- **Example/pattern code** (illustrates pattern, not executed directly): comments may also document expected output, pattern motivation, when to apply — value code alone cannot convey.

## Writing Style — Compression Tiers

Three tiers by reader:

| Content | Tier | Rule |
| --- | --- | --- |
| READMEs, `docs/`, user-facing guides | Verbose | Full sentences, rationale, examples |
| Final reports (`.reports/`), human-read output | Normal caveman | Drop articles/filler/hedging; full sentences where clarity needs |
| Agent source (`<workflow>`, `<role>`, `<notes>`, skills, rules, modes), handover files (`.temp/`), inter-agent prose | Ultra caveman | Max compression — fragments OK, zero filler, shortest synonyms |

Verbatim always (no compression): code blocks, bash commands, tool citations, file:line refs, JSON keys, structured field labels, compact JSON envelopes.

Unsure: human reads artifact directly → normal; only agents read → ultra.

## Length Unit Convention

All size/length limits in plugin files: **tokens primary, lines secondary**.

Format: `N tokens (~M lines)` — e.g. `10K tokens (~500 lines)`.

- Never lines-only or chars-only as sole unit — line length unbounded; chars opaque to humans
- Token estimate: `$(( $(wc -c < file) / 4 ))` (chars / 4; conservative for dense markdown/code)
- Apply to: per-file limits, per-turn budgets, envelope size caps, output size constraints, consolidator thresholds

## File Layout

- `.claude-plugin/plugin.json` — version + metadata
- `agents/`, `skills/`, `README.md`, `CLAUDE.md` (optional)
- `bin/` — optional: standalone executables (`.sh`, `.py`) auto-added to Bash `PATH` by Claude Code; invoked via `${CLAUDE_PLUGIN_ROOT}/bin/<script>` inside skills
  - **Language policy — `bin/`**: Python default (minimum 3.10); bash only for enumerated cases: (1) plugin install-path resolution, (2) `$ARGUMENTS` parsing where bash regex shorter and quoting-safe, (3) `find | sort | head` pipelines with no business logic
    - Python scripts: type hints, module docstring, `if __name__ == "__main__"` guard; ruff-format 120-char line length (pre-commit enforced); aggregate related print output into single `print()` using `\n`/`\t`; pure functions (no I/O, no subprocess, no env-var reads) → `doctest` in docstring; anything with I/O/subprocess/argv → `pytest` with `capsys`/`monkeypatch` in `tests/` alongside `bin/`
    - bin/ scope: deterministic transforms only (parse args, resolve paths, compute one value); decision flow, branching prompts, agent-dispatch logic stays in SKILL.md prose
    - Reference design: `plugins/codemap/bin/` (typed, docstrings, `__name__` guards, dataclass serialization boundaries)
  - **Language policy — inline blocks in SKILL.md**: bash default; Python only when bash version requires JSON parsing, multi-line string manipulation, or numeric computation (note: `Bash(python:*)` not in allow list — inline Python triggers approval prompt every invocation)
- `rules/`, `hooks/` — foundry only

## Shared File Authoring Rule (modes/, templates/, _shared/)

Every file added to `plugins/*/skills/*/modes/`, `plugins/*/skills/*/templates/`, or `plugins/*/skills/_shared/` **must** satisfy at least one:

1. **Basename appears as literal string** in ≥1 consumer `.md` file (SKILL.md, agent `.md`, or another shared file) — e.g. `# loads: upgrade.md` or inline in prose
2. File itself contains `<!-- file: <basename> — consumers: ... -->` header declaring cross-plugin consumers (use when all consumers in different plugin)

**Why**: grep-based orphan check finds zero hits → agent concludes file dead → deletes it. Happened to `adversarial.md`, `upgrade.md`, `vitality-calibration.md`. Single comment line prevents deletion. Check R2 (`/foundry:audit plugins`) detects violations.

**At authoring time**: before writing file, identify consumer SKILL.md, add `# loads:` comment there first, then create file. Consumer in different plugin → add `<!-- file: ... -->` header to file itself.

## Loading Shared Docs — `cat`, not the Read tool

Load `_shared/*.md` (+ `modes/`, `templates/`) via `cat "$VAR/foo.md"` in bash. Never Read tool.

**Why**: Read tool path-matched vs permission globs; resolved cache path version-pinned (`~/.claude/plugins/cache/borda-ai-rig/<plugin>/<ver>/skills/_shared/...`) — plugin update kills user's "always allow", re-prompts. `Bash(cat:*)` command-matched: version-proof, prompts once ever.

- `$VAR` resolve + `cat` same bash block — bash state don't persist cross-call
- Keep surrounding "follow/execute protocol" prose — only load mechanism changes
- **Don't revert to `` Read `$VAR/foo.md` `` — intentional.** Audit/curator seeing `cat` here: leave as-is.

## Sentinel Reads — `read`, not `$(cat ...)`

Single-line sentinel read-back: `IFS= read -r VAR < "${TMPDIR:-/tmp}/<name>-${CSID}" 2>/dev/null || VAR=<default>` — never `VAR=$(cat ...)`. Command substitution `$(...)` triggers "Contains expansion" permission prompt in subagents regardless of allow list. Bare `cat "$VAR/foo.md"` (section above) unaffected — no substitution. Full rule + newline caveat: `cc_foundry/rules/claude-config.md` §TMPDIR Sentinel Scoping. Every plugin ships `hooks/sentinel-read-allow.js` (canonical: cc_foundry; propagated via `propagate_shared.py`) auto-allowing the legacy idiom, `$(date -u +FMT)` stamps, and the read-form itself (its first token `IFS=` matches no prefix allow-rule) in read-only compounds.

## Installability

- Every file installable via `claude plugin install <name>@borda-ai-rig`
- No file depend on source tree — assume installed path only
- No hardcoded paths to sibling plugins or `plugins/<name>/` directories
- **No hardcoded absolute user paths** (`/Users/<name>/`, `/home/<name>/`, `/tmp/`) in any plugin file — critical installability violation; breaks on every other machine. Always `~/`, `$(git rev-parse --show-toplevel)`, or `$CLAUDE_PLUGIN_ROOT`. Check R3 flags violations.
- Validate: after `claude plugin install`, all agents/skills/rules/hooks resolve without local `plugins/` tree
- **Bare `plugins/` path = only valid as final fallback** after cache-path resolution: `VAR="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/_shared 2>/dev/null | head -1)"; [ -z "$VAR" ] && VAR="plugins/<plugin>/skills/_shared"`. Never bare `plugins/` as primary path. Check C32 flags violations.
- **Health monitoring mandatory for background agents**: any skill spawning `Agent(..., run_in_background=true)` must implement CLAUDE.md §6 (sentinel + 5-min poll + 15-min cutoff). Reference `_FOUNDRY_SHARED/agent-spawn-protocol.md`, don't reproduce inline. Check C35 flags violations.

## Naming

- Plugin-prefixed refs always: `foundry:sw-engineer`, `oss:review` — never bare names
- Agent `subagent_type` must match filename (e.g. `sw-engineer.md` → `foundry:sw-engineer`)

## Cross-References

- `description` field = routing signal; calibrated threshold `routing accuracy ≥90%`
- NOT-for lines mandatory in every agent; `/audit` Check 16 flags ≥40% overlap
- **Independent instances** — each plugin independent install; treat as if source tree absent
  - Never cross-ref via local/relative path (e.g. `../foundry/agents/foo.md`) — breaks after install
  - Reference only via installed plugin-prefixed name (e.g. `foundry:sw-engineer`)
- **Opt-in gating required** — plugins opt-in; user may have only subset installed
  - Any cross-plugin usage **must** check availability first
  - Degrade gracefully if dependency plugin absent
  - Unchecked cross-plugin call = broken UX for users without plugin
- **Prose references too**: any mention of `/plugin:skill` in `<notes>`, follow-up chains, or documentation prose (not just dispatch calls) must include `(requires \`<plugin>\` plugin)` inline caveat. Check 28c flags unguarded prose refs.

## Fallback / Resilience Infrastructure

**Self-defeating plugin trap** — hook or skill whose job is "handle plugin `foo` being absent" cannot live inside plugin `foo`. If `foo` absent, hook never runs.

- **General rule: resilience code lives in plugin whose users need protecting, not plugin being protected against**
- Examples: fallback for missing `foundry` agents → cannot live in `foundry`; fallback for missing `oss` agents → cannot live in `oss`; same for any plugin pair

Correct placement: every plugin dispatching agents from others ships own fallback hook. Source of truth in one plugin; copies in each consuming plugin. **Byte-identical shared files propagated by `plugins/cc_foundry/bin/propagate_shared.py`** — its `MANIFEST` maps each canonical file to copies that must equal it (currently `agent-router.js`: foundry canonical → oss/develop/research). `--apply` syncs; default `--check` mode enforced in pre-commit and audit Check 14e — drift caught at commit. Edit manifested shared file → edit canonical, run `propagate_shared.py --apply`. `sync.sh` installs Claude plugins and Codex Rig from the public Git remote; it does NOT propagate cross-plugin files or copy `.codex/` into a user home. NOTE: files that legitimately vary per plugin (`agent-resolution.md` fallback tables, per-plugin `rules/quality-gates.md`) intentionally NOT manifested — do not add them.

No plugin dependency system in Claude Code — never propose "install `foo` as prerequisite" or "register globally via `foo` init" as solution to missing-plugin resilience. Circular: requires thing that might be absent.

## README Sync

**Edit agents/skills/rules/hooks → update plugin `README.md` before done.**

- Added/removed → update README table
- Changed trigger/scope/NOT-for/hook behaviour → update README description
- Changed user-facing API/usage patterns (flags, argument names, invocation syntax, skill modes) → revise affected README sections, propagate to all cross-plugin READMEs referencing changed interface; search other plugin READMEs for any mention of changed flag/argument before declaring done
- Changed model tier for agent → update README agent entry's **Model** line + agent-relationships model-tiering paragraph; update `curator.md` antipatterns table if agent appears there
- Significant behaviour change (new phase, changed default, removed option) → add note in relevant README skill or agent section; breaking → mark `! BREAKING` in README change description

Unsynced change = incomplete.

## Versioning

> **Commit gate**: any `plugins/<name>/` **non-test** file in `git diff HEAD` → run pre-bump checklist before `git add`. ALL changed files in plugin under `tests/` → no bump, skip checklist entirely. Each plugin touched gets own independent bump. Baseline = HEAD every time — post-compaction sessions have no memory of prior bumps; always re-read HEAD version, never trust session recall.

Per-plugin version in `.claude-plugin/plugin.json`. Space: `0.X.Y`.

| Change type | Bump |
| --- | --- |
| Fix, wording, refactor, cleanup, or restoring behaviour to original design intent | `Y` |
| New capability, new agent/skill, new designed behaviour (not intended before) | `X` |
| Test-only changes (adding/editing `tests/*.py` or `tests/*_sh.py`, no source file changes) | none — skip |

> **Rule**: Ask "was this *supposed* to work this way?" Yes + it didn't → `Y` (fix). No, new intent → `X` (feature). Internal restructuring always `Y` regardless of size or visibility. Test-only commits (no changes outside `tests/`) need no bump.

**Bump at commit, not per edit** — single bump per commit, highest-magnitude change wins:

- Session has both `Y`- and `X`-class changes → bump `X` only, reset `Y` to `0`
- **Baseline = HEAD, not disk** — always get current version via:
  `git show HEAD:<plugin-path>/.claude-plugin/plugin.json | grep version`
- Bump `X` → reset `Y` to `0` (e.g. `0.2.3` → `0.3.0`)

**Example**: start `0.2.0`, session: wording fix + feature add → commit as `0.3.0` (not `0.2.1`).

**Pre-bump checklist** — all steps mandatory; skipping any step = violation:

0. **Test-only guard**: run `git diff HEAD --name-only -- plugins/<name>/`, check if every changed path under `plugins/<name>/tests/`. Yes → **STOP; no bump needed** — test-only commits never touch version.
1. Read HEAD baseline: `git show HEAD:<plugin-path>/.claude-plugin/plugin.json | grep version`
2. **Read on-disk version: `grep version <plugin-path>/.claude-plugin/plugin.json`** — on-disk ≠ HEAD → session bump already applied → **STOP; do not proceed**
3. Classify highest-magnitude change in session (`X` or `Y`)
4. Calculate new version from HEAD baseline: `X` → bump minor, reset patch to `0`; `Y` → bump patch only; max +1 on bumped component
5. Write calculated version — must be exactly HEAD + single bump; anything higher = double-bump violation

**One bump per commit session** — after writing once, all further edits to that plugin in same uncommitted session must NOT bump again. Step 2 catches this: on-disk already differs from HEAD. Never treat on-disk bumped value as new baseline to increment from.

## Edit Quality Gate

Before any edit, delete, or addition to plugin files — self-challenge:

- **Best approach?** Simpler path exists → take it; no unnecessary complexity or speculative abstractions
- **No side effects?** Cross-refs still resolve, existing callers unaffected, no behavior regression
- **Complete and clean?** No gaps/TODOs, no dead instructions, no orphaned cross-refs, no leftover stubs
- **Verified?** Every claim backed by code/disk evidence — no hypothesis or assumption stated as fact
- **bin/ scripts wired?** Created/edited `bin/` script? Consumer `.md` references basename before commit (inline invocation or `<!-- file: ... consumers: ... -->` header in owning plugin). Run `check_orphaned_bin.py` — must exit 0.
