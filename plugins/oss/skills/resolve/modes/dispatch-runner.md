<!-- oss:resolve Step 8 dispatcher — executed BY a foundry:sw-engineer SUBAGENT spawned from SKILL.md, NOT by the orchestrator. -->
<!-- fragment — no <workflow> wrapper; loaded via Read by the dispatcher subagent -->
<!-- Spawn shape: Agent(subagent_type="foundry:sw-engineer", prompt="... Read $_OSS_RESOLVE/modes/dispatch-runner.md and execute with these variables: ...") -->
<!-- consumer: plugins/oss/skills/resolve/SKILL.md (Step 8) -->

# Step 8 dispatcher — per-item loop

You are the dispatcher subagent for `/oss:resolve` Step 8. The orchestrator passes these variables via the spawn prompt:

| Var | Source | Use |
| --- | --- | --- |
| `SELECTED_ITEMS` | Step 3d | space-separated item IDs to process |
| `COMMIT_MODE` | Step 3d | `each` / `all` / `grouped` / `stage` |
| `IMPL_AGENT` | Step 8 prelude | `codex:codex-rescue` (default) or `--agent <name>` override |
| `IMPL_DIR` | Step 3b | dir with `action-items.jsonl`; write `results.jsonl`, `challenge-log.jsonl` here |
| `PR_NUMBER`, `PR_AUTHOR` | Step 3b | commit message templating |
| `BLAST_RADIUS_CONTEXT` | Step 8 prelude | per-item caller context (may be empty string) |
| `NO_CHALLENGE` | `--no-challenge` flag | `true` → skip Phase 1a/1b; treat every item as VALID/VALID |
| `CODEX_AVAILABLE` | Step 1 | informational; orchestrator already chose `IMPL_AGENT` |
| `CLAUDE_PLUGIN_ROOT` | env | bin/ script paths |
| `RESOLVE_TASK_IDS_FILE` | Step 8 prelude | `$IMPL_DIR/task-ids.json` mapping `{item_id: task_id}` — used only for `results.jsonl` `task_id` field (orchestrator owns TaskUpdate sweep) |

## Hard constraints (binding — failure to satisfy = quality regression)

1. **Every item in `SELECTED_ITEMS` MUST get a `results.jsonl` line** before you exit, regardless of outcome. No silent drops. Orchestrator validates `wc -l results.jsonl == |SELECTED_ITEMS|` and surfaces mismatch.
2. **No `AskUserQuestion`** — subagent context; the call hangs the parent. If you encounter a scenario the orchestrator didn't anticipate, write a `results.jsonl` line with `status="error"` + `reason` and continue.
3. **No `TaskUpdate` / `TaskCreate`** — orchestrator owns the task list; you write to `results.jsonl` and orchestrator sweeps post-return.
4. **No challenge bypass** — when `NO_CHALLENGE=false`, spawn 1a + 1b for every item; `challenge_evidence` and `challenge_suggestion` fields in `results.jsonl` must be non-null.
5. **No auto-promotion of REJECT** — evidence REJECT → status `"skipped"`; suggestion REJECT → status `"committed"` (or `"staged"`) with `resolution="self-resolved"`. Never silently treat a REJECT as straight success.
6. **Verbatim challenge/impl prompts** — the prompts below are the canonical strings; do not paraphrase, do not omit fields.

## Per-item loop

Process items in `SELECTED_ITEMS` in priority order (`[req]` first, then `[suggest]`). Read full item data from `$IMPL_DIR/action-items.jsonl`:

```bash
ITEM_DATA=$(jq -c ". | select(.id == <id>)" "$IMPL_DIR/action-items.jsonl")  # timeout: 5000
```

Extract per-item fields: `.full_comment_text`, `.file`, `.line`, `.change`, `.severity`, `.author`, `.type`.

### Effort classification (`ITEM_EFFORT`)

- typo/spelling/whitespace/formatting/comment/rename-single/docstring → `medium`
- multi-file/refactor/architecture/new-feature/redesign → `xhigh`
- everything else → `high` (default)
- minimum is `medium` — never `low`

### Extract per-item caller context

```bash
item_id=<id>
ITEM_CALLERS=$(awk "/^item #${item_id} /,/^[[:space:]]*$/" <<< "$BLAST_RADIUS_CONTEXT" | tail -n +2)
```

Include non-empty `$ITEM_CALLERS` in Phase 2 impl prompt.

### Phase 1: Two-phase challenge (skip when `NO_CHALLENGE=true`)

Route by item domain to challenger:

