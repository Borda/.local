---
description: Output quality standards — Confidence block, link verification, output routing
paths:
  - '**'
---

> §Evidence Grounding, §Python Code Complexity, §Output Routing, §Report File Format have worked detail (tier tables, citation tracing, per-limit rationale, exact bash/example snippets) in `_full/quality-gates.md`. Resolve + Read when that section's own trigger applies — not needed for routine work:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/quality-gates.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/cc_foundry/rules/_full/quality-gates.md"  # timeout: 5000
> ```

## Evidence Grounding (universal)

**Never generate without grounding in evidence** — every claim, finding, URL, or fact: read source, run command, check file first. No hypothesis as fact, no URL unverified, no finding unread. "Obvious"/"well-known"/session recall/training knowledge are **never** evidence — current disk state beats all of them. Evidence inaccessible → state `unable to verify: [reason]` explicitly, never substitute recall or inference.

**Design premises gate at entry, not delivery** — any assumption, hypothesis, constraint claim, or stated fact used as a pillar for a design/implementation decision (technical constraint, feasibility assumption, recalled fact, behavioral assumption) must be grounded in evidence read now, when it first enters the design — not caught post-delivery. "Where is this documented?" first — no answer = unverified = no design built on it. A false premise caught before the first line is written costs nothing; caught after layers of implementation it can make the whole design infeasible.

**Evidence tiers**: Tier 1 (official docs, source code read from disk, release notes, spec/RFC, this-session test output) — sufficient alone. Tier 2 (blog posts, tutorials, forums, training knowledge) — needs ≥3 genuinely independent sources (not citing each other / not sharing an origin) OR an experiment that empirically confirms or refutes it.

## Adversarial Pass (all generation)

While producing output — not only after — ask "what would make this wrong?". Code: trace the failure path, not just the happy path (off-by-one, stale API, the edge case real data actually hits). Claims: separate "verified" from "pattern-matched" — verify or hedge the latter explicitly.

## Confidence Block (required on all analysis tasks)

<!-- policy-sibling: plugins/cc_oss/rules/quality-gates.md, plugins/cc_develop/rules/quality-gates.md, plugins/cc_research/rules/quality-gates.md -->

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

- Omit **Refinements** if 0 passes (don't write "0 passes") — omit individual **Gaps** bullets if none, but keep the **Gaps** header
- **Score**, **Gaps**, **Refinements** = peer top-level fields — never nest Refinements under Gaps; blank line before **Refinements** required
- Score < 0.85 → ⚠ on the score line AND on the line immediately after (standalone, not a Gaps bullet): "orchestrator may re-run with the specific gap addressed"
- Gaps = primary signal — surfaces implicit limitations for re-run decisions

## Internal Quality Loop (analysis tasks only)

Before returning: draft → self-evaluate (missed issues, unsupported claims, coverage gaps) → score. Score < 0.9: name the highest-impact gap concretely, address what you can — even info-access limits: document + add inferences/caveats; re-score; cap 2 passes. Score rises only when a **named, specific gap** is addressed — generic phrases ("re-checked, looks fine", "reviewed for completeness") don't count; the pass must name the gap (e.g. "Added versioning section missing from initial draft"). After 2 passes, report the real score — never inflate; `foundry:calibrate` catches bias.

## Python Code Complexity (when writing or reviewing Python)

Before delivering any Python function or class: cyclomatic complexity ≤12, required (no-default) arguments ≤7, branches ≤12, statements ≤50, return points ≤6. Violation → refactor before delivering. `# noqa: PLR...` / `# noqa: C901` permitted only when refactoring is genuinely impossible (generated code, protocol-mandated signature) — always paired with an inline comment explaining why. Verify: `ruff check --select C901,PLR`.

## Pre-Handover Check

