---
name: release
description: 'Prepare release communication and check release readiness. Main mode: notes with optional flags --changelog, --summary, --migration; range as v1->v2. Other modes: prepare (full pipeline: audit → all artifacts), audit (pre-release readiness check: blockers, docs alignment, version consistency, CVEs), demo (story-telling release notebook in jupytext # %% format). Use whenever the user says "prepare release", "write changelog", "what changed since v1.x", "prepare v2.0", "write release notes", "am I ready to release", "check release readiness", or wants to announce a version to users.'
argument-hint: '[notes] [v1->v2] [--changelog] [--summary] [--migration] | prepare <version> | audit [version] | demo [range]'
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, TaskCreate, TaskUpdate, Agent, AskUserQuestion
model: opus
effort: high
when_to_use: 'Use when the user says "prepare release", "write changelog", "what changed since vX.Y", "write release notes", "am I ready to release", "check release readiness", or wants to announce a version to users.'
---

<objective>

Prepare release communication from what changed. Output adapts to audience — user-facing notes, CHANGELOG entry, internal summary, or migration guide.

NOT for ecosystem impact analysis without a release (use oss:analyse). NOT for contributor communication or post-release announcements (use oss:shepherd). NOT for retrospective analysis of past releases (audit mode checks forward readiness only — historical review belongs in oss:analyse).

</objective>

<inputs>

Mode comes **first**; range or flags follow:

| Invocation | Arguments | Writes to disk |
| --- | --- | --- |
| `/release [notes] [range]` | optional range (default: last-tag..HEAD); use `v1->v2` for explicit range | `DRAFT.md` |
| `/release notes [range] --changelog` | optional range + flag | `DRAFT.md` + prepends `CHANGELOG.md` |
| `/release notes [range] --summary` | optional range + flag | `DRAFT.md` + `.temp/output-release-summary-<branch>-<date>.md` |
| `/release notes [range] --migration` | optional range + flag | `DRAFT.md` + `.temp/output-release-migration-<branch>-<date>.md` |
| `/release notes [range] --changelog --summary --migration` | all flags | All four outputs |
| `/release prepare <version>` | version to stamp, e.g. `v1.3.0` | All artifacts in `releases/<version>/`: `DRAFT.md` + `CHANGELOG.md` + `SUMMARY.md` + `MIGRATION.md` + `demo.py` |
| `/release audit [version]` | optional target version | Terminal readiness report; emits `verdict: READY | NEEDS_ATTENTION | BLOCKED` as final line for orchestrator consumption |
| `/release demo [range]` | optional range (default: last-tag..HEAD) | `releases/<version>/demo.py` or `.temp/release-demo-<branch>-<date>.py` |

Range notation: `v1->v2` (e.g. `v1.2->v2.0`) — converted internally to git range. No mode given → defaults to `notes`. Flags add outputs alongside notes. `prepare` = full pipeline — runs audit first, then all artifacts; use when cutting release, not drafting.

</inputs>

<workflow>

**Task hygiene**: Call `TaskList`; triage found tasks (`completed` / `deleted` / `in_progress`).

**Task tracking** — create ALL tasks upfront at invocation, then execute sequentially; mark completed as each phase finishes. After mode detection, mark tasks that do not apply to the active mode as `deleted`:
- `demo` mode: mark deleted — Classify each change, Audit changelog, Extract contributors, Draft migration guide, Draft executive summary, Write release draft
- bug-fix-only release (no 🚀 Added items): mark deleted — Generate release demo

Tasks:
- Gather changes (git log + find common base tag)
- Explore codebase (changed files, impl detail)
- Validate docs alignment
- Classify each change
- Audit changelog
- Extract contributors
- Identify highlights
- Draft migration guide
- Generate release demo (feature releases only)
- Draft executive summary
- Write release draft

**Sequential enforcement**: never begin a phase until all prior phases have their task marked `completed`. Process one phase at a time. If any phase fails (empty range, git error, demo execution failure), stop and report to user — do not attempt downstream phases.

## Delegation strategy

Gather + explore + validate phases produce large git/PR output that bloats main context. In `prepare` and `audit` modes, delegate these phases to a subagent via file-based handoff (CLAUDE.md §2):

1. Pre-compute gather file path and create dir:
   ```bash
   # BRANCH and DATE defined in Shared setup block below — see next section
   GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
   mkdir -p .temp  # timeout: 5000
   ```
2. Spawn `Agent(subagent_type="general-purpose")` — expand `$REPO_ROOT`, `$RANGE`, `$GATHER_FILE` to their literal values (REPO_ROOT and GATHER_FILE defined in Shared setup; RANGE set in Gather changes phase) before spawning:
   ```text
   Agent(subagent_type="general-purpose", prompt="Working directory: <REPO_ROOT>. Run all git commands from that directory (use: git -C <REPO_ROOT> <cmd> or cd <REPO_ROOT> first). For git range <RANGE>:
   Run gather phase: git log, git diff --stat, gh pr list.
   Run classify phase on all commits and PR data.
   Run explore phase: top 3–5 most significant changed files (read actual diffs).
   Write full findings — commit list, classified change table, diff excerpts — to <GATHER_FILE> using the Write tool.
   Return ONLY: {\"status\":\"done\",\"file\":\"<GATHER_FILE>\",\"changes\":N,\"breaking\":N,\"confidence\":0.N}")
   ```
