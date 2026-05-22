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
IMPL_DIR="${TMPDIR:-/tmp}/resolve-impl-$$"
mkdir -p "$IMPL_DIR"  # timeout: 5000

SENTINEL=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/compute_commit_sentinel.py")  # timeout: 5000
touch "$SENTINEL"  # timeout: 3000
trap 'rm -f "$SENTINEL"; rm -rf "$IMPL_DIR"' EXIT INT TERM
CHALLENGE_LOG=()  # per-item records: id|evidence|suggestion|resolution
```

`CODEX_AVAILABLE=false`: use `change` field to route to internal agent; never blanket-skip all items.

| `change` value | `IMPL_AGENT` |
| --- | --- |
| `code` · `refactor` · `config` · `ci` | `foundry:sw-engineer` |
| `test` | `foundry:qa-specialist` |
| `docs` | `foundry:doc-scribe` |
| `style` | `foundry:linting-expert` |

Complex items (effort `xhigh`, multi-file) with `CODEX_AVAILABLE=false` → skip with `⚠ codex not found — skipping item #<id> (xhigh effort). Install: /plugin marketplace add openai/codex-plugin-cc`.

`--agent <name>` overrides this routing table unconditionally.

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

**Hard cap: max 20 items per dispatch** — each item spawns up to 3 agents (1a challenge, 1b challenge, impl); 20 items = 60 agent spawns, already at context budget boundary. When `SELECTED_ITEMS` contains >20 items (`$(echo "$SELECTED_ITEMS" | wc -w)` > 20): invoke `AskUserQuestion` — (a) Apply first 20 now, re-run for remainder · (b) Apply all `[req]` only · (c) Proceed with all (slow, may hit context limits). Never silently start loop with >20 items.

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
# Ensure clean state before each item — substitute <id> with item.id.
# Stash with a trap so we never leave the working tree dirty when the
# implementation agent makes no changes (no pop in that branch).
STASHED=false
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠ dirty tree before item #<id> — stashing"
    git stash push -m "resolve-pre-item-<id>" && STASHED=true  # timeout: 3000
fi
# Pop on any exit path; STASHED=false after a successful pop makes the
# trap body a no-op. This appends to the EXIT/INT/TERM traps already set
# in the loop header (sentinel + IMPL_DIR cleanup) — fold the stash-pop
# into the existing single trap line rather than overwriting it.
trap '[ "$STASHED" = "true" ] && git stash pop >/dev/null 2>&1; rm -f "$SENTINEL"; rm -rf "$IMPL_DIR"' EXIT INT TERM
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

Code changed → pop stash BEFORE committing (and clear `STASHED` so the EXIT trap is a no-op), then stage and commit per `COMMIT_MODE`:

```bash
if [ "$STASHED" = "true" ]; then
    git stash pop || { echo "⚠ stash pop conflict — resolve conflicts in $(git stash list | head -1) before item #<id>"; exit 1; }  # timeout: 3000
    STASHED=false
fi

python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/stage_item_changes.py" "<id>"  # timeout: 5000
```

**`COMMIT_MODE=each`** (commit-each, default) — commit immediately after each item. Write the per-item commit message to a temp file, then dispatch to `bin/commit_action_item.py` (handles sentinel touch + `git add` + `git commit` and cleans the sentinel on every exit path). Omit the Codex co-author line when `IMPL_AGENT ≠ codex:codex-rescue`:

```bash
COMMIT_MSG=$(mktemp)  # timeout: 3000
trap 'rm -f "$COMMIT_MSG"' RETURN
cat >"$COMMIT_MSG" <<EOF
<imperative short summary of the change>

[resolve #<item_id>] Review by @<author> (PR #<PR_NUMBER>):
"<first 72 chars of full_comment_text>..."
Challenge: evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>

---
Co-authored-by: Claude Code <noreply@anthropic.com>
Co-authored-by: OpenAI Codex <codex@openai.com>
EOF

python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/commit_action_item.py" \
    --message-file "$COMMIT_MSG" \
    --files <files-changed-by-this-item>  # timeout: 10000
```

**`COMMIT_MODE=all`** — stage only here; commit once after all items (see end of loop section).

**`COMMIT_MODE=stage`** — stage only; no commit now or later. ⚠ Cannot cleanly restore original branch — changes stay staged on PR branch.

No code changed → record agent's reason; do NOT create empty commit. Record per-item: `committed <SHA>` or `staged` or `skipped — <reason>`.

Mark item's task completed:

```text
TaskUpdate(task_id=<item.task_id>, status="completed")
```

**After loop — `COMMIT_MODE=all` only**: derive counters from `CHALLENGE_LOG`, then create single commit:

```bash
N_AS_SUGGESTED=0; N_SELF_RESOLVED=0; N_REJECTED=0; SUMMARIES_FILE=""
for _entry in "${CHALLENGE_LOG[@]}"; do
    case "$_entry" in
        *resolution=as-suggested*) N_AS_SUGGESTED=$(( N_AS_SUGGESTED + 1 )) ;;
        *resolution=self-resolved*) N_SELF_RESOLVED=$(( N_SELF_RESOLVED + 1 )) ;;
        *evidence=REJECT*) N_REJECTED=$(( N_REJECTED + 1 )) ;;
    esac
done
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/commit_all_items.py" "$PR_NUMBER" "$N_AS_SUGGESTED" "$N_SELF_RESOLVED" "$N_REJECTED" "$SUMMARIES_FILE" $( [ "${CODEX_AVAILABLE:-false}" = "true" ] && echo "--codex" )  # timeout: 10000
```
