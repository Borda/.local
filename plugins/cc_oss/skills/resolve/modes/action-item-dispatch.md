<!-- oss:resolve Step 8 — executed via: cat $_OSS_RESOLVE/modes/action-item-dispatch.md; execute -->
<!-- fragment — no <workflow> wrapper; executed inline by SKILL.md -->
<!-- Input: SELECTED_ITEMS (from Step 3e), COMMIT_MODE (from Step 3d), CODEX_AVAILABLE (from Step 1), $_OSS_RESOLVE, ARGUMENTS -->
<!-- Output: items implemented/staged/committed; CHALLENGE_LOG populated; CHANGE_SCOPE set for Step 9 -->

## Step 8: Implement action items

**Commit authorization — entire Step 8**: `COMMIT_MODE` from Step 3d governs all commits; never re-ask regardless of mode, item count, or sentinel state. Multiple resolve flows per session each honor own Step 3d choice.

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

**Concurrency guard — mutex + HEAD fingerprint** (Phase 2 holds worktrees open for the slowest specialist's whole runtime — minutes — so an external write to the branch, or a second resolve run, is far likelier to land mid-flight than under the old per-item design). The lock path is deterministic (recompute anytime from the git-common-dir + branch); the base SHA is a point-in-time value, so persist it to a tmpfile — shell vars don't survive between Step 8's separate bash calls:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_GITDIR=$(git rev-parse --git-common-dir 2>/dev/null || echo ".git")  # timeout: 3000
_BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo "detached")  # timeout: 3000
RESOLVE_LOCK="$_GITDIR/oss-resolve-${_BRANCH}.lock"  # shared across worktrees (git-common-dir)
if [ -f "$RESOLVE_LOCK" ]; then
    if [ -n "$(find "$RESOLVE_LOCK" -mmin +30 2>/dev/null)" ]; then
        echo "⚠ stale resolve lock (>30 min) — prior run almost certainly dead; overriding: $RESOLVE_LOCK"
        rm -f "$RESOLVE_LOCK"
    else
        echo "⛔ another oss:resolve is active on branch '$_BRANCH' (lock: $RESOLVE_LOCK) — aborting."
        echo "  Wait for it to finish, or remove the lock if you know that run died."
        exit 1
    fi
fi
echo "$$ $(date -u +%FT%TZ)" > "$RESOLVE_LOCK"  # timeout: 3000
git rev-parse HEAD > "${TMPDIR:-/tmp}/resolve-base-sha-${CSID}" 2>/dev/null || true  # HEAD fingerprint  # timeout: 3000
```

The lock is released in Phase 3's cleanup block (and the 30-min staleness override reclaims it if a run crashes before then).

`change` → `IMPL_AGENT` routing table — drives Phase 2 specialist grouping **unconditionally** (not gated behind `CODEX_AVAILABLE`; Codex only ever handles items via the C1 medium-effort shortcut below, never as a Phase 2 specialist group). Keep in sync with `_shared/review-section-taxonomy.md`'s resolve `change` column:

| `change` value | `IMPL_AGENT` |
| --- | --- |
| `code` · `refactor` · `config` · `ci` | `foundry:sw-engineer` |
| `test` | `foundry:qa-specialist` |
| `docs` | `foundry:doc-scribe` |
| `style` | `foundry:linting-expert` |
| `perf` | `foundry:perf-optimizer` |
| `architecture` | `foundry:solution-architect` |

`CODEX_AVAILABLE=false`: C1 (medium-effort Codex shortcut, below) is skipped entirely — medium-effort items fall through to Phase 1+2 like any other item, routed by this same table. `xhigh`-effort, multi-file items still skip, unchanged from before (`⚠ codex not found — skipping item #<id> (xhigh effort). Install: /plugin marketplace add openai/codex-plugin-cc`) — too much surface for a single specialist without Codex's broader context; never blanket-skip anything below `xhigh`.

`--agent <name>` overrides this routing table unconditionally — every Phase 2 group uses `<name>` regardless of `change`.

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

