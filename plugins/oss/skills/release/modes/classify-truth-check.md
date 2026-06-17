<!-- file: classify-truth-check.md — consumers: release/SKILL.md (Classify each change + Truth check phases) -->

## Classify each change

**Net-state principle**: classify only HEAD state, not development journey. Feature added then removed within range = net effect zero — omit.

**PR accumulation**: list ALL contributing PR numbers for net-surviving entry. **Same category only** — two PRs merge under one bullet only when both classify into SAME section. Later PR fixing bug in same-range feature = own 🔧 Fixed entry. **Trivial-fix exception**: fix or doc tweak with no standalone user-visible effect folds into parent Added bullet. When in doubt: separate entries safer.

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

**Breaking vs Deprecated vs Removed**: old call still works → Deprecated. Deprecated in prior release and now removed → Removed. **Prior-deprecation body-signal**: commit body contains "deprecated in vX", "previously deprecated", "was deprecated", "emits DeprecationWarning since", or "deprecated since" → treat as Removed regardless of `feat!:`/`BREAKING CHANGE:` markers. **Bug fixed to match spec**: classify as 🌱 Changed when users relied on buggy behavior; ⚠️ Breaking Changes only if load-bearing and causes widespread breakage.

**OMIT-INTERNAL body-signal override**: commit body contains "No code changes", "no user-facing changes", "internal only", "no public API changes", "internal buffer changes only", "internal restructure" OR all paths under `.github/`, `ci/`, `scripts/`, `Makefile`, `*.yml` under `.github/` → classify as Internal. **Exception**: BREAKING CHANGE footer or confirmed user-visible breakage overrides.

**Cherry-pick annotation (stable-branch mode)**: when `$CHERRY_PICK_SUBJECTS` set, match subject against it. Match → append "(backported from $SOURCE_TAG_REF)". Subject-text matching is heuristic — verify manually for generic subjects.

**Self-correction discipline**: present only final corrected table — no intermediate classifications.

---

## Truth check

Gate — runs after Classify, before Audit changelog.

**Scope**: 🚀 Added, ⚠️ Breaking Changes, 🌱 Changed naming a symbol. Skip: 🔧 Fixed, 🔒 Security, 🗑️ Deprecated, ❌ Removed, 🔄 Reverted.

For each in-scope change — prefer codemap (immune to false positives from comments/stubs):

```bash
# Check codemap index first (installed by /codemap:scan-codebase)
CODEMAP_OK=$(scan-query list 2>/dev/null | wc -l)  # timeout: 5000
# Non-zero = index loaded; fall back to grep otherwise

# Codemap: structural symbol lookup
scan-query find-symbol '^<symbol_name>$' 2>/dev/null  # timeout: 5000

# Grep fallback: definition-pattern only — skips comments and leftovers
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null || \
  git grep -wl "<symbol_name>" HEAD -- '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null  # timeout: 3000

# For removals/breaking — confirm absent at HEAD
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null \
  && echo "PRESENT (unexpected)" || echo "ABSENT (confirmed)"  # timeout: 3000

# For behavior changes — confirm changed code path at HEAD
git show HEAD:<changed_file> | grep -n "<distinguishing_pattern>"  # timeout: 3000
```

Outcomes: confirmed present → keep (note "truth-checked"); not found → remove, log `[REMOVED] <description>`; cannot determine → keep with "(not HEAD-verified)" qualifier.

Gate loop (max 3 iterations): truth-check → remove unverified → re-run on updated set → after 3 iterations surface remaining unverified claims and proceed.

Runs before Identify highlights — highlights and demo must never reference unverified items.
