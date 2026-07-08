<!-- oss:resolve Step 8 — executed via: Read $_OSS_RESOLVE/modes/action-item-dispatch.md; execute -->
<!-- fragment — no <workflow> wrapper; executed inline by SKILL.md -->
<!-- Input: SELECTED_ITEMS (from Step 3e), COMMIT_MODE (from Step 3d), CODEX_AVAILABLE (from Step 1), $_OSS_RESOLVE, ARGUMENTS -->
<!-- Output: items implemented/staged/committed; CHALLENGE_LOG populated; CHANGE_SCOPE set for Step 9 -->

## Step 8: Implement action items

**Commit authorization — entire Step 8**: `COMMIT_MODE` from Step 3d governs all commits; never re-ask regardless of mode, item count, or sentinel state. Multiple resolve flows per session each honor their own Step 3d choice.

Determine implementation agent, set up file-handoff dir, and authorize commits before the loop:

```bash
IMPL_AGENT="codex:codex-rescue"
[[ "$ARGUMENTS" == *"--agent "* ]] && {
    IMPL_AGENT=$(echo "$ARGUMENTS" | grep -oP '(?<=--agent )\S+')
    echo "→ Using --agent: $IMPL_AGENT"
}

# set in Step 3b (pr-intelligence subagent); idempotent if already set
[ -z "$IMPL_DIR" ] && IMPL_DIR=$(mktemp -d)  # timeout: 3000
mkdir -p "$IMPL_DIR"  # timeout: 3000
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

**Caps** — soft cap 10, hard cap 20 items per dispatch. When `SELECTED_ITEMS` > 10 (`$(echo "$SELECTED_ITEMS" | wc -w)` > 10): invoke `AskUserQuestion` — (a) Apply first 10 now, re-run for remainder · (b) Apply all `[req]` only · (c) Proceed with all up to 20 (slow, context risk). Never silently start loop with >10 items; never exceed 20 in one dispatch (context budget boundary).

**≥4 selected items — batched dispatch** (token lever: cuts spawn count ~3×, per-item rigor unchanged): group items by file affinity (items touching the same file or same concern class → one batch; max 5 per batch; unrelated items → solo batch). Per batch:
- **One combined challenge call** to `DOMAIN_CHALLENGER` (route by the batch's dominant domain; mixed-domain batch → `foundry:challenger`) covering ALL batch items — prompt lists each item's `<id>`, `full_comment_text`, `<file:line>`; agent writes full analysis to `$IMPL_DIR/challenge-batch-<ids>.md`; returns per-item verdict array: `{"items":[{"id":N,"evidence":"VALID"|"REJECT","evidence_rationale":"…","suggestion":"VALID"|"REJECT","suggestion_rationale":"…","alternative":"…|null"}]}`. Same per-item parsing/CHALLENGE_LOG rules as Phase 1 — verdict granularity is NOT relaxed; rejected items drop from the batch.
- **One impl agent per batch** for surviving items (route by batch `change` majority per the routing table; effort = highest `ITEM_EFFORT` in batch): prompt lists per-item feedback + per-item `ITEM_CALLERS`; agent writes `$IMPL_DIR/impl-batch-<ids>.md`; returns `{"status":"done"|"partial","items_done":[ids],"items_skipped":[{"id":N,"reason":"…"}],"files_changed":N}`. Stage/commit per `COMMIT_MODE` using each item's own id for attribution (`stage_item_changes.py <id>` per item).
- Print compact progress `[N/total] batch #<ids> — <files>`. Skip per-item stash/unstash — one clean-state check per batch instead.
- C1 Codex-first routing still applies BEFORE batching: `medium`-effort items go to Codex individually as usual; only items falling through to Phase 1+2 are batched.

**Per action item** — loop over `SELECTED_ITEMS` in priority order. Per item, read full details from `$IMPL_DIR/action-items.jsonl` (written by Step 3b pr-intelligence subagent) — this is the authoritative source for `full_comment_text`, `file`, `line`, `change`, `severity`, `author`:

```bash
ITEM_DATA=$(jq -c ". | select(.id == <id>)" "$IMPL_DIR/action-items.jsonl")  # timeout: 5000
```

Use `.full_comment_text` for `IMPL_PROMPT`, `.file`/`.line` for stash label and commit scope, `.change`/`.severity` for effort classification and agent routing.

**Pre-loop blast-radius scan** — run once in the main orchestrator before the loop starts; collect caller context per item so each impl subagent knows which contracts to preserve. Soft: missing `scan-query` is a no-op.

