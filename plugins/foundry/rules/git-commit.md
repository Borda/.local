---
description: Git commit conventions and safety rules — applies globally
paths:
  - '**'
---

## Commit Message Format

- First line: short TLDR subject in imperative mood, ≤50 chars — name up to 3 most significant changes/additions/removals only
  - Tie-breaker: prefer user-visible impact when significance comparable

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

**Ranking rule — diff first, recency last**: rank significance across full diff before writing title.
- Conversational recency bias must not dominate
- Title must reflect most significant change in diff, not most recent one

**New files always significant**: any file marked `A` in `git status` must be explicitly mentioned in commit bullet list, regardless of line count. New files = added capability, not just changed lines.

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

Default branch is repo-specific — do NOT hardcode `main` or `master`. Hook detects dynamically via `git symbolic-ref refs/remotes/origin/HEAD`, `gh repo view`, or `git remote show origin`. Committing to default branch requires **second sentinel** (Gate 2 below).

Before any `git commit`, check current branch:

```bash
CURRENT_BRANCH=$(git branch --show-current)
```

On default branch: two sentinels required (Gate 1 + Gate 2). On feature branch: one sentinel required (Gate 1 only).

## Commit Gate (two gates)

**Gate 1 — commit authorization** (all branches):

Sentinel path: `/tmp/claude-commit-auth-<repo-slug>-<branch-slug>` · TTL: 15 min

**Gate 2 — default-branch protection** (default branch only):

Sentinel path: `/tmp/claude-commit-default-<repo-slug>-<branch-slug>` · TTL: 5 min (must touch immediately before commit)

Slug algorithm: all non-alphanumeric → `-`, lowercased, consecutive dashes squeezed, trailing dashes stripped.

```bash
# Compute both sentinel paths
REPO_SLUG=$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
BRANCH_SLUG=$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
SENTINEL="/tmp/claude-commit-auth-${REPO_SLUG}-${BRANCH_SLUG}"
DEFAULT_SENTINEL="/tmp/claude-commit-default-${REPO_SLUG}-${BRANCH_SLUG}"
```

**Path A — skill pre-auth** (skills committing as part of workflow, e.g. `/oss:resolve`):
- `touch $SENTINEL` at start of commit phase; `rm -f $SENTINEL` on finish or abort (use `trap` to guarantee cleanup)
- If committing to default branch: also `touch $DEFAULT_SENTINEL`; `rm -f $DEFAULT_SENTINEL` in same `trap`
- Gate 1 sentinel exists and <15 min old (Gate 2 valid if on default branch) → hook allows commit
- Sentinel absent, expired, or branch mismatch → hook blocks → fall through to Path B

**Path B — user ad-hoc request**:
- No Gate 1 sentinel → invoke `AskUserQuestion` before `git commit`
- Question must show: target branch, whether default branch, diff size (`N files, +A −B lines` from `git diff --stat HEAD`), draft commit message subject line
- On user confirmation:
  - Feature branch: `touch $SENTINEL` → `git commit` → `rm -f $SENTINEL`
  - Default branch: `touch $SENTINEL && touch $DEFAULT_SENTINEL` → `git commit` → `rm -f $SENTINEL $DEFAULT_SENTINEL`
- Never self-create sentinels without `AskUserQuestion` first — bypasses Gate 2 entirely

## Staging and Hooks

- Never `git add -A` or `git add .` — always stage specific files by name
- Never `--no-verify` — if pre-commit blocks, fix underlying issue
- Never `--no-gpg-sign` unless user explicitly requests it

## Push Safety

- **Never push without explicit user confirmation** — always ask before any `git push`, including branch pushes, PR pushes, and release tags
- Authorization scoped: "commit this" does not authorize "push this"; ask separately for every push
- Applies inside skill workflows — if skill (e.g. `/resolve`) includes push step, treat as "propose and confirm", not "auto-execute"; stop after committing, report what ready to push, wait for user to say push
- Never push in autonomous bug fixing or as "final step" without being explicitly asked in that message
- Never force-push (`--force`, `--force-with-lease`) to main/master; never force-push without explicit user instruction even on feature branches

## History Safety

- Prefer `git revert` over `git reset --hard` (preserves history)
- Prefer merge commits for conflict resolution over rebase (preserves SHAs)