3. Validate envelope and pass file path downstream:
   - Parse the `file` field using: `GATHER_FILE=$(echo "$ENVELOPE" | jq -r '.file' 2>/dev/null)`
   - Assert `status == "done"`; if not or if parse fails, abort with clear error message
   - If `breaking` field absent from envelope, default to `0` — do not skip migration guide on missing field
   - Verify `[ -f "$GATHER_FILE" ]` before passing path to artifact phase; abort if file missing
   - Pass `file` path to artifact phase — do NOT read the gather file into main context; artifact agent reads it directly

`notes` and `demo` modes: skip delegation — single-pass; run gather/explore/validate inline.

## Mode Detection

Parse `$ARGUMENTS` by first token:

```bash
read FIRST REST <<<"$ARGUMENTS"

# Range-first detection: if FIRST looks like a range (contains -> or ..),
# force notes mode and reframe args so the shared flag-parse loop runs over the
# whole tail (REST). Without this, "/release v1->v2 --changelog" falls to the
# default route which assigns RANGE="$ARGUMENTS" verbatim — leaving --changelog
# embedded inside the range string and the flag silently ignored.
if [[ "$FIRST" == *"->"* ]] || [[ "$FIRST" == *".."* ]]; then
    MODE="notes"
    REST="$FIRST $REST"   # re-include FIRST so the flag loop discovers the range as a non-flag token
    FIRST="notes"
fi
```

| First token | Mode | Routing |
| --- | --- | --- |
| `prepare` | prepare | Skip to **Mode: prepare** |
| `audit` | audit | Skip to **Mode: audit** |
| `demo` | demo | Skip to **Mode: demo** |
| `notes` | notes | Parse flags and range from `$REST`; run all phases |
| *(bare range — handled above by range-first detection)* | notes | Falls through to `notes` route after `FIRST` is rewritten |
| *(none)* | notes | `RANGE=""`, no flags; run all phases |

After matching `notes`, parse flags from `$REST`:

```bash
DO_CHANGELOG=false; DO_SUMMARY=false; DO_MIGRATION=false; RANGE=""
for arg in $REST; do
  case "$arg" in
    --changelog)  DO_CHANGELOG=true ;;
    --summary)    DO_SUMMARY=true ;;
    --migration)  DO_MIGRATION=true ;;
    *)            RANGE="$arg" ;;
  esac
done
# Convert v1->v2 shorthand to git range notation
RANGE="${RANGE/->/../}"
```

