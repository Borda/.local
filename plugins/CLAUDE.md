<!-- scope: project-local plugin authoring rules — not synced to ~/.claude/ -->

# Plugin Authoring Rules

<!-- policy-sibling-sync: AGENTS.md, plugins/AGENTS.md, plugins/CLAUDE.md -->

Any policy change in one listed instruction file must trigger a relevance review of the other two before completion. Synchronize applicable shared policy in either direction; preserve intentional agent-specific differences and record when no counterpart change is needed.

Plugins under `plugins/`. See `README.md` for user-facing detail. Sections below with a "Full ... : `AUTHORING.md` §X" pointer have narrow-trigger detail (worked checklists, mechanism rationale, precedent, catalogues) in `plugins/AUTHORING.md`, same directory — load on demand, not needed for routine edits.

## Markdown Annotation Convention

In `.md` plugin files, prose annotations, notes, and load directives use `>` blockquotes. Use `#` only for real Markdown headings and, inside fenced `bash`/`python` blocks, code comments — never as a fake prose comment or load directive, since that changes heading hierarchy.

```
> loads: modes/resume.md   ✓    # loads: modes/resume.md   ✗ (H1)
```

## Markdown No-Wrap

Never hard-wrap prose in any Markdown file — one physical line per prose paragraph; preserve breaks in headings/lists/tables/blockquotes/links/`<details>`/fenced code. Edit only the intended prose, never a whole-file reflow.

**Code block comments**: procedural code (steps an agent/skill executes) — comments explain WHY only (non-obvious constraint, workaround, incident ref, safety rationale), never WHAT/HOW; remove self-documenting comments. Example/pattern code (illustrates a pattern, not executed directly) — comments may also document expected output, motivation, or when to apply. Self-documenting-comment examples: `AUTHORING.md` §Markdown No-Wrap.

## Benchmark Isolation

Benchmark task IDs, target repositories, prompt wording, expected answers, and task-specific source or symbol examples are test evidence, not shipped plugin content. Use neutral generic examples in Skills, templates, and user-facing docs; retain the generalized contract in production regressions without copying benchmark fixtures.

## GitHub Reference Scoping — `#N` and `@name`

<!-- policy-sibling: plugins/cc_foundry/rules/git-commit.md, plugins/cc_foundry/rules/_full/git-commit.md, plugins/cc_oss/skills/_shared/shepherd-voice.md — same GH #/@ scoping policy restated for each consumer's own context. Editing this section → grep repo for `policy-sibling` to find every copy, update in lockstep (rationale + precedent: §Policy Duplication Marker below). -->

`#N` bare in prose = GitHub issue/PR/discussion number only; `@name` bare in prose = a real GitHub username mention only — both are live link/notify tokens once text lands in a GH comment, PR body, issue, or commit message. Never use bare `#N` for local ordinals (list items, step indices, ranks, internal check IDs) or bare `@word` for non-GitHub tokens (decorators, role handles) — use plain numbers/words instead, or backticks to render as code; backticks are for code-shaped tokens only, never to defang a real person's handle. `#N` is same-repo only (cross-repo needs the full URL, never `#N` or `owner/repo#N`); `@name` needs certainty of ping intent — drop the `@` if uncertain, except release-note/CHANGELOG contributor credit, which is deliberate ping intent and stays live. Full forbidden/OK catalogue: `AUTHORING.md` §GitHub Reference Scoping.

## Writing Style — Compression Tiers

Three compression tiers by reader: user-facing docs = verbose (full sentences, rationale); reports/human-read output = normal caveman (drop filler, keep clarity); agent source/handover files/inter-agent prose = ultra caveman (max compression, fragments OK). Code, commands, file:line refs, JSON keys/envelopes are always verbatim, never compressed. Full tier table + unsure-rule: `AUTHORING.md` §Writing Style — Compression Tiers.

