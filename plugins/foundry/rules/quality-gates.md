---
description: Output quality standards — Confidence block, link verification, output routing
paths:
  - '**'
---

## Evidence Grounding (universal)

**NEVER generate without grounding in evidence.**

Every claim, finding, URL, or stated fact — read source, run command, check file first. No hypothesis as fact. No URL unverified. No finding unread.

**No exemptions:** "obvious", "well-known", "session recall", or training knowledge are not evidence. Current disk state beats all of these every time.

**When evidence inaccessible** — state `unable to verify: [reason]` explicitly; never substitute training knowledge or inference for unread source.

## Confidence Block (required on all analysis tasks)

Every analysis agent **must** end with:

```markdown
## Confidence
**Score**: 0.N — [high ≥0.9 | moderate 0.85–0.9 | low <0.85 ⚠]
**Gaps**:
- [specific limitation]
                          ← blank line required; Refinements is a peer field, not a sub-bullet
**Refinements**: N passes.
- Pass 1: [what gap was addressed — must name the gap, not just say "re-checked"]
```

> **Never skip** — missing Confidence block = rule violation.

- Omit **Refinements** if 0 passes (don't write "0 passes") — omit individual **Gaps** bullets if none, but keep **Gaps** header
- **Score**, **Gaps**, **Refinements** = peer top-level fields — never nest Refinements under Gaps; blank line before **Refinements** required
- Score < 0.85 → ⚠ on score line AND on the line immediately after (standalone line, not a Gaps bullet): "orchestrator may re-run with the specific gap addressed"
- Gaps = primary signal — surfaces implicit limitations for re-run decisions

## Internal Quality Loop (analysis tasks only)

Before returning, self-review:

1. Draft → self-evaluate (missed issues, unsupported claims, coverage gaps) → score
2. Score < 0.9: name highest-impact gap concretely, address what you can — even info-access limits: document + add inferences/caveats; re-score; cap 2 passes
3. Score rises only when **named, specific gap** addressed — generic phrases ("re-checked, looks fine", "reviewed for completeness") don't count; pass must name gap (e.g. "Added versioning section missing from initial draft")
4. After 2 passes, report real score — never inflate; `foundry:calibrate` catches bias

## Pre-Handover Check

Confidence < 0.9 → push back on the analysis before handing over: ask for proof for each uncertain claim (read source code, read docs, trace through examples), re-examine assumptions, rethink conclusions from first principles. If `codex` plugin available → also spawn `Agent(subagent_type="codex:codex-rescue")` naming the low-confidence area for adversarial review — incorporate findings before handover. After re-examination (and codex review if available): if confidence still < 0.9 → state the specific gap explicitly so user can decide to re-run.

## Link Verification

**Never add URL without all three steps:**

1. **Fetch** — call WebFetch (or equivalent); URL must return non-error (not 4xx/5xx). HTTP 200 is necessary but not sufficient — steps 2 and 3 are still mandatory even when Fetch succeeds

2. **Read** — read actual page content; don't rely on URL structure or HTTP status alone

3. **Match** — confirm content matches intended description; no match = don't add link

4. **Independent** — every URL requires its own Fetch+Read+Match pass regardless of domain, protocol, or path similarity; no URL is ever exempt because another URL on any domain was already verified; skipping any step (including inferring validity from URL structure or HTTP status alone) is violation

- Applies to: agent files, skill files, CLAUDE.md, any markdown

## Output Routing

- **Long output** (multi-item analysis, 5+ findings — including lists of 5+ items: module names, issues, files —, or prose >~10 lines) → two mandatory steps in order:

1. Call **Write tool** to create `.temp/output-<slug>-<branch>-<YYYY-MM-DD>.md` where `<branch>` is `$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')` (new file — never overwrite; append counter suffix if slug exists, e.g. `-2.md`); file gets **full content** — **execute the Write tool call; do not narrate intent and proceed without calling it** — this Write step is never skipped; pipeline/background mode only exempts the AskUserQuestion gate (step 2.iv), not this Write step. This is a **distinct, additional Write call** — writing to any other path (e.g. a run-directory response file, a report file) does not satisfy this step. Two writes are expected: one to `.temp/output-*.md` (this step) and any other file writes for the task.
2. Print to terminal in this order:
   1. **YAML header block** — print the `---` metadata block verbatim from the top of the report file (see **Report File Format** below); if skill has no YAML block in file, fall back to plain ASCII verdict line using `·` as separator: `verdict: NEEDS_WORK · findings: 8 · ...`
   2. **Report path** — `→ <filepath>`
   3. **Executive summary** — prose: 2–3 sentence overview + each critical/high finding listed individually; omit medium/low detail unless ≤2 total findings
   4. **Follow-up gate** — invoke `AskUserQuestion` as final step; skip when: spawned via `Agent()` tool, running inside another skill's pipeline, or prompt explicitly states background/pipeline mode — when in doubt, invoke

- **Short inline status** (single result, pass/fail, one-sentence finding) → terminal only; do **not** create file
- **Copy-intent override**: when output will be pasted into external artifact (PR body, release notes, report to share) → write to file regardless of length; when output read in-context and acted on immediately (audit findings, calibration result, code review) → terminal only even if long
- Prose paragraphs: no hard line breaks at column width
- **Follow-up gate options**: skill-defined; minimum: (a) primary action · (b) skip. Canonical examples by skill:
  - `foundry:audit` → (a) `/foundry:setup` (sync clean config) · (b) fix all findings · (c) skip
  - `foundry:distill` → (a) `/foundry:manage create` (scaffold suggestion) · (b) edit existing · (c) skip
- **Follow-up gate follow-through**: when `AskUserQuestion` returns with skill-invocation option selected — call `Skill(skill=..., args=...)` same response turn; never narrate intent as prose ("Invoke that next.", "Will now run /skill") and stop without acting
- **Don't ask what you can't honor**: if selected option cannot trigger automatic action (e.g. skill has `disable-model-invocation: true`, or output is intermediate with a downstream AskUserQuestion coming anyway) — do NOT use AskUserQuestion for that option; print the suggestion as plain text instead so user can copy-paste it. Hollow question = worse UX than no question.

## Prose Compression — Output Files

Applies to all agents. Compression tier by destination:

Estimate file size: `$(( $(wc -c < file) / 4 ))` tokens. Over budget → drop LOW/Nitpick first; preserve CRITICAL and HIGH intact.

| Destination | Tier | Size limit | Rule |
| --- | --- | --- | --- |
| `.reports/` (human review) | normal caveman | ≤10K tokens (~500 lines) | Drop articles/filler/hedging; full sentences where clarity demands; fragments OK for terse findings |
| `.temp/` (consolidator handover) | ultra caveman | ≤10K tokens (~500 lines) | Fragments only; zero filler; shortest synonyms; ~30–40% token reduction; per file-handoff-protocol.md §Synthesis budget |

## Report File Format

Every report file created via output routing must begin with a YAML metadata block between `---` delimiter lines. This block is the canonical meta summary — printed verbatim to terminal before the executive summary, machine-parseable by downstream skills.

**Required minimum fields** (all reports):

```yaml
---
[Skill] — [subject]
Date:       [YYYY-MM-DD]
Scope:      [what was analyzed — file paths, topic, PR#, run-id, etc.]
Focus:      [aspect examined — "quality audit" / "SOTA research" / "code review" / etc.]
Agents:     [agent names that contributed — comma-separated]
Outcome:    [verdict — APPROVED | READY | NEEDS_ATTENTION | BLOCKED | etc.]
Confidence: [score] — [key gaps]
Next steps: [recommended follow-up skill invocation]
Path:       → .reports/<skill>/<timestamp>/<name>.md
---
```

After the required fields, add **skill-specific fields** relevant to the report type (e.g. Verdict, CI, Risk, Blockers for `develop:review`; Best method, Papers for `research:topic`; Methodology, Findings for `research:judge`). `develop:review` report template is the canonical reference. Skills with dedicated output routing (audit, review, resolve, analyse, release) must include an equivalent `---` block at the top of their report files.

## Reporting Findings

- **Report before fixing**: state every finding before any fix — never silently mutate
- **Per-fix narration**: before each file edit or tool call, state what changes and why
- **! BREAKING format**: breaking findings = standalone block — never inline or buried in table row:

```text
! BREAKING — <one-line impact: what breaks and who is affected>
Fix: <concrete action to resolve>
```

- Severity markers: `!` = critical · `⚠` = warnings · `✓` = pass · hint = fix hint
- **Block merge integrity**: after merging two blocks (combining e.g. `<antipatterns>` + `<quality_checks>` into one), diff combined output against both originals; every named rule (`##` heading or bold title) must survive; zero silent drops
- **Deferred work must appear in delivered artifact**: if any analysis, rubric definition, or implementation is deferred, approximated, or left incomplete, document it explicitly in the output file — "Phase 2 / requires X / not yet implemented" notes must appear in the artifact, not only in conversation
