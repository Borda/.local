# Shared Checks (all scopes) — 17, 21, 4, 5, 9, 16, 15

## Check 12 — File length (context budget risk)

Thresholds: agents > 300 lines (~4 k tokens) · skill SKILL.md > 600 lines (~8 k tokens) · rules > 200 lines (~2.5 k tokens).

> **Line count = human-readable proxy; token count = true measure.** Thresholds guide human review — not actual context budget. Short sentences + short lines preferred: easier to read AND cheaper per logical unit. Collapsing multiple short lines into one long line does NOT reduce token cost and destroys readability. Fix = remove or distill content. Collapsing lines not a fix.

```bash
# Token estimate: wc -c (bytes) / 4 — rough but consistent proxy (1 token ≈ 4 bytes in English markdown)
printf "%-52s %8s %8s\n" "FILE" "~TOKENS" "LINES"
for f in .claude/agents/*.md; do # timeout: 5000
    [ -f "$f" ] || continue
    lines=$(wc -l <"$f" | tr -d ' ')
    bytes=$(wc -c <"$f" | tr -d ' ')
    est=$((bytes / 4))
    [ "$est" -gt 4000 ] &&
    printf "⚠ OVER BUDGET: agents/%s — ~%d tokens / %d lines (limit: ~4 k)\n" "$(basename "$f")" "$est" "$lines" ||
    printf "  %-50s %8d %8d\n" "agents/$(basename "$f")" "$est" "$lines"
done
for f in .claude/skills/*/SKILL.md; do
    [ -f "$f" ] || continue
    lines=$(wc -l <"$f" | tr -d ' ')
    bytes=$(wc -c <"$f" | tr -d ' ')
    est=$((bytes / 4))
    [ "$est" -gt 8000 ] &&
    printf "⚠ OVER BUDGET: skills/%s/SKILL.md — ~%d tokens / %d lines (limit: ~8 k)\n" "$(basename "$(dirname "$f")")" "$est" "$lines" ||
    printf "  %-50s %8d %8d\n" "skills/$(basename "$(dirname "$f")")/SKILL.md" "$est" "$lines"
done
for f in .claude/rules/*.md; do
    [ -f "$f" ] || continue
    lines=$(wc -l <"$f" | tr -d ' ')
    bytes=$(wc -c <"$f" | tr -d ' ')
    est=$((bytes / 4))
    [ "$est" -gt 2500 ] &&
    printf "⚠ OVER BUDGET: rules/%s — ~%d tokens / %d lines (limit: ~2.5 k)\n" "$(basename "$f")" "$est" "$lines" ||
    printf "  %-50s %8d %8d\n" "rules/$(basename "$f")" "$est" "$lines"
done
```

**Severity**: **medium** — report only, never auto-fix. When flagging, remind fixer: only content removal or distillation counts; collapsing lines not acceptable.

## Check 13 — Markdown heading hierarchy continuity

````bash
printf "=== Check 13: Heading hierarchy continuity ===\n"
violations=0
for f in .claude/agents/*.md .claude/skills/*/SKILL.md .claude/rules/*.md; do # timeout: 5000
    [ -f "$f" ] || continue
    awk -v file="$f" '
    /^```/ { in_code = !in_code; next }
    in_code { next }
    /^#+ / {
      n = 0; s = $0
      while (substr(s,1,1) == "#") { n++; s = substr(s,2) }
      if (prev > 0 && n > prev + 1) {
        printf "  ⚠ HEADING JUMP: %s:%d — h%d followed by h%d (skipped h%d)\n", \
          file, NR, prev, n, prev+1
        found++
      }
      prev = n
    }
    END { exit (found > 0) ? 1 : 0 }
  ' "$f" || violations=$((violations + 1))
done
if [ "$violations" -eq 0 ]; then
    printf "✓: Check 13 — no heading hierarchy violations found\n"
fi
````

**Severity**: **medium** — heading jumps impair navigation. Fix: insert missing intermediate heading level, or demote/promote offending heading. **Report only** — never auto-fix.

## Check 14a — Structural tag symmetry

Checks two failure modes: (1) empty blocks — `<tag></tag>` with only whitespace between open and close; (2) unbalanced tags — open count differs from close count. Both leave files structurally broken.

Scan all agent and skill files via deterministic bin/ script:

```bash
printf "=== Check 14a: Structural tag symmetry ===\n"
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_tag_symmetry.py" \
    .claude/agents/*.md .claude/skills/*/SKILL.md  # timeout: 10000