Confidence < 0.9 → push back on the analysis before handing over: ask for proof for each uncertain claim (read source code, read docs, trace through examples), re-examine assumptions, rethink conclusions from first principles. If `bridge@borda-ai-rig` is available, render and call `Skill(skill="bridge:review", args="Read-only adversarial review of <exact area and target paths>. Uncertain claims: <complete claim list>. Current evidence: <source paths or observations>. Challenge each claim, identify missing evidence and alternatives, and return actionable findings with locations; do not apply fixes.")`; never pass the placeholders or a workflow step label. Incorporate findings before handover. If the bridge is absent or disabled, state the specific gap explicitly so the user can decide to re-run.

## Write-Delegation Checklist (`bridge:implement`)

Before calling `bridge:implement`, construct a complete brief containing the exact finding, target paths, current evidence, permitted edits, required result, stop condition, and verification command. Clean the git tree first (`git status -sb` — a dirty tree blocks; it makes the diff impossible to isolate). After it returns, read the **full diff** yourself and run the actual proof command. Repeated fix rounds on the same issue (2+) → stop delegating and finish by hand. Commit only after your own diff read plus proof run; the bridge never commits.

## Link Verification

**Never add a URL without all three steps, every time — no exemption for domain/protocol/path similarity to an already-verified URL:**

1. **Fetch** — call WebFetch (or equivalent); URL must return non-error (not 4xx/5xx). HTTP 200 is necessary but not sufficient — steps 2 and 3 still mandatory
2. **Read** — read the actual page content; don't rely on URL structure or HTTP status alone
3. **Match** — confirm content matches the intended description; no match = don't add the link

Applies to: agent files, skill files, CLAUDE.md, any markdown.

## Output Routing

**Long output** (multi-item analysis, 5+ findings — including lists of 5+ items: module names, issues, files —, or prose >~10 lines) → two mandatory steps, in order:

1. **Write tool call** — create `.temp/output-<slug>-<branch>-<YYYY-MM-DD>.md` (new file — never overwrite; append a counter suffix if the slug exists, e.g. `-2.md`); full evidence coverage, ultra-caveman compressed (see §Prose Compression — "full" means no dropped findings, not verbose prose). **Execute the Write tool call; do not narrate intent and proceed without calling it** — never skipped; pipeline/background mode only exempts the follow-up gate (step 2.4), not this Write. Distinct from any other file write the task also does.
2. Print to terminal, in this order: (1) **YAML header table** — render the `---` metadata block as a two-column Markdown table (`Field | Value`, one row per key, each value on a single physical line ≤100 chars — a wrapped value loses its leading `|` and breaks GFM table parsing from that row down); never print raw YAML (see §Report File Format). No YAML block → fall back to a plain ASCII verdict line, `·` separator: `verdict: ⚠ NEEDS_WORK · findings: 8 · ...` (verdict word prefixed with its symbol — see §Reporting Findings). (2) **Report path** — `→ <filepath>`. (3) **Executive summary** — 2–3 sentence overview + every critical/high finding listed individually; omit medium/low detail unless ≤2 total findings. (4) **Follow-up gate** — invoke `AskUserQuestion` as the final step; skip only when: spawned via `Agent()`, running inside another skill's pipeline, or the prompt explicitly states background/pipeline mode — when in doubt, invoke.

- **Short inline status** (single result, pass/fail, one-sentence finding) → terminal only; do **not** create a file
- **Copy-intent override**: output destined for an external artifact (PR body, release notes, report to share) → write to file regardless of length; output read in-context and acted on immediately (audit findings, calibration result, code review) → terminal only even if long
- **Follow-up gate follow-through**: selected option triggers a skill → call `Skill(skill=..., args=...)` in the same turn; never narrate intent as prose ("Invoke that next.") and stop without acting
- **Don't ask what you can't honor**: selected option can't trigger automatic action (`disable-model-invocation: true`, or output is intermediate with a downstream AskUserQuestion coming anyway) → print the suggestion as plain text instead of asking a hollow question

## Prose Compression — Output Files

