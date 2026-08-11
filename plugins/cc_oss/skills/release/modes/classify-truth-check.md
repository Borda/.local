<!-- file: classify-truth-check.md — consumers: release/SKILL.md (Classify each change + Truth check + Breaking-change classification phases; loaded once, all three phases read from that single load) -->

## Classify each change

**Net-state principle**: classify only HEAD state, not development journey. Feature added then removed within range = net effect zero — omit.

**Cross-cycle extension** (`--append` only): the Net-state principle above applies within `$RANGE`; Gather changes' "Cross-cycle revert/pivot detection" extends it *across* append cycles — a revert or symbol pivot that supersedes a bullet a PRIOR cycle already wrote into `DRAFT.md`/`$CHANGELOG_FILE` nets to a removal of that stale entry, not an additive one. See Gather changes for the detection rule; classify each in-scope item against `CROSS_CYCLE_MATCH` before finalizing this table.

**PR accumulation**: list ALL contributing PR numbers for net-surviving entry. **Same category only** — two PRs merge under one bullet only when both classify into SAME section. Later PR fixing bug in same-range feature = own 🔧 Fixed entry. **Trivial-fix exception**: fix or doc tweak with no standalone user-visible effect folds into parent Added bullet. When in doubt: separate entries safer

**Commit-label distrust**: `fix:`/`feat:`/etc. type prefix and subject line are self-reported by the author, not verified — a commit titled `fix: progress bar` can in fact reintroduce a feature, and a mislabeled subject slips through unnoticed more often than a mislabeled body trailer. Classify from the actual diff (files touched, symbols added/changed, net behavior at HEAD), never from the type prefix or subject text alone — treat both as a hint to check, not a verdict.

**SHA tracking (for provenance)**: alongside PR numbers, also retain the full 40-char commit sha(s) contributing to each net-surviving entry — already visible in context from Gather changes' `git log $RANGE --no-merges --format="--- %H%n%B"` output. Needed downstream by the Provenance record step (`release-draft-template.md` "Post-write bookkeeping"), which derives each sha's content-stable `git patch-id --stable` for the actual store key — a bullet folding N squashed commits keeps all N shas, each mapped to that one bullet's final text once written.

Section order (fixed): 🚀 Added → ⚠️ Breaking Changes → 🌱 Changed → 🗑️ Deprecated → ❌ Removed → 🔧 Fixed → 🔒 Security → 🔄 Reverted

| Category | Section | What goes here |
| --- | --- | --- |
| New Features | 🚀 Added | User-visible additions |
| Breaking Changes | ⚠️ Breaking Changes | Existing code stops working immediately — no prior deprecation period. Prior release deprecated → ❌ Removed instead. |
| Improvements | 🚀 Added or 🌱 Changed | Enhancements to existing behavior |
| Performance | 🚀 Added / 🔧 Fixed / 🌱 Changed | Quantitative claims require benchmark evidence; else rewrite to "improved performance" without number. |
| Deprecations | 🗑️ Deprecated | Old API still works; scheduled removal; replacement exists |
| Removals | ❌ Removed | Previously deprecated — users had warning. Not ⚠️ Breaking Changes. |
| Bug Fixes | 🔧 Fixed | Correctness fixes |
| Security | 🔒 Security | Security fixes + CVE dep updates. Security-intent keywords in body always classify here regardless of commit type. OMIT-INTERNAL does NOT apply. |
| Internal | *(omit)* | Refactors, CI/tooling, deps, housekeeping — omit unless user-impacting |
| Reverted | 🔄 Reverted | Introduced AND reverted within range (REVERT_SET) — net effect zero |

**Same-release feature+fix dedup**: 🔧 Fixed targeting code introduced same release = never shipped = fold into 🚀 Added or omit.

**Breaking vs Deprecated vs Removed**: old call still works → Deprecated. Deprecated in prior release, now removed → Removed. **Prior-deprecation body-signal**: commit body contains "deprecated in vX", "previously deprecated", "was deprecated", "emits DeprecationWarning since", or "deprecated since" → treat as Removed regardless of `feat!:`/`BREAKING CHANGE:` markers. **Bug fixed to match spec**: classify as 🌱 Changed when users relied on buggy behavior; ⚠️ Breaking Changes only if load-bearing, causes widespread breakage.

**OMIT-INTERNAL body-signal override**: commit body contains "No code changes", "no user-facing changes", "internal only", "no public API changes", "internal buffer changes only", "internal restructure" OR all paths under `.github/`, `ci/`, `scripts/`, `Makefile`, `*.yml` under `.github/` → classify as Internal. **Exception**: BREAKING CHANGE footer or confirmed user-visible breakage overrides.

**Cherry-pick annotation (stable-branch mode)**: when `$CHERRY_PICK_SUBJECTS` set, match subject against it. Match → append "(backported from $SOURCE_TAG_REF)". Subject-text matching is heuristic — verify manually for generic subjects.

