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
  Co-authored-by: Claude Code <noreply@anthropic.com>
  ```

- **No line wrapping** — bullets and prose single continuous lines; never hard-break at any column width

## Gathering Diff Context

Before writing commit, run three in parallel:

- `git status` — identify staged new files (`A` prefix) and unstaged changes
- `git diff HEAD` — **not** bare `git diff`; bare `git diff` shows only unstaged changes, misses staged new files; `git diff HEAD` captures staged and unstaged vs HEAD
- `git log --oneline -5` — reference repo's existing commit style

**Truncated diff — mandatory follow-up**: when `git diff HEAD` output large and Bash tool saves to file (showing only 2 KB preview), **read saved file completely before writing commit**. Don't write from preview alone — most significant changes often past truncation point. Also run `git diff --stat HEAD` (always fits in context) for complete file-by-file change map; use stat output to identify which files changed most and whether any missed in preview.

**High-churn files — mandatory diff read**: any file with >50 lines changed in `git diff --stat` NOT already in planned bullets — read actual diff before writing message. Don't assume from session memory or prior context; post-compaction sessions have no reliable recall. User/developer-facing changes (command syntax, CLI argument names, invocation patterns, API surface, usage examples) must be identified and prioritised regardless of earlier discussion — outrank internal restructuring of equal line count.

**Ranking rule — diff first, recency last**: classify all changes into tiers (see Subject priority table above) before writing title.
- Conversational recency bias must not dominate — last task in session ≠ most significant
- Title must reflect highest-tier change in diff, not most recent one

**New files — classify by content, not by `A` marker**: any file marked `A` in `git status` must be explicitly mentioned in commit bullet list. But tier depends on content origin:
- Content is genuinely new → tier 1 (new capability)
- Content extracted/refactored from existing file → tier 4 (maintenance); mention as "extracted from X", not "added"
- New file + new content = tier 1. New file + moved content = tier 3.

**Semantic novelty beats diff verbosity**: new capability/interface/script outranks verbose-but-routine config edit even if config diff has more lines. Ask "what would reviewer need to know first?" — that most significant change.

## Co-authors

Separate co-author block from bullet list with `---`:

```markdown
- last bullet

---
Co-authored-by: Claude Code <noreply@anthropic.com>
```

- Claude: `Co-authored-by: Claude Code <noreply@anthropic.com>`
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
