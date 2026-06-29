<!-- oss:release Mode: prepare — executed via: Read $SKILL_DIR/modes/prepare.md; execute -->
<!-- Variables available: $SKILL_DIR, $_OSS_SHARED, $LAST_TAG, $BRANCH, $DATE, $RANGE, $VERSION, $REPO_ROOT, $GATHER_FILE -->

**Trigger**: `/release prepare <version>` (e.g., `prepare v1.3.0` or `prepare 1.3.0`)

**Purpose**: Full release pipeline — audit first, generate all artifacts. Use when cutting release; use individual modes for drafting.

```bash
# fresh shell loses vars; Mode Detection persists REST to tmpdir
REST=$(cat "${TMPDIR:-/tmp}/release-rest" 2>/dev/null || echo "")
VERSION="${REST%% *}"
[[ "$VERSION" != v* ]] && VERSION="v$VERSION"
RANGE="${RANGE:-$LAST_TAG..HEAD}"
# BRANCH, DATE, LAST_TAG, REPO_ROOT, SKILL_DIR from Shared setup above
```

### Phase 1: Readiness audit

Run all checks from **Mode: audit** with `$VERSION` as target. The `| Check | Status | Detail |` readiness table must appear inline in the terminal before proceeding — audit-checks.md requires this even in sub-phase context. If the table is absent from the response after running audit, re-execute the terminal output step from audit-checks.md before continuing.

**If verdict is BLOCKED**: stop. List blockers, tell user to resolve before re-running `/release prepare $VERSION`. Write no artifacts.

**If verdict is READY or NEEDS_ATTENTION**: surface warnings, continue to Phase 2.

### Phase 2: Gather, classify, and changelog

**a. Gather and classify** — spawn gather subagent per **Delegation strategy** for `$RANGE`; write findings to `GATHER_FILE`. Read returned JSON envelope; pass file path downstream. Don't read gather file into main context. Note `breaking` count from envelope — gates Phase 3b (migration guide). After envelope validation, check `unconfirmed_breaking` from envelope: if > 0, apply the post-validation truth-check gate from **Delegation strategy** (partial `[UNCONFIRMED]` read + `AskUserQuestion` per breaking item) before proceeding to 2b.

**b. Audit changelog** — apply **Audit changelog** logic inline: locate `$CHANGELOG_FILE` (per search order in Audit changelog section), cross-check classified changes from `$GATHER_FILE`, add missing entries, stamp unreleased section as `## [$VERSION] — $DATE`. Report: "N items added, M flagged."

### Phase 3: Highlights and migration

Set up release directory, back up existing artifacts:

```bash
RELEASE_DIR="releases/$VERSION"
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/setup_release_dir.py" "$RELEASE_DIR" "$CHANGELOG_FILE"  # timeout: 5000
```

**a. Identify highlights** — apply **Identify highlights** logic using classified changes from `$GATHER_FILE`: rank top 3–5 most significant changes (breaking > new public API > major UX > notable fixes), pull one concrete code example per highlight from diff. Write to `releases/$VERSION/HIGHLIGHTS.md`. Source of truth for demo, executive summary, release draft spotlights.

**b. Draft migration guide** — apply **Draft migration guide** logic using breaking/deprecated changes from `$GATHER_FILE`. No breaking changes → single line: `No breaking changes in this release.` Shepherd voice review applies. Write to `releases/$VERSION/MIGRATION.md`.

### Phase 4: Demo and summary

**a. Demo notebook** — reuse `$GATHER_FILE` and `releases/$VERSION/HIGHLIGHTS.md` from Phase 3. Apply demo generation logic from **Mode: demo**, Phase 2 (Generate demo script). Output path:

```bash
DEMO_OUT="releases/$VERSION/demo.py"
```

Write generated script to `$DEMO_OUT` using Write tool. **Execution gate** — run:
```bash
python "$DEMO_OUT"  # timeout: 600000
```
Fix and re-run until exits 0 with expected output. Don't proceed to 4b until gate passes.

**b. Executive summary** — apply **Draft executive summary** logic using `releases/$VERSION/HIGHLIGHTS.md` and demo output. Write to `releases/$VERSION/SUMMARY.md`.

### Phase 5: Write release draft

`releases/$VERSION/DRAFT.md` — final assembly. Source: `releases/$VERSION/HIGHLIGHTS.md` (spotlights), `releases/$VERSION/MIGRATION.md`, `releases/$VERSION/SUMMARY.md`. Apply **Write release draft** logic (release-draft.md format). Adversarial review applies (use `$GATHER_FILE` from Phase 2a as gather context). Shepherd voice review applies.

### Output

```markdown
## Release prepare: $VERSION

### Audit
Reproduce the full Phase-1 readiness table verbatim — the `| Check | Status | Detail |` markdown table from audit-checks.md with ALL check rows (Working tree, CI, Blocking issues, Open PRs, README aligned, CHANGELOG entry, Version consistent, Dependency CVEs, Scheduled removals, Doc proportionality) and their Status glyphs (`✅`/`⚠️`/`❌`). "Condensed" applies to the Detail column only (trim verbose detail) — never to row count. Do NOT replace this table with a finding-bullet digest, and do NOT substitute a different table (e.g. a `File | Status` artifacts box).
[any warnings carried forward]

### Written (documentation artifacts — complementary to the release, not the release itself)
Render as the markdown bullet list below — NOT a box-drawing (`┌─┬─┐`) `File | Status` table.
- `$CHANGELOG_FILE` — $VERSION entry stamped (Phase 2b); `releases/$VERSION/CHANGELOG.md` symlinks here
- `releases/$VERSION/HIGHLIGHTS.md` — top 3–5 spotlights with code examples (Phase 3a)
- `releases/$VERSION/MIGRATION.md` — migration guide (N breaking changes, or "No breaking changes") (Phase 3b)
- `releases/$VERSION/demo.py` — story-telling jupytext notebook (Phase 4a)
- `releases/$VERSION/SUMMARY.md` — internal executive summary (Phase 4b)
- `releases/$VERSION/DRAFT.md` — user-facing release notes, final assembly (Phase 5)

### Next steps
1. Review all written files
2. Bump version in the project manifest
3. Commit, push, open PR
4. On merge: publish the release — `gh release create $VERSION --notes-file releases/$VERSION/DRAFT.md` (user-run; DRAFT.md is source for release notes, not the release itself)
5. Upload package to PyPI (or relevant registry) — separate step after GitHub release
6. Convert demo: `jupytext --to notebook releases/$VERSION/demo.py`
```

End terminal response (not written artifacts) with `## Confidence` block per CLAUDE.md output standards: `**Score**: 0.0–1.0 — [label]`; omit Refinements if 0 passes.
