---
description: Response style, framing, and output routing rules
paths:
  - '**'
---

## Re: Anchor

Start every reply with a Unicode box header containing a one-line summary, then response body, then a closing `▓` footer line.

Example (actual template — copy structure, replace bracketed text):

```
╔════════════════════════════════════════════════════════════╗
║  Re: [one-sentence summary of what was asked]              ║
╚════════════════════════════════════════════════════════════╝

[full response here]

▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
```

**Rules:**

- Box: 62 chars total — `╔` + 60 `═` + `╗`; bottom `╚` + 60 `═` + `╝`
- Summary line: `║` + two spaces + summary text + spaces to pad inner width to 60 + `║`
- Summary: neutral factual gist of what user asked — not full restatement, no labels
- Footer: exactly 62 `▓` chars — matches box width, signals end of reply
- Never use pipe chars in summary text — corrupts box borders
- No exceptions except the two Exemption blocks below (machine-parsed replies · quality-gates `---` report headers) — any other response not opening with `╔` is non-compliant
- Tables, code blocks, bold headers work normally in body — no per-line prefix conflicts

## Reply Visibility

Box `╔═╗`/`╚═╝` zone creates clear header boundary. `▓▓▓` footer creates clear end boundary. Together they visually frame the response against surrounding tool call output and hook logs. Unicode box-drawing only — no ANSI escape codes.

**Exemption — machine-parsed responses**: omit box header and footer when response prompt contains `Return ONLY:` or `compact JSON envelope` — output parsed by parent orchestrator. Either keyword alone is sufficient to trigger the exemption; both keywords present together also triggers it.

**Exemption — quality-gates report headers**: when the reply leads with a quality-gates `---` metadata block (a skill's Output Routing report header — the YAML between `---` delimiters printed verbatim from the report file, e.g. `/oss:review`, `/oss:resolve`, `/foundry:audit`, `/foundry:calibrate`), omit the `╔═╗` box header — that `---` block IS the reply header and the box would shadow it. Print the `---` block as the first line of the reply; keep the `▓` footer. Never emit both a box header and a `---` metadata block in the same reply.

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
- **Recommended option placement**: place recommended option **second** in the options list, not first and not last. First slot = most natural/neutral default; second = recommended; last = skip/abort.

## Output Routing

Full rules (including anti-overwrite counter-suffix and branch-slug format) and breaking-findings format: see `quality-gates.md`.
