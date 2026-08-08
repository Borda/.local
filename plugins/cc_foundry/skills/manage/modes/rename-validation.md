# Mode: Rename Occurrence Validation

<!-- file: rename-validation.md — consumers: manage/SKILL.md -->

Triggered after cross-reference propagation (Step 5, rename mode only). Scan for remaining occurrences using word-boundary matching to reduce noise from short or common names:

```bash
rg --fixed-strings -n '\b<old-name>\b' plugins/ .claude/ README.md docs/ 2>/dev/null \
  || grep -rn "\b<old-name>\b" plugins/ .claude/ README.md docs/ 2>/dev/null \
  | grep -v ".git/" | grep -v "__pycache__"  # timeout: 10000
```

Grep returns **zero hits**: report "✓ No remaining occurrences of `<old-name>` found." and proceed.

**Large hit set gate** — hits exceed 50: invoke `AskUserQuestion` before classifying: "Found N occurrences of `<old-name>` — this name may be too generic for safe automated classification. Proceed with classification or abort?" Options: (a) Proceed · (b) Abort. On abort: stop and report to user.

Hits within limit: read a 5-line context window (2 lines before + matched line + 2 lines after) for every hit using the Read tool, assign each hit a stable integer `id` (1…N). Then spawn a **`haiku`-model** `Agent` to classify in batches of ≤30 hits — pass `model="haiku"` explicitly. Before spawning, resolve the entity's canonical surface forms from the rename context: slash-command form (`` `/foundry:<old-name>` `` or `` `/<old-name>` ``), `subagent_type` value, file-path pattern (`.claude/agents/<old-name>.md`, `.claude/skills/<old-name>/`). Include these in the prompt as `<entity_context>`.

Haiku agent prompt (one spawn per batch of ≤30 hits):

```
Classify grep hits for a rename: `<old-name>` → `<new-name>` (type: <agent|skill|rule|hook>).
Canonical surface forms for this entity: <entity_context>

For each hit output exactly one JSON object per line (no prose):
{"id":<N>,"file":"...","line":<N>,"verdict":"genuine"|"false_positive"|"ambiguous","reason":"one sentence"}

Classification rules — word match alone is NOT sufficient; read context:
- genuine: matches a canonical surface form; clearly names this specific entity (slash-command, subagent_type, NOT-for/TRIGGER cross-ref, dispatch directive, README table row)
- false_positive: generic English word used differently, unrelated comment, example string, sentence where the word means something else entirely
- ambiguous: context too short, name too generic, or evidence conflicts

Hits:
--- HIT {id} ---
file: {file}
line: {line}
context:
  {line-2}: ...
  {line-1}: ...
> {line}:   <matched line>
  {line+1}: ...
  {line+2}: ...
```

**JSON parse fallback**: returned output contains malformed JSON or missing `id` fields → retry once with the parse error appended to the prompt. On second failure, mark all unresolved hits `"ambiguous"` and escalate to the user.

Collect all batch results. Classify each hit:

- **Genuine reference** → Apply Edit tool fix targeting the exact token at the classified line — do NOT use `replace_all: true` on the whole file; replace only the specific occurrence on that line.
- **False positive** → Skip; log haiku's reason.
- **Ambiguous** → Collect for user escalation.

After all haiku fixes applied and all user-resolved fixes applied, run one final grep to confirm:

```bash
rg --fixed-strings -n '\b<old-name>\b' plugins/ .claude/ README.md docs/ 2>/dev/null \
  || grep -rn "\b<old-name>\b" plugins/ .claude/ README.md docs/ 2>/dev/null \
  | grep -v ".git/" | grep -v "__pycache__"  # timeout: 10000
```

Remaining hits must exactly equal the documented false-positive set (by file+line). Any remaining hit not in the false-positive list is an unresolved genuine reference — loop through classification once more for those, or flag in Step 10 as requiring manual review.

Collect ambiguous hits and invoke `AskUserQuestion` — show file + 5-line context per hit, ask: "Is this a real reference to `<old-name>` that should be updated, or a false positive?" Batch max 4 per call; loop if more. Apply user-confirmed fixes before the final grep.