**Parallel specialist-worktree dispatch** (replaces sequential/one-item-at-a-time execution — real wall-clock lever, not just spawn-count reduction): C1 Codex-first routing (below) still runs first, sequentially, per item — fast individual calls, no batching benefit to chase there. Everything falling through C1 splits into three passes: **Phase 1** challenge (read-only, parallel by domain), **Phase 2** implementation (one isolated `git worktree` per specialist, parallel), **Phase 3** merge-back (sequential, orchestrator-owned cherry-pick in original priority order). See Phase 1/2/3 below.

**Per action item** — loop over `SELECTED_ITEMS` in priority order. Per item, read full details from `$IMPL_DIR/action-items.jsonl` (written by Step 3b pr-intelligence subagent) — this is the authoritative source for `full_comment_text`, `file`, `line`, `change`, `severity`, `author`:

```bash
ITEM_DATA=$(jq -c ". | select(.id == <id>)" "$IMPL_DIR/action-items.jsonl")  # timeout: 5000
```

Use `.full_comment_text` for `IMPL_PROMPT`, `.file`/`.line` for commit scope and blast-radius lookup, `.change`/`.severity` for effort classification and agent routing.

**Pre-loop blast-radius scan** — run once in main orchestrator before loop starts; collect caller context per item so each impl subagent knows which contracts to preserve. Soft: missing `scan-query` is a no-op.

Each module's `rdeps` answer served from **review pre-flight cache** first (materialized in SKILL.md Step 8; contract in `$_DEV_SHARED/codemap-context.md` §Review→resolve pre-flight cache). `codemap_cache.py read` returns `{"reuse":true,...}` only when cached answer fresh against current index (matching `git_sha`, `scanned_at` not older); cache hit skips `scan-query` process entirely, so resolve after `/review` issues 0 duplicate pre-flight queries. Cache miss (`reuse:false`, no artifact, or oss helper absent) → query live, unchanged. Reused hits marked in artifact `delta.notes` so `codemap_cache.py report` can compute `reuse_ratio` as health metric.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# pre-loop; BLAST_RADIUS_CONTEXT shared with impl agents
BLAST_RADIUS_CONTEXT=""
IFS= read -r CODEMAP_CACHE_DIR < "${TMPDIR:-/tmp}/resolve-codemap-cache-dir-${CSID}" 2>/dev/null || CODEMAP_CACHE_DIR=""  # timeout: 3000
_IDX_FILE="${CODEMAP_INDEX_DIR:-.cache/codemap}/$(git rev-parse --show-toplevel 2>/dev/null | xargs basename | tr -cd 'a-zA-Z0-9._-').json"
_CACHE_BIN="${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/codemap_cache.py"
if command -v scan-query >/dev/null 2>&1 && [ -f "$IMPL_DIR/action-items.jsonl" ]; then
    echo "→ Codemap pre-scan — caller context for selected action items:"
    for _id in $SELECTED_ITEMS; do
        _f=$(jq -r "select(.id == $_id) | .file // empty" "$IMPL_DIR/action-items.jsonl")  # timeout: 5000
        [[ "$_f" == *.py ]] || continue
        _m=$(echo "$_f" | sed -E 's|^src/||; s|/|.|g; s|\.py$||')
        _c=""
        # cache-first: reuse review's rdeps answer when fresh; only query on miss
        if [ -n "$CODEMAP_CACHE_DIR" ] && [ -f "$_CACHE_BIN" ] && [ -f "$_IDX_FILE" ]; then
            _V=$(python "$_CACHE_BIN" read --module "$_m" --index "$_IDX_FILE" --cache-dir "$CODEMAP_CACHE_DIR" 2>/dev/null)  # timeout: 5000
            if echo "$_V" | grep -q '"reuse": *true'; then
                _c=$(echo "$_V" | python -c "import json,sys; a=json.load(sys.stdin)['answers'].get('rdeps',{}); print('\n'.join((a.get('imported_by') or a.get('importers') or [])[:20]))" 2>/dev/null)
                _ART="$CODEMAP_CACHE_DIR/${_m}.json"
                [ -f "$_ART" ] && python -c "import json,sys; p='$_ART'; d=json.load(open(p)); d['delta']['notes'].append('reused@'+__import__('datetime').datetime.utcnow().isoformat()); json.dump(d,open(p,'w'))" 2>/dev/null || true
                echo "  #${_id} ${_m} ← callers (cached, reused): $(echo "$_c" | tr '\n' ' ')"
            fi
        fi
        [ -z "$_c" ] && _c=$(scan-query rdeps "$_m" 2>/dev/null | head -20)  # timeout: 10000
        if [ -n "$_c" ]; then
            printf "  #%s %s ← callers: %s\n" "$_id" "$_m" "$(echo "$_c" | tr '\n' ' ')"
            BLAST_RADIUS_CONTEXT+="item #${_id} (${_m}) callers:"$'\n'"${_c}"$'\n\n'
        fi
    done
    [ -z "$BLAST_RADIUS_CONTEXT" ] && echo "  (no Python callers found for selected items)"
    # health metric — reuse_ratio over the materialized cache
    [ -n "$CODEMAP_CACHE_DIR" ] && [ -f "$_CACHE_BIN" ] && python "$_CACHE_BIN" report --cache-dir "$CODEMAP_CACHE_DIR" 2>/dev/null || true  # timeout: 5000
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