```

**Severity**: **medium** — gate-level; must fix before audit passes.
- **Empty block**: **Auto-fix: YES** — remove empty open+close tag pair entirely; no content to lose.
- **Unbalanced tag**: **Auto-fix: NO** — missing open or close tag requires manual inspection to determine intended structure.

> Root cause: prior fix moved or removed block content but left container tags (empty block); or copy-paste error dropped closing tag (unbalanced). Empty `<constants>` most common empty-block case.

## Check 14b — Code fence symmetry

Detects two failure modes: (1) unclosed fence — opening ` ``` ` or ` ```lang ` with no matching closing ` ``` `; (2) bad nesting — inner fence uses same or more backticks as outer (outer must use ```` ```` or more to contain inner ` ``` `).

Scan all agent and skill files via deterministic bin/ script:

```bash
printf "=== Check 14b: Code fence symmetry ===\n"
python "${CLAUDE_PLUGIN_ROOT:-plugins/foundry}/bin/check_fence_symmetry.py" \
    .claude/agents/*.md .claude/skills/*/SKILL.md  # timeout: 10000
```

**Severity**: **high** — unclosed fence corrupts all subsequent code blocks in the file; Claude misparses the rest of the file.
- **Unclosed fence**: **Auto-fix: YES** — add missing closing ` ``` ` at end of block; confirm content boundary by reading surrounding context.
- **Bad nesting**: **Auto-fix: YES** — promote outer fence to ```` ```` ```` ````; or demote inner if outer is intentionally 3-backtick.
- **Timeout comment on closing fence** (```` ``` # timeout: N ````): **Auto-fix: YES** — move comment to last command inside block; change closing line to plain ` ``` `.

> Root cause: timeout annotation placed on closing fence delimiter instead of inside block (most common); or copy-paste lost a closing ` ``` `.

## Check 15 — Hardcoded user paths

Use Grep tool (pattern `/Users/|/home/`, glob `{agents/*.md,skills/*/SKILL.md}`, path `.claude/`, output mode `content`) to flag non-portable paths in agent and skill files. Run second Grep on `.claude/settings.json` with same pattern to catch absolute hook paths.

**Important**: run on every file regardless of prior critical/high findings — path portability orthogonal to other severity classes, must not deprioritize.

Also grep for bare `plugins/<name>/` prefix as primary path in skill/agent bodies — source-tree paths that work during authoring but break post-install. See Check C32 for full scan.

## Check 16 — Example value vs. token cost

First, detect whether project has local context files:

```bash
for f in AGENTS.md CONTRIBUTING.md .claude/CLAUDE.md; do # timeout: 5000
    [ -f "$f" ] && printf "✓ found: %s\n" "$f"
done
```

Scan agent and skill files for inline examples:

````bash
for f in .claude/agents/*.md .claude/skills/*/SKILL.md; do # timeout: 5000
    count=$(grep -cE '^```|^## Example|^### Example' "$f" 2>/dev/null || true)
    lines=$(wc -l <"$f" | tr -d ' ')
    [ "$count" -gt 0 ] && printf "%s: %d example blocks, %d total lines\n" "$f" "$count" "$lines"
done
````

Classify each example block via model reasoning:

- **High-value**: non-obvious pattern, nuanced judgment, or output-format spec prose can't convey → keep
- **Low-value**: restates prose, trivial, or superseded by project-local docs → **low** finding: suggest removing or replacing with pointer to local doc

Report per-file: `N examples total, K high-value, M low-value (est. ~X tokens wasted)`.

## Check 17 — Cross-file code block inventory

Block count across all .md files in scope. NxN similarity analysis is expensive — runs in `--efficiency` mode only (Phase B2), which subsumes this check. When `--efficiency` active, skip Check 17.

```bash
if [ "$LOCAL_MODE" = "true" ]; then
    _C17_GLOBS="plugins/*/skills/*/SKILL.md plugins/*/skills/*/modes/*.md plugins/*/skills/_shared/*.md plugins/*/skills/*/templates/*.md plugins/*/agents/*.md plugins/*/rules/*.md"
else
    _C17_GLOBS=".claude/skills/*/SKILL.md .claude/agents/*.md"
fi
printf "%-55s %s\n" "FILE" "BLOCKS"
for f in $_C17_GLOBS; do # timeout: 5000
    [ -f "$f" ] || continue
    name="${f#plugins/}"
    name="${name#.claude/}"
    blocks=$(grep -c '^\`\`\`' "$f" 2>/dev/null || echo 0)
    blocks=$(( blocks / 2 ))
    printf "%-55s %d\n" "$name" "$blocks"
done
```

Flag files with block count ≥ 10 as extraction candidates — recommend `--efficiency` run for full NxN analysis.

For 17a (step-level prose overlap, ≥40% consecutive steps): flag pair, name canonical owner; route to Check 20 `merge-prune` if no clear owner.

| Sub-check | Algorithm | Threshold | Severity | Output |
| --- | --- | --- | --- | --- |
| 17a — step overlap | consecutive step fraction | ≥40% steps | medium | findings list only |
| 17b — block duplicate | NxN similarity (moved) | run `--efficiency` for full analysis | — | Phase B2 in efficiency.md |

## Check C32 — Hardcoded source-tree paths (install-path regression)

Plugin skill and agent files must not contain bare `plugins/<name>/` paths as primary references. Resolve in source tree but break post-install where `plugins/` absent. Install-path resolution pattern (cache + fallback) mandatory.

```bash
printf "=== Check C32: Hardcoded source-tree paths ===\n"
# C32 inherently scans plugin source tree — only meaningful in LOCAL mode
if [ "$LOCAL_MODE" != "true" ]; then
    printf "✓ [Check C32/shared] Skipped in non-local mode (no plugin source tree)\n"
else
    # Find bare plugins/ primary paths — not inside comments, not inside fallback guards
    grep -rn ' plugins/[a-z]' plugins/*/skills/*/SKILL.md plugins/*/agents/*.md 2>/dev/null |
      grep -v '^Binary' |
      grep -v '^\s*#' |
      grep -v '&& .*plugins/' |
      grep -v ':-.*plugins/' |
      grep -v '"plugins/' | grep -v "'plugins/" | while IFS= read -r hit; do
        printf "! BREAKING C32: %s\n" "$hit"
        printf "  fix: replace with installed-path resolution:\n"
        printf "        VAR=\"\$(ls -td ~/.claude/plugins/cache/borda-ai-rig/<plugin>/*/skills/_shared 2>/dev/null | head -1)\"\n"
        printf "        [ -z \"\$VAR\" ] && VAR=\"plugins/<plugin>/skills/_shared\"\n"
    done
    printf "✓: Check C32 scan complete\n"
fi  # timeout: 5000
```

Severity: **high** — skill silently fails for any user who installed via marketplace (primary install path).

| Sub-check | Pattern | Severity | Auto-fix |
| --- | --- | --- | --- |
| C32 — source-tree primary path | `plugins/<name>/` not in comment or fallback | high | no |

> **Related**: Check 15 covers `/Users/` and `/home/` hardcoded paths. C32 covers `plugins/` source-tree paths.

## Check 18 — Rules integrity and efficiency

Four sub-checks covering `.claude/rules/`. Skip if `rules/` directory absent or empty.

**18a — Inventory vs MEMORY.md**:

```bash
ls .claude/rules/*.md 2>/dev/null | xargs -I{} basename {} .md | sort # timeout: 5000
```

Rules on disk absent from MEMORY.md → **medium**. Rules in MEMORY.md absent on disk → **medium**.

**18b — Frontmatter completeness**:

```bash
for f in .claude/rules/*.md; do # timeout: 5000
    desc=$(awk '/^---$/{c++; if(c==2)exit} c==1 && /^description:/{found=1} END{print found+0}' "$f")
    [ "$desc" -eq 0 ] && printf "MISSING description: %s\n" "$f"
done
```

Missing `description:` → **high**. Malformed `paths:` → **high**.

**18c — Redundancy check**: Per rule file, identify 2–3 most specific directive phrases. Grep verbatim in `.claude/CLAUDE.md` and `.claude/agents/*.md`. Exact phrase in ≥2 locations outside rule file → **medium** (distillation incomplete).

```bash
grep -l "Never switch to NumPy" .claude/agents/*.md .claude/CLAUDE.md 2>/dev/null # timeout: 5000
grep -l "never git add" .claude/agents/*.md .claude/CLAUDE.md 2>/dev/null         # timeout: 5000
```

**18d — Cross-reference integrity**: Grep agent files, skill files, CLAUDE.md for `.claude/rules/<name>.md` patterns. Verify each referenced filename exists on disk → missing → **high**.

```bash
grep -rh '\.claude/rules/[a-z_-]*\.md' .claude/agents/ .claude/skills/ .claude/CLAUDE.md 2>/dev/null |
grep -o 'rules/[a-z_-]*\.md' | sort -u # timeout: 5000
```

Severity: 18b = **high**; 18a/18c/18d = **medium**.

## Check 25 — Implicit agent references (missing plugin prefix)

All agent dispatch calls must use fully-qualified plugin-prefixed form (`foundry:sw-engineer`, `oss:shepherd`, etc.). Bare names like `sw-engineer` ambiguous: rely on `~/.claude/agents/` symlinks being present, break if symlinks stale, missing, or pointing to wrong plugin.

Scan agent files, skill files, CLAUDE.md for `subagent_type=` patterns:

```bash
printf "=== Check 25: Implicit agent references ===\n"
grep -rn 'subagent_type=' .claude/agents/ .claude/skills/ .claude/CLAUDE.md 2>/dev/null |
grep -v '^Binary' |
grep 'subagent_type="[a-z]' |
grep -v '"[a-z][a-z-]*:[a-z]' |
grep -v '"general-purpose"\|"Explore"\|"Plan"\|"claude-code-guide"\|"statusline-setup"' || true  # timeout: 5000
```

Exempt built-in types (no plugin prefix required): `general-purpose`, `Explore`, `Plan`, `claude-code-guide`, `statusline-setup`.

Every non-exempt bare name = **high** finding:

```text
[high] Implicit agent reference: subagent_type="<name>" in <file>
fix: use fully-qualified form, e.g. subagent_type="foundry:<name>"
```

**Report only** — no auto-fix; correct prefix depends on which plugin owns agent.

> **Related**: Check 28 (in `checks-skills.md`) covers cross-plugin fallback coverage — dispatched agent exists but no fallback when that plugin absent. Check 25 and Check 28 address different failure modes; run both.

## Check 29 — LLM context minimality (verbosity)

Every token in agent, skill, rule file = inference cost on every invocation. Each file must be semantically minimal — all information retained, zero redundant wording.

**Scan targets**: `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/rules/*.md`.

Via model reasoning, apply four criteria per file:

**1 — Within-file repetition**: same rule or instruction in two sections. Sub-bullet fully restates parent with no additive content. Workflow step re-explains constraint already defined in preamble or `<notes>`.

**2 — Prose inflation**: filler preambles ("Note that", "It is important to", "Please be aware", "Keep in mind") — flag phrase; substantive content survives without it. Unconditional rule hedged with "might", "could potentially", "in some cases" where rule absolute. Opening sentence paraphrases heading with no additive content.

**3 — Restatement of obvious consequence**: "Do X" immediately followed by "Failing to do X causes Y" where Y self-evident from X alone.

**4 — Information gap test (mandatory before flagging any candidate)**: "If removed, can reader reconstruct from remaining content?" YES = safe to flag. NO = not a finding — content load-bearing even if verbose. Always skip: code blocks, inline examples (Check 16), cross-reference tables, numbered lists where order carries meaning.

Per finding: location (section heading + approx line range) · pattern type (repetition / prose-inflation / obvious-consequence) · estimated token savings (small <20 / medium 20–80 / large >80) · proposed shorter form or "remove entirely".

**Severity**: **medium** — total savings >= medium across >= 2 distinct locations. **low** — isolated small savings only. **Report only** — never auto-fix; minimization risks removing load-bearing nuance.

## Check 26 — Symbol and shortcut consistency

Three sub-checks for within-file consistency of emoji symbols, slash-command notation, legend alignment.

**26a — Emoji/symbol consistency within files**

Per agent or skill file, extract lines with emoji and annotated concept label. Group by concept. Flag concepts with 2+ distinct emoji in same file.

````bash
printf "=== Check 26a: Emoji/symbol consistency ===\n"
for f in .claude/agents/*.md .claude/skills/*/SKILL.md; do # timeout: 5000
    [ -f "$f" ] || continue
    # Print filename + any line containing common status emoji (skip code fences)
    awk '/^```/{skip=!skip} !skip && /[🔴🟡🟢🔵⛔✅❌⚠️💭▶️🔗🔹🔸🚫]/{print FILENAME": "NR": "$0}' "$f" 2>/dev/null
done
````

Via model reasoning, identify concept labels (e.g., "closed", "open", "active focus", "merged") appearing with two+ distinct symbols in same file. Example: file marks branch 🔴 (closed) in one section and ⛔ closed in another = violation.

Flag: `[medium] Inconsistent symbol for "<concept>" in <file>: <symbol-A> (line N) vs <symbol-B> (line M)`

**26b — Slash command notation consistency**

Directive references to other skills (e.g., "run → /audit") must use `/name` form. Prose mentions (e.g., "the audit skill") may omit slash. Flag files mixing `` `/name` `` and `` `name` `` in same directive context.

```bash
printf "=== Check 26b: Slash command notation ===\n"
for f in .claude/agents/*.md .claude/skills/*/SKILL.md; do # timeout: 5000
    [ -f "$f" ] || continue
    # Collect directive-looking references in both forms
    grep -n '→ `/\?[a-z][a-z:-]*`\|run `/\?[a-z][a-z:-]*`\|suggest.*`/\?[a-z][a-z:-]*`' "$f" 2>/dev/null
done
```

Via model reasoning: same skill referenced with both `/name` and bare `name` in directive context in same file → **low** finding.

**26c — Legend ↔ body symbol alignment**

When file defines legend (any line matching `Legend:` followed by symbol/concept pairs), every body use of concept must match legend symbol exactly.

```bash
printf "=== Check 26c: Legend/key alignment ===\n"
grep -n 'Legend:\|^Key:' .claude/agents/*.md .claude/skills/*/SKILL.md 2>/dev/null || true # timeout: 5000
```

Via model reasoning: extract (symbol, concept) pairs from legend. Per concept, scan file body outside code fences for different symbol. Flag: `Legend defines <concept> as <symbol-A> but body uses <symbol-B> at line N`.

**Report only** — never auto-fix; symbol choices may be intentional or constrained by existing docs.

| Sub-check | Severity | Auto-fix |
| --- | --- | --- |
| 26a — same concept, different symbols | medium | no |
| 26b — directive notation mixed `/name` vs `name` | low | no |
| 26c — body symbol contradicts legend | medium | no |
