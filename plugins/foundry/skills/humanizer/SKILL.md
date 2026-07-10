---
name: humanizer
description: 'Strip AI-writing tells from prose destined for humans — docs, PR/commit bodies, reports, release notes, blog posts, Slack/email drafts. Removes LLM-vocabulary clichés (delve, boasts, testament, underscore, robust, tapestry...), banned constructions (not just X but Y, rule-of-three triads, "-ing" superficial-analysis clauses, vague-attribution weasel words), and formatting tells (title-case headings, mechanical bolding, em-dash overuse, curly quotes, bare-bullet inline-header lists). TRIGGER when: user asks to humanize/polish/de-AI a piece of text or file; before finalizing a substantial human-facing prose artifact drafted as part of the current task (docs, PR/commit body, report, blog post, release notes, external message) — self-review pass, best-effort model-initiated, not a guaranteed intercept. SKIP when: output is a terse conversational chat reply, code, JSON/YAML/config, a machine-parsed agent envelope ("Return ONLY:"), or the target is an ultra-caveman-tier handover file (`.temp/`, inter-agent prose per `plugins/CLAUDE.md` compression tiers).'
argument-hint: "[text or file path to humanize] | check <file>"
allowed-tools: Read, Edit, Grep, Glob
model: haiku
---

<objective>

Detect and remove statistical AI-writing fingerprints from human-facing prose before it ships. Grounded in Wikipedia's crowd-sourced AI-detection corpus (`Wikipedia:Signs of AI writing`) — a maintained list of vocabulary, syntax, and formatting patterns that over-represent in LLM output vs human baseline. Apply as a final pass, not a rewrite-from-scratch: preserve meaning, facts, and structure; only excise the tells.

</objective>

<inputs>

- **text or file path to humanize**: optional. Inline text, or a file path (Markdown/plain text) to edit in place.
- **check `<file>`**: read-only mode — report findings without editing.
- No argument: humanize the draft already composed earlier in this turn (self-review pass) — only reachable when the model chooses to invoke this skill mid-task; there is no platform hook that guarantees a pre-send interception, so treat this path as best-effort, not a hard gate.

</inputs>

<workflow>

**Task hygiene**: call `TaskList` first; triage orphaned tasks. **Task tracking**: skip for single-pass humanize calls under 3 steps; use for multi-file batch runs.

## 1. Load the target text

- Inline text → work on it directly, no file I/O.
- File path → `Read` the file.
- No argument → treat the draft already composed earlier in this turn as the target.

## 2. Scan against the checklist

Walk the text once per category below; flag every hit before editing anything (report-first, matches `check` mode output).

**Vocabulary — cut or replace with plain equivalent:**

| Banned | Plain replacement |
| --- | --- |
| delve, boasts, testament, underscore(s), showcase, tapestry, intricate/intricacies, meticulous, robust, vibrant, pivotal, crucial, garner, foster(ing), align with, landscape, interplay, enduring, enhance | say the specific thing instead — drop the word, don't swap in another vague one |
| "stands as", "serves as", "marks a", "represents" (as copula dodge) | "is" / "was" |
| "Additionally,", "Moreover,", "It is important to note that" | delete, or state the fact directly |

**Syntax — flag and restructure:**

- Negative parallelism: "not just X, but Y" / "not X, but Y" / "not only X but also Y" / "X rather than Y" used as a crutch
- Rule-of-three triads used for false comprehensiveness ("fast, reliable, and scalable")
- "-ing" superficial-analysis tails: "highlighting...", "underscoring...", "contributing to..." tacked onto a claim with no source
- Vague attribution / weasel words: "industry reports", "observers", "experts argue", "some critics" with no named source
- Formulaic "Despite its [positives], X faces challenges..." conclusion pattern

**Formatting — flag and fix:**

- Title Case In Headings → sentence case
- Mechanical bolding of every instance of a repeated term
- Markdown overuse — bold/bullets/headers where a plain sentence reads fine; the single most common tell in PR bodies and reports
- Bare-bullet inline-header lists (`• **Header:** text`) where prose or a real table reads better
- Em dash overuse — chain of `—` clauses instead of periods/commas
- Curly ("smart") quotes/apostrophes mixed inconsistently with straight ones
- `---`/`***` thematic breaks before headings (Markdown artifact bleeding into prose)

## 3. Apply fixes

- `check` mode: stop here — report findings (category, location, quote, suggested fix), do not edit.
- Edit mode: apply the minimal edit per flagged instance using `Edit`. Preserve every fact, number, and citation — only the phrasing/formatting changes. Re-read the result once to confirm no fact was dropped in the rewrite.

## 4. Report

One line per category with hit count and net edits made (e.g. "vocabulary: 4 removed, syntax: 2 restructured, formatting: 1 fixed"). Zero hits → say so plainly, do not pad the report.

</workflow>

<notes>

- Source of the checklist: Wikipedia's `Wikipedia:Signs of AI writing` essay — a living document; the vocabulary list drifts as models change ("delve" was the 2023-24 tell, largely purged by 2025). Treat the table above as a snapshot, not gospel — if a word reads natural and specific in context, don't force a cut just because it once trended in AI output.
- This skill governs **artifacts** headed for human eyes, not conversational chat turns or ultra-caveman-tier handover files — see the SKIP list in `description:` for the exact destination-based cutoff.
- Never invent facts while trimming a vague-attribution sentence — either name the real source (if known from context) or cut the claim entirely. Don't launder a weasel-worded claim into a confident unsourced one.
- Dense co-occurrence (5+ flagged patterns in one passage) is the real signal — a single "robust" or one bolded term is not worth flagging in isolation; don't over-trigger on incidental matches.
- Commit messages: `rules/git-commit.md` structural rules are inviolable (subject ≤50 chars, `type(scope): detail`, no line-wrap, mandatory co-author trailers, self-contained no internal labels) — on a commit message, humanizer only touches word choice inside those constraints, never subject length, wrapping, or trailer lines.
- Checklist deliberately excludes Wikipedia-only categories (broken wikitext, DOI/ISBN citation format, AfC submission-statement framing, non-existent Wikipedia templates) — those don't apply outside Wikipedia; don't re-add them.

</notes>