### Phase 1: Challenge — parallel by domain (skip when `--no-challenge`)

Route by domain to foreground challenge agent:

| Item domain | Challenger |
| --- | --- |
| Architecture, API design, coupling | `foundry:challenger` |
| Code logic, correctness, edge cases | `foundry:sw-engineer` |
| Test coverage, assertions, regressions | `foundry:qa-specialist` |
| Default / unclassified | `foundry:challenger` |

Set `DOMAIN_CHALLENGER` from routing table: architecture/API/coupling/default → `foundry:challenger`; code logic/correctness/edge-cases → `foundry:sw-engineer`; test coverage/assertions/regressions → `foundry:qa-specialist`. Use agent-resolution.md fallback if foundry absent.

Group items by `DOMAIN_CHALLENGER`, preserving each item's original priority-order position within its group (stable partition — needed later so Phase 3's merge plan also respects each specialist's internal commit order). One combined challenge call per domain group, covering ALL that group's items:

```text
Agent(subagent_type="${DOMAIN_CHALLENGER}", prompt="Two-part challenge for these review items.
Part 1 — for each, does the stated problem actually exist in the code as described?
Part 2 — if problem exists, is the suggested fix the right approach?
Read each referenced file at <file:line>. Max 3 tool calls per item.
Items:
<id>: <full_comment_text> (<file>:<line>)
...
Write full analysis to $IMPL_DIR/challenge-domain-<domain>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"items\":[{\"id\":N,\"evidence\":\"VALID\"|\"REJECT\",\"evidence_rationale\":\"<one sentence>\",\"suggestion\":\"VALID\"|\"REJECT\",\"suggestion_rationale\":\"<one sentence>\",\"alternative\":\"<brief alternative or null>\"}]}")
```

**Fire every domain group's `Agent()` call in the same response turn** — read-only (no working-tree writes), safe to run concurrently regardless of file overlap between domains.