**Comments inside `.md` code blocks are prose, not code — ultra caveman.** The verbatim rule above covers the *code*; a `#` comment beside it is agent-source prose and compresses like any other. It is also re-sent into context on every invocation of that skill, so verbosity there is a recurring cost. One to two lines, fragments, no articles or hedging. **Strip dates, audit/basket names and back-references** ("2026-08 audit (…)", "already computed above") — git history holds provenance. Keep the measured fact, the mechanism, and any deliberate exclusion with its reason.

- **Never remove or reword `# timeout: N`** — parsed by the harness to set the Bash tool timeout; it is functional, not documentation. Same for `# tmpdir-exempt:`, `# noqa:`, `# shellcheck`.
- **Compress wording, never content**, for any comment encoding a constraint, a why-not, or a bug that was fixed — those comments are why the bug stays fixed. Losing one silently re-opens it.
- **`.py` files are exempt**: Python docstrings and comments stay plain and extensive. They serve maintainers, and cost nothing at skill-load time.

Worked before/after example: `AUTHORING.md` §Comment Compression.

## Code Density — Bash/Code Blocks

Balance compression against readability in inline bash/code blocks — don't trade one for the other, tune both. Readability is carried by **variable names**, not by extra blank lines, comments, or nesting — `MATCH_REPORT`/`GATE_LINE` need no surrounding whitespace to stay legible; a cryptic name does. Compression is validated by **tokens actually used** (`$(( $(wc -c < file) / 4 ))`, per §Length Unit Convention), not by how short a snippet looks — cutting a line that adds no information (a blank separator, a nested nothing block, a nested loop a single `grep`/pipeline replaces) lowers the real number; renaming a variable to something shorter but vaguer does not, it just moves the cost onto whoever reads it next.

- Prefer an early-exit guard (`[ -n "$X" ] || exit 0`) over wrapping the rest of the block in `if`.
- Collapse a loop-with-break searching for one match into a single `grep`/`awk`/pipeline when the semantics are identical (mind edge cases — e.g. a glob expanding to zero files feeding a filter with no explicit input turns into a stdin hang).
- Drop blank lines between statements that read as one step; keep one where it marks a genuine phase change.
- Terse code never overrides correctness — a safety check (fail-closed on an unverifiable value) stays even if it costs a line.

## Length Unit Convention

All size/length limits: **tokens primary, lines secondary** — format `N tokens (~M lines)` (e.g. `10K tokens (~500 lines)`); never lines-only or chars-only as sole unit. Token estimate: `$(( $(wc -c < file) / 4 ))`. Applies to per-file limits, per-turn budgets, envelope caps, consolidator thresholds. Rationale + full apply-list: `AUTHORING.md` §Length Unit Convention.

## File Layout

- `.claude-plugin/plugin.json` — version + metadata; `agents/`, `skills/`, `README.md`, `CLAUDE.md` (optional); `rules/`, `hooks/` — foundry only
- `bin/` — standalone executables (`.py`, ≥3.10 — never `.sh`, see §Installability), auto-added to Bash `PATH`, invoked via `python "${CLAUDE_PLUGIN_ROOT}/bin/<script>.py"`. Scope: deterministic transforms only — decision flow/branching/agent-dispatch stays in SKILL.md prose. Full language policy: `AUTHORING.md` §bin/ Language Policy.
- Inline SKILL.md blocks: bash default; Python only when bash needs JSON parsing, multi-line strings, or numeric computation (`Bash(python:*)` not allow-listed — prompts every call).
- `references/<agent>/*.md` — agent sidecar fragments, loaded via `cat`. **Never nest under `agents/`** (registers as an uncontrolled dispatchable agent) or `bin/` (PATH-scanned); `skills/<name>/` is safe. Mechanism: `AUTHORING.md` §references/<agent> Nesting Mechanism.

## Shared File Authoring Rule (modes/, templates/, _shared/)

Every file added to `plugins/*/skills/*/modes/`, `plugins/*/skills/*/templates/`, or `plugins/*/skills/_shared/` **must** satisfy one: (1) basename appears as a literal string in ≥1 consumer `.md` file (e.g. `# loads: upgrade.md`); or (2) file contains `<!-- file: <basename> — consumers: ... -->` header (cross-plugin consumers). **At authoring time**: add the loads-comment or header to the consumer *before* creating the shared file — a grep-based orphan check deletes unmarked files with zero hits. Check R2 (`/foundry:audit plugins`) detects violations. Why + precedent: `AUTHORING.md` §Shared File Authoring Rule.

