---
name: create
description: "Interactive outline co-creation for developer advocacy content — collects format, audience profile, story arc (Problem→Journey→Insight→Action), and voice/tone; detects out-of-scope requests (FAQs, comparison tables); surfaces conflicts between user brief and audience needs. Writes approved outline to .plans/content/<slug>-outline.md for foundry:creator to execute. Use when starting a blog post, Marp slide deck, social thread, talk abstract, or lightning talk."
argument-hint: "[topic]"
disable-model-invocation: true
allowed-tools: Write, TaskCreate, TaskUpdate, TaskList, AskUserQuestion, Agent
when_to_use: "Use when creating developer advocacy content — blog posts, Marp slides, social threads, talk abstracts, or lightning talk outlines."
effort: medium
---

<objective>

Story arc four-beat: Problem → Journey → Insight → Action.

NOT for: implementation, code gen, README writing (use `foundry:doc-scribe`), structured ref docs (FAQs, comparison tables — use `foundry:doc-scribe`).

</objective>

<inputs>

- **$ARGUMENTS**: optional — topic or goal, any form; one sentence enough. Format hints accepted ("a blog post about…", "talk abstract for…").

</inputs>

<workflow>

**Task hygiene**: Call `TaskList`; mark clearly-done tasks `completed`, orphaned tasks `deleted`, genuinely-continuing tasks `in_progress`.

**Task tracking**: TaskCreate all steps before any tool calls.

## Step 1 — Parse topic and out-of-scope detection

- If $ARGUMENTS provided: extract topic; note embedded format hint.
- If no $ARGUMENTS: AskUserQuestion — "What are you trying to write about, and for whom?" (free text). After receiving the answer, re-check against out-of-scope conditions: if answer describes FAQs, comparison tables, feature matrices, README content, or docstrings — stop. Respond: "This format doesn't fit a narrative arc — use `foundry:doc-scribe` for structured reference content." No further steps.
- Out-of-scope gate (when $ARGUMENTS provided): if brief describes FAQs, comparison tables, feature matrices, or ref docs — stop. Respond: "This format doesn't fit a narrative arc — use `foundry:doc-scribe` for structured reference content." No further steps.

## Step 2 — Format and audience (max 2 AskUserQuestion calls)

**Format question** (AskUserQuestion):
> What content format?
> a: blog post
> b: conference / meetup talk with Marp slide deck ★
> c: social thread (Twitter/LinkedIn)
> d: talk abstract (CFP submission)
> e: lightning talk (5–10 min)

After answer: restate one sentence ("Got it — a [format] on [topic].").

**Audience question** (AskUserQuestion):
> Who is the audience?
> a: beginners — new to problem space ★
> b: intermediate — familiar with basics, seeking depth
> c: expert — know landscape, want novel insight
> d: describe your own profile

After answer: restate one sentence, note implied audience needs.

## Step 3 — Arc construction and conflict check

Propose four-beat arc from topic + audience:

- **Problem**: concrete opening hook — specific pain or question, not generic
- **Journey**: 3–5 key points (what tried, what failed, what arc covers)
- **Insight**: core "aha" framed for stated audience level — name directly
- **Action**: specific next step for audience

**Editorial conflict check**: if brief implies expert audience but topic introductory, or vice versa — surface before continuing:
> "Your brief suggests [X] but audience profile is [Y] — recommend adjusting [Z]. Proceed as-is or adjust?"

**Arc approval** (AskUserQuestion):
> Show proposed arc. Ask: approve as-is, or which beat needs adjustment? (free text or "approve")

After approval: restate confirmed arc two sentences.

## Step 4 — Voice and tone (1 AskUserQuestion)

**Voice question** (AskUserQuestion):
> What voice/tone?
> a: neutral developer advocate — balanced, educational ★
> b: opinionated / direct first-person — no hedging
> c: conversational / approachable — informal, relatable
> d: provide your own style brief

Never apply default silently. Always ask.

## Step 5 — Write outline file

- Derive slug from topic: kebab-case, max 5 words (e.g. `tracing-python-services-otel`).
- Write creates `.plans/content/` if absent — no separate mkdir needed.
- Write `.plans/content/<slug>-outline.md` with this structure:

```md
---
topic: <topic from brief>
created: YYYY-MM-DD
---

## Audience
[who they are, experience level, what they've likely seen, what they need]

## Format
[blog post | conference talk (N min) | social thread (twitter|linkedin) | talk abstract | lightning talk (N min)]

## Voice
[tone brief: e.g., "direct and opinionated, first-person, no hedging"]

## Arc

### Problem
[concrete opening hook — the pain or question]

### Journey
[key points to explore: what was tried, what failed, what the arc covers]

### Insight
[the core "aha" — what was learned or built; name it directly]

### Action
[call to action — specific, what audience should do next]

## Constraints
[length target, things to avoid, format-specific constraints]
```

- Confirm file path to user.
- Derive the artifact extension `<ext>` from the format selected in Step 2 — substitute the literal value into the spawn prompt before invoking `Agent()`; do not pass the literal `<ext>` placeholder. Mapping:

  | Format (Step 2 choice) | `<ext>` |
  | --- | --- |
  | a) blog post | `md` |
  | b) conference / meetup talk with Marp slide deck | `md` (Marp markdown) |
  | c) social thread (Twitter/LinkedIn) | `md` |
  | d) talk abstract (CFP submission) | `md` |
  | e) lightning talk | `md` |

  Every supported format currently renders to a markdown source file, so `<ext>` resolves to `md` in every branch — but the substitution must still happen explicitly so the artifact path on disk is `.plans/content/<slug>.md`, not `.plans/content/<slug>.<ext>`. If a future format uses a different extension, extend the table.

- End with an `AskUserQuestion` gate with two options:
  (a) **Generate the full artifact now** — spawn `foundry:creator` via `Agent(subagent_type='foundry:creator', prompt='Read .plans/content/<slug>-outline.md and generate the complete <format> artifact. Output file path: .plans/content/<slug>.<ext>')` where `<slug>`, `<format>`, and `<ext>` are substituted from the generated outline (see extension table above) before the call — never pass literal angle-bracket placeholders to the spawned agent.
  (b) **Stop here** — I'll invoke `foundry:creator` manually when ready.

  If the user selects (a), issue the Agent() call in the same response turn. Do not narrate intent — call the tool.
- End with `## Confidence` block per quality-gates.md protocol, score based on outline coverage of topic, arc, audience.

</workflow>

<notes>

- 5 questions in baseline flow; up to 7 with arc-conflict resolution (steps 2–4 use exactly 4; step 1 adds one only when $ARGUMENTS absent; arc conflicts in step 3 may add 1–2 more).
- Each AskUserQuestion uses lettered options with one ★ recommended default.
- After each answer, restate understanding 1–2 sentences before proceeding.
- Never silently adjust arc to match audience — always surface conflicts explicitly (Step 3).
- Refuse FAQs / comparison tables / ref docs at Step 1 gate; name `foundry:doc-scribe` as redirect.
- Write outline exactly once after approval — no second draft unless user requests.
- `foundry:creator` reads output outline file and generates full artifact autonomously.
- Outline spec files written to `.plans/content/` — see `artifact-lifecycle.md` for TTL policy (30d).

</notes>