**Structural prep — fire in this same turn, concurrently with the challenge agents** (the codemap queries below are read-only and depend only on item *files*, known from Step 3b — not on any challenge verdict — so they run under the challenge agents' latency shadow, adding ~0 wall-clock; grouping in Phase 2 then finds its maps already warm). Keyed off all `SELECTED_ITEMS` (not yet-unknown `SURVIVING_ITEMS`) — a few queries for items challenge later drops are cheap and hidden under the agent latency; Phase 2 filters to survivors. Resolve each file to its canonical module name + build the whole-repo centrality map (`resolve_centrality.py`), then capture each module's **forward imports** (`deps`, fan-*out*, naturally small — never the 20-cap that truncates reverse `rdeps`):

```bash
CODEMAP_MAPS="$IMPL_DIR/codemap-maps.json"; : > "$CODEMAP_MAPS"
DEPS_MAP="$IMPL_DIR/codemap-deps.jsonl"; : > "$DEPS_MAP"
if command -v scan-query >/dev/null 2>&1 && [ -f "$IMPL_DIR/action-items.jsonl" ]; then
    _FILES=$(for _id in $SELECTED_ITEMS; do
        jq -r "select(.id == $_id) | .file // empty" "$IMPL_DIR/action-items.jsonl"
    done | paste -sd, -)  # timeout: 5000
    scan-query central --top 100000 2>/dev/null \
        | python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/resolve_centrality.py" --files "$_FILES" > "$CODEMAP_MAPS" 2>/dev/null \
        || : > "$CODEMAP_MAPS"
    if [ -s "$CODEMAP_MAPS" ]; then
        for _m in $(python -c 'import json,sys; print(" ".join(sorted({v for v in json.load(open(sys.argv[1]))["file_module"].values() if v})))' "$CODEMAP_MAPS"); do
            scan-query deps "$_m" 2>/dev/null \
                | python -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({d["module"]: d.get("direct_imports", [])}))' >> "$DEPS_MAP"  # timeout: 5000
        done
    fi
fi
```

Parse each group's per-item verdict array — same granularity as a single-item challenge, never relaxed by grouping:
- `evidence=REJECT` → print `⊘ #<id> evidence rejected: <evidence_rationale>`; set type `[challenged:reject]`; append to `CHALLENGE_LOG`; drop from `SURVIVING_ITEMS`
- `evidence=VALID` + `suggestion=VALID` → `SUGGESTION_VERDICT[id]=VALID`; use original suggestion for implementation
- `evidence=VALID` + `suggestion=REJECT` → `SUGGESTION_VERDICT[id]=REJECT`; self-resolve using `alternative` as guidance

Append every item's verdict to `CHALLENGE_LOG`: `id=<id> evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>`. Items with `evidence=VALID` form `SURVIVING_ITEMS`.

### Phase 2: Implementation — parallel, one worktree per specialist

The codemap maps (`$IMPL_DIR/codemap-maps.json` — `file_module` + `centrality`; `$IMPL_DIR/codemap-deps.jsonl` — per-module `direct_imports`) were built in Phase 1's Structural prep, concurrently with the challenge agents, so both tiebreaks below read them with no fresh query. They cover all `SELECTED_ITEMS`; filter to survivors as needed.

Group `SURVIVING_ITEMS` by `IMPL_AGENT` (routing table at top of this file; `--agent` override applies to every group uniformly). Preserve original priority-order position within each group (stable partition, same reason as Phase 1).

**File-ownership tiebreak** (kills Phase 3 cherry-pick conflicts at the root, instead of only resolving them after the fact): before capping group size, check whether any `.file` is claimed by items in more than one group. Rank specialists least → most foundational/invasive — a change from a higher-ranked specialist is more likely to reshape the file, so lower-ranked items should defer to it rather than risk a conflicting concurrent edit:

`foundry:linting-expert < foundry:doc-scribe < foundry:qa-specialist < foundry:perf-optimizer < foundry:sw-engineer < foundry:solution-architect`

(`foundry:challenger` never appears here — Phase 1 only, read-only, holds no file ownership.) For each contested file, reassign **every** item touching it to the single highest-ranked group in the contest — the item's original `IMPL_AGENT` routing is overridden by ownership, not by its own `change` value. Print `→ #<id> reassigned <from> → <to> (file overlap: <path>)` per reassignment so it's auditable.

**Import-coupling merge** (soft — catches the *semantic* conflict the file-path tiebreak is blind to): file overlap only co-locates items editing the **same** file. Two items in **different** files still collide when one imports the other — item A renames a symbol in `pkg.auth`, item B edits `pkg.middleware` which imports it; both land, cherry-pick textually clean, code broken. Structural prep already captured the links: items A and B are **import-coupled** when one's module is in the other's `direct_imports` — B's module ∈ A's imports (or vice versa), reading `$IMPL_DIR/codemap-deps.jsonl` keyed by the module names in `codemap-maps.json`'s `file_module`. This uses forward `deps` (fan-out, bounded) rather than reverse `rdeps`, so recall is **not** truncated by the 20-caller display cap. After the file-overlap pass, for each import-coupled pair still split across two groups, reassign the lower-ranked item's group to the higher-ranked one (same specialist ranking above) so both land in one worktree and the specialist keeps them consistent. Print `→ #<id> reassigned <from> → <to> (import coupling: <mod> ↔ <mod>)`. This merge is **soft**, unlike file overlap: it yields to the 5-item cap below — if honoring it would push a group past 5, leave the pair split and rely on Phase 3's conflict fallback plus the blast-radius context already handed to each agent. Empty `codemap-deps.jsonl` (no scan-query / query failure) → no-op; file-overlap grouping stands.

Re-derive group membership after all reassignments (file overlap + import coupling), **then** cap 5 items/group — same context ceiling the old file-affinity batching used; a specialist with more than 5 items splits into `ceil(N/5)` groups, **keeping every file's items together in the same sub-group** (never split one file's items across two sub-groups — would reintroduce the exact conflict this tiebreak exists to prevent). Each resulting sub-group is one worktree with its own `group` tag (reused in Phase 3's merge plan).

Per group, mark its items' tasks in_progress, then dispatch with worktree isolation so concurrent specialists never race on a shared working tree (no stash dance needed — dirty state in one worktree can't collide with another):

