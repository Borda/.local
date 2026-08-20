---
description: Universal operational rules — no hardcoded paths, Bash timeouts, and directory navigation pattern
paths:
  - '**'
---

## Bash Timeouts — Per-Operation-Class Table

| Operation class | Expected P90 | 3× timeout |
| -- | -- | -- |
| `gh pr view`, `gh pr diff`, `gh issue view` | 2 s | `timeout: 6000` |
| `gh pr checks`, `gh pr list` | 5 s | `timeout: 15000` |
| `gh api --paginate`, `gh release list` | 10 s | `timeout: 30000` |
| Local git commands (`git log`, `git diff`, `git status`) | 1 s | `timeout: 3000` |
| `pip install`, `npm install`, `brew install` | 30 s | `timeout: 90000` |
| Test suite (`pytest`, `uv run pytest`) | 3 min | `timeout: 600000` |
| Build / compile step | 2 min | `timeout: 360000` |
| Simple shell utilities (`wc`, `find`, `grep`, `ls`) | 0.5 s | `timeout: 5000` |
| Any other command (unknown duration) | estimate P90 conservatively | 3× estimate; min `timeout: 15000` |

## Directory Navigation Commands — Why + Worktrees

**Why**: Claude Code's permission matcher checks only **first token** of Bash command.

- Compound using `&&`, `;`, or `||` presents `cd` as first token — matches no allow entry
- Even when `Bash(uv run pytest:*)`, `Bash(python:*)`, or similar rules in allow list
- Applies to every command, not just worktrees

**Worktrees**: same rule applies inside `isolation: "worktree"` agents (CWD = worktree root — no `cd` prefix needed). Settings in worktrees are snapshot from worktree-creation time — permissions added to main project after worktree created are NOT reflected; worktree agent hitting unexpected permission prompts → check if `settings.local.json` was updated since worktree creation.

## TMPDIR Sentinel Scoping — Verified Facts, Wrong-Form Examples, Exemptions, Migration Debt

**Wrong-form examples** (stub keeps the correct form only):

```bash
# ✗ wrong — bare name, collides across concurrent sessions/projects
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir"

# ✗ wrong — `CLAUDE_SESSION_ID` does not exist; `$$` is a NEW shell PID every Bash tool call
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir-${CLAUDE_SESSION_ID:-$$}"
```

**Verified token facts** (2026-07-21): env var is `CLAUDE_CODE_SESSION_ID` (not `CLAUDE_SESSION_ID`); `$$` changes per Bash tool call (fresh shell each call) — never use it; `$PPID` = Claude Code process PID, stable across all Bash calls in a session; spawned subagents inherit the SAME `CLAUDE_CODE_SESSION_ID` and `$PPID` as the lead, so cross-agent sentinel sharing works.

**Cross-OS** (Linux/macOS/Windows-Git-Bash): `${TMPDIR:-/tmp}`, `$PPID`, `export` all work in Git Bash where `/tmp` mounts to the Windows temp dir.

**Exempt** (no `CSID` suffix, mark line with trailing `# tmpdir-exempt: <reason>`): `mktemp ...XXXXXX` templates (already unique); sentinels produced/consumed by code running outside Claude Code (e.g. git post-commit hooks — no session env there; keep project-slug scoping).

**Migration debt**: existing bare-name sentinels (78 files, 794 occurrences repo-wide as of 2026-07-21) are known debt — migration plan: `.plans/active/todo_protected-locations-rollout.md`; their lack of suffixing is not precedent to copy in new code.
