---
description: Output quality standards — Confidence block, link verification, output routing
paths:
  - '**'
---

## Confidence Block (required on all analysis tasks)

<!-- policy-sibling: plugins/cc_oss/rules/quality-gates.md, plugins/cc_foundry/rules/quality-gates.md, plugins/cc_research/rules/quality-gates.md -->

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

- Omit **Refinements** if 0 passes — omit **Gaps** bullets if none, keep **Gaps** header
- **Score**, **Gaps**, **Refinements** = peer top-level fields — never nest Refinements under Gaps; blank line before **Refinements** required
- Score < 0.85 → ⚠ on score line AND next line: "orchestrator may re-run with the specific gap addressed"
- Gaps = primary signal — surface implicit limitations for re-run decisions

## Internal Quality Loop (analysis tasks only)

Before return, self-review:

1. Draft → self-evaluate (missed issues, unsupported claims, coverage gaps) → score
2. Score < 0.9: name highest-impact gap concretely, address what possible — even info-access limits: document + add inferences/caveats; re-score; cap 2 passes
3. Score rise only when **named, specific gap** addressed — generic phrases ("re-checked, looks fine", "reviewed for completeness") not count; pass must name gap (e.g. "Added versioning section missing from initial draft")
4. After 2 passes, report real score — never inflate

## Pre-Handover Check

Confidence < 0.9 and `bridge@borda-ai-rig` available → render and call `Skill(skill="bridge:review", args="Read-only adversarial review of <exact area and target paths>. Uncertain claims: <complete claim list>. Current evidence: <source paths or observations>. Challenge each claim, identify missing evidence and alternatives, and return actionable findings with locations; do not apply fixes.")`; never pass the placeholders or a workflow step label. Incorporate findings before handover. If the bridge is absent or disabled → state the gap and score explicitly so the user can re-run.

## Link Verification

**Never add URL without all three steps:**

1. **Fetch** — call WebFetch (or equivalent); URL must return non-error (not 4xx/5xx)

2. **Read** — read actual page content; not rely on URL structure or HTTP status alone

3. **Match** — confirm content match intended description; no match = no link

4. **Independent** — every URL need own Fetch+Read+Match pass; verified URL on same domain not exempt others; skip any step = violation

- Applies to: agent files, skill files, CLAUDE.md, any markdown

## Output Routing

- **Long output** (multi-item analysis, 5+ findings — including lists of 5+ items: module names, issues, files —, or prose >~10 lines) → two mandatory steps in order:

1. Call **Write tool** to create `.temp/output-<slug>-<branch>-<YYYY-MM-DD>.md` where `<branch>` is `$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')` (new file — never overwrite; append counter suffix if slug exists, e.g. `-2.md`); file gets **full content**
2. Print to terminal in this order:
   1. **YAML header table** — render `---` metadata block from top of report file as simple two-column Markdown table (`Field | Value`, one row per key, each value single physical line ≤100 chars — never wrap a value inside a cell: wrapped continuation line loses leading `|`, breaks GFM table parsing from that row down) — never print raw YAML verbatim (see **Report File Format** below); if skill has no YAML block in file, fall back to plain ASCII verdict line with `·` separator: `verdict: ⚠ NEEDS_WORK · findings: 8 · ...` (verdict word prefixed with its symbol — see §Reporting Findings)
   2. **Report path** — `→ <filepath>`
   3. **Executive summary** — prose: 2–3 sentence overview + each critical/high finding listed individual; omit medium/low detail unless ≤2 total findings
   4. **Follow-up gate** — invoke `AskUserQuestion` as final step; skip when background agent or inside other skill pipeline

- **Short inline status** (single result, pass/fail, one-sentence finding) → terminal only; **no** file
- Prose paragraphs: no hard line breaks at column width
- **Follow-up gate options**: skill-defined; minimum: (a) primary action · (b) skip. Canonical examples by skill:
  - `develop:review` → (a) `/develop:fix` · (b) `/develop:refactor` · (c) walk through findings · (d) skip
  - `develop:debug` → (a) `/develop:fix --diagnosis <file>` · (b) skip
  - `develop:plan` → (a) `/develop:feature --plan <file>` · (b) `/develop:fix --plan <file>` · (c) skip
- **Follow-up gate follow-through**: `AskUserQuestion` return with skill-invocation option selected → call `Skill(skill=..., args=...)` same response turn; never narrate intent as prose and stop without act

## Report File Format

<!-- policy-sibling: plugins/cc_foundry/rules/quality-gates.md, plugins/cc_develop/rules/quality-gates.md, plugins/cc_research/rules/quality-gates.md, plugins/cc_oss/rules/quality-gates.md -->

Every report file from output routing must begin with YAML metadata block between `---` delimiter lines. Block = canonical meta summary — file keeps raw YAML (machine-parseable by downstream skills); when printed to terminal, convert to two-column table (`Field | Value`, one row per key) before executive summary — never raw YAML in terminal.

**Value cap — single line only**: each value ≤100 chars, one physical line, no wrap. Wrapped cell loses leading `|` on continuation line → parser drops table from that row down. Long detail (Focus, Summary) → short label in cell, full text in prose exec summary below.

**Required minimum fields** (all reports):

```yaml
---
Title:      [Skill] — [subject]
Date:       [YYYY-MM-DD]
Scope:      [what was analyzed — file paths, topic, PR#, run-id, etc.]
Focus:      [aspect examined — "quality audit" / "SOTA research" / "code review" / etc.]
Agents:     [agent names that contributed — comma-separated]
Outcome:    [verdict — ✓ APPROVED | ✓ READY | ⚠ NEEDS_ATTENTION | ✗ BLOCKED | etc.]
Confidence: [score] — [key gaps]
Next steps: [recommended follow-up skill invocation]
Path:       → .reports/<skill>/<timestamp>/<name>.md
---
```

_Outcome legend: `✓` = approved/ready/clean · `⚠` = needs-attention/needs-work · `✗` = blocked/rejected. Distinct from `!`, which is reserved for standalone alert blocks (`! BREAKING`) — see §Reporting Findings._

After required fields, add **skill-specific fields** for report type (e.g. Verdict, CI, Risk, Blockers for `develop:review`; Best method, Papers for `research:topic`; Methodology, Findings for `research:judge`). `develop:review` report template = canonical reference. Skills with dedicated output routing (audit, review, resolve, analyse, release) must include equivalent `---` block at top of report files.

## Reporting Findings

- **Report before fixing**: state every finding before any fix — never silent mutate
- **Per-fix narration**: before each file edit or tool call, state what change and why
- **! BREAKING format**: breaking finding = standalone block — never inline or buried in table row:

```text
! BREAKING — <one-line impact: what breaks and who is affected>
Fix: <concrete action to resolve>
```

- Severity markers: `!` = critical (standalone alert-block prefix only, e.g. `! BREAKING`) · `⚠` = warnings · `✓` = pass · hint = fix hint. Outcome/verdict tables use `✗` for blocked/rejected instead (§Report File Format) — `!` never appears as a table-cell symbol, only as the alert-block prefix
- Terminal colors: RED = critical · YELLOW = warnings · GREEN = pass · CYAN = fix hint