```text
Agent(subagent_type="<specialist>", isolation="worktree", prompt="Effort level: <highest ITEM_EFFORT in group>.
Implement these action items one at a time. For each, apply the fix using best judgment
(if suggestion was rejected in challenge, fix the underlying issue instead — see rationale/alternative below),
then commit it individually before moving to the next item:
python \"${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/commit_action_item.py\" --build --summary \"<short summary>\" \\
    --item-id \"<id>\" --author \"<author>\" --pr \"<PR_NUMBER>\" --comment \"<full_comment_text>\" \\
    --challenge \"evidence=VALID suggestion=<VALID|REJECT> resolution=<as-suggested|self-resolved>\" \\
    --files <files-changed-by-this-item>
Items:
<id>: <IMPL_PROMPT for this item> — blast-radius callers: <ITEM_CALLERS for this item, if any>
...
Write findings (approach taken, files changed per item) to $IMPL_DIR/impl-worktree-<group_tag>.md using the Write tool.
Return ONLY compact JSON as your FINAL message (nothing after it):
{\"commits\":[{\"item_id\":N,\"sha\":\"<sha>\"}],\"skipped\":[{\"item_id\":N,\"reason\":\"<why no commit>\"}]}")
```

**Fire all specialist groups in the same response turn** — this is the actual wall-clock win: N specialists implementing and committing concurrently, each isolated in its own worktree/branch.

> **Health monitoring**: parallel foreground dispatch — same rule as any multi-agent fan-out (CLAUDE.md §6). No response from a group within ~15 min → surface partial results from the groups that did return; mark the stalled group ⏱, proceed to merge-back with whatever landed; its unresolved items stay `in_progress` and get reported alongside other pending work.

Parse each group's JSON: `commits` entries feed Phase 3's merge plan; `skipped` entries record `skipped — <reason>` (no empty commit, no cherry-pick attempt).

### Phase 3: Merge-back — sequential, orchestrator-owned

**HEAD fingerprint check** — the worktrees branched from `resolve-base-sha`; verify the PR branch hasn't moved under us while Phase 2 ran. A moved base means an external write (human push, or a run that slipped the mutex) landed during Phase 2 — cherry-picks still apply (they replay each diff onto the current tip), but overlapping edits now surface as conflicts, so surface the drift rather than stack silently:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
IFS= read -r _BASE_SHA < "${TMPDIR:-/tmp}/resolve-base-sha-${CSID}" 2>/dev/null || _BASE_SHA=""  # timeout: 3000
_NOW_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")  # timeout: 3000
if [ -n "$_BASE_SHA" ] && [ "$_NOW_SHA" != "$_BASE_SHA" ]; then
    echo "⚠ base HEAD moved during Phase 2: ${_BASE_SHA:0:8} → ${_NOW_SHA:0:8} (external write)."
    echo "  Cherry-picks apply onto the new base; any overlapping edit surfaces as a conflict → routed to Step 5a below."
