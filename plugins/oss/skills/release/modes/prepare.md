<!-- oss:release Mode: prepare — executed via: Read $SKILL_DIR/modes/prepare.md; execute -->
<!-- Variables available: $SKILL_DIR, $_OSS_SHARED, $LAST_TAG, $BRANCH, $DATE, $RANGE, $VERSION, $REPO_ROOT, $GATHER_FILE -->

**Trigger**: `/release prepare <version>` (e.g., `prepare v1.3.0` or `prepare 1.3.0`)

**Purpose**: Full release pipeline — audit first, then generate all artifacts. Use when cutting release; use individual modes for drafting.

```bash
VERSION="${REST%% *}"
[[ "$VERSION" != v* ]] && VERSION="v$VERSION"
RANGE="${RANGE:-$LAST_TAG..HEAD}"
# BRANCH, DATE, LAST_TAG, REPO_ROOT, SKILL_DIR resolved in Shared setup block above
```

### Phase 1: Readiness audit

Run all checks from **Mode: audit** with `$VERSION` as target. Present readiness table.

**If verdict is BLOCKED**: stop. List blockers, instruct user to resolve before re-running `/release prepare $VERSION`. Write no artifacts.

**If verdict is READY or NEEDS_ATTENTION**: surface warnings, continue to Phase 2.

### Phase 2: Gather, classify, and changelog

**a. Gather and classify** — spawn gather subagent per **Delegation strategy** for `$RANGE`; write findings to `GATHER_FILE`. Read returned JSON envelope; pass file path downstream. Do not read gather file into main context. Note `breaking` count from envelope — gates Phase 3b (migration guide).

**b. Audit changelog** — apply **Audit changelog** logic inline: locate `$CHANGELOG_FILE` (per search order in Audit changelog section), cross-check classified changes from `$GATHER_FILE`, add missing entries, stamp unreleased section as `## [$VERSION] — $DATE`. Report: "N items added, M flagged."

### Phase 3: Highlights and migration

Set up release directory and back up any existing artifacts:

```bash
RELEASE_DIR="releases/$VERSION"
mkdir -p "$RELEASE_DIR"  # timeout: 5000

# Symlink canonical changelog into release dir — no duplication, single source of truth.
# $CHANGELOG_FILE resolved by Phase 2b Audit changelog step.
ln -sf "$(realpath "$CHANGELOG_FILE")" "$RELEASE_DIR/CHANGELOG.md"

# Overwrite guard — back up any existing release artifacts before re-running prepare.
# Re-running /release prepare for the same version is legitimate (post-audit-fix retry),
# but silently overwriting hand-edited notes is destructive.
# CHANGELOG.md excluded — symlink; re-linking on re-run is safe and intentional.
for f in HIGHLIGHTS.md DRAFT.md SUMMARY.md MIGRATION.md demo.py; do
    if [ -f "$RELEASE_DIR/$f" ]; then
        cp "$RELEASE_DIR/$f" "$RELEASE_DIR/$f.bak"
        echo "⚠ $RELEASE_DIR/$f exists — backed up to $f.bak before overwrite"
    fi
done
```

**a. Identify highlights** — apply **Identify highlights** logic using classified changes from `$GATHER_FILE`: rank top 3–5 most significant changes (breaking > new public API > major UX > notable fixes), pull one concrete code example per highlight from diff output. Write to `releases/$VERSION/HIGHLIGHTS.md`. This document is source of truth for demo, executive summary, and release draft spotlights.

**b. Draft migration guide** — apply **Draft migration guide** logic using breaking/deprecated changes from `$GATHER_FILE`. No breaking changes → single line: `No breaking changes in this release.` Shepherd voice review applies. Write to `releases/$VERSION/MIGRATION.md`.

### Phase 4: Demo and summary

**a. Demo notebook** — reuse `$GATHER_FILE` and `releases/$VERSION/HIGHLIGHTS.md` from Phase 3. Apply demo generation logic from **Mode: demo**, Phase 2 (Generate demo script). Output path:

```bash
DEMO_OUT="releases/$VERSION/demo.py"
```

Write generated script to `$DEMO_OUT` using Write tool. **Execution gate** — run:
```bash
python3 "$DEMO_OUT"  # timeout: 600000
```
Fix and re-run until script exits 0 and prints expected output. Do not proceed to 4b until gate passes.

**b. Executive summary** — apply **Draft executive summary** logic using `releases/$VERSION/HIGHLIGHTS.md` and demo output. Write to `releases/$VERSION/SUMMARY.md`.

### Phase 5: Write release draft

`releases/$VERSION/DRAFT.md` — final assembly. Source: `releases/$VERSION/HIGHLIGHTS.md` (spotlights), `releases/$VERSION/MIGRATION.md`, `releases/$VERSION/SUMMARY.md`. Apply **Write release draft** logic (release-draft.md format). Adversarial review applies (use `$GATHER_FILE` from Phase 2a as gather context). Shepherd voice review applies.

### Output

```markdown
## Release prepare: $VERSION

### Audit
[readiness table from Phase 1, condensed]
[any warnings carried forward]

### Written
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
4. On merge: create GitHub release from DRAFT.md
5. Convert demo: `jupytext --to notebook releases/$VERSION/demo.py`
```

End terminal response (not the written artifacts) with `## Confidence` block per CLAUDE.md output standards: `**Score**: 0.0–1.0 — [label]`; omit Refinements if 0 passes.