```bash
# pre-loop; BLAST_RADIUS_CONTEXT shared with impl agents
BLAST_RADIUS_CONTEXT=""
if command -v scan-query >/dev/null 2>&1 && [ -f "$IMPL_DIR/action-items.jsonl" ]; then
    echo "→ Codemap pre-scan — caller context for selected action items:"
    for _id in $SELECTED_ITEMS; do
        _f=$(jq -r "select(.id == $_id) | .file // empty" "$IMPL_DIR/action-items.jsonl")  # timeout: 5000
        [[ "$_f" == *.py ]] || continue
        _m=$(echo "$_f" | sed -E 's|^src/||; s|/|.|g; s|\.py$||')
        _c=$(scan-query rdeps "$_m" 2>/dev/null | head -20)  # timeout: 10000
        if [ -n "$_c" ]; then
            printf "  #%s %s ← callers: %s\n" "$_id" "$_m" "$(echo "$_c" | tr '\n' ' ')"
            BLAST_RADIUS_CONTEXT+="item #${_id} (${_m}) callers:"$'\n'"${_c}"$'\n\n'
        fi
    done
    [ -z "$BLAST_RADIUS_CONTEXT" ] && echo "  (no Python callers found for selected items)"
fi
```

Per item before impl dispatch, extract this item's caller section:

```bash
item_id=$_id  # align with blast-radius scan loop variable
ITEM_CALLERS=$(awk "/^item #${item_id} /,/^[[:space:]]*$/" <<< "$BLAST_RADIUS_CONTEXT" | tail -n +2)
```

Include non-empty `$ITEM_CALLERS` in impl agent prompt — see Phase 2.

**C1 — Codex-first routing for `medium` effort items** (skip Phase 1+2 when Codex handles it):

When `ITEM_EFFORT=medium` AND `CODEX_AVAILABLE=true`: dispatch Codex for evidence check + implementation in one call.

```text
Agent(subagent_type="codex:codex-rescue", prompt="Effort level: medium. Review and implement this action item if valid.
Item: <full_comment_text>
File: <file>  Line: <line>
Implement directly if the issue clearly exists. Return ONLY compact JSON as your FINAL message:
{\"verdict\":\"DONE\"|\"UNCERTAIN\",\"reason\":\"<one sentence>\",\"files_changed\":N}")
```

Parse JSON:
- **DONE** → mark item resolved; stage/commit per `COMMIT_MODE`; append to `CHALLENGE_LOG`: `id=<id> evidence=VALID suggestion=VALID resolution=codex-direct`; skip Phase 1+2; proceed to next item
- **UNCERTAIN** → fall through to Phase 1+2 (normal challenge + implementation flow)

When `CODEX_AVAILABLE=false` OR `ITEM_EFFORT!=medium`: skip Codex routing; use Phase 1+2 directly.

### Phase 1: Challenge (skip when `--no-challenge`)

Route by domain to foreground challenge agent:

| Item domain | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases | `foundry:sw-engineer` |
| Test coverage, assertions, regressions | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

Set `DOMAIN_CHALLENGER` from routing table: architecture/API/coupling/default → `foundry:challenger`; code logic/correctness/edge-cases → `foundry:sw-engineer`; test coverage/assertions/regressions → `foundry:qa-specialist`. Use agent-resolution.md fallback if foundry absent.

**Combined evidence + suggestion challenge** (B1 — single agent call, saves one opus spawn per item):

```text
Agent(subagent_type="${DOMAIN_CHALLENGER}", prompt="Two-part challenge for this review item.
Part 1 — does the stated problem actually exist in the code as described?
Part 2 — if problem exists, is the suggested fix the right approach?
Read the referenced file at <file:line>. Max 3 tool calls.
Write full analysis to $IMPL_DIR/challenge-<id>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"evidence\":\"VALID\"|\"REJECT\",\"evidence_rationale\":\"<one sentence>\",\"suggestion\":\"VALID\"|\"REJECT\",\"suggestion_rationale\":\"<one sentence>\",\"alternative\":\"<brief alternative or null>\"}")
```

Parse compact JSON from agent final message:
- `evidence=REJECT` → print `⊘ #<id> evidence rejected: <evidence_rationale>`; set type `[challenged:reject]`; append to `CHALLENGE_LOG`; skip to next item
- `evidence=VALID` + `suggestion=VALID` → `SUGGESTION_VERDICT=VALID`; use original suggestion for implementation
- `evidence=VALID` + `suggestion=REJECT` → `SUGGESTION_VERDICT=REJECT`; self-resolve using `alternative` as guidance

Append to `CHALLENGE_LOG`: `id=<id> evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>`.

### Phase 2: Implementation