fi
```

Build the cherry-pick plan in **original `SELECTED_ITEMS` priority order**, interleaved across specialist groups by item id — NOT grouped by specialist, so the base order matches severity ranking regardless of which group finished first. This global sort is safe because Phase 1/2 grouping preserved each specialist's internal relative order (stable partition) — sorting by original priority never reorders two items from the same specialist relative to each other. Each entry also carries its worktree `group` tag (from Phase 2) and its `module` — the **canonical codemap name** for the item's `.file`, read from `file_module` in `$IMPL_DIR/codemap-maps.json` (built in Structural prep), blank when unresolved. Never hand-derive it with a sed transform: codemap names a package `__init__.py` after the package (`pkg`, not `pkg.__init__`), so a sed guess silently mismatches the centrality keys and scores 0.

**Centrality ordering** (lands the most foundational change first, so contract-defining commits precede their dependents): the `{module: rdep_count}` centrality map was already built once in Structural prep (`$IMPL_DIR/codemap-maps.json`, from a single authoritative `scan-query central` pass — not the 20-capped `BLAST_RADIUS_CONTEXT`, which saturates). Extract it to a file so the merge step can reorder **whole worktree groups** most-central-first. Safe precisely because the file-ownership tiebreak guarantees distinct groups touch disjoint files — reordering whole chains can't add a textual conflict, and commit order **within** a chain is never touched (chains may build on themselves). Missing maps (no `scan-query` / query failure) → flag omitted, plan applies in priority order unchanged.

```bash
CENTRALITY_FILE=""
if [ -s "$IMPL_DIR/codemap-maps.json" ]; then
    CENTRALITY_FILE=$(mktemp)  # timeout: 3000
    python -c 'import json, sys; json.dump(json.load(open(sys.argv[1]))["centrality"], open(sys.argv[2], "w"))' \
        "$IMPL_DIR/codemap-maps.json" "$CENTRALITY_FILE"  # timeout: 5000
    [ -s "$CENTRALITY_FILE" ] || CENTRALITY_FILE=""
fi

python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/merge_specialist_batch.py" \
    --plan "$PLAN_FILE" --commit-mode "$COMMIT_MODE" \
    ${CENTRALITY_FILE:+--centrality-file "$CENTRALITY_FILE"}  # timeout: 30000
```

`PLAN_FILE` = JSON array of `{"item_id", "sha", "group", "module"}` in priority order (assembled from every Phase 2 group's `commits`). With `--centrality-file` the script reorders whole groups most-central-first (`order_plan`) before cherry-picking each in turn:

- **`COMMIT_MODE=each`** — commit lands as-is (own `[resolve #<id>]` attribution message, carried over from the worktree commit); no reset.
- **`COMMIT_MODE=grouped` / `all` / `stage`** — commit lands then is immediately soft-reset (`git reset --soft HEAD~1`), leaving the diff staged, uncommitted — same state the post-loop sections below already expect.

**Clean run** (`conflict: null`) → every item's commit is on the PR branch (or staged, per mode above).

**Conflict** → two specialists touched overlapping code; the script stops mid-cherry-pick on the reported item (`CHERRY_PICK_HEAD` present) and returns the still-unapplied `remaining` entries. Route to `conflict-resolution.md`'s task-creation pattern (Step 5a), substituting `CHERRY_PICK_HEAD` for `MERGE_HEAD` in the state check; after resolving, `git cherry-pick --continue`, then re-invoke `merge_specialist_batch.py` with only the `remaining` entries.

Mark item's task per `COMMIT_MODE`, right after its own cherry-pick lands — not when its specialist group returns (a group finishing early doesn't mean its items are safely on the PR branch yet):

```text
# each / stage → completed now (commit landed, or staged = terminal; no "staged" task status)
# all / grouped → leave in_progress; post-loop commit block below flips after the real commit
if COMMIT_MODE == "each" or COMMIT_MODE == "stage":
    TaskUpdate(task_id=<item.task_id>, status="completed")
```

