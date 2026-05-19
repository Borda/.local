# Comment Dispatch — oss:resolve independent entry point

Reached when `$ARGUMENTS` = bare comment text (not PR number or URL). File read + executed by `/oss:resolve` Step 12.

<workflow>

## Step 12: Comment dispatch + Codex review loop

Reached when $ARGUMENTS = bare comment text (not PR number or URL).

Create task:

```text
TaskCreate(
  subject="Resolve: <60-char summary of $ARGUMENTS>",
  description="<full $ARGUMENTS>",
  activeForm="Resolving comment"
)
```

If `CODEX_AVAILABLE=false`: stop with `⚠ codex plugin not found — install: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`, mark task completed:

```text
TaskUpdate(task_id=<task_id_from_above>, status="completed")
```

and stop.

### 12a: Dispatch

Compute the scoped sentinel path (matches `git-commit.md` Path A pattern — `/tmp/claude-commit-auth-<repo-slug>-<branch-slug>`), touch it, and register a cleanup trap so the authorization is revoked on completion or abort:

```bash
REPO_SLUG=$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
BRANCH_SLUG=$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')
SENTINEL="/tmp/claude-commit-auth-${REPO_SLUG}-${BRANCH_SLUG}"
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"' EXIT INT TERM
```

```bash
Agent(subagent_type="codex:codex-rescue", prompt="Apply this review comment to the codebase. If the change is already present, or the comment has no actionable code change, make no changes and briefly explain why. Comment: $ARGUMENTS")
```

Record initial dispatch outcome (code changed or no change + reason).

### 12b: Codex review loop (max 5 passes)

```bash
git diff HEAD --stat # timeout: 3000 — confirm there are changes to review
```

No changes: skip loop; set `CODEX_REVIEW_FINDINGS=""`.

Otherwise:

```pseudocode
for REVIEW_PASS in 1 2 3 4 5; do  # pseudocode — not shell

  # Review phase — Agent() is a Claude Code tool call, not a shell command
  CODEX_OUT = Agent(subagent_type="codex:codex-rescue",
                    prompt="Review working-tree changes. End output with ISSUES_FOUND=N.")
  ISSUES_FOUND = parse CODEX_OUT for ISSUES_FOUND=N (default 0)

  if ISSUES_FOUND == 0: break

  # Fix phase
  Agent(subagent_type="codex:codex-rescue",
        prompt="Apply this fix: <issue description from review>")

done

if REVIEW_PASS == 5 and ISSUES_FOUND > 0:
  echo "⚠ Review loop hit 5-pass cap — $ISSUES_FOUND issues remain; surface to user"
```

### 12c: Lint and QA gate

If code changed:

```bash
RUN_DIR=".reports/resolve/$(date -u +%Y-%m-%dT%H-%M-%SZ)"  # timeout: 5000
mkdir -p "$RUN_DIR"                                          # timeout: 5000
```

Apply **Step 9 lint and QA gate pattern** from main resolve workflow — same parallel spawn of `foundry:linting-expert` + `foundry:qa-specialist`, commit lint fixes, surface blocking QA issues. Use `$RUN_DIR/linting-expert-step12c.md` and `$RUN_DIR/qa-specialist-step12c.md` as output paths.

Commit authorization is revoked automatically by the `trap 'rm -f "$SENTINEL"' EXIT INT TERM` registered in Step 12a — `$SENTINEL` stays in scope for the entire dispatch + review + gate sequence. Do **not** issue a separate `rm -f /tmp/claude-commit-authorized` here; that path is no longer used (sentinel is now scoped per repo + branch per `git-commit.md`).

Mark task `completed`:

```text
TaskUpdate(task_id=<task_id_from_above>, status="completed")
```

Then print:

```markdown
## Resolve Report

**Verdict**: ✓ resolved | ⊘ no change — <Codex's reason>

### Codex Review
<findings across passes, or "No issues found" / "Skipped — no changes">

### Lint + QA
<linting-expert summary: N fixes applied | or "no violations"> / <foundry:qa-specialist summary: N blocking fixed, N warnings | or "clean">

**Next**: review diff and commit | reply to reviewer with Codex's explanation

## Confidence
**Score**: [0.N]
**Gaps**: [e.g. Codex partial completion, ambiguous comment intent]
**Refinements**: N passes. — omit if 0 passes
```

</workflow>