| Item domain (from `.change` + `.type`) | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases (`code`/`refactor`) | `foundry:sw-engineer` |
| Test coverage, assertions (`test`) | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

Set `DOMAIN_CHALLENGER` accordingly.

**1a — evidence challenge**:

```text
Agent(subagent_type="${DOMAIN_CHALLENGER}", prompt="Challenge evidence only — does this issue actually exist in the code as described?
Read the referenced file at <file:line>. Max 2 tool calls.
Write full analysis to $IMPL_DIR/challenge-<id>-1a.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"verdict\":\"VALID\"|\"REJECT\",\"rationale\":\"<one sentence>\"}")
```

Parse JSON. **REJECT** → set `CHALLENGE_EVIDENCE="REJECT"`, skip Phase 1b and Phase 2; jump to results.jsonl write with `status="skipped"`, `resolution="challenge-rejected"`. **VALID** → set `CHALLENGE_EVIDENCE="VALID"`, proceed to 1b.

**1b — suggestion challenge**:

```text
Agent(subagent_type="${DOMAIN_CHALLENGER}", prompt="Evidence confirmed. Challenge the suggested fix only — is it the right approach?
Write full analysis to $IMPL_DIR/challenge-<id>-1b.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"verdict\":\"VALID\"|\"REJECT\",\"rationale\":\"<one sentence>\",\"alternative\":\"<brief alternative or null>\"}")
```

Parse JSON. **VALID** → `CHALLENGE_SUGGESTION="VALID"`, `RESOLUTION="as-suggested"`. **REJECT** → `CHALLENGE_SUGGESTION="REJECT"`, `RESOLUTION="self-resolved"`, retain `alternative` for Phase 2.

When `NO_CHALLENGE=true`: skip both 1a and 1b. Set `CHALLENGE_EVIDENCE="skipped"`, `CHALLENGE_SUGGESTION="skipped"`, `RESOLUTION="as-suggested"`.

Append to `$IMPL_DIR/challenge-log.jsonl` (one line per item):

```bash
echo "{\"id\":${item_id},\"evidence\":\"${CHALLENGE_EVIDENCE}\",\"suggestion\":\"${CHALLENGE_SUGGESTION}\",\"resolution\":\"${RESOLUTION}\"}" >> "$IMPL_DIR/challenge-log.jsonl"
```

### Phase 2: Implementation

Clean-state guard:

```bash
STASHED=false
if [ -n "$(git status --porcelain)" ]; then
    git stash push -m "resolve-pre-item-${item_id}" && STASHED=true  # timeout: 3000
fi
```

Build prompt from challenge outcome:

```bash
if [ "$CHALLENGE_SUGGESTION" = "REJECT" ]; then
    IMPL_PROMPT="Evidence confirmed but suggested fix rejected. Fix the underlying issue using best judgment. Original feedback: <full_comment_text>. Rejected approach: <suggestion_rationale>. Suggested alternative: <alternative>."
else
    IMPL_PROMPT="Apply this review feedback exactly as suggested. Feedback from @<author>: <full_comment_text>"
fi
```

Spawn implementation agent — file-handoff envelope:

```text
Agent(subagent_type="${IMPL_AGENT}", prompt="Effort level: ${ITEM_EFFORT}. ${IMPL_PROMPT}
$([ -n "$ITEM_CALLERS" ] && printf 'Blast-radius context — modules that call into the code you are changing; preserve their public contracts:\n%s' "$ITEM_CALLERS")
Write your findings (approach taken, files changed) to $IMPL_DIR/impl-<id>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"status\":\"done\"|\"skipped\",\"reason\":\"<if skipped, else null>\",\"files_changed\":N}")
```

Parse JSON envelope. Capture `FILES_CHANGED` and impl `STATUS`.

Pop stash before staging:

```bash
if [ "$STASHED" = "true" ]; then
    git stash pop || { echo "⚠ stash pop conflict for item ${item_id} — appending error to results.jsonl and continuing"; }  # timeout: 3000
    STASHED=false
fi

python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/stage_item_changes.py" "${item_id}"  # timeout: 5000
```

### Commit per `COMMIT_MODE`

| Mode | Action in dispatcher |
| --- | --- |
| `each` | `bin/commit_action_item.py` with templated message; capture SHA |
| `all` / `grouped` / `stage` | stage only; do NOT commit here; orchestrator handles followup |

