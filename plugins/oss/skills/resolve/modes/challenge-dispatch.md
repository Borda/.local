<!-- oss:resolve Step 3d — executed via: Read $_OSS_RESOLVE/modes/challenge-dispatch.md; execute -->
<!-- Input: $ACTION_ITEMS (JSON array from Step 3b), $RUN_DIR, $PR_NUMBER -->
<!-- Output: $CHALLENGE_VERDICTS variable set after completion -->

## Step 3d: Challenge action items

```bash
# --no-challenge flag: skip this step entirely
[[ "$ARGUMENTS" == *"--no-challenge"* ]] && {
    echo "⚠ --no-challenge: skipping Step 3d — all pending items treated as VALID"
    CHALLENGE_VERDICTS="[]"
    # proceed directly to Step 3e; all items keep their type unchanged
}
```

When `--no-challenge` NOT set:

Route each pending item by domain (default `foundry:challenger`); spawn one agent per group **in background**:

| Item domain | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases | `foundry:sw-engineer` |
| Test coverage, assertions, regressions | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

Write per-group output file before spawning each agent:

```bash
CHALLENGE_DIR="/tmp/resolve-challenge-$$"
mkdir -p "$CHALLENGE_DIR"  # timeout: 5000
CHALLENGE_CHECKPOINT="/tmp/resolve-check-$$"
touch "$CHALLENGE_CHECKPOINT"
LAUNCH_AT=$(date +%s)
NUM_GROUPS=0  # incremented once per spawned agent group below
```

Before spawning, write all pending action items to file via Write tool (file-handoff protocol — CLAUDE.md §2):

Write `$CHALLENGE_DIR/items.json` with all pending ACTION_ITEMS:
`{"items": [{"id": <id>, "summary": "<summary>", "file_line": "<file:line or —>", "author": "<author>", "full_comment_text": "<full text>"}]}`

Spawn each challenge group with `run_in_background=true`; write compact JSON to `$CHALLENGE_DIR/<group>.json`; increment `NUM_GROUPS` after each spawn:

```text
Agent(subagent_type="foundry:challenger", run_in_background=true, prompt="
Challenge each review comment for PR #<N>.
Read items from $CHALLENGE_DIR/items.json (JSON array under key 'items', each with id, summary, file_line, author, full_comment_text).
For each item: read referenced file at file_line if given; determine if comment is valid against actual code, or should be pushed back.
Be concise — max 2 tool calls per item.

Write ONLY compact JSON to $CHALLENGE_DIR/challenger.json using the Write tool:
{\"verdicts\": [{\"id\": <id>, \"verdict\": \"VALID\"|\"REJECT\", \"rationale\": \"<one sentence>\"}]}
Then return the same JSON as your final message.
")
```

(Repeat for `foundry:sw-engineer` → `$CHALLENGE_DIR/sw-engineer.json`, `foundry:qa-specialist` → `$CHALLENGE_DIR/qa-specialist.json`; `((NUM_GROUPS++))` after each `Agent(...)` call.)

**5-min health monitor** — poll every 90 s; hard cutoff 300 s:

```bash
# Tightened from CLAUDE.md §8: hard cutoff 15min→5min, poll 5min→90s (appropriate for short challenge tasks)
# Poll until all groups done or 5-min deadline reached
while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - LAUNCH_AT))
    DONE=$(find "$CHALLENGE_DIR" -name "*.json" ! -name "items.json" -newer "$CHALLENGE_CHECKPOINT" 2>/dev/null | wc -l | tr -d ' ')

    [ "$DONE" -ge "$NUM_GROUPS" ] && break   # all groups returned
    [ "$ELAPSED" -ge 300 ] && {
        echo "⏱ Challenge timeout at ${ELAPSED}s — marking remaining items VALID"
        break
    }
    sleep 90
done  # timeout: 360000
```

Aggregate verdicts — read each `$CHALLENGE_DIR/*.json` that exists:

- File present → use verdicts
- File absent (agent timed out) → mark group items `VALID`, rationale `"challenge timed out — treated as VALID"`

```bash
rm -rf "$CHALLENGE_DIR" && rm -f "$CHALLENGE_CHECKPOINT"  # cleanup  # timeout: 5000
```

Per verdict:
- **VALID** → keep item unchanged
- **REJECT** → set type `[challenged:reject]`; store rationale; exclude from SELECTED_ITEMS

Print challenge summary:

```markdown
### Challenge Results — PR #<number>

| # | Type | Author | Verdict | Rationale |
|---|------|--------|---------|-----------|
| 1 | [gh][req] | @reviewer | VALID | — |
| 2 | [gh][suggest] | @maintainer | REJECT | already addressed in commit abc123 |
```

`[challenged:reject]` items appear in final report (Step 11) with `⊘ rejected` status and rationale — maintainer communicates back to reviewer.