```bash
# clean state before each item (substitute <id> with item.id); STASHED=false when agent
# makes no changes — no pop needed
STASHED=false
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠ dirty tree before item #<id> — stashing"
    git stash push -m "resolve-pre-item-<id>" && STASHED=true  # timeout: 3000
fi
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

# file-handoff: agent writes full context to file; orchestrator reads compact JSON only
Agent(subagent_type="$IMPL_AGENT", prompt="Effort level: $ITEM_EFFORT. $IMPL_PROMPT
$([ -n "$ITEM_CALLERS" ] && printf "Blast-radius context — modules that call into the code you are changing; preserve their public contracts:\n%s" "$ITEM_CALLERS")
Write your findings (approach taken, files changed) to $IMPL_DIR/impl-<id>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"status\":\"done\"|\"skipped\",\"reason\":\"<if skipped, else null>\",\"files_changed\":N}")

# parse compact JSON; read impl-<id>.md only if full context needed
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

**`COMMIT_MODE=each`** — commit immediately after each item. `commit_action_item.py --build` assembles the canonical per-item message (subject + `[resolve #<id>]` attribution block + co-author trailers) — pass `--codex` only when `IMPL_AGENT = codex:codex-rescue`:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/commit_action_item.py" --build \
    --summary "<imperative short summary of the change>" \
    --item-id "<item_id>" \
    --author "<author>" \
    --pr "<PR_NUMBER>" \
    --comment "<full_comment_text>" \
    --challenge "evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>" \
    $([ "$IMPL_AGENT" = "codex:codex-rescue" ] && echo "--codex") \
    --files <files-changed-by-this-item>  # timeout: 10000
```

**`COMMIT_MODE=all`** — stage only here; commit once after all items (see end of loop section).

**`COMMIT_MODE=stage`** — stage only; no commit now or later. ⚠ Cannot cleanly restore original branch — changes stay staged on PR branch.

No code changed → record agent's reason; do NOT create empty commit. Record per-item: `committed <SHA>` or `staged` or `skipped — <reason>`.

Mark item's task per COMMIT_MODE — do NOT fire `completed` here for `all`/`grouped` (commit hasn't happened yet; a post-loop commit failure would leave false-completed tasks):

```text
# each → completed now (committed this iteration)
# stage → completed now (staged = terminal; no "staged" task status)
# all/grouped → leave in_progress; post-loop commit block flips after commit
if COMMIT_MODE == "each" or COMMIT_MODE == "stage":
    TaskUpdate(task_id=<item.task_id>, status="completed")
```

**After loop — `COMMIT_MODE=grouped` only**: collect topic labels, group items, commit each group.

Invoke `AskUserQuestion` after the implementation loop completes (all items staged, no commits yet):

```text
AskUserQuestion: "Assign a topic label to each implemented item (e.g. style, logic, tests, docs, config).
Items implemented:
  <for each item in SELECTED_ITEMS: "#<id>: <summary>">
Type a topic for each item ID (e.g. '1=style 2=logic 3=tests'), or type 'auto' to infer labels from change field."
```

- User types labels → parse `<id>=<topic>` pairs from response
- User types `auto` → infer topic from each item's `.change` field: `style`→`style`, `test`→`tests`, `docs`→`docs`, `ci`→`ci`, `config`→`config`, `code`|`refactor`→`logic`; default `misc` when unclassified
- Any item not assigned a label → assign topic `misc`
- User skips (empty response or blank) → fall back to `each` mode: commit each already-staged item individually using the same `commit_action_item.py` path as `COMMIT_MODE=each`

Group items by topic label. For each unique topic group (ordered by first item ID in group):

```bash
GROUP_IDS=(<item ids in this group>)
GROUP_SUMMARIES=(<item summaries in this group>)
COMBINED_SUMMARY=$(echo "${GROUP_SUMMARIES[@]}" | tr ' ' '\n' | head -5 | paste -sd '; ')
COMMIT_MSG=$(mktemp)  # timeout: 3000
trap 'rm -f "$COMMIT_MSG"' RETURN
cat >"$COMMIT_MSG" <<EOF
<topic>: ${COMBINED_SUMMARY}

[resolve group] PR #<PR_NUMBER> — items ${GROUP_IDS[*]}

---
Co-authored-by: claude[bot] <209825114+claude[bot]@users.noreply.github.com>
$([ "${CODEX_AVAILABLE:-false}" = "true" ] && echo "Co-authored-by: OpenAI Codex <codex@openai.com>")
EOF
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/commit_action_item.py" \
    --message-file "$COMMIT_MSG" \
    --files <all files changed by items in this group>  # timeout: 10000
```

Commit subject format: `<topic>: <combined summary of items in group>` (≤72 chars total; truncate combined summary with `…` if needed). One commit per unique topic. Print `→ Committed group "<topic>" — items <ids>` after each commit.

After each successful group commit, flip the tasks for that group to completed:

```text
for each item_id in GROUP_IDS:
    TaskUpdate(task_id=<SELECTED_ITEMS[item_id].task_id>, status="completed")
```

**After loop — `COMMIT_MODE=all` only**: derive counters from `CHALLENGE_LOG`, create single commit:

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

After the commit succeeds, flip all staged items to completed (deferred from per-item loop body where commit had not yet happened):

```text
for each item in SELECTED_ITEMS where status != "skipped":
    TaskUpdate(task_id=<item.task_id>, status="completed")
```