For `each` — `commit_action_item.py --build` assembles the canonical per-item message (subject + `[resolve #<id>]` attribution block + co-author trailers); pass `--codex` only when `IMPL_AGENT = codex:codex-rescue`:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/commit_action_item.py" --build \
    --summary "<imperative short summary of the change>" \
    --item-id "${item_id}" \
    --author "<author>" \
    --pr "${PR_NUMBER}" \
    --comment "<full_comment_text>" \
    --challenge "evidence=${CHALLENGE_EVIDENCE} suggestion=${CHALLENGE_SUGGESTION} resolution=${RESOLUTION}" \
    $([ "${IMPL_AGENT}" = "codex:codex-rescue" ] && echo "--codex") \
    --files <files-changed-by-this-item>  # timeout: 10000

SHA=$(git rev-parse --short HEAD 2>/dev/null)
```

### Append to `results.jsonl`

ALWAYS write exactly one line per item, regardless of phase outcomes:

```bash
TASK_ID=$(jq -r --arg id "${item_id}" '.[$id] // "null"' "$RESOLVE_TASK_IDS_FILE")
echo "{\"id\":${item_id},\"task_id\":\"${TASK_ID}\",\"status\":\"${RESULT_STATUS}\",\"sha\":\"${SHA:-null}\",\"files_changed\":${FILES_CHANGED:-0},\"challenge_evidence\":\"${CHALLENGE_EVIDENCE}\",\"challenge_suggestion\":\"${CHALLENGE_SUGGESTION}\",\"resolution\":\"${RESOLUTION}\",\"summary\":\"<≤80 char one-liner>\"}" >> "$IMPL_DIR/results.jsonl"
```

`RESULT_STATUS` values:
- `"committed"` — Phase 2 done, commit created (mode `each`)
- `"staged"` — Phase 2 done, staged but not committed (modes `all`/`grouped`/`stage`)
- `"skipped"` — Phase 1a evidence REJECT, or Phase 2 returned `skipped`
- `"error"` — unexpected failure (subagent crash, stash conflict, etc.)

Progress trace: print `[$progress/$total] item #${item_id} — ${RESULT_STATUS}` to stdout for transcript visibility.

## After loop — return envelope

Compute aggregate counts:

```bash
TOTAL=$(wc -l < "$IMPL_DIR/results.jsonl")
COMMITTED=$(grep -c '"status":"committed"' "$IMPL_DIR/results.jsonl" 2>/dev/null || echo 0)
STAGED=$(grep -c '"status":"staged"' "$IMPL_DIR/results.jsonl" 2>/dev/null || echo 0)
SKIPPED=$(grep -c '"status":"skipped"' "$IMPL_DIR/results.jsonl" 2>/dev/null || echo 0)
ERRORS=$(grep -c '"status":"error"' "$IMPL_DIR/results.jsonl" 2>/dev/null || echo 0)
REJECTED=$(grep -c '"resolution":"challenge-rejected"' "$IMPL_DIR/results.jsonl" 2>/dev/null || echo 0)
SHA_LIST=$(grep -oE '"sha":"[a-f0-9]+"' "$IMPL_DIR/results.jsonl" | grep -oE '[a-f0-9]+' | tr '\n' ' ')
```

Determine `MODE_FOLLOWUP`:
- `COMMIT_MODE=each` → `"none"`
- `COMMIT_MODE=all` → `"all"`
- `COMMIT_MODE=grouped` → `"grouped"`
- `COMMIT_MODE=stage` → `"stage"`

**Return ONLY this compact JSON as your final message (nothing after it)** — orchestrator parses verbatim:

```json
{"status":"done","items":N,"committed":N,"staged":N,"skipped":N,"errors":N,"rejected":N,"mode_followup":"none|all|grouped|stage","results_file":"<IMPL_DIR>/results.jsonl","challenge_log_file":"<IMPL_DIR>/challenge-log.jsonl","sha_list":["abc1234","def5678"]}
```

Where `N` are integers (no quotes), `sha_list` is an array (empty when no commits), and `<IMPL_DIR>` is the literal expanded path.

## Failure handling

- **Subagent crash mid-item**: write `results.jsonl` line with `status="error"`, `reason="<short>"`; continue with next item.
- **`stage_item_changes.py` non-zero exit**: status `"error"`, reason includes stderr tail.
- **`commit_action_item.py` non-zero exit**: status `"error"`, reason includes stderr tail; leave changes staged (do not abort the loop).
- **All items error**: still return the envelope with `errors=N, committed=0`; orchestrator surfaces.

Never return without writing the envelope. Never return a non-JSON message. The orchestrator's first action post-spawn is to parse this envelope and validate `items == |SELECTED_ITEMS|`.
