---
description: Response style, framing, and output routing rules
paths:
  - '**'
---

## Re: Anchor

Start every reply with bold anchor summarising request, then response on next line.

Example (actual template — copy structure, replace bracketed text):

```markdown
**Re: [one-sentence summary of what was asked]**

[full response here]
```

Rules:

- Bold line: neutral factual gist of what user asked — not full restatement, no labels
- Blank line between bold summary and response
- Never use table or pipe-delimited format for anchor line — pipe chars pollute copy-paste
- No exceptions — apply to every response including short ones

## Reply Visibility

Terminal output mixes tool calls, hook output, and intermediate logging. To make the actual reply easy to find when scrolling:

**Anchor line**: bold magenta; **response body**: cyan:

```
\033[1;35m**Re: [one-sentence summary]**\033[0m

\033[0;36m[full response here]\033[0m
```

Anchor in magenta makes it visually distinct from tool output; body in cyan separates prose from tool/hook logging. Apply to every response. Reset (`\033[0m`) after anchor line and at end of response body.

**Exemption — machine-parsed responses**: skip ANSI wrapping when response prompt contains `Return ONLY:` or `compact JSON envelope` — output parsed by parent orchestrator, not displayed to user. ANSI codes in machine output corrupt JSON parsing.

Example:
```
\033[1;35m**Re: adding error handling to auth middleware**\033[0m

\033[0;36mHere's the fix: ...\033[0m
```

## Progress and Transparency

- Narrate at milestones; print `[→ what and why]` before significant Bash calls
- 5+ min silence warrants status note

## Execution Failure Signaling

When unable to execute or proceed with any part of a request (unsupported flag, `disable-model-invocation` block, parse error, missing prerequisite, permission denied, tool unavailable):

**Mandatory**: lead the response with a RED-colored block — never bury the failure at the end, never silently skip it:

```
\033[1;31m! BLOCKED — [one-line reason]\033[0m
\033[1;31m! UNSUPPORTED — [what and why]\033[0m
\033[1;31m! MISSING — [what is needed]\033[0m
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
- Applies to: ambiguous input, clarifying choices, scope decisions, continuation guards, any point where user input required before proceeding
- **Scope decisions count**: user asks "should I also X?" mid-task → scope decision requiring AskUserQuestion — not rhetorical; never silently resolve
- Applies globally — all skills, agents, model-generated questions without exception
- When `AskUserQuestion` not in skill's `allowed-tools`, add it before asking any question
- Max 4 questions per call; group related sub-questions into one option set rather than asking sequentially

## Output Routing

Full rules (including anti-overwrite counter-suffix and branch-slug format), breaking-findings format, and terminal colors: see `quality-gates.md`.
