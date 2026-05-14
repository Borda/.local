<!-- oss:resolve Step 8 — executed via: Read $_OSS_RESOLVE/modes/action-item-dispatch.md; execute -->
<!-- Input: SELECTED_ITEMS (from Step 3e), COMMIT_MODE (from Step 3d), CODEX_AVAILABLE (from Step 1), $_OSS_RESOLVE, ARGUMENTS -->
<!-- Output: items implemented/staged/committed; CHALLENGE_LOG populated; CHANGE_SCOPE set for Step 9 -->

## Step 8: Implement action items

Determine implementation agent, set up file-handoff dir, and authorize commits before the loop:

```bash
IMPL_AGENT="codex:codex-rescue"
[[ "$ARGUMENTS" == *"--agent "* ]] && {
    IMPL_AGENT=$(echo "$ARGUMENTS" | grep -oP '(?<=--agent )\S+')
    echo "→ Using --agent: $IMPL_AGENT"
}

# File-handoff dir — subagents write full output here; orchestrator reads only compact JSON envelopes
IMPL_DIR="/tmp/resolve-impl-$$"
mkdir -p "$IMPL_DIR"  # timeout: 5000

SENTINEL="/tmp/claude-commit-auth-$(git rev-parse --show-toplevel | xargs basename | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')-$(git branch --show-current | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | tr -s '-' | sed 's/-$//')"
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"; rm -rf "$IMPL_DIR"' EXIT INT TERM
CHALLENGE_LOG=()  # per-item records: id|evidence|suggestion|resolution
```

`CODEX_AVAILABLE=false`: apply degradation rules from Step 1 (simple items → foundry:sw-engineer; complex items → skip with notice). Never blanket-skip all items.

> **Conflict gate**: verify all Step 5a conflict tasks `completed` before any action item. Still `pending`/`in_progress` → stop, surface list, wait. Items on unresolved conflicts compound diff.

Process items in `SELECTED_ITEMS` (from Step 3e) in priority order (`[req]` first, then `[suggest]`).

**Codex effort classification** — classify each item before dispatch; set `ITEM_EFFORT`; aggregate to `CHANGE_SCOPE` for Step 9:
- typo/spelling/whitespace/formatting/comment/rename-single/docstring → `medium`; multi-file/refactor/architecture/new-feature/redesign → `xhigh`; all else → `high` (default)
- Minimum effort is always `medium` — never `low`
- `ITEM_EFFORT` set per item; include in agent prompt as `"Effort level: $ITEM_EFFORT.\n..."` prefix
- `CHANGE_SCOPE` = aggregate across all `SELECTED_ITEMS`:
  - ALL items classified `medium` → `CHANGE_SCOPE=lint-only`
  - ANY item classified `xhigh` → `CHANGE_SCOPE=full`
  - otherwise → `CHANGE_SCOPE=targeted` (default)
- Compute `CHANGE_SCOPE` once before the loop; pass to Step 9 via shell variable

**≥10 selected items — batched dispatch**: group items by file affinity (items touching the same file → one batch; max 3 per batch; unrelated items → solo batch). Challenge each batch item individually (phases 1a/1b) before batching — items that pass both phases → batch together. Print compact progress `[N/total] batch #<ids> — <files>`. Skip per-item stash/unstash — one clean-state check per batch instead.

**Per action item** — loop over `SELECTED_ITEMS` in priority order:

### Phase 1: Two-phase challenge (skip when `--no-challenge`)

Route by domain to foreground challenge agent:

| Item domain | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases | `foundry:sw-engineer` |
| Test coverage, assertions, regressions | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

**1a — challenge evidence** (does the stated problem actually exist in the code?):

```text
Agent(subagent_type="<domain-challenger>", prompt="Challenge evidence only — does this issue actually exist in the code as described?
Read the referenced file at <file:line>. Max 2 tool calls.
Write full analysis to $IMPL_DIR/challenge-<id>-1a.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"verdict\":\"VALID\"|\"REJECT\",\"rationale\":\"<one sentence>\"}")
```

Parse compact JSON from agent final message:
- **REJECT** → print `⊘ #<id> evidence rejected: <rationale>`; set type `[challenged:reject]`; append to `CHALLENGE_LOG`; skip to next item
- **VALID** → proceed to 1b

**1b — challenge suggestion** (is the suggested fix the right approach?):

