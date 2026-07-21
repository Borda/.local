<!-- file: release-draft-template.md — consumers: release/SKILL.md (## Write release draft section) -->

### CHANGELOG Entry (`--changelog` flag)

Use this format:

```markdown
## [version] — [date]
### Added
### Changed
### Deprecated
### Removed
### Fixed
### Security
```

### Internal Release Summary (`--summary` flag)

Use this format:

```markdown
## Release [version]
**What shipped**: [2-3 sentence summary of the most important changes]
**Impact**: [who is affected and how]
**Action required**: [anything ops/support/consumers need to do]
**Rollback**: [safe to roll back? any caveats?]
```

### Semantic consistency review

Runs on full draft after adversarial review, before writing to disk. Check for each:

| Check | What to look for | Flag format |
| --- | --- | --- |
| **Double-mention** | Same concept named twice under different labels (e.g. "async functions" and "async generators" as separate entries for same change) | `DUPLICATE: "<A>" and "<B>" describe the same change — merge or drop one` |
| **Impossible fix** | 🔧 Fixed entry whose subject was introduced in this same release (can't fix what was never shipped) | `IMPOSSIBLE-FIX: "<entry>" — feature added this release, can't be a fix` |
| **Causation non sequitur** | "X: Y" where Y doesn't explain or follow from X | `NON-SEQUITUR: "<X>: <Y>" — Y doesn't explain X` |
| **Contradictory claim** | Headline or first sentence asserts X; immediate caveat or next sentence denies X | `CONTRADICTION: "<headline>" contradicted by "<caveat>"` |
| **Verbatim duplication** | Identical or near-identical sentence appearing in ≥2 sections (Summary, Spotlight, Notable changes, Migration guide) | `VERBATIM-DUP: "<sentence>" appears in <section A> and <section B>` |
| **Misclassified scope** | Internal-only change (dead code removal, doc reformat, test-only, CI config) appearing in user-facing section | `SCOPE: "<entry>" is internal-only — move to Internal or remove` |

For each finding: emit one flag line with location (`§<section-name>`, item text). Collect all findings before taking action — don't fix inline during scan.

**After scan**: zero findings → proceed to Polish. Findings present → list all; fix each; re-scan once; proceed only when clean.

### Polish and write to disk

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
[ -f "$SKILL_DIR/guidelines/writing-rules.md" ] && cat "$SKILL_DIR/guidelines/writing-rules.md"  # timeout: 5000
```
Follow above (if present). If absent, proceed without style guidelines.

Dispatch shepherd for public-facing voice/tone review before writing to disk. Check availability first:

```bash
SHEPHERD_AVAILABLE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/check_agent.py" oss shepherd 2>/dev/null)  # timeout: 5000
# expand to literal value before spawning
SHEPHERD_DIR=".temp/release-shepherd-$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')-$(date +%Y-%m-%d)"
mkdir -p "$SHEPHERD_DIR"  # timeout: 5000
```

If `$SHEPHERD_AVAILABLE` equals `true`:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_OSS_SHARED=$(cat "${TMPDIR:-/tmp}/release-oss-shared-${CSID}" 2>/dev/null || echo "")
[ -f "$_OSS_SHARED/shepherd-voice.md" ] || { echo "⚠ shepherd-voice.md not found — falling back"; SHEPHERD_AVAILABLE=false; }  # timeout: 5000
```

If still `true`, write draft to `$SHEPHERD_DIR/draft.md`, then spawn:

```text
Agent(subagent_type="oss:shepherd", prompt="Review the full release draft at <$SHEPHERD_DIR/draft.md> for public-facing voice and tone. Apply shepherd voice guidelines: human and direct, no internal jargon, no staff names, no internal maintenance details. Write the revised content to <$SHEPHERD_DIR/shepherd-revised.md>. Return ONLY: {\"status\":\"done\",\"changes\":N,\"file\":\"<$SHEPHERD_DIR/shepherd-revised.md>\"}")
```

If `oss:shepherd` not available, use draft content directly — skip shepherd review.

Read `$SHEPHERD_DIR/shepherd-revised.md` → validate: `if [ -s "$SHEPHERD_DIR/shepherd-revised.md" ]; then SHEPHERD_REVISED_PATH="$SHEPHERD_DIR/shepherd-revised.md"; else echo "⚠ shepherd output empty or missing — using original draft"; SHEPHERD_REVISED_PATH="$SHEPHERD_DIR/draft.md"; fi`. Shepherd runs once per invocation.

Write to disk:

Shepherd review policy (applies when `$SHEPHERD_AVAILABLE == true`):
<!-- branch: draft-exists — only when DRAFT.md non-empty (notes/prepare path); call 1 of ≤2 on notes+changelog path -->
- **notes** (always): shepherd review → write to `DRAFT.md` at repo root. **Overwrite guard** — if `DRAFT.md` non-empty, invoke `AskUserQuestion` ("DRAFT.md already exists — overwrite, append, or abort?") with: (a) **Overwrite** · (b) **Append** (after `---` separator) · (c) **Abort**. Skip prompt only when DRAFT.md is empty or missing. Notify: `→ written to DRAFT.md` / `→ appended to DRAFT.md` / `→ DRAFT.md unchanged — aborted`.
<!-- branch: changelog-confirm — only with --changelog flag; call 2 of ≤2 on notes+changelog path; max 4 total on prepare+changelog+draft path -->
- **`--changelog`** (if set): no shepherd (structured, internal) → invoke `AskUserQuestion`: "Ready to prepend to `$CHANGELOG_FILE`?" Options: (a) Proceed · (b) Preview only. On (b): display content, stop. On (a): derive `VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "")` and `VERSION_BARE="${VERSION#v}"`. **Idempotency check**: if `$CHANGELOG_FILE` already contains version header in any supported form (`grep -qF "## [${VERSION_BARE}]" "$CHANGELOG_FILE"` for Keep-a-Changelog `## [1.2.0]`, OR `grep -qF "## [${VERSION}]" "$CHANGELOG_FILE"` for `## [v1.2.0]`, OR `grep -qE "^## v?${VERSION_BARE}([^0-9.]|$)" "$CHANGELOG_FILE"` for `## v1.2.0` / `## 1.2.0`) → skip prepend, notify `→ CHANGELOG.md already contains version header — prepend skipped`; otherwise prepend after `# Changelog` heading (create if missing). Notify: `→ prepended to CHANGELOG.md`
- **`--summary`** (if set): no shepherd (internal) → Draft executive summary saved to `.temp/output-release-summary-$BRANCH-$DATE.md` — confirm written. Notify: `→ saved to .temp/output-release-summary-<branch>-<date>.md`
- **`--migration`** (if set): shepherd review (public-facing) → save to `.temp/output-release-migration-$BRANCH-$DATE.md`. Notify: `→ saved to .temp/output-release-migration-<branch>-<date>.md`

**Human gate** — stop, hand off after writing files. GitHub release must be created with project-level tooling (`gh release create`). Exact release steps:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_OSS_SHARED=$(cat "${TMPDIR:-/tmp}/release-oss-shared-${CSID}" 2>/dev/null || echo "")
cat "$_OSS_SHARED/release-checklist.md"  # timeout: 5000
```

> Confidence block — notes mode: end response here with `## Confidence` block per CLAUDE.md output standards.
