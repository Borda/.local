---
description: Git commit conventions and safety rules — applies globally
paths:
  - '**'
---

## Commit Message Format

Subject line format: `type(scope): detail` — ≤50 chars total; name up to 3 most significant changes only.

**type** — pick lowest that fits:

| type | when |
| --- | --- |
| `fix` | Bug fix, correctness repair |
| `feat` | New user-visible capability |
| `refactor` | Internal restructure, no behaviour change |
| `perf` | Performance improvement |
| `test` | Test-only changes |
| `docs` | Documentation only |
| `ci` | CI/CD pipeline |
| `chore` | Tooling, config, deps, build |
| `refine` | Improvement to existing behaviour (not pure fix, not new feature) |
| `compress` | Compression / caveman reformatting pass |

**scope** — affected area: `plugins`, `oss`, `foundry`, `docs`, `cli`, `<module_name>`, etc. Omit only when change is truly cross-cutting.

**Subject priority — classify before drafting**

Enumerate ALL changes from diff, assign each a tier, pick subject from highest tier present:

| Tier | Change type | Example |
| --- | --- | --- |
| 1 | New capability — new file, new agent/skill, new flag, new user-visible behaviour | `efficiency.md` added |
| 2 | Changed behaviour — existing feature works differently, routing/trigger updated | TRIGGER/SKIP added to agent |
| 3 | Fix or removal — correctness repair, deleted dead code | audit findings fixed |
| 4 | Maintenance — quoting, README sync, version bump, formatting, refactor/extract | frontmatter `"..."` wrap, extract to `_shared/` |

Rules:
- **Never draft subject from session memory** — always enumerate from diff first, classify each change, then write subject
- Session recency bias must not dominate: last task worked on ≠ most significant change
- Line count ≠ tier: 200-line maintenance diff < 20-line new capability
- Multiple tiers present → subject names tier-1 change; lower tiers appear in bullet list only
- Tie-breaker: prefer user-visible impact when type/significance comparable

- Blank line, then bullet list — one bullet per logical change; extended description of top changes plus all other notable changes
  - Skip: typos, linting, whitespace-only edits
  - All changes skip-worthy → omit bullet list; subject-only commit — still include co-author block separated by blank line and `---`:

  ```markdown
  Fix typo in config key name

  ---
  Co-authored-by: claude[bot] <209825114+claude[bot]@users.noreply.github.com>
  ```

- **No line wrapping** — bullets and prose single continuous lines; never hard-break at any column width. Overrides any skill-level `Wrap at N chars` instruction (e.g. caveman-commit).
- **No GitHub auto-links** — never use `#N`, `@name`, or `@org` in commit messages; GitHub renders these as issue/PR links and user/org mentions, creating unintended cross-references in any repo that picks up the commit
- **No non-VCS paths** — never reference files or paths not tracked in the repo (e.g. `/tmp/`, `~/.claude/`, local cache dirs, machine-specific paths); commit message must be meaningful on any machine that clones the repo

## Gathering Diff Context

Before writing commit, run three in parallel:

- `git status` — identify staged new files (`A` prefix) and unstaged changes
- `git diff HEAD` — **not** bare `git diff`; bare `git diff` shows only unstaged changes, misses staged new files; `git diff HEAD` captures staged and unstaged vs HEAD
- `git log --oneline -5` — reference repo's existing commit style

**Truncated diff — mandatory follow-up**: when `git diff HEAD` output large and Bash tool saves to file (showing only 2 KB preview), read saved file completely before writing commit. Don't write from preview alone — most significant changes often past truncation point. Also run `git diff --stat HEAD` (always fits in context) for complete file-by-file change map; use stat output to identify which files changed most and whether any missed in preview. If saved diff file exceeds ~2000 lines, escalate to subagent summarization — see Large diff rule below.

**Large diff — subagent summarization**: when diff file exceeds ~2000 lines OR `git diff --stat HEAD` shows >10 files spanning >2 plugins/concerns, spawn one Agent task per logical file group — one agent per top-level directory in stat output (e.g. one per `plugins/<name>/`, one collective for everything outside `plugins/`); max 5 agents, group smallest partitions until ≤5. Each task runs inline (not background); **use `model: haiku`** — diff summarisation is bounded, low-complexity output; receives `git diff HEAD -- <file> [<file> ...]` and returns compact bullet summary: what changed and highest tier classification. Orchestrator aggregates summaries, writes commit from aggregated evidence only — never from session memory. After aggregation, cross-check every file in `git diff --stat HEAD` appears in at least one summary; missing file → spawn one additional Agent task for that file before drafting. On agent failure or timeout: fall back to direct `git diff HEAD -- <files>` read for that group; surface unread group as a gap in commit message.

**Grouped commit — resolve/verify flow**: when committing grouped changes, any post-commit verification step (`/oss:resolve`, lint gate, test run) is also batched — one delegated agent covers the entire grouped commit, not one agent per change. Agent writes full findings to `.temp/`; returns compact JSON envelope to orchestrator. Orchestrator reads envelope verdict; reads full file only on FAIL. Never spawn N resolve agents for N grouped changes in the same commit.