**Unsupported flag check** — after all supported flags extracted, scan `$ARGUMENTS` for any remaining `--<token>` tokens. If any found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--changelog\`, \`--summary\`, \`--migration\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke with correct flags) · (b) **Continue ignoring** (skip unknown flags, proceed). On Abort: stop.

## Shared setup

```bash
# Locate oss plugin shared dir — installed first, local workspace fallback
# sort -V orders semver correctly (0.9.0 < 0.10.0); tail -1 picks newest
_OSS_SHARED=$(ls -d ~/.claude/plugins/cache/borda-ai-rig/oss/*/skills/_shared 2>/dev/null | sort -V | tail -1)
[ -z "$_OSS_SHARED" ] && _OSS_SHARED="plugins/oss/skills/_shared"
# Resolve skill directory — used by all modes for templates and guidelines
SKILL_DIR="$(find ~/.claude/plugins -path "*/oss/skills/release" -type d 2>/dev/null | head -1)"  # timeout: 5000
[ -z "$SKILL_DIR" ] && SKILL_DIR="plugins/oss/skills/release"
REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")  # timeout: 3000
# BRANCH and DATE — computed once here; all phases use these variables, never re-compute
BRANCH=$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')
DATE=$(date +%Y-%m-%d)
# Branch-aware range detection — sets LAST_TAG for all modes
# rc/dev/alpha/beta tags excluded — base must be last stable release
BRANCH_TAG=$(git describe --tags --abbrev=0 --first-parent --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null)
if [ -n "$BRANCH_TAG" ]; then
    LAST_TAG="$BRANCH_TAG"
    CHERRY_PICK_SUBJECTS=""
    SOURCE_TAG_REF=""
else
    SOURCE_TAG=$(git describe --tags --abbrev=0 --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' 2>/dev/null)
    if [ -z "$SOURCE_TAG" ]; then
        SOURCE_TAG=$(git rev-list --max-parents=0 HEAD)
        echo "ℹ No stable tags found — using initial commit as range base (first release; range covers full history)"
    fi
    SOURCE_COMMIT=$(git rev-list -n1 "refs/tags/$SOURCE_TAG" 2>/dev/null || echo "$SOURCE_TAG")
    COMMON_COMMIT=$(git merge-base HEAD "$SOURCE_COMMIT" 2>/dev/null)
    [ -z "$COMMON_COMMIT" ] && { echo "Warning: no common ancestor found — range may span full history"; COMMON_COMMIT=$(git rev-list --max-parents=0 HEAD 2>/dev/null || echo ""); }
    LAST_TAG=$(git describe --tags --abbrev=0 --exclude='*rc*' --exclude='*dev*' --exclude='*alpha*' --exclude='*beta*' "$COMMON_COMMIT" 2>/dev/null || echo "$COMMON_COMMIT")
    CHERRY_PICK_SUBJECTS=$(git log "$LAST_TAG..$SOURCE_TAG" --no-merges --format="%s" 2>/dev/null)
    SOURCE_TAG_REF="$SOURCE_TAG"
    echo "ℹ Stable-branch mode: base=$LAST_TAG  source=$SOURCE_TAG"
fi
```

## Gather changes

Find common base tag across ALL branches (not just current branch). Strategy: `git tag --list` sorted by version, then `git merge-base HEAD <tag-commit>` to find deepest common ancestor with current branch tip. Use as lower bound of commit range when current branch has no direct tag ancestry.

```bash
# LAST_TAG and CHERRY_PICK_SUBJECTS set in Shared setup — use directly
RANGE="${RANGE:-$LAST_TAG..HEAD}"
[ -z "$RANGE" ] && echo "Error: could not determine commit range" && exit 1

# One-liner overview (navigation index)
git log $RANGE --oneline --no-merges # timeout: 3000

# Full commit messages — read these to catch BREAKING CHANGE footers,
# co-authors, and details omitted from the subject line
git log $RANGE --no-merges --format="--- %H%n%B" # timeout: 3000

# File-level diff stat — confirms what areas actually changed
git diff --stat "$(echo "$RANGE" | sed 's/\.\.\./\ /;s/\.\./\ /')" # timeout: 3000

# PR titles, bodies, and labels for merged PRs (richer context than commits)
TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | { read -r _ _ val; echo "${val:-main}"; })
# timeout: 15000
gh pr list --state merged --base "${TRUNK:-main}" --limit 500 \
    --json number,title,body,labels,mergedAt,author 2>/dev/null
```

Cross-reference commit bodies against Pull Request (PR) descriptions — canonical source of truth for *why* change was made. `BREAKING CHANGE:` footer = breaking change regardless of PR label.

**Detect revert pairs**: scan full commit messages from `git log $RANGE --no-merges --format="%H %s"` for subjects beginning with `Revert "`. For each such commit:
1. Extract original subject from between the quotes.
2. Search remaining commits in range for a commit whose subject matches (or closely matches) the extracted subject.
3. If both original and revert commit are found within range → they form a `REVERT_SET` pair: net effect is zero.

Record all `REVERT_SET` pairs before entering Classify. Commits in `REVERT_SET` are excluded from all standard sections (Added, Fixed, etc.) and instead collected for the 🔄 Reverted section. If only the revert is in range (original predates range) → the feature WAS shipped in a prior release and is now gone; classify as ❌ Removed (or ⚠️ Breaking Changes if API surface changed without a prior deprecation period) — NOT 🔄 Reverted, because the net user effect is non-zero: something they relied on is missing.

## Explore codebase

For top 3–5 most significant changes (features, breaking, major behavior), read actual diff or changed files:

```bash
git diff $RANGE -- <file>    # timeout: 3000
git show <commit>:<file>     # timeout: 3000
```

Goal: understand what change actually does at implementation level — new APIs, parameters, behavior — so notes describe real functionality, not just commit subjects.

Skip for trivial changes (typos, dep bumps, CI config).

## Validate docs

Check public API surface documented in docs/ (or README) matches what changed in diff. Flag any public symbol added/renamed/removed in Gather changes commits that is absent from docs. Report as bulleted list: `- [MISSING/STALE] <symbol> in <doc-file>`. Empty list = docs aligned.

## Classify each change

Section order (fixed — never reorder): 🚀 Added → ⚠️ Breaking Changes → 🌱 Changed → 🗑️ Deprecated → ❌ Removed → 🔧 Fixed → 🔒 Security → 🔄 Reverted

| Category | Output section | What goes here |
| --- | --- | --- |
| **New Features** | 🚀 Added | User-visible additions |
| **Breaking Changes** | ⚠️ Breaking Changes | Existing code **stops working immediately** after upgrade — API removed or signature changed with **no prior deprecation period**. If the API was marked deprecated in a prior release, classify as ❌ Removed instead. Must be 100% certain it no longer works and users had no warning. |
| **Improvements** | 🚀 Added or 🌱 Changed | Enhancements to existing behavior |
| **Performance** | 🚀 Added or 🔧 Fixed or 🌱 Changed | Speed or memory improvements. Use 🔧 Fixed if it corrects a regression, use 🚀 Added if it's a new optimization feature, use 🌱 Changed if it's a refactor for efficiency. **Quantitative claims** ("2× faster", "50% less memory") require evidence from PR body or benchmark artifacts — unsubstantiated claims from commit subjects alone → rewrite to "improved performance" without the number (see `guidelines/numbers-reference.md`). |
| **Deprecations** | 🗑️ Deprecated | Old API **still works** this release but is scheduled for removal — emits a warning, replacement exists |
| **Removals** | ❌ Removed | Previously deprecated API now gone — was marked 🗑️ Deprecated in a prior release, users had fair warning. Not classified as ⚠️ Breaking Changes. |
| **Bug Fixes** | 🔧 Fixed | Correctness fixes |
| **Security** | 🔒 Security | Security fixes and vulnerability patches — omit CVE numbers in public notes; link to advisory if public |
| **Internal** | *(omit)* | Refactors, CI/tooling, deps, code cleanup, developer-facing housekeeping — omit unless directly user-impacting |
| **Reverted** | 🔄 Reverted | Introduced AND reverted within range (REVERT_SET pairs) — net effect zero; list as "Reverted: <original description>"; do NOT classify original change in any other section; omit from highlights, demo, and migration guide |

**Breaking vs Deprecated vs Removed**: old call still works (even with warning) → Deprecated, never Breaking. API was deprecated in prior release and now removed → Removed, never Breaking — users had fair warning. Breaking = upgrade causes immediate failures with **no prior deprecation period** between two consecutive versions.

Filter out: merge commits, minor dep bumps, CI/tooling config, comment typos, internal refactors, code cleanup, internal-only dep bumps, developer housekeeping, no-user-impact changes. **Never include internal staff names or internal maintenance details in public-facing output.** Always include: breaking changes, behavior changes, new API surface.

**Cherry-pick annotation (stable-branch mode)**: when `$CHERRY_PICK_SUBJECTS` is set (populated in gather phase for stable/bug-fix branches), check each commit's subject against it. Match → commit is a backport from `$SOURCE_TAG_REF`; append "(backported from $SOURCE_TAG_REF)" to the classification entry. No match → fix is original to this stable branch; no annotation needed.

## Truth check

Gate — runs after Classify, before Audit changelog. Verifies each classified change actually exists in HEAD (codebase is the source of truth, not commit messages).

**Scope**: apply to all changes classified as 🚀 Added, ⚠️ Breaking Changes, or 🌱 Changed that introduce or remove a named symbol (function, class, CLI flag, config key). Skip: 🔧 Fixed (absence of bug is not greppable), 🔒 Security, 🗑️ Deprecated (still present by definition), ❌ Removed (confirmed absent by removal logic), 🔄 Reverted (already excluded from net changes).

**For each in-scope classified change**:

```bash
# For additions — confirm symbol present in implementation files at HEAD
# Restrict to src/ directories; docs/, tests/, CHANGELOG exclude (they document, not implement)
git grep -l "<symbol_name>" HEAD -- 'src/**' '*.py' '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null || \
  git grep -l "<symbol_name>" HEAD -- . --exclude-dir=docs --exclude-dir=tests --exclude-dir=.github  # timeout: 3000
# For removals / breaking changes — confirm symbol absent from implementation at HEAD
git grep -l "<symbol_name>" HEAD -- 'src/**' '*.py' '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null && echo "PRESENT (unexpected)" || echo "ABSENT (confirmed)"  # timeout: 3000
# For behavior changes — read the relevant file at HEAD and confirm the changed code path
git show HEAD:<changed_file> | grep -n "<distinguishing_pattern>"  # timeout: 3000
```

**Outcomes**:
- Confirmed present → keep in classified section; note "truth-checked"
- Not found in HEAD → change was reverted after range end (post-range revert), or was merged to a different branch; move entry from its section to ⚠️ Unconfirmed with note: "classified from commit history but not found in HEAD — verify before publishing"; do NOT include in highlights or demo
- Cannot determine (e.g. behavioral change without greppable symbol) → keep classification; add "(not verified)" qualifier to the entry

**Gate rule**: at least the top 3 most significant classified changes (breaking, new public API) must pass truth check before proceeding to Identify highlights. If any top-3 change moves to ⚠️ Unconfirmed, flag for user review before continuing — do not silently drop.

## Audit changelog

Locate project changelog — search in order: `CHANGELOG.md` at repo root, `docs/CHANGELOG.md`, any `CHANGELOG*` file under repo root (one level deep). Store resolved path as `$CHANGELOG_FILE`. Mode does not change search order — always prefer existing project changelog regardless of mode.

If exists: cross-check classified changes against existing entries for current unreleased section. Items classified in Classify each change but absent from CHANGELOG → add them (use same emoji-prefixed format already in file). Items in CHANGELOG that don't match any classified change → flag for review (do not delete automatically).

**Reverted-entry handling**: for each REVERT_SET pair, add a `🔄 Reverted` entry: `🔄 Reverted: <original change description> (introduced and reverted in this release)`. If the original change was already written to CHANGELOG before the revert (e.g. during earlier drafting), strike or remove it from the main section and add the Reverted entry instead — a change that did not ship must not appear as shipped. Items in CHANGELOG marked as Reverted are never promoted to highlights or migration guide.

If missing: create `CHANGELOG.md` at repo root; set `$CHANGELOG_FILE` to that path. Populate with `# Changelog` header and `## [Unreleased]` section from Classify each change.

Always report: "N items added to changelog, M items flagged for review."

**Working document**: this phase owns the CHANGELOG-format classification (emoji-prefixed sections, `# Changelog` header). The Write release draft phase reads from this classification — it does NOT copy it. DRAFT.md uses a different format (see Write release draft template).

## Extract contributors

```bash
# All commit authors and co-authors in range
git log $RANGE --no-merges --format="%aN <%aE>%n%(trailers:key=Co-authored-by,valueonly)" \
  | grep -v '^$' | sort -u  # timeout: 3000
```

Deduplicate by email. Exclude bot accounts (e.g. `[bot]`, `noreply@`).

For each unique contributor, inspect their commits in range (`git log $RANGE --no-merges --author="<email>" --oneline`) and summarize contribution in 3–6 words — what area or feature they worked on. No PR numbers, no links.

Format per contributor: `- **Name** — <brief what they did>` (e.g. `- **Alice** — added streaming API`, `- **Bob** — fixed CUDA memory leak`).

## Identify highlights

From Classify each change, identify top 3–5 most significant changes for release. Significance ranking: breaking changes > new public API > major UX improvements > notable fixes > everything else. For each highlight, pull one concrete code example from explore-codebase diff output. These spotlights drive Summary paragraph and Spotlights section of draft.

## Draft migration guide

Always produce migration guide section. If no breaking changes exist: single line "No breaking changes in this release." If deprecations or removals exist: show before→after code examples for each. Note: releases should not introduce ⚠️ Breaking Changes without a prior deprecation period. API deprecated in prior release and now removed → classify as ❌ Removed (not Breaking) — state this distinction in guide preamble.

## Generate release demo

**Only for feature releases** (Classify each change has ≥1 new 🚀 Added items). For bug-fix-only releases: skip this step.

Generate self-contained Python script in jupytext percent (`# %%`) format. Based on Identify highlights spotlights. Full story: install → setup → demonstrate each highlight → verify output.

```bash
# BRANCH and DATE set in Shared setup block above
# notes mode: always write to .temp/ — $LAST_TAG is the PREVIOUS release, not the one being drafted
DEMO_OUT=".temp/release-demo-$BRANCH-$DATE.py"
mkdir -p .temp  # timeout: 5000
```

Write demo to `$DEMO_OUT`. (`prepare` mode: `releases/$VERSION/demo.py` — see Phase 4.)

**Gate: demo must execute to completion with expected outputs before proceeding to Draft executive summary.** Run:
```bash
python3 "$DEMO_OUT"  # timeout: 600000
```
If execution fails: fix and re-run. Do not proceed until script exits 0 and prints expected output. Self-contained rules: package under release is installed in current env; no live API calls or network deps; deterministic synthetic data; `# !pip install` lines are Python comments — interpreter skips them.

## Draft executive summary

Write 1–2 paragraph executive summary suitable for team announcement or PR description. Covers: what this release is, why it matters, who benefits. Based on Identify highlights output.

Save to `.temp/output-release-summary-$BRANCH-$DATE.md`. (`BRANCH` and `DATE` from Shared setup block.)

## Write release draft

Pre-flight — verify all templates present before proceeding:

```bash
# $SKILL_DIR resolved in Shared setup block above
[ -z "$SKILL_DIR" ] && echo "Error: could not locate release skill directory" && exit 1
for tmpl in release-draft.tmpl.md changelog.tmpl.md summary.tmpl.md migration.tmpl.md audit-checks.md; do # timeout: 5000
    [ -f "$SKILL_DIR/templates/$tmpl" ] || {
        echo "Missing template: $tmpl — aborting"
        exit 1
    }
done
```

Before writing, fetch last 2–3 releases to check project-specific formatting conventions:

```bash
gh release list --limit 5                                                  # timeout: 30000
LATEST_TAG=$(gh release list --limit 100 --json tagName --jq '[.[] | select(.tagName | test("rc|dev|alpha|beta"; "i") | not)] | .[0].tagName // empty') # timeout: 30000
[ -z "$LATEST_TAG" ] || [ "$LATEST_TAG" = "null" ] && echo "No releases found — using template defaults" || gh release view "$LATEST_TAG"  # timeout: 15000
```

Existing releases deviate from templates → match their tone and prose style only. **Never** adopt `# Changelog` or CHANGELOG section structure for DRAFT.md — always use the release notes template structure (`release-draft.tmpl.md`) regardless of existing release format. Template = default structure; project conventions take precedence for prose/tone only. `gh release list` returns empty → skip style-matching step; proceed with template defaults.

Fetch origin URL for full changelog link:
```bash
ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")  # timeout: 3000
```

**DRAFT.md format guard**: DRAFT.md must NOT start with `# Changelog` and must NOT use CHANGELOG section structure. The CHANGELOG-format classification produced by the Audit changelog phase is an internal working document only — derive the sections below from it, do not copy it verbatim to DRAFT.md.

Read release draft template from `$SKILL_DIR/templates/release-draft.tmpl.md` and use as format. Replace `[org]/[repo]` with actual values from `$ORIGIN_URL` at runtime. Omit sections with no content.

Key differences from `prepare`: all phases run inline (no subagent delegation), output to `DRAFT.md` and root `CHANGELOG.md`. Use the CHANGELOG-format classification from the Audit changelog phase as source material — write DRAFT.md in the release notes template format above, not in CHANGELOG format.

### CHANGELOG Entry (`--changelog` flag)

Read CHANGELOG entry template from $SKILL_DIR/templates/changelog.tmpl.md and use as format.

### Internal Release Summary (`--summary` flag)

Read internal release summary template from $SKILL_DIR/templates/summary.tmpl.md and use as format.

### Adversarial review

Challenge every factual claim in the assembled draft against the actual codebase and project docs. Runs before voice/tone polish — facts must be correct before prose is refined.

**Scope**: applies to `notes` mode (DRAFT.md) and `prepare` mode (releases/$VERSION/DRAFT.md) and `--migration` flag output. Skip for `--summary` (internal audience) and `--changelog` entries (structured format, not claim-heavy prose).

```bash
# Adversarial review run dir — expand to literal value before spawning
ADVERSARIAL_DIR=".temp/release-adversarial-$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')-$(date +%Y-%m-%d)"
mkdir -p "$ADVERSARIAL_DIR"  # timeout: 5000
```

Write full assembled draft content to `$ADVERSARIAL_DIR/draft-to-review.md` using Write tool.

Spawn adversarial reviewer:

```text
Agent(subagent_type="general-purpose", prompt="Adversarial review of a release draft against the project codebase and docs. Working directory: <REPO_ROOT>.

Read the release draft at: <$ADVERSARIAL_DIR/draft-to-review.md>

Challenge across 4 dimensions — treat every claim as unproven until verified:

1. FACTUAL ACCURACY — for every claim ('adds X', 'fixes Y', 'removes Z', 'improves performance'), verify against HEAD: git grep or read the relevant file. Quote the file:line that confirms or refutes. A claim with no verifiable trace in HEAD = finding.
2. COMPLETENESS — <gather context below>: significant commits (breaking changes, new public API) not mentioned in draft = finding. Minor/internal commits being absent is expected.
3. SEMVER CORRECTNESS — if draft says 'no breaking changes', scan for removed or renamed public API, changed function signatures, removed config keys using git diff. Flag any contradiction.
4. DOCS ALIGNMENT — for each new API or behavior claimed in draft, confirm docs/ or README covers it. Missing doc = finding.

<gather context>
$([ -n \"<GATHER_FILE>\" ] && [ -f \"<GATHER_FILE>\" ] && echo 'Full commit/PR classification in: <GATHER_FILE> — read it for the ground-truth change list.' || echo 'Use the git range <RANGE> directly: git log <RANGE> --no-merges --oneline to get the change list.')
</gather context>

For each finding: severity (critical=claim directly contradicts codebase | high=significant missing change or SemVer misclassification | medium=overstated claim or minor missing item | low=style/wording inaccuracy). For critical and high findings: quote exact draft text and quote codebase evidence.

Write full findings report to <$ADVERSARIAL_DIR/adversarial-review.md> using the Write tool.
Return ONLY on your final line: {\"status\":\"done\",\"file\":\"<$ADVERSARIAL_DIR/adversarial-review.md>\",\"critical\":N,\"high\":N,\"medium\":N,\"low\":N,\"confidence\":0.N}")
```

Expand `<REPO_ROOT>`, `<RANGE>`, `<GATHER_FILE>`, `<$ADVERSARIAL_DIR>` to their literal values before spawning — never pass variable names literally.

**Gate — read `$ADVERSARIAL_DIR/adversarial-review.md`**:
- **Critical or high findings**: fix in draft before proceeding; re-run adversarial review on fixed sections once (max 1 re-run); if findings persist after re-run, surface to user and stop
- **Medium or low findings**: append as `> ⚠️ Reviewer notes: <summary>` to the response; include in Human gate handoff; do not block Polish step
- **0 findings**: proceed directly to Polish

### Polish and write to disk

Read writing guidelines from $SKILL_DIR/guidelines/writing-rules.md and follow them. If file absent, proceed without style guidelines.

After polishing, dispatch shepherd for public-facing voice/tone review of full release draft before writing to disk. Check availability first:

```bash
# Check oss:shepherd availability (may not be installed in partial setups)
SHEPHERD_AVAILABLE=0
find ~/.claude/plugins -name "shepherd.md" -path "*/oss/agents/*" 2>/dev/null | grep -q . && SHEPHERD_AVAILABLE=1
[ -f ".claude/agents/shepherd.md" ] && SHEPHERD_AVAILABLE=1
# Pre-compute shepherd run dir (file-handoff protocol)
SHEPHERD_DIR=".temp/release-shepherd-$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')-$(date +%Y-%m-%d)"
mkdir -p "$SHEPHERD_DIR"  # timeout: 5000
# Write the generated draft content to: $SHEPHERD_DIR/draft.md before dispatching
# IMPORTANT: expand $SHEPHERD_DIR to its literal computed value before inserting into the spawn prompt — do not pass the variable name literally.
```

If `$SHEPHERD_AVAILABLE` equals 1, write full Write release draft output to `$SHEPHERD_DIR/draft.md`, then spawn shepherd:

```text
Agent(subagent_type="oss:shepherd", prompt="Review the full release draft at <$SHEPHERD_DIR/draft.md> for public-facing voice and tone. Apply shepherd voice guidelines: human and direct, no internal jargon, no staff names, no internal maintenance details. Write the revised content to <$SHEPHERD_DIR/shepherd-revised.md>. Return ONLY: {\"status\":\"done\",\"changes\":N,\"file\":\"<$SHEPHERD_DIR/shepherd-revised.md>\"}")
```

If `oss:shepherd` not available, use draft content directly — skip shepherd review.

Read `$SHEPHERD_DIR/shepherd-revised.md` → use as final content for disk write. Shepherd runs once per invocation — full release draft (Write release draft output) is the shepherd input.

Write to disk: (`BRANCH` and `DATE` from Shared setup block.)

Shepherd review policy (applies when `$SHEPHERD_AVAILABLE == 1`):
- **notes** (always): shepherd review → write to `DRAFT.md` at repo root. Notify: `→ written to DRAFT.md`
- **`--changelog`** (if set): no shepherd (structured format, internal audience) → prepend to `CHANGELOG.md` after `# Changelog` heading (create file if missing). Notify: `→ prepended to CHANGELOG.md`
- **`--summary`** (if set): no shepherd (internal audience) → Draft executive summary already saved to `.temp/output-release-summary-$BRANCH-$DATE.md` — confirm written. Notify: `→ saved to .temp/output-release-summary-<branch>-<date>.md`
- **`--migration`** (if set): shepherd review (public-facing) → save to `.temp/output-release-migration-$BRANCH-$DATE.md`. Notify: `→ saved to .temp/output-release-migration-<branch>-<date>.md`

**Human gate** — stop and hand off to user after writing files: GitHub release must be created with project-level tooling (`gh release create`). See `$_OSS_SHARED/release-checklist.md` for exact release steps.

End response with `## Confidence` block per CLAUDE.md output standards.

## Mode: prepare

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

`releases/$VERSION/DRAFT.md` — final assembly. Source: `releases/$VERSION/HIGHLIGHTS.md` (spotlights), `releases/$VERSION/MIGRATION.md`, `releases/$VERSION/SUMMARY.md`. Apply **Write release draft** logic (release-draft.tmpl.md format). Adversarial review applies (use `$GATHER_FILE` from Phase 2a as gather context). Shepherd voice review applies.

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

## Mode: audit

**Trigger**: `/release audit [version]`

**Purpose**: Pre-release readiness check — surfaces outstanding work, alignment gaps, and blockers before cutting release.

```bash
# LAST_TAG, REPO_ROOT, SKILL_DIR resolved in Shared setup block above
RANGE="${RANGE:-$LAST_TAG..HEAD}"
```

### Phase A: Gather and explore changes

Use **Delegation strategy** above — spawn gather subagent for `$RANGE` to run gather/explore/validate phases and write findings to `GATHER_FILE`. Read returned JSON envelope only. Audit agent (Phase B) reads `GATHER_FILE` directly — do not pull into main context.

### Phase B: Readiness checks

Read and execute all checks from `$SKILL_DIR/templates/audit-checks.md`. Checks cover: version consistency across manifests, docs/CHANGELOG alignment, open blocking issues, dependency CVE scan, unreleased commits since last tag.

After readiness table, if issues found, append **Findings summary** table with one row per issue:

| # | Issue | Location | Severity |
| --- | --- | --- | --- |
| 1 | <what is wrong> | <section or file> | critical/high/medium/low |

Ensures every finding has explicit location, severity, and action — matching structured output format of `notes` and `changelog` modes.

### Verdict line (mandatory final output)

After the findings table, print exactly one verdict line immediately before the `## Confidence` block so callers (e.g. `prepare` Phase 1) can pattern-match without parsing prose:

- `verdict: READY` — no CRITICAL or HIGH findings
- `verdict: NEEDS_ATTENTION` — one or more HIGH findings, no CRITICAL
- `verdict: BLOCKED` — one or more CRITICAL findings (also written when readiness checks themselves cannot complete)

Then end response with `## Confidence` block per CLAUDE.md output standards.

## Mode: demo

**Trigger**: `/release demo [range]`

**Purpose**: Story-telling release notebook — self-contained Python script in jupytext percent (`# %%`) format. Highlights the 2–3 most significant contributions with narrative prose and runnable code cells. Suitable for Colab, local Jupyter, or blog embeds.

```bash
# LAST_TAG, REPO_ROOT, SKILL_DIR resolved in Shared setup block above
RANGE="${REST:+${REST/->/../}}"
RANGE="${RANGE:-$LAST_TAG..HEAD}"
# BRANCH, DATE from Shared setup block above
```

### Phase 1: Gather and pick headline features

Run gather/explore/validate inline for `$RANGE` (no delegation — demo is single-pass like `notes` mode). Use the same commands as the **Gather changes** section above (git log, gh pr list). For diff stat, prefer three-dot range to include all commits merged on the release branch:

```bash
git diff --stat "$(echo "$RANGE" | sed 's/\.\./.../')"  # three-dot range preferred; timeout: 3000
```

From the gathered commits and diffs, select 2–3 headline features:
- Prefer: new public API, breaking changes, significant performance wins, major UX improvements
- Exclude: internal refactors, CI/tooling, dep bumps, doc-only changes

For each headline feature, read the actual diff or changed source file to understand the before/after interface — demo cells must show real API, not a paraphrase.

### Phase 2: Generate demo script

**Real-world data constraint**: demo must use actual project artifacts, real API calls against the package under release, or genuine example data already present in the repo. Fabricated or synthetic inputs are not acceptable by default. Sources in priority order: repo test fixtures, example scripts shipped with package, public datasets referenced in project docs, real CLI invocations against installed package.

**Fallback protocol — if a real demo cannot be assembled** (e.g. no usable fixtures, installed package not functional, API requires live credentials): before writing any synthetic script, execute these steps in order:

1. **Document each failed attempt**: output a `## Demo attempts` block to the terminal listing every approach tried and the specific reason it was rejected (e.g. "test fixtures require database connection", "example script imports non-installable C extension"). Minimum one entry per attempt.
2. **Ask Codex (if available)**: check `codex` plugin availability; if present, spawn `Agent(subagent_type="codex:codex-rescue")` with the `## Demo attempts` log and ask it to locate or construct a real-world demo from project artifacts. If Codex returns a viable approach, use it — stop here and do not proceed to steps 3–4.
3. **Ask user**: invoke `AskUserQuestion` with the `## Demo attempts` log (and Codex outcome if attempted), asking the user to either provide real-world assets or explicitly approve a synthetic demo.
4. **Synthetic demo only on explicit approval**: proceed with synthetic/fabricated demo content only if the `AskUserQuestion` response in step 3 explicitly authorises it.

Write a Python script in jupytext percent format. Structure in order:

1. **Jupytext header** — read from `$SKILL_DIR/templates/demo-header.tmpl.py` and prepend verbatim as the first block of the generated script.
2. **Title cell** (`# %% [markdown]`):
   - `# <PackageName> <VERSION>: <tagline — one clause per headline feature>`
   - Colab badge placeholder: `[![Open In Colab](...)](<repo-url>/blob/main/releases/<VERSION>/demo.ipynb)`
   - `**What you'll learn:**` — bullet per headline feature
   - `**Sections:**` — numbered TOC with anchor links
   - 2–3 paragraphs of narrative: what this release adds, why it matters; `> **Breaking change:**` blockquote if any breaking changes
3. **Install cell** (`# %%`): `# !pip install <package>==<VERSION>`
4. **Config cell** (`# %%`): all notebook-level constants (`OUTPUT_DIR`, `BATCH_SIZE`, etc.); `num_workers` pattern for macOS/Windows safety if training involved
5. **One section per headline feature** — for each:
   - Markdown cell: `## N. <Feature name>` + prose (before/after, motivation, API shape)
   - Code cell(s): demonstrate the feature; if showing old→new migration, old API in commented block above
   - Verification cell where output confirms the feature works (e.g. print, assertion, plot)
6. **Next steps cell** (`# %% [markdown]`):
   - `## <N+1>. Next steps` header
   - Bullet list: docs link, changelog link (GitHub compare URL), migration guide link if breaking changes, links to prior release demos; use `<placeholder-url>` format — never invent real URLs

Content rules:
- All code must be syntactically valid Python
- Placeholder URLs use `<repo-url>`, `<docs-url>` — never invent real URLs
- Narrative cells explain WHY, not just what — write for a developer who hasn't seen this release
- No class docstrings or multi-line comment blocks in demo code cells; inline `# comments` only
- Breaking changes get both a `> **Breaking change:**` callout in the title cell AND a comparison cell in the relevant section

### Phase 3: Write output

```bash
# BRANCH and DATE from Shared setup block above
# $LAST_TAG is the previous release (range lower bound) — not the release being drafted.
# Write to .temp/ always; prepare mode uses releases/$VERSION/ with the explicit target version.
DEMO_OUT=".temp/release-demo-$BRANCH-$DATE.py"
mkdir -p .temp  # timeout: 5000
```

Write generated script to `$DEMO_OUT` using Write tool.

Notify: `→ written to $DEMO_OUT`

> Convert `.py` → `.ipynb` with `jupytext --to notebook $DEMO_OUT` — user runs this; skill does not execute it.

</workflow>

<notes>

- **Numbers reference**: all numeric limits and claims in this skill are documented with rationale and evidence in `guidelines/numbers-reference.md`; update that file whenever limits change
- **Revert handling**: REVERT_SET pairs (both original and revert in range) = net-zero; appear only in 🔄 Reverted section; never in highlights, demo, migration guide; if only the revert is in range (original predates range) → classify as ❌ Removed or ⚠️ Breaking (not 🔄 Reverted) — from user's perspective the feature is gone from a version it was in
- **Truth check is mandatory**: top-3 classified changes (breaking, new API) must be confirmed present in HEAD before Identify highlights; unconfirmed changes move to ⚠️ Unconfirmed and require user sign-off
- **Adversarial review is mandatory for public-facing output**: runs after draft assembly, before shepherd/polish; critical/high findings block write-to-disk; medium/low included as reviewer notes; skip for internal-only outputs (--summary, --changelog); applies in `notes`, `prepare`, and `--migration` modes
- **Pre-release tag exclusion**: rc, dev, alpha, beta tags are never used as range base — always resolve to last stable release; applies in all modes (notes, prepare, audit)
- Filter noise (CI config, dep bumps, typos) unless user-impacting
- **Public-facing content policy**: release notes, changelogs, migration guides = user-visible changes only. Never include: internal staff names, internal maintenance, internal refactors, CI/tooling changes, internal dep bumps, code cleanup, developer housekeeping with no user impact.
- Public-facing output co-authored with `oss:shepherd` — follow `$_OSS_SHARED/shepherd-voice.md` guidelines for human, direct tone
- **Demo mode output**: jupytext percent format — convert to `.ipynb` with `jupytext --to notebook <file>.py`; placeholder URLs (`<repo-url>`, `<docs-url>`) must be replaced before publishing; Colab badge URL must point to actual notebook after upload
- **Sequential gate**: gather → explore → validate docs → classify → audit changelog → extract contributors → identify highlights → draft migration → demo (feature only, execution gate) → executive summary → write draft — never reorder
- **Demo execution gate**: demo phase blocks executive summary — no draft without executable demo for feature releases; script must exit 0 and print expected outputs before proceeding
- **Demo real-world-only policy**: demo must use actual project data/fixtures/API — synthetic inputs not acceptable without explicit user approval in the same session; mandatory fallback sequence: (1) document each failed attempt in `## Demo attempts` block, (2) ask Codex if available (`Agent(subagent_type="codex:codex-rescue")`), (3) ask user via `AskUserQuestion`, (4) synthetic proceeds only on explicit user approval
- **Changelog audit non-destructive**: adds missing entries, flags extras, never removes existing entries automatically
- Follow-up chains:
  - Readiness check → `/release prepare <version>` runs built-in audit first; use standalone `/release audit [version]` only for readiness check without cutting release
  - Release includes breaking changes → `/oss:analyse` for downstream ecosystem impact
  - Notes/changelog written → see Publish for release-create gate (`gh release create` must be user-run via project tooling)
  - `migration` content written → add to project docs and link from CHANGELOG entry (see inputs table for mode/flag summary)

</notes>

<calibration>

Calibratable modes: notes (classification accuracy), prepare (pipeline completeness), audit (verdict accuracy: READY/NEEDS_ATTENTION/BLOCKED), demo (headline feature selection, narrative quality, code cell correctness).

</calibration>