Applies to all agents; compression tier by destination. Cap is a **soft compression target, not a truncation trigger** — never drop evidence, findings, or CRITICAL/HIGH content to force a file under cap. Compress prose (articles, filler, hedging, verbose framing) first; still over cap after full compression → let it run over rather than lose substance. Structurally large artifacts (multi-agent aggregates, batch reports) legitimately exceed the target — that's a signal the content warrants its size. Only LOW/Nitpick-severity items are droppable for space; CRITICAL and HIGH always survive intact.

Size estimate: `$(( $(wc -c < file) / 4 ))` tokens.

- `.reports/` (human review) — **normal caveman**, ~10K tokens (~500 lines) target: drop articles/filler/hedging; full sentences where clarity demands; fragments OK for terse findings
- `.temp/` (consolidator handover) — **ultra caveman**, ~10K tokens (~500 lines) target: fragments only, zero filler, shortest synonyms, ~30–40% tighter than normal caveman; full evidence coverage still required — compress prose, not substance

## Report File Format

<!-- policy-sibling: plugins/cc_foundry/rules/quality-gates.md, plugins/cc_develop/rules/quality-gates.md, plugins/cc_research/rules/quality-gates.md, plugins/cc_oss/rules/quality-gates.md -->

**Universal terminal-print rule**: when a skill or agent writes a report file whose first non-whitespace line is `---` (YAML metadata block), that block MUST be rendered in the terminal as a **simple two-column Markdown table** (`Field | Value`, one row per YAML key, in file order) — never dumped as raw YAML — as the **first content of the reply**, before the report path, before the executive summary, before anything else. Applies to ALL skills and agents producing such reports, no per-skill restatement needed. The table IS the reply header; omit the `╔═╗` Re:Anchor box when leading with it (see `communication.md` exemption).

Every report file created via output routing begins with this YAML `---`-delimited block; it stays raw YAML on disk (machine-parseable by downstream skills) and is converted to the table only for the terminal print.

**Value length cap — single physical line only**: every field value ≤100 chars, one line, no embedded wrap. A value that soft-wraps at terminal width breaks into a continuation line with no leading `|` — the table parser reads that as prose and drops the table from that row down. Long detail (`Focus`, `Summary`) belongs in the prose executive summary below the table, not crammed into the cell.

**Required minimum fields** (all reports): `Title`, `Date`, `Scope`, `Focus`, `Agents`, `Outcome`, `Confidence`, `Next steps`, `Path`. Add skill-specific fields after (e.g. Verdict/CI/Risk/Blockers for `develop:review`). Skills with dedicated output routing (audit, review, resolve, analyse, release) must include an equivalent `---` block at the top of their report files.

_Outcome legend_: `✓` = approved/ready/clean · `⚠` = needs-attention/needs-work · `✗` = blocked/rejected. Distinct from `!`, reserved for standalone alert blocks (`! BREAKING`, `**! BLOCKED**`) — see §Reporting Findings.

## Reporting Findings

- **Report before fixing**: state every finding before any fix — never silently mutate
- **Per-fix narration**: before each file edit or tool call, state what changes and why
- **! BREAKING format**: breaking findings = standalone block — never inline or buried in a table row:

```text
! BREAKING — <one-line impact: what breaks and who is affected>
Fix: <concrete action to resolve>
```

- Severity markers: `!` = critical (standalone alert-block prefix only, e.g. `! BREAKING`) · `⚠` = warnings · `✓` = pass · hint = fix hint. Outcome/verdict tables use `✗` for blocked/rejected instead (§Report File Format) — `!` never appears as a table-cell symbol, only as the alert-block prefix
- **Block merge integrity**: after merging two blocks (combining e.g. `<antipatterns>` + `<quality_checks>` into one), diff the combined output against both originals; every named rule (`##` heading or bold title) must survive; zero silent drops
- **Deferred work must appear in the delivered artifact**: if any analysis, rubric definition, or implementation is deferred, approximated, or left incomplete, document it explicitly in the output file ("Phase 2 / requires X / not yet implemented") — not only in conversation