**Large diff — agent handover format**: before spawning, create run dir: `RUN_TS=".temp/commit-diff/$(date -u +%Y-%m-%dT%H-%M-%SZ)"; mkdir -p "$RUN_TS"`. Each agent task writes to `$RUN_TS/group-<dir-slug>.md` using this fixed structure:

```markdown
## Group: <top-level-dir>
Files in scope: <comma-separated list>

| File | Change | Tier | Type |
|------|--------|------|------|
| `path/to/file` | one-line what changed | 1 | feat |

Highest tier: <N>
Tier-1 items: <file — specific new capability>
Tier-2 items: <file — specific behaviour change>
Recurring theme: <pattern visible across ≥2 files in this group, e.g. "python→python3 migration" or "none">
```

Agent returns ONLY this JSON envelope (no prose after it):

```json
{"status":"done","group":"<dir>","files_covered":["a","b"],"highest_tier":1,"theme":"<cross-file pattern or null>","file":"<path>","summary":"<file>: <change> T<N>; <file>: <change> T<N>"}
```

`theme` — one-phrase pattern visible across ≥2 files in this group (e.g. `"python→python3 migration"`, `"TRIGGER/SKIP added to all agents"`); `null` when no pattern.

Orchestrator: collect envelopes, verify coverage (every file in `git diff --stat HEAD` in at least one `files_covered`), then read `.md` files directly — ≤5 small files is within direct-read threshold (file-handoff-protocol.md). Draft commit from `.md` file content only — never from envelope `summary` strings (too lossy). `status: "done_with_concerns"` → flag that group as uncertain in commit message.

**Compound synthesis step** (mandatory before drafting): after reading all group `.md` files, scan across all groups for repeated themes — same concept changed in N **codebase** files across different groups each classified T3–T4 individually. If ≥3 codebase files share a theme (same pattern replaced, same flag added everywhere, same agent property updated system-wide), elevate the aggregate to T2 minimum and name the cross-cutting change in the commit subject. Per-group tiers are local signal only — aggregate tier governs the subject line. Exclude docs/supplementary files (README, CHANGELOG, comments, docstrings) from the ≥3 threshold count — they do not compound.

**High-churn files — mandatory diff read**: any file with >50 lines changed in `git diff --stat` NOT already in planned bullets — read actual diff before writing message. Don't assume from session memory or prior context; post-compaction sessions have no reliable recall. User/developer-facing changes (command syntax, CLI argument names, invocation patterns, API surface, usage examples) must be identified and prioritised regardless of earlier discussion — outrank internal restructuring of equal line count.

**Ranking rule — diff first, recency last**: classify all changes into tiers (see Subject priority table above) before writing title.
- Conversational recency bias must not dominate — last task in session ≠ most significant
- Title must reflect highest-tier change in diff, not most recent one

**Same-tier tie-breaking — session work over bundled pre-existing**: when multiple T1 items exist in the diff, the item explicitly produced in the current session takes subject priority. If one T1 item was the explicit focus of conversation, design, and iteration in this session, it leads — even if a different T1 item appears first in subagent output or has more lines. This does NOT override the "never draft from session memory" rule — still classify from diff; use session context only to rank among same-tier items, not to skip diff analysis. Ask: "which T1 item did this session set out to produce?" — that one leads.

**New files — classify by content, not by `A` marker**: any file marked `A` in `git status` must be explicitly mentioned in commit bullet list. But tier depends on content origin:
- Content is genuinely new capability/behaviour → tier 1
- Content extracted/refactored from existing file → tier 4 (maintenance); mention as "extracted from X", not "added"
- Test-only new file (adds tests, no source change) → tier 4; `test` type; not tier 1 even though content is new
- New file + new content = tier 1. New file + moved content = tier 3. New file + tests only = tier 4.

**Semantic novelty beats diff verbosity**: new capability/interface/script outranks verbose-but-routine config edit even if config diff has more lines. Ask "what would reviewer need to know first?" — that most significant change.

**Compound change detection**: when ≥3 **codebase** files share a common theme in their changes (same concept replaced, same flag added, same pattern adopted everywhere), treat the aggregate as potentially higher tier than any individual file suggests. Signals: same function/string replaced across N files → migration pattern; same trigger/description updated in N agents → routing change (T2 minimum); same convention adopted across all plugins → new standard. Rule: after reading all per-file diffs (or all subagent `.md` summaries), ask "do these individually small changes form a coordinated pattern?" — if yes, classify the whole at the aggregate tier, not the per-file tier. Name the pattern in the commit subject, not the individual files. **Docs/supplementary exempt**: README, CHANGELOG, inline comments, docstrings, and other documentation-only files are standalone entities — repeated small doc tweaks do not compound into a higher tier regardless of count.

**Reverted-change leak guard**: conversation context may contain changes introduced then rolled back before commit — visible in chat history but absent from `git diff HEAD` (no `+` or `-` line). Never mention such rolled-back content. Distinct from content removed BY this commit, which appears as `-` lines in `git diff HEAD` and IS valid to mention. Hard rule: if a change cannot be found in `git diff HEAD` output as a `+` or `-` line, omit it regardless of what was discussed. When uncertain whether a discussed change landed: save `git diff HEAD` to file and `grep -F <distinctive-token>` (function/class name, error string, config key); no hit = change did not land. If subagent summarization was used instead of full inline read, re-run `git diff HEAD -- <file>` for the specific file before including the change in any bullet.

