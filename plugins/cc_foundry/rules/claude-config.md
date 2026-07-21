---
description: Universal operational rules — no hardcoded paths, Bash timeouts, and directory navigation pattern
paths:
  - '**'
---

## Path Rules

- No hardcoded absolute user paths — use `.claude/`, `~/`, or `git rev-parse --show-toplevel`
- **Artifact dirs** belong at project root, not inside `.claude/` — see `artifact-lifecycle.md`

## Bash Timeouts

Every Bash call must include explicit `timeout` — **3× expected P90 duration**.
Never rely on default 120 s cap; fail fast, let caller retry.

| Operation class | Expected P90 | 3× timeout |
| --- | --- | --- |
| `gh pr view`, `gh pr diff`, `gh issue view` | 2 s | `timeout: 6000` |
| `gh pr checks`, `gh pr list` | 5 s | `timeout: 15000` |
| `gh api --paginate`, `gh release list` | 10 s | `timeout: 30000` |
| Local git commands (`git log`, `git diff`, `git status`) | 1 s | `timeout: 3000` |
| `pip install`, `npm install`, `brew install` | 30 s | `timeout: 90000` |
| Test suite (`pytest`, `uv run pytest`) | 3 min | `timeout: 600000` |
| Build / compile step | 2 min | `timeout: 360000` |
| Simple shell utilities (`wc`, `find`, `grep`, `ls`) | 0.5 s | `timeout: 5000` |
| Any other command (unknown duration) | estimate P90 conservatively | 3× estimate; min `timeout: 15000` |

Rules:

- Use 3× fastest plausible time — not worst case
- Timed-out fast op = signal to investigate; frozen session is not
- `timeout: 120000` only for test suites or builds, never network calls

## Directory Navigation Commands

Never combine directory navigation with command in single Bash call — always use **two separate Bash calls**:

```bash
# ✓ correct — two calls; CWD persists between calls
cd /path/to/dir
uv run pytest tests/

# ✗ wrong — all three forms cause same failure
cd /path && uv run pytest tests/
cd /path
uv run pytest tests/
cd /path || uv run pytest tests/
```

**Why**: Claude Code's permission matcher checks only **first token** of Bash command.
- Compound using `&&`, `;`, or `||` presents `cd` as first token — matches no allow entry
- Even when `Bash(uv run pytest:*)`, `Bash(python:*)`, or similar rules in allow list
- Applies to every command, not just worktrees

Working directory persists between Bash calls — two sequential calls equivalent.

**Worktrees**: same rule applies inside `isolation: "worktree"` agents (CWD = worktree root — no `cd` prefix needed). Settings in worktrees are snapshot from worktree-creation time — permissions added to main project after worktree created are NOT reflected; worktree agent hitting unexpected permission prompts → check if `settings.local.json` was updated since worktree creation.

## TMPDIR Sentinel Scoping

Cross-bash-block state (Bash tool state doesn't persist across separate tool invocations within a skill) commonly persists via `${TMPDIR:-/tmp}/<name>` sentinel files. `/tmp` is machine-global, not project- or session-scoped — a bare name like `${TMPDIR:-/tmp}/oss-review-run-dir` collides if two Claude Code sessions run the same skill concurrently (different projects, or two terminals in the same project).

**Rule**: every bash block touching sentinels derives the session token once (first line), then every sentinel name takes `-${CSID}` as its **terminal** suffix (after any dynamic part, after any extension):

```bash
# ✓ correct — session-scoped, safe under concurrent sessions
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir-${CSID}"

# ✗ wrong — bare name, collides across concurrent sessions/projects
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir"

# ✗ wrong — `CLAUDE_SESSION_ID` does not exist; `$$` is a NEW shell PID every Bash tool call
echo "$RUN_DIR" > "${TMPDIR:-/tmp}/oss-review-run-dir-${CLAUDE_SESSION_ID:-$$}"
```

Verified token facts (2026-07-21): env var is `CLAUDE_CODE_SESSION_ID` (not `CLAUDE_SESSION_ID`); `$$` changes per Bash tool call (fresh shell each call) — never use it; `$PPID` = Claude Code process PID, stable across all Bash calls in a session; spawned subagents inherit the SAME `CLAUDE_CODE_SESSION_ID` and `$PPID` as the lead, so cross-agent sentinel sharing works.

- `export` (not plain assignment) — python/node children invoked in the same block must see `CSID`
- Python scripts: `_CSID = os.environ.get("CSID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "shared"` — never `os.getppid()` (that returns the transient bash shell PID, not the CC process); temp base via `os.environ.get("TMPDIR") or tempfile.gettempdir()`, never hardcoded `/tmp` (absent on native Windows Python)
- Cross-OS (Linux/macOS/Windows-Git-Bash): `${TMPDIR:-/tmp}`, `$PPID`, `export` all work in Git Bash where `/tmp` mounts to the Windows temp dir
- Exempt (no `CSID` suffix, mark line with trailing `# tmpdir-exempt: <reason>`): `mktemp ...XXXXXX` templates (already unique); sentinels produced/consumed by code running outside Claude Code (e.g. git post-commit hooks — no session env there; keep project-slug scoping)
- Applies to every new sentinel added to any skill, hook, or bin script
- Existing bare-name sentinels (78 files, 794 occurrences repo-wide as of 2026-07-21) are known debt — migration plan: `.plans/active/todo_protected-locations-rollout.md`; their lack of suffixing is not precedent to copy in new code
- Args-derived suffixes alone (e.g. `${CLEAN_ARGS}`, a PR number) are not sufficient — two sessions in two *different* projects invoking the same skill with the same args still collide; `-${CSID}` is still required alongside them, not instead of them
- Cleanup (`rm -f`) at skill completion must target the exact session-scoped filename, never a glob that could match another session's sentinel of the same base name

## List Range Label Discipline

When editing file with lettered/numbered list range labels (e.g. `**Close-scenario archetypes (A–G):**`):

- After any edit adding/removing list items, update **all** range labels in file — not just edited section
- Non-contiguous letter ranges: use explicit form `A–C, F–G`, not `A–G`, when items missing
- Scan entire file after edits to catch stale range labels elsewhere

## Ask Before Acting on Unknown Cause

When user asks "why" about something (deleted content, unexpected state, missing items) and cause unknown:

- **Never act** — do not restore, revert, or modify anything
- State clearly cause unknown and why (e.g. "pre-session change not made by me")
- Call `AskUserQuestion` tool directly — prose questions in brackets (`[AskUserQuestion: ...]`, `[Invoking AskUserQuestion: ...]`) do NOT satisfy this requirement; only actual tool invocation does

Restoring without being asked = overstepping. "Why" = question, not request to fix.