## Policy Duplication Marker

Policies restated in prose across multiple files (each consumer needs the rule inline in its own reading context) have no structural link back to siblings — a plain grep for violations of a refined rule won't surface stale copies. **Rule**: documents that declare a shared `policy-sibling-sync` set at the top use that single document-level contract (a policy change in any listed doc triggers a relevance review of the others, preserving intentional differences) instead of repeating markers per section. For a policy duplicated outside that declared set, add a section-specific `<!-- policy-sibling: <path1>, <path2>, ... -->` marker in every copy and inspect every listed copy before completion. Precedent + worked example: `AUTHORING.md` §Policy Duplication Marker.

## Loading Shared Docs — `cat`, not the Read tool

Load `_shared/*.md` (+ `modes/`, `templates/`) via `cat "$VAR/foo.md"` in bash — never the Read tool. Read tool path-matches version-pinned cache paths (plugin update re-prompts permission); `Bash(cat:*)` command-matches (prompts once ever).

- `$VAR` resolve + `cat` same bash block — bash state doesn't persist cross-call
- Keep surrounding "follow/execute protocol" prose — only the load mechanism changes
- **Don't revert to `` Read `$VAR/foo.md` `` — intentional.** Audit/curator seeing `cat` here: leave as-is.

## Sentinel Reads — `read`, not `$(cat ...)`

Single-line sentinel read-back: `IFS= read -r VAR < "${TMPDIR:-/tmp}/<name>-${CSID}" 2>/dev/null || VAR=<default>` — never `VAR=$(cat ...)`. Command substitution `$(...)` triggers "Contains expansion" permission prompt in subagents regardless of allow list. Bare `cat "$VAR/foo.md"` (section above) unaffected — no substitution. Full rule + newline caveat: `cc_foundry/rules/claude-config.md` §TMPDIR Sentinel Scoping. Every plugin ships `hooks/sentinel-read-allow.js` (canonical: cc_foundry; propagated via `propagate_shared.py`) auto-allowing the legacy idiom, `$(date -u +FMT)` stamps, and the read-form itself (its first token `IFS=` matches no prefix allow-rule) in read-only compounds.

## Installability

- Every file installable via `claude plugin install <name>@borda-ai-rig`; no dependency on source tree — installed path only; no hardcoded paths to sibling plugins or `plugins/<name>/` dirs
- **No hardcoded absolute user paths** (`/Users/<name>/`, `/home/<name>/`, `/tmp/`) — critical, breaks on every other machine. Always `~/`, `$(git rev-parse --show-toplevel)`, or `$CLAUDE_PLUGIN_ROOT`. Check R3.
- Validate: after `claude plugin install`, all agents/skills/rules/hooks resolve without a local `plugins/` tree
- **Bare `plugins/` path = only valid as final fallback** after cache-path resolution: `VAR="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/_shared 2>/dev/null | head -1)"; [ -z "$VAR" ] && VAR="plugins/<plugin>/skills/_shared"`. Never bare `plugins/` as primary path. Check C32.
- **Background agents require health monitoring**: any skill spawning `Agent(..., run_in_background=true)` must implement CLAUDE.md §6 (sentinel + poll + cutoff) — reference `_FOUNDRY_SHARED/agent-spawn-protocol.md`, don't reproduce inline. Check C35.
- **`bin/` executables are Python (`.py`), never shell (`.sh`)** — these plugins must run on Windows, where `.sh` does not execute. Call sites use `python "$PLUGIN_ROOT/bin/<name>.py"`, never `bash …/<name>.sh`. Python must itself stay portable: temp dir via `os.environ.get("TMPDIR") or tempfile.gettempdir()` (never hardcoded `/tmp` — absent on native Windows Python), session token via `os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "shared"` (never `os.getppid()`), `pathlib` over string path concatenation. Three legacy `.sh` files remain tracked (`cc_research/bin/{git_slugs,resolve-quality-gates}.sh`, `codemap-py/bin/setup_scan_env.sh`) — **they are debt, not precedent**; never add to them or match them when authoring new scripts.