## Co-authors

Separate co-author block from bullet list with `---`:

```markdown
- last bullet

---
Co-authored-by: claude[bot] <209825114+claude[bot]@users.noreply.github.com>
```

- Claude: `Co-authored-by: claude[bot] <209825114+claude[bot]@users.noreply.github.com>`
- Codex (if contributed anything — code, review, diagnosis, analysis, architectural guidance, or "here's what needs fixing and why"): `Co-authored-by: OpenAI Codex <codex@openai.com>`

**Codex intellectual contributions count**: Codex earns trailer whenever it shaped outcome — even if Claude wrote final code.
- Examples: Codex identified root cause, Codex suggested approach, Codex returned review comment that led to change
- Test: "would this commit exist in current form without Codex's input?" — if yes, include trailer

Co-author trailer on every Claude Code commit — not conditional on user mentioning involvement.

**Skill commit templates — trailers not optional**: when skill or workflow step provides `git commit -m "..."` template (heredoc or one-liner), template is **message body scaffold only**. `---` separator and co-author block must always be appended regardless of whether template shows them:

- **Heredoc** (`cat <<'EOF' ... EOF`): insert `---` block and trailers before closing `EOF`
- **One-liner `-m "string"`**: convert to heredoc — one-liners cannot carry multi-line trailers

Never skip trailers because skill template omits them.

## Branch Safety

Default branch is repo-specific — do NOT hardcode `main` or `master`. Detect dynamically via `git symbolic-ref refs/remotes/origin/HEAD`, `gh repo view`, or `git remote show origin`.

Before any `git commit`, check current branch:

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

Feature branch: `commit-guard.js` hook enforces authorization via sentinel files — never bypass it. Default branch: `AskUserQuestion` always required before commit.

## Commit Authorization

Hook `commit-guard.js` is the runtime enforcement layer. Claude's role is to trigger the right flow; the hook blocks unauthorized `git commit` calls.

**Sentinel paths** (hook checks these):

- Gate 1: `/tmp/claude-commit-auth-<repo-slug>-<branch-slug>` · TTL 15 min
- Gate 2 (default branch only): `/tmp/claude-commit-default-<repo-slug>-<branch-slug>` · TTL 5 min

**Feature branch — three authorization sources**:

| Source | Gate 1 created by | Claude action |
| --- | --- | --- |
| **In-message** — user said "commit [this/it]", "make a commit", etc. | Hook auto-creates at `UserPromptSubmit` | Run `git commit` directly — sentinel already present |
| **In-workflow** — skill commits as documented step (e.g. `/oss:resolve`) | Skill: `touch $SENTINEL` before commit, `rm -f $SENTINEL` after | Run `git commit` inside skill workflow |
| **In-confirmation** — no explicit instruction; user confirmed via `AskUserQuestion` | Claude: `touch $SENTINEL` → `git commit` → `rm -f $SENTINEL` | Show branch + diff size + draft subject in question |

**Default branch — always AskUserQuestion**: invoke before any commit. On confirmation: `touch $SENTINEL && touch $DEFAULT_SENTINEL` → `git commit` → `rm -f $SENTINEL $DEFAULT_SENTINEL`. Gate 2 TTL is 5 min — touch immediately before commit.

**Never commit autonomously**: no commit without in-message signal, active skill workflow, or in-turn AskUserQuestion confirmation.
- Each message is independent — prior messages in session containing "commit" do not authorize commits in later messages; pattern-matching on session history is not a valid signal source.

## Staging and Hooks

- Never `git add -A` or `git add .` — always stage specific files by name
- Never `--no-verify` — if pre-commit blocks, fix underlying issue
- Never `--no-gpg-sign` unless user explicitly requests it

## Push Authorization

Same signal model as §Commit Authorization — no AskUserQuestion when signal present. Note: `git push` is not pre-allowed in settings; harness will prompt once regardless (by design).

**Feature branch — authorized when any signal present**:

| Signal | What it looks like |
| --- | --- |
| **In-message** | Current user message contains unambiguous push instruction: "push", "push this", "push the branch" |
| **In-workflow** | Running skill that names push as documented step AND user invoked that skill |
| **In-confirmation** | User confirmed via `AskUserQuestion` in the current response turn |

**When no signal present**: invoke `AskUserQuestion` before `git push`. Show: target branch, remote, whether default branch.

**Authorization scoped**: "commit this" does not authorize "push this" — push requires its own signal in the current message or turn.

**Default branch**: `AskUserQuestion` always required — no signal overrides this.

**Force-push**:
- Main/master: forbidden even with explicit user instruction
- Other branches: only with explicit user instruction in current message; never as autonomous "final step"

## History Safety

- Prefer `git revert` over `git reset --hard` (preserves history)
- Prefer merge commits for conflict resolution over rebase (preserves SHAs)
