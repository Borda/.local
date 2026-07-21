# Comment Dispatch — oss:resolve independent entry point

Reached when `$ARGUMENTS` = bare comment text (not PR number or URL). File read, executed by `/oss:resolve` Step 12.

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

If `CODEX_AVAILABLE=false`: degrade gracefully — match `action-item-dispatch.md` routing. Classify the comment by intended `change` type (infer from comment text: mentions of tests → `test`; mentions of docs/README → `docs`; mentions of style/lint → `style`; configuration/CI → `config`/`ci`; default → `code`). Route to internal agent:

| Inferred `change` value | Fallback agent |
| --- | --- |
| `code` · `refactor` · `config` · `ci` | `foundry:sw-engineer` |
| `test` | `foundry:qa-specialist` |
| `docs` | `foundry:doc-scribe` |
| `style` | `foundry:linting-expert` |
| ambiguous / config-only changes | `foundry:sw-engineer` |

Print `⚠ codex plugin not found — falling back to <agent> for this comment. For broader Codex support: /plugin marketplace add openai/codex-plugin-cc && /plugin install codex@openai-codex && /reload-plugins`. Set `IMPL_AGENT=<fallback agent>`; proceed to Step 12a with fallback agent in place of `codex:codex-rescue`. Skip Codex review loop (Step 12b) when no Codex available — single dispatch only.

### 12a: Dispatch

**BATCH_SIZE=5** — dispatch at most 5 `Agent()` calls per response turn; wait for all to return before next batch. If $ARGUMENTS expands to more than 5 comment items (multi-comment dispatch), process first 5, wait for results, then continue with next 5. Prevents rate-limit hits, unbounded parallel spawn.

Compute the scoped sentinel path via `compute_commit_sentinel.py`, touch it, and register a cleanup trap:

```bash
SENTINEL=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/compute_commit_sentinel.py")  # timeout: 5000
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"' EXIT INT TERM
```

```bash
# IMPL_AGENT: codex:codex-rescue default; falls back per table above when CODEX_AVAILABLE=false
Agent(subagent_type="${IMPL_AGENT:-codex:codex-rescue}", prompt="Apply this review comment to the codebase. If the change is already present, or the comment has no actionable code change, make no changes and briefly explain why. Comment: $ARGUMENTS")
```

Record initial dispatch outcome (code changed or no change + reason).

### 12b: Codex review loop (max 5 passes)

**Skip entirely when `CODEX_AVAILABLE=false`** — review loop is Codex-specific. Set `CODEX_REVIEW_FINDINGS=""` and continue to Step 12c.

```bash
git diff HEAD --stat  # timeout: 3000
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

If code changed, ensure `$CHANGE_SCOPE` set (default `targeted` if unset), then delegate to gate:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_OSS_RESOLVE=$(cat "${TMPDIR:-/tmp}/resolve-oss-resolve-${CSID}" 2>/dev/null || echo "")  # reload (Check 41)
cat "$_OSS_RESOLVE/modes/lint-qa-gate.md"  # timeout: 5000
```

Execute its steps (loaded above).

Commit authorization revoked automatically by `trap 'rm -f "$SENTINEL"' EXIT INT TERM` registered in Step 12a — `$SENTINEL` stays in scope for entire dispatch + review + gate sequence. Do **not** issue separate `rm -f /tmp/claude-commit-authorized` here; that path no longer used (sentinel now scoped per repo + branch per `git-commit.md`).

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
**Refinements**: N passes.
```

</workflow>