```text
Agent(subagent_type="<domain-challenger>", prompt="Evidence confirmed. Challenge the suggested fix only — is it the right approach?
Write full analysis to $IMPL_DIR/challenge-<id>-1b.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"verdict\":\"VALID\"|\"REJECT\",\"rationale\":\"<one sentence>\",\"alternative\":\"<brief alternative or null>\"}")
```

Parse compact JSON from agent final message:
- **VALID** → `SUGGESTION_VERDICT=VALID`; use original suggestion for implementation
- **REJECT** → `SUGGESTION_VERDICT=REJECT`; self-resolve: implement best fix for confirmed issue using `alternative` as guidance

Append to `CHALLENGE_LOG`: `id=<id> evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>`.

### Phase 2: Implementation

```bash
# Ensure clean state before each item — substitute <id> with item.id
test -z "$(git status --porcelain)" || { echo "⚠ dirty tree before item #<id> — stashing"; git stash push -m "resolve-pre-item-<id>"; }  # timeout: 3000
git diff HEAD --stat  # timeout: 3000
```

Mark item's task in_progress:

```text
TaskUpdate(task_id=<item.task_id>, status="in_progress")
```

Build prompt from challenge outcome, then dispatch implementation agent:

```bash
if [ "$SUGGESTION_VERDICT" = "REJECT" ]; then
    IMPL_PROMPT="Evidence confirmed but suggested fix rejected. Fix the underlying issue using best judgment. Original feedback: <full_comment_text>. Rejected approach: <suggestion_rationale>. Suggested alternative: <alternative>."
else
    IMPL_PROMPT="Apply this review feedback exactly as suggested. Feedback from @<author>: <full_comment_text>"
fi

# File-handoff: agent writes full context to file; orchestrator reads only compact JSON envelope
Agent(subagent_type="$IMPL_AGENT", prompt="Effort level: $ITEM_EFFORT. $IMPL_PROMPT
Write your findings (approach taken, files changed) to $IMPL_DIR/impl-<id>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"status\":\"done\"|\"skipped\",\"reason\":\"<if skipped, else null>\",\"files_changed\":N}")

# Parse compact JSON from agent final message; read $IMPL_DIR/impl-<id>.md only if full context needed
git diff HEAD --stat  # timeout: 3000
```

Code changed → pop stash BEFORE committing, then stage and commit per `COMMIT_MODE`:

```bash
if git stash list --quiet | grep -q "resolve-pre-item-<id>"; then
    git stash pop || { echo "⚠ stash pop conflict — resolve conflicts in $(git stash list | head -1) before item #<id>"; exit 1; }  # timeout: 3000
fi

git add $(git diff HEAD --name-only)                                                     # timeout: 3000
UNTRACKED=$(git ls-files --others --exclude-standard | grep -E '\.(py|md|yaml|yml|toml|cfg|ini|json|txt|sh|js|ts|go|rs|rb|java|c|cpp|h|hpp)$' 2>/dev/null)
[ -n "$UNTRACKED" ] && echo "$UNTRACKED" | xargs git add -- 2>/dev/null || true         # timeout: 3000
```

**`COMMIT_MODE=each`** (commit-each, default) — commit immediately after each item:

```bash
git commit -m "$(
    cat <<'EOF'
<imperative short summary of the change>

[resolve #<item_id>] Review by @<author> (PR #<PR_NUMBER>):
"<first 72 chars of full_comment_text>..."
Challenge: evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>

---
Co-authored-by: Claude Code <noreply@anthropic.com>
Co-authored-by: OpenAI Codex <codex@openai.com>
EOF
)"  # timeout: 3000
# Omit Codex co-author line when IMPL_AGENT ≠ codex:codex-rescue
```

**`COMMIT_MODE=all`** — stage only here; commit once after all items (see end of loop section).

**`COMMIT_MODE=stage`** — stage only; no commit now or later. ⚠ Cannot cleanly restore original branch — changes stay staged on PR branch.

No code changed → record agent's reason; do NOT create empty commit. Record per-item: `committed <SHA>` or `staged` or `skipped — <reason>`.

Mark item's task completed:

```text
TaskUpdate(task_id=<item.task_id>, status="completed")
```

**After loop — `COMMIT_MODE=all` only**: create single commit referencing all implemented items:

```bash
git commit -m "$(
    cat <<'EOF'
Resolve N review items for PR #<PR_NUMBER>

<bullet list of item summaries>
Challenge log: <N> as-suggested, <M> self-resolved, <K> rejected

---
Co-authored-by: Claude Code <noreply@anthropic.com>
Co-authored-by: OpenAI Codex <codex@openai.com>
EOF
)"  # timeout: 3000
```