## Worktree Base — verify before trusting agent output

Agent worktrees are created from **`origin/main`**, not local `main` (reflog: `branch: Created from origin/main`). When local `main` is ahead of the remote — which it is whenever work is committed but unpushed — every new worktree starts on a **stale base**, and its diff silently reverts everything committed since.

Measured 2026-08-07: 3 of 7 agent worktrees were cut from a commit predating that session entirely; one would have reverted a 44-guard correctness fix and deleted 219 files of unrelated work. The agents that succeeded differed only in having run a fast-forward first.

- **Spawned agent, step 0**: `git merge main --ff-only` then assert `git merge-base --is-ancestor main HEAD`. Abort and report if it fails. Include this verbatim in any spawn prompt that may run in a worktree — an agent cannot opt out of worktree placement, so it must self-correct.
- **Orchestrator, before transplanting anything**: `git -C <worktree> log --oneline -1` must equal local `main`. Never `git apply` a worktree diff without this check. If the base is stale, salvage **new files only** and re-derive edits to existing files against current `main`.
- **Root fix**: keep `origin/main` current. A stale remote-tracking ref is the actual cause; the guards above are mitigation.
- Detection tell: a file the agent never touched differs from `main` — that is proof of a stale base, not of agent error.

## Naming

Plugin-prefixed refs always (`foundry:sw-engineer`, `oss:review` — never bare names); agent `subagent_type` must match filename (`sw-engineer.md` → `foundry:sw-engineer`).

## Cross-References

- `description` field = routing signal; calibrated threshold `routing accuracy ≥90%`
- NOT-for lines mandatory in every agent; `/audit` Check 16 flags ≥40% overlap
- **Independent instances**: never cross-ref via local/relative path (breaks after install) — reference only via installed plugin-prefixed name (`foundry:sw-engineer`)
- **Opt-in gating required**: any cross-plugin usage must check availability first and degrade gracefully if absent — unchecked call = broken UX for users without that plugin
- **Prose references too**: any `/plugin:skill` mention in `<notes>`, follow-ups, or docs prose must include `(requires \`<plugin>\` plugin)` inline caveat. Check 28c.

## Fallback / Resilience Infrastructure

**Self-defeating plugin trap**: a hook/skill whose job is "handle plugin `foo` being absent" cannot live inside `foo` — if `foo` is absent, the hook never runs. **Rule: resilience code lives in the plugin whose users need protecting, not the plugin being protected against.**

Correct placement: every plugin dispatching agents from others ships its own fallback hook. Source of truth in one plugin; **byte-identical copies propagated by `plugins/cc_foundry/bin/propagate_shared.py`** (`MANIFEST` maps canonical → copies, e.g. `agent-router.js`: foundry → oss/develop/research). Edit a manifested file → edit canonical, run `propagate_shared.py --apply`; default `--check` mode enforced in pre-commit and audit Check 14e. `sync.sh` installs plugins/Codex Rig from the public remote only — it does not propagate cross-plugin files.

No plugin dependency system in Claude Code — never propose "install `foo` as prerequisite" as a resilience fix; circular, requires the thing that might be absent. Examples + per-plugin-variance exceptions: `AUTHORING.md` §Fallback / Resilience Infrastructure.

## Self-Contained `_shared`

**Every plugin points at its own `skills/_shared`. No global path, no sibling reach-in.** Enforced by audit Check 27.