No commit for an item (it was in Phase 2's `skipped` list) → record the agent's reason; do NOT create an empty commit or add it to `PLAN_FILE`.

Cleanup — remove each specialist worktree once all its commits are cherry-picked, then release the resolve mutex (recompute the deterministic lock path — the entry-block shell var is gone by this separate bash call):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
for _wt in "${SPECIALIST_WORKTREES[@]}"; do
    git worktree remove "$_wt" --force 2>/dev/null || true  # timeout: 5000
done
_GITDIR=$(git rev-parse --git-common-dir 2>/dev/null || echo ".git")  # timeout: 3000
_BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo "detached")  # timeout: 3000
rm -f "$_GITDIR/oss-resolve-${_BRANCH}.lock" "${TMPDIR:-/tmp}/resolve-base-sha-${CSID}"  # timeout: 3000
```

> If Phase 3 stops on a conflict (routed to Step 5a) the lock is **not** released here — intentional: the run is still live. It clears on the retry's cleanup, or via the 30-min staleness override if the session is abandoned.

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
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/commit_action_item.py" \
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
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/commit_all_items.py" "$PR_NUMBER" "$N_AS_SUGGESTED" "$N_SELF_RESOLVED" "$N_REJECTED" "$SUMMARIES_FILE" $( [ "${CODEX_AVAILABLE:-false}" = "true" ] && echo "--codex" )  # timeout: 10000
```

After the commit succeeds, flip all staged items to completed (deferred from per-item loop body where commit had not yet happened):

```text
for each item in SELECTED_ITEMS where status != "skipped":
    TaskUpdate(task_id=<item.task_id>, status="completed")
```

## Step 8 — design scope & residual limitations

Worktree isolation + the two grouping tiebreaks + centrality ordering *reduce* Phase 3 conflicts; they don't eliminate them. Phase 3's cherry-pick conflict path (Step 5a) is the catch-all for whatever slips through.

**Deliberate design choices (not limitations):**

- **Python-scoped semantic grouping** — codemap indexes `.py` (by design — the plugin's stated scope). Same-file *textual* conflict on `.yaml`/`.toml`/`.github/*.yml`/`.md` is still caught: the file-ownership tiebreak is path-based, not codemap-based, so it works for any language. Only the *semantic* layers (import-coupling, centrality) are Python-scoped; non-Python items simply skip them (no coupling merge, centrality 0 → ordered last). Config/CI PRs keep full textual safety.
- **Depth-1 coupling** — coupling merges only directly-importing pairs, not transitive A→B→C. Deliberate: every coupling-merge trades parallelism for conflict-safety; a direct import is a high break-risk (good trade), a transitive one is a rare break at the *same* parallelism cost (bad trade) — and a central module's transitive closure would collapse the whole batch into one group, defeating the parallelism the redesign exists for. Direct-only is the optimum, not a shortfall.
- **Import centrality, not call centrality** — ordering weight is module `rdep_count` (import graph), matching the module-granularity of the grouping. `fn-central` (call graph) is finer than the unit being ordered, so it wouldn't change whole-group order.

**Residual limitations (true gaps, all backstopped by Step 5a):**

- **Centrality ≠ semantic-break cure** — most-central-first ordering cuts conflict *cascade* and yields saner intermediate trees, but a dependent commit already contains its call to the old contract; landing order can't un-break it. The actual mitigation for semantic breakage is the per-agent blast-radius context (each specialist is told its callers); centrality is only ordering.
- **Stale index** — coupling + centrality read whatever codemap index exists. Currency is gated at skill entry (SKILL.md Gate B refreshes a stale index before Step 8), so mid-run staleness is the only exposure, and it only skews grouping slightly (all heuristic, never dangerous). `central` auto-build exceeding the 15 s budget → maps empty → plan falls back to priority order.
- **Mutex is advisory** — the branch lock stops a *second oss:resolve*, not a human `git push` or an unrelated tool writing the tree; that class is detected after the fact by the Phase 3 HEAD-fingerprint warning + Step 5a, not prevented.