**Self-correction discipline**: present only final corrected table — no intermediate classifications.

---

## Truth check

Gate — runs after Classify, before Audit changelog.

**Scope**: 🚀 Added, ⚠️ Breaking Changes, 🌱 Changed naming a symbol. Skip: 🔧 Fixed, 🔒 Security, 🗑️ Deprecated, ❌ Removed, 🔄 Reverted.

For each in-scope change — prefer codemap (immune to false positives from comments/stubs):

```bash
# codemap index (installed by /codemap-py:scan-codebase)
CODEMAP_OK=$(codemap-py query list 2>/dev/null | wc -l)  # timeout: 5000
# non-zero = index loaded; else grep fallback

codemap-py query find-symbol '^<symbol_name>$' 2>/dev/null  # timeout: 5000

# grep fallback: definition-pattern only — skips comments/stubs
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null || \
  git grep -wl "<symbol_name>" HEAD -- '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null  # timeout: 3000

# removals/breaking: confirm absent at HEAD
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null \
  && echo "PRESENT (unexpected)" || echo "ABSENT (confirmed)"  # timeout: 3000

# behavior changes: confirm changed path at HEAD
git show HEAD:<changed_file> | grep -n "<distinguishing_pattern>"  # timeout: 3000
```

Outcomes: confirmed present → keep (note "truth-checked"); not found → remove, log `[REMOVED] <description>`; cannot determine → keep with "(not HEAD-verified)" qualifier.

Gate loop (max 3 iterations): truth-check → remove unverified → re-run on updated set → after 3 iterations surface remaining unverified claims and proceed.

Runs before Identify highlights — highlights and demo must never reference unverified items.

---

## Breaking-change classification

Gate — runs after Truth check, before Audit changelog. Labels each diff-derived public symbol **Breaking** (external caller) or **internal** (same-package caller only), and drafts migration evidence lines.

**Codemap-gated** — `fn-rdeps` needs a v3 index. No index → skip; keep the human Classify labels as-is.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload RANGE (Check 41: fresh shell)
IFS= read -r RANGE < "${TMPDIR:-/tmp}/release-range-${CSID}" 2>/dev/null || RANGE=""
CODEMAP_OK=$(codemap-py query list 2>/dev/null | wc -l)  # timeout: 5000
# 0 = no index → skip this phase entirely (human Classify labels stand)
```

When `CODEMAP_OK` non-zero:

1. Extract changed public symbols (diff-derived, `__init__.py` surface):
   ```bash
   CHANGED_SYMBOLS=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/extract_changed_symbols.py" "$RANGE")  # timeout: 15000
   [ -z "$CHANGED_SYMBOLS" ] && echo "No changed public symbols — skipping Breaking classification"
   ```
2. Resolve each bare name to a `module::symbol` qname (skip test modules) and build one `fn-rdeps --exclude-tests` batch query per resolved qname. Removed public name (no `find-symbol` match) → still add its `<pkg>::<name>` qname so `fn-rdeps` errors and the helper labels it Breaking-removed. Write the query array to `$QUERIES_FILE`:
   ```json
   [{"cmd": "fn-rdeps", "args": ["<module>::<symbol>", "--exclude-tests"]}]
   ```
3. Classify in one batched pass (one process, one coverage block) — pipe batch output through the classifier:
   ```bash
   export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
   IFS= read -r BRANCH < "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || BRANCH=""
   IFS= read -r DATE < "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || DATE=""
   BREAKING_FILE=".temp/release-breaking-$BRANCH-$DATE.json"
   mkdir -p .temp  # timeout: 5000
   codemap-py query batch "$QUERIES_FILE" 2>/dev/null \
     | python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/classify_breaking.py" > "$BREAKING_FILE"  # timeout: 15000
   echo "${BREAKING_FILE:-}" > "${TMPDIR:-/tmp}/release-breaking-file-${CSID}"
   ```

`classify_breaking.py` output: `{breaking:[{symbol,package,external_callers|reason}], internal:[...], query_complete, migration_lines}`. "External caller" = caller whose top-level package differs from the symbol's own package.

**Apply**:
- Every `breaking` symbol not already under ⚠️ Breaking Changes → move it there (or add), citing its external callers as evidence.
- `migration_lines` = the affected call-site draft — carry into **Draft migration guide** (`breaking_callers` findings); each external call site gets a before→after entry.
- `internal` symbols → leave under their human Classify label (🚀 Added / 🌱 Changed); a same-package-only caller is not a downstream break.
- `query_complete:false` → label the evidence "possibly-incomplete (codemap coverage partial)" rather than dropping it; do not silently trust it as exhaustive.

**Do not block** — this phase re-labels and drafts evidence; it never removes classified items.