- Resolve via the plugin's **own** resolver: `cc_foundry`/`cc_oss` `bin/resolve_shared_path.py <own-plugin> skills/_shared`; `cc_develop` `bin/dev_shared_resolve.py`; `cc_research` `bin/resolve_shared.py`. Bare `plugins/<own-plugin>/skills/_shared` allowed only as final fallback tier (§Installability).
- **Never** `$HOME/.claude/skills/_shared/...` or bare `.claude/skills/_shared/...` — that path doesn't exist (`/foundry:setup` symlinks only `rules/*.md` + `TEAM_PROTOCOL.md`), and a `SKILL.md` dropped there silently shadows Claude Code's bundled skill of the same name. Incident + precedent: `AUTHORING.md` §Self-Contained _shared.
- **Never** read another plugin's `_shared` or `bin/` (`resolve_shared_path.py foundry` from a non-foundry plugin, `--foundry`, `$_FOUNDRY_SHARED`, `$_FOUNDRY_BIN`, literal `plugins/cc_<other>/`). Shared content two plugins need is **duplicated, not borrowed** — copy in each + a `MANIFEST` entry in `propagate_shared.py` to stay byte-identical.
- Corollary: a standalone install of any single plugin must work with no other plugin present. Agent-dispatch fallback (`hooks/agent-router.js` + per-plugin `_shared/agent-resolution.md`) is unaffected and stays.

## README Sync

**Edit agents/skills/rules/hooks → update plugin `README.md` before done. Unsynced change = incomplete.**

- Added/removed → update README table; changed trigger/scope/NOT-for/hook behaviour → update README description
- Changed user-facing API (flags, arg names, invocation syntax, skill modes) → revise affected README sections + all cross-plugin READMEs referencing that interface (search other plugin READMEs before declaring done)
- Changed agent model tier → update README **Model** line + agent-relationships tiering paragraph + `curator.md` antipatterns table if agent appears there
- Significant behaviour change (new phase, changed default, removed option) → note it in README; breaking → mark `! BREAKING` in the change description

## Versioning

> **Commit gate**: any `plugins/<name>/` **non-test** file in `git diff HEAD` → run pre-bump checklist (`AUTHORING.md` §Versioning) before `git add`. All changed files under `tests/` → no bump, skip entirely. Each touched plugin bumps independently. **Baseline = HEAD every time** — re-read it fresh each session, never trust prior-session recall.

Per-plugin version in `.claude-plugin/plugin.json`, space `0.X.Y`:

| Change type | Bump |
| --- | --- |
| Fix, wording, refactor, cleanup, or restoring behaviour to original design intent | `Y` |
| New capability, new agent/skill, new designed behaviour (not intended before) | `X` |
| Test-only changes (adding/editing `tests/*.py` or `tests/*_sh.py`, no source file changes) | none — skip |

> **Rule**: Ask "was this *supposed* to work this way?" Yes + it didn't → `Y` (fix). No, new intent → `X` (feature). Internal restructuring always `Y` regardless of size or visibility. Bump once per commit, at the highest-magnitude change: session has both `Y`- and `X`-class changes → bump `X` only, reset `Y` to `0`. Baseline read via `git show HEAD:<plugin-path>/.claude-plugin/plugin.json | grep version`, never from disk — on-disk already differing from HEAD means a bump already landed **for this pending commit**; do not bump again before committing it. Scope is the commit, never the session: splitting one session's work into N commits means N bumps for every plugin each commit touches, each derived from the preceding commit.

Full pre-bump checklist (test-only guard, on-disk-vs-HEAD double-check, calculation steps, worked example, multi-manifest note): `AUTHORING.md` §Versioning.

## Edit Quality Gate

Before any edit, delete, or addition to plugin files — self-challenge:

- **Best approach?** Simpler path exists → take it; no unnecessary complexity or speculative abstractions
- **No side effects?** Cross-refs still resolve, existing callers unaffected, no behavior regression
- **Complete and clean?** No gaps/TODOs, no dead instructions, no orphaned cross-refs, no leftover stubs
- **Verified?** Every claim backed by code/disk evidence — no hypothesis or assumption stated as fact
- **bin/ scripts wired?** Created/edited `bin/` script? Consumer `.md` references basename before commit (inline invocation or `<!-- file: ... consumers: ... -->` header in owning plugin). Run `check_orphaned_bin.py` — must exit 0.
