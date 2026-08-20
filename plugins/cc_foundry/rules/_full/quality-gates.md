---
description: Output quality standards — Confidence block, link verification, output routing
paths:
  - '**'
---

## Evidence Grounding

**Scope** — any of: technical constraints ("X cannot do Y", "not supported by", "requires workaround"), feasibility assumptions ("this approach will work because", "X is fast/reliable enough"), recalled facts from memory or training ("I know that X does Y", "typically Z", "this library usually"), behavioral assumptions ("this function returns", "this API expects", "this version changed").

**Evidence authority — not all sources are equal**

Tier 1 — Authoritative (sufficient alone): official documentation (versioned), source code read from disk, official release notes / changelogs, specification or RFC from governing body, test suite output from this session.

Tier 2 — Weak (requires ≥3 independent sources OR experimental validation): blog posts, tutorials, Stack Overflow, forum posts, social media, third-party summaries, training knowledge. When only Tier 2 available: find ≥3 genuinely independent corroborating sources, OR run a minimal experiment that empirically confirms or refutes the premise. Document which path was taken.

**Independence requirement**: sources are independent only when they derive from different authors and different primary research — not when they cite each other or all trace back to a common origin. N posts all referencing the same blog post = 1 source, not N. Count unique origin nodes, not surface-level citations.

**Citation tracing — mandatory before counting sources**:

1. For each Tier 2 source: follow its citations and references one level deep
2. Map each source to its origin: `source → cites → origin`
3. Singleton detection: if ≥2 sources share the same origin → merge into one; count distinct origins only
4. Tier upgrade: if tracing reveals a Tier 1 source (official doc, spec, changelog) that a Tier 2 source cited but wasn't found directly — read that Tier 1 source; if it confirms the claim, the premise is now Tier 1 verified (sufficient alone)
5. If after tracing, distinct-origin count < 3 and no Tier 1 found → require experimental validation

## Python Code Complexity

Full per-limit rationale (stub keeps the numbers + violation consequence):

- **Cyclomatic complexity ≤12** — more than 12 independent paths → extract sub-functions or introduce guard clauses
- **Required arguments (no default) ≤7** — primary rule, enforced in review; more than 7 required params = introduce a config dataclass; kwargs with defaults may exceed 7 freely; ruff `PLR0913` is set to ≤12 as a blunt total-args backstop
- **Branches ≤12** — more than 12 `if`/`elif`/`match` arms → dispatch table or strategy pattern
- **Statements ≤50** — more than 50 logical lines in one function → split responsibility
- **Return points ≤6** — more than 6 `return` statements → consolidate early-return paths

Applies to all Python written or reviewed by any agent.

## Output Routing

**Branch-slug expression** for the `.temp/output-*.md` filename: `<branch>` is `$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')`.

**Follow-up gate options** — skill-defined; minimum: (a) primary action · (b) skip. Canonical examples by skill:

- `foundry:audit` → (a) `/foundry:setup` (sync clean config) · (b) fix all findings · (c) skip
- `foundry:distill` → (a) `/foundry:manage create` (scaffold suggestion) · (b) edit existing · (c) skip

## Report File Format

<!-- policy-sibling: plugins/cc_foundry/rules/quality-gates.md (stub, canonical rule text + marker), plugins/cc_develop/rules/quality-gates.md, plugins/cc_research/rules/quality-gates.md, plugins/cc_oss/rules/quality-gates.md — this section is worked-example detail only; the restated policy statement lives in the stub. -->

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

After required fields, add skill-specific fields relevant to the report type (e.g. Verdict, CI, Risk, Blockers for `develop:review`; Best method, Papers for `research:topic`; Methodology, Findings for `research:judge`). `develop:review`'s report template is the canonical reference. Skills with dedicated output routing (audit, review, resolve, analyse, release) must include an equivalent `---` block at the top of their report files.

**Terminal render of the block above** (one row per key, in file order, values verbatim — no re-wrapping, no truncation):

```markdown
| Field | Value |
| --- | --- |
| Title | [Skill] — [subject] |
| Date | [YYYY-MM-DD] |
| Scope | [what was analyzed] |
| Focus | [aspect examined] |
| Agents | [agent names] |
| Outcome | [✓/⚠/✗ verdict] |
| Confidence | [score] — [key gaps] |
| Next steps | [recommended follow-up] |
| Path | → .reports/<skill>/<timestamp>/<name>.md |
```
