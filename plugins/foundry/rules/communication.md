---
description: Response style, framing, and output routing rules
paths:
  - '**'
---

## Re: Anchor

Start every reply with bold anchor summarising request, then response as blockquote.

Example (actual template — copy structure, replace bracketed text):

```markdown
**Re: [one-sentence summary of what was asked]**

> [full response here]
```

Rules:

- Bold line: neutral factual gist of what user asked — not full restatement, no labels
- Response body in blockquote (`>`) — visually distinct from tool/hook output in terminal
- Never use table or pipe-delimited format for anchor line — pipe chars pollute copy-paste
- No exceptions to the anchor rule — a response beginning with any word other than `**Re:**` is non-compliant

## Blockquote Exceptions — Tables and Code Blocks

**Hard constraint**: tables and fenced code blocks must NEVER appear inside `>` lines.

`> | col |` renders as `▎ | col |` in terminal — pipe alignment destroyed. Same for ` ``` ` inside `>` — loses copy-paste fidelity.

Pattern: close `>` before table/code block, reopen after if prose continues. Never emit `> |` sequence.

## Reply Visibility

Bold anchor + blockquote body creates a clear visual boundary from surrounding tool call output and hook logs. No ANSI codes — Claude Code renders markdown, not escape sequences.

**Exemption — machine-parsed responses**: omit Re: anchor and blockquote when response prompt contains `Return ONLY:` or `compact JSON envelope` — output parsed by parent orchestrator. Either keyword alone is sufficient to trigger the exemption; both keywords present together also triggers it.

## Progress and Transparency

- Narrate at milestones; print `[→ what and why]` before significant Bash calls
- 5+ min silence warrants status note

## Execution Failure Signaling

When unable to execute or proceed with any part of a request (unsupported flag, `disable-model-invocation` block, parse error, missing prerequisite, permission denied, tool unavailable):

**Mandatory**: lead the response with a bold failure block — never bury the failure at the end, never silently skip it:

```
**! BLOCKED — [one-line reason]**
**! UNSUPPORTED — [what and why]**
**! MISSING — [what is needed]**
```

Rules:
- Color+! block is the FIRST content in the response — not a footnote, not a trailing note
- State: what was asked · what cannot proceed · what alternative is available (if any)
- Applies to partial failures too: if 3 of 4 sub-tasks fail, color-flag the 3 at top before reporting the 1 success
- Never use grey prose ("note: X was skipped") as a substitute — that's what gets missed

## Tone

- **Flag early**: surface risks and blockers before starting; propose alternatives upfront
- **Positive but critical**: lead with what is good, then call out issues clearly
- **Objective and direct**: no flattery, no filler — state what works and what doesn't

## Artifact Framing

- **Verbal summary as skeleton**: user verbal summary = output skeleton — mirror order, abstraction level, named examples verbatim; no added info user didn't mention; source material (README, code) fill explicit gaps only; preserve quotable phrases exact, no paraphrasing
- **Format-label register**: translate format label to implied register before writing:
  - *Slack message* — no headers, 2–4 short paragraphs, casual voice, inline links, one quotable block max
  - *PR description* — sections with headers, tables ok, technical register
  - *Executive summary* — bullets, outcome-first, no jargon
  - When format ambiguous, ask one question before writing.

## Interactive Questions

**Hard constraint — stop before writing any question.** Need user info → invoke `AskUserQuestion` tool immediately. Prose question + "note: should use tool" caveat = still violation. Two options only: answer without asking, or call tool. No plain-text question ever.

Labelled or annotated question (e.g. `[AskUserQuestion simulated] — What format?`) still plain text, still violates rule. Only actual tool invocation satisfies constraint.

Describing, simulating, or annotating a tool call in any form — parenthetical ("AskUserQuestion would be invoked here"), bracket notation (`[Invoking AskUserQuestion: ...]`), or intent narration ("I would ask...") — is plain text and a violation. Call the tool directly; emit no prose description of intent before or instead of the call.

Compliant example — this is the only valid form:
> Call `AskUserQuestion(questions=["What format is the data in? (JSON, CSV, XML)"])` — no prose question in the response body.

- Plain text questions easily missed, don't block execution, don't surface as distinct UI affordance
- Bracketed, annotated, or narrated tool calls are plain text and violate this constraint — examples of violations: `[AskUserQuestion: ...]`, `"I would ask..."`, `"AskUserQuestion would be invoked here"`, `(AskUserQuestion simulated)`
- Only an actual tool invocation (tool call block in the response) satisfies this constraint
- Applies to: ambiguous input, clarifying choices, scope decisions, continuation guards, any point where user input required before proceeding
- **Scope decisions count**: user asks "should I also X?" mid-task → scope decision requiring AskUserQuestion — not rhetorical; never silently resolve
- Applies globally — all skills, agents, model-generated questions without exception
- When `AskUserQuestion` not in skill's `allowed-tools`, add it before asking any question
- Max 4 questions per call; group related sub-questions into one option set rather than asking sequentially

## Long Reply File Dump

**Trigger**: reply >1 sentence OR contains MD formatting (headers `#`, bullets `-`/`*`, fenced code ` ``` `, tables `|`).

**Rule**: write full reply to `.temp/reply-<slug>-<YYYY-MM-DD>.md`; print path as first output line: `→ .temp/reply-<slug>-<YYYY-MM-DD>.md`.
- `<slug>` = 3–4 word kebab summary of reply subject
- Verbatim — no extra wrapping, no ANSI codes

**Exemptions**: machine-parsed responses; pure status/narration lines.

## Output Routing

Full rules (including anti-overwrite counter-suffix and branch-slug format) and breaking-findings format: see `quality-gates.md`.
