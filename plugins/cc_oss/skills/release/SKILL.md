---
name: release
description: "Prepare release communication and check readiness. Main mode: notes with optional flags --changelog, --summary, --migration; range as v1->v2. Other modes: prepare (full pipeline: audit → all artifacts), audit (pre-release readiness: blockers, docs alignment, version consistency, CVEs), demo (story-telling release notebook in jupytext # %% format). TRIGGER when: user requests release notes, CHANGELOG entry, migration guide, internal summary, release readiness audit, or release demo; phrases: 'draft release notes', 'prepare release', 'audit release readiness', 'generate CHANGELOG for v1->v2', 'release demo notebook'. SKIP: actual git tagging or PyPI/registry upload (use git tag, gh release create, twine upload directly); release communication for a non-Python project where this skill's pytest-centric audit assumptions do not apply; PR-level review (use /oss:review); thread/issue analysis (use /oss:analyse)."
argument-hint: "[notes] [v1->v2] [--changelog] [--summary] [--migration] | prepare <version> | audit [version] | demo [range]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, TaskList, TaskCreate, TaskUpdate, Agent, AskUserQuestion
model: sonnet
effort: high
---

<objective>

Prepare release communication from changes. Output adapts to audience — user-facing notes, CHANGELOG entry, internal summary, migration guide.

**All outputs = documentation artifacts** (CHANGELOG.md, DRAFT.md, MIGRATION.md, SUMMARY.md, demo.py). Released product = code/package published separately via project tooling (`git tag`, `gh release create`, PyPI upload). Skill prepares communication; doesn't perform release.

NOT for ecosystem impact without release (use oss:analyse (requires `oss` plugin)). NOT for contributor communication or post-release announcements (use oss:shepherd (requires `oss` plugin)). NOT for retrospective analysis — historical review → oss:analyse (requires `oss` plugin).

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

Range notation: `v1->v2` (e.g. `v1.2->v2.0`) — converted internally to git range. No mode → defaults to `notes`. `prepare` = full pipeline — runs audit first, then all artifacts; use when cutting release, not drafting.
</inputs>

<workflow>

**Task hygiene**: Call `TaskList`; triage found tasks (`completed` / `deleted` / `in_progress`).

**Task tracking** — create ALL tasks upfront, execute sequentially; mark completed as each phase finishes. After mode detection, mark inapplicable tasks `deleted`:
- `demo` mode: mark deleted — Classify each change, Classify breaking changes, Validate migration docs, Audit changelog, Extract contributors, Draft migration guide, Draft executive summary, Write release draft
- bug-fix-only release (no 🚀 Added items): mark deleted — Generate release demo

Tasks:
- Gather changes (git log + find common base tag)
- Explore codebase (changed files, impl detail)
- Validate docs alignment
- Classify each change
- Classify breaking changes (codemap-gated; skip without index)
- Validate migration docs (skip when no migration doc found)
- Audit changelog
- Extract contributors
- Identify highlights
- Draft migration guide
- Generate release demo (feature releases only)
- Draft executive summary
- Write release draft

**Sequential enforcement**: never begin phase until prior marked `completed`. On failure (empty range, git error, demo fail), stop and report — no downstream phases.

## Delegation strategy

In `prepare` and `audit` modes, delegate gather/explore/validate to subagent via file-based handoff (CLAUDE.md §2) — these phases produce large output, bloat main context:

1. Pre-compute gather file path and create dir:
   ```bash
   # BRANCH, DATE from Shared setup below
   GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
   mkdir -p .temp  # timeout: 5000
   ```
2. Assert variables before spawning:
   ```bash
   [ -n "$GATHER_FILE" ] && [ -n "$REPO_ROOT" ] && [ -n "$RANGE" ] || { echo "Error: GATHER_FILE, REPO_ROOT, or RANGE is empty — verify Shared setup and Gather changes completed"; exit 1; }  # timeout: 5000
   export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
   # Reload SKILL_DIR (Check 41: fresh shell)
   SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
   cat "$SKILL_DIR/templates/gather-prompt.md"  # timeout: 5000
   ```
   Template (loaded above). Substitute `<REPO_ROOT>`, `<RANGE>`, `<GATHER_FILE>` with literal values. Spawn:
   > loads: gather-prompt.md
   `Agent(subagent_type="foundry:sw-engineer", prompt=<substituted gather-prompt.md content>)`
3. Validate envelope; every "abort" is a hard `exit 1`:
   ```bash
   STATUS=$(echo "$ENVELOPE" | jq -r '.status' 2>/dev/null)
   GATHER_FILE=$(echo "$ENVELOPE" | jq -r '.file' 2>/dev/null)
   BREAKING=$(echo "$ENVELOPE" | jq -r '.breaking // 0' 2>/dev/null)  # default 0 — never skip migration guide on missing field
   UNCONFIRMED=$(echo "$ENVELOPE" | jq -r '.unconfirmed // 0' 2>/dev/null)
   UNCONFIRMED_BREAKING=$(echo "$ENVELOPE" | jq -r '.unconfirmed_breaking // 0' 2>/dev/null)
   if [ "$STATUS" != "done" ] || [ -z "$GATHER_FILE" ] || [ "$GATHER_FILE" = "null" ] || [ ! -f "$GATHER_FILE" ]; then
       echo "Error: delegation validation failed — status=$STATUS, file=$GATHER_FILE" >&2
       exit 1
   fi
   ```

When `unconfirmed > 0`, surface removed items as notification (not a gate — already removed). Read REMOVED log from `$GATHER_FILE`:

   ```bash
   if [ "${UNCONFIRMED:-0}" -gt 0 ] 2>/dev/null; then
       REMOVED_ITEMS=$(grep '^REMOVED:' "$GATHER_FILE" | head -20)  # timeout: 3000
       echo "Truth check removed ${UNCONFIRMED} unverified claim(s) from release notes (not found in HEAD):"
       echo "$REMOVED_ITEMS"
   fi
   ```

   Pass `$GATHER_FILE` path to artifact phase — do NOT read gather file into main context; REMOVED log grep above = sole sanctioned exception.

**Phases 5–6 parallel delegation** (`prepare`/`audit` modes, after phases 1–4 complete): Audit changelog and Extract contributors are independent — delegate concurrently to reclaim tokens.

Pre-compute output paths and persist for downstream reload (fresh shell, Check 41):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Check 41: fresh shell loses between blocks
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || echo "")
RANGE=$(cat "${TMPDIR:-/tmp}/release-range-${CSID}" 2>/dev/null || echo "")
REPO_ROOT=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/REPO_ROOT" 2>/dev/null || echo "")
GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
[ -f "$GATHER_FILE" ] || { echo "Error: GATHER_FILE missing — phases 1–4 must complete first"; exit 1; }  # timeout: 5000
CHANGELOG_AUDIT_FILE=".temp/release-changelog-audit-$BRANCH-$DATE.md"
CONTRIBUTORS_FILE=".temp/release-contributors-$BRANCH-$DATE.md"
mkdir -p .temp  # timeout: 5000
echo "${CHANGELOG_AUDIT_FILE:-}" > "${TMPDIR:-/tmp}/release-changelog-audit-${CSID}"
echo "${CONTRIBUTORS_FILE:-}" > "${TMPDIR:-/tmp}/release-contributors-${CSID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/changelog-audit-prompt.md"  # timeout: 5000
```

<!-- loads: modes/changelog-audit-prompt.md -->
Prompt (loaded above) — execute (spawn Agent A + Agent B per instructions in that file).

Validate both envelopes:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
STATUS_A=$(echo "$ENVELOPE_A" | jq -r '.status' 2>/dev/null)
CHANGELOG_AUDIT_FILE=$(echo "$ENVELOPE_A" | jq -r '.file' 2>/dev/null)
CHANGELOG_FILE_FROM_A=$(echo "$ENVELOPE_A" | jq -r '.changelog_file // ""' 2>/dev/null)
STATUS_B=$(echo "$ENVELOPE_B" | jq -r '.status' 2>/dev/null)
CONTRIBUTORS_FILE=$(echo "$ENVELOPE_B" | jq -r '.file' 2>/dev/null)
if [ "$STATUS_A" != "done" ] || [ -z "$CHANGELOG_AUDIT_FILE" ] || [ ! -f "$CHANGELOG_AUDIT_FILE" ]; then
    echo "Error: changelog-audit delegation failed — status=$STATUS_A, file=$CHANGELOG_AUDIT_FILE" >&2; exit 1
fi
if [ "$STATUS_B" != "done" ] || [ -z "$CONTRIBUTORS_FILE" ] || [ ! -f "$CONTRIBUTORS_FILE" ]; then
    echo "Error: contributors delegation failed — status=$STATUS_B, file=$CONTRIBUTORS_FILE" >&2; exit 1
fi
# re-persist — subagent may canonicalize paths
echo "${CHANGELOG_AUDIT_FILE:-}" > "${TMPDIR:-/tmp}/release-changelog-audit-${CSID}"
echo "${CONTRIBUTORS_FILE:-}" > "${TMPDIR:-/tmp}/release-contributors-${CSID}"
[ -n "$CHANGELOG_FILE_FROM_A" ] && echo "${CHANGELOG_FILE_FROM_A}" > "${TMPDIR:-/tmp}/release-changelog-file-${CSID}"
ADDED=$(echo "$ENVELOPE_A" | jq -r '.added // 0' 2>/dev/null)
FLAGGED=$(echo "$ENVELOPE_A" | jq -r '.flagged // 0' 2>/dev/null)
COUNT=$(echo "$ENVELOPE_B" | jq -r '.count // 0' 2>/dev/null)
echo "Phases 5–6 delegated: $ADDED changelog entries added, $FLAGGED flagged; $COUNT contributors extracted."  # timeout: 5000
```

`notes` and `demo` modes: skip delegation — single-pass; run gather/explore/validate inline. **Size guard**: estimate commit count with `git rev-list --count ${RANGE:-${LAST_TAG:-HEAD~20}..HEAD} 2>/dev/null`. If >50, delegate to `foundry:sw-engineer` subagent same as prepare mode — inline gather with >50 commits causes context flood. Define `GATHER_FILE` before spawning so envelope-validation block above can resolve the path:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload BRANCH, DATE (Check 41: fresh shell)
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || echo "")
GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
mkdir -p .temp  # timeout: 5000
```

## Mode Detection

| First token | MODE | Routing |
| --- | --- | --- |
| `prepare` | prepare | **Shared setup** first, then **Mode: prepare** |
| `audit` | audit | **Shared setup** first, then **Mode: audit** |
| `demo` | demo | **Shared setup** first, then **Mode: demo** |
| `notes` | notes | Strip `notes` token; parse flags and range from remainder |
| *(bare range or flag)* | notes | Parse flags and range from full string |
| *(none)* | notes | `RANGE=""`, no flags; run all phases |

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
DO_CHANGELOG=false; DO_SUMMARY=false; DO_MIGRATION=false
FIRST=$(echo "$ARGUMENTS" | awk '{print $1}')
# empty when single-word ARGUMENTS (cut -d' ' -f2- echoes whole line for missing delimiter)
REST=""; case "$ARGUMENTS" in *" "*) REST="${ARGUMENTS#* }";; esac
echo "${REST:-}" > "${TMPDIR:-/tmp}/release-rest-${CSID}"
# strip mode token — prevents leak into RANGE
_PARSE_INPUT="$ARGUMENTS"; case "$FIRST" in notes|prepare|audit|demo) _PARSE_INPUT="$REST";; esac
RANGE=$(echo "$_PARSE_INPUT" | grep -oE '[^ ]+([[:space:]]*->[[:space:]]*|\.\.)[^ ]+' | head -1 | tr -d '[:space:]')
for _a in $_PARSE_INPUT; do case "$_a" in --changelog) DO_CHANGELOG=true;; --summary) DO_SUMMARY=true;; --migration) DO_MIGRATION=true;; --*) echo "⚠ unknown flag: $_a";; *) [ -z "$RANGE" ] && RANGE="$_a";; esac; done
RANGE="${RANGE/->/..}"
```

<!-- branch: unsupported-flags — isolated; ≤1 call; fires only when unknown flags present -->
**Unknown flags**: if any `⚠ unknown flag:` lines printed above, invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke) · (b) **Continue ignoring**. On Abort: stop.

## Shared setup

Run this first — cold-start fallback (sets `$_OSS_SHARED`):

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
# Check 41: persist across Bash blocks
echo "${_OSS_SHARED:-}" > "${TMPDIR:-/tmp}/release-oss-shared-${CSID}"
# loads: oss-shared-resolver.md
```

Extracted to `bin/release_setup.py` — resolves `SKILL_DIR`, `REPO_ROOT`, `BRANCH`, `DATE`, `LAST_TAG`, `CHERRY_PICK_SUBJECTS`, `SOURCE_TAG_REF`. Writes each var under `${TMPDIR:-/tmp}/release-setup-${CSID}/`; stable-branch banner and "no stable tag" warnings go to stderr.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/release_setup.py"  # timeout: 10000
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
REPO_ROOT=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/REPO_ROOT" 2>/dev/null || echo "")
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || echo "")
LAST_TAG=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/LAST_TAG" 2>/dev/null || echo "")
CHERRY_PICK_SUBJECTS=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/CHERRY_PICK_SUBJECTS" 2>/dev/null || echo "")
SOURCE_TAG_REF=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SOURCE_TAG_REF" 2>/dev/null || echo "")
[ -z "$REPO_ROOT" ] && { echo "Error: release_setup.py failed — REPO_ROOT empty; verify oss plugin installation"; exit 1; }
```

<!-- branch: no-stable-tags — isolated; ≤1 call; fires only when repo has no stable git tags -->
When no stable tags exist, `LAST_TAG` resolves to initial commit — surface via `AskUserQuestion` ("No stable tags found. Range base is initial commit — proceed?"). Options: (a) Proceed with initial commit as base · (b) Abort — stop release process. On (b): stop, print "Release aborted — no stable tags found; create a tag first with `git tag v0.1.0`" and exit.

## Gather changes

Find common base tag across ALL branches via `git tag --list` sorted by version, then `git merge-base HEAD <tag-commit>`. Use as range lower bound when current branch has no direct tag ancestry.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload Shared setup vars (Check 41: fresh shell)
LAST_TAG=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/LAST_TAG" 2>/dev/null || echo "")
CHERRY_PICK_SUBJECTS=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/CHERRY_PICK_SUBJECTS" 2>/dev/null || echo "")
RANGE="${RANGE:-$LAST_TAG..HEAD}"
[ -z "$RANGE" ] && echo "Error: could not determine commit range" && exit 1
# Check 41: persist across Bash blocks
echo "${RANGE:-}" > "${TMPDIR:-/tmp}/release-range-${CSID}"

# quote RANGE — tags may carry unusual chars (e.g. v1.2-rc.1+build.42)
git log "$RANGE" --oneline --no-merges # timeout: 3000
git log "$RANGE" --no-merges --format="--- %H%n%B" # timeout: 3000
git diff --stat "$(echo "$RANGE" | sed 's/\.\.\./\ /;s/\.\./\ /')" # timeout: 3000

# prefer gh; fallback to git remote show origin; never hardcode main
TRUNK=$(gh repo view --json defaultBranchRef --jq '.defaultBranchRef.name' 2>/dev/null)  # timeout: 6000
if [ -z "$TRUNK" ]; then
    TRUNK=$(git remote show origin 2>/dev/null | grep 'HEAD branch' | { read -r _ _ val; echo "$val"; })  # timeout: 5000
fi
if [ -n "$TRUNK" ]; then
    gh pr list --state merged --base "$TRUNK" --paginate \
        --json number,title,body,labels,mergedAt,author 2>/dev/null  # timeout: 15000
else
    echo "⚠ Could not detect default branch — listing all merged PRs"
    gh pr list --state merged --paginate \
        --json number,title,body,labels,mergedAt,author 2>/dev/null  # timeout: 15000
fi
```

Cross-reference commit bodies against PR descriptions — canonical source of truth for *why* change made. `BREAKING CHANGE:` footer = breaking change regardless of PR label.

**Detect revert pairs**: scan `git log $RANGE --no-merges --format="%H %s"` for subjects beginning with `Revert "`. For each: extract original subject, search range for matching commit. Both found → `REVERT_SET` pair (net effect zero).

Record all `REVERT_SET` pairs before Classify. Commits in `REVERT_SET` excluded from standard sections; collected for 🔄 Reverted. If only revert is in range (original predates range) → classify as ❌ Removed (or ⚠️ Breaking Changes if API surface changed without prior deprecation) — NOT 🔄 Reverted; net user effect is non-zero.

## Explore codebase

For top 3–5 significant changes (features, breaking, major behavior), read actual diff or changed files:

```bash
git diff "$RANGE" -- <file>    # timeout: 3000
git show <commit>:<file>       # timeout: 3000
```

Goal: understand new APIs, parameters, behavior — notes describe real functionality, not just commit subjects. Skip trivial changes (typos, dep bumps, CI config).

## Validate docs

Check public API surface in docs/ (or README) matches diff. Flag public symbol added/renamed/removed in Gather changes but absent from docs. Report: `- [MISSING/STALE] <symbol> in <doc-file>`. Empty list = docs aligned.

**Doc weight check** — for each 🚀 Added change identifying significant new entity (new public skill, new command, new agent, new submodule, new mode): compute **doc weight** for that feature and 2–3 comparable existing features of same nature in relevant README or docs file.

Doc weight = `header_score + coverage_score + example_score`:
- `header_score`: H2 = 3, H3 = 2, H4/deeper = 1, no heading = 0
- `coverage_score`: `min(non_blank_lines_in_section / 5, 5)` — lines from feature heading to next same-or-higher heading
- `example_score`: fenced code blocks in section, capped at 3

Weight ratio = `new_feature_weight / mean(comparable_weights)`. Flag UNDERTREATED when ratio < 0.5.
Report: `- [UNDERTREATED] <feature> in <doc-file> — weight N vs peers M1/M2 (ratio R)`. Collect as `doc_proportionality` list in findings.

## Classify each change

<!-- loads: modes/classify-truth-check.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/classify-truth-check.md"  # timeout: 5000
```
Follow above and execute. Contains: category table, PR accumulation rules, dedup rules, OMIT-INTERNAL body-signal override, cherry-pick annotation.

## Truth check

<!-- loads: modes/classify-truth-check.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/classify-truth-check.md"  # timeout: 5000
```
Follow above (Truth check section) and execute. Gate: runs after Classify, before Audit changelog. Verifies 🚀 Added / ⚠️ Breaking Changes / 🌱 Changed symbols exist in HEAD via codemap or grep fallback. Max 3 loop iterations.

## Breaking-change classification

<!-- loads: modes/classify-truth-check.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/classify-truth-check.md"  # timeout: 5000
```
Follow above (Breaking-change classification section) and execute. Codemap-gated (skips without a v3 index). For each diff-derived public symbol, `fn-rdeps --exclude-tests` labels it Breaking (caller outside its own package) or internal; Breaking symbols move to ⚠️ Breaking Changes with caller evidence, and `migration_lines` feed the Draft migration guide as `breaking_callers` findings.

## Validate migration docs

Gate — runs after Truth check. Only when project has migration docs page.

**Detect** — migration doc OR any alternative describing API changes between versions:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload REPO_ROOT (Check 41: fresh shell)
REPO_ROOT=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/REPO_ROOT" 2>/dev/null || echo "")
MIGRATION_DOC=$(find "$REPO_ROOT" -maxdepth 3 \( \
  -iname "MIGRATION*" -o -iname "UPGRADING*" -o \
  -iname "migration.md" -o -iname "upgrading.md" -o \
  -iname "CHANGELOG*" -o -iname "BREAKING*" -o \
  -iname "api-changes*" -o -iname "release-notes*" \
\) -not -path "*/node_modules/*" -not -path "*/.venv/*" -not -path "*/.git/*" \
| head -1)  # timeout: 5000
[ -z "$MIGRATION_DOC" ] && MIGRATION_DOC=$(find "$REPO_ROOT/docs" -maxdepth 2 \( \
  -iname "migration*" -o -iname "upgrade*" -o -iname "breaking*" -o -iname "api-changes*" \
\) 2>/dev/null | head -1)  # timeout: 5000
```

Skip entirely when `$MIGRATION_DOC` empty — no migration/upgrade docs exist in project.

**When found**: for every classified item in ⚠️ Breaking Changes, 🗑️ Deprecated, and ❌ Removed — verify present and described in `$MIGRATION_DOC`. "Present" = migration doc contains symbol name or semantically equivalent reference with upgrade instructions.

Check each item:
```bash
grep -i "<symbol_or_key>" "$MIGRATION_DOC" 2>/dev/null  # timeout: 3000
```

**Outcomes**:
- Found with upgrade path → `✓ <symbol> covered`
- Found but no upgrade path → `[SHALLOW] <symbol> in <doc> — present but missing upgrade instructions`
- Not found → `[MISSING-MIGRATION] <symbol> — ⚠️ Breaking/🗑️ Deprecated but absent from <doc>`

Collect all findings as `migration_gaps` list. Zero findings → migration doc complete. Report before proceeding.

**Do not block** on `[SHALLOW]` findings — flag and continue. `[MISSING-MIGRATION]` findings surface as warnings; Draft migration guide phase must fill the gaps.

## Audit changelog

**`prepare`/`audit` modes**: delegated in parallel (see Delegation strategy). Reload paths:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
CHANGELOG_AUDIT_FILE=$(cat "${TMPDIR:-/tmp}/release-changelog-audit-${CSID}" 2>/dev/null || echo "")
CHANGELOG_FILE=$(cat "${TMPDIR:-/tmp}/release-changelog-file-${CSID}" 2>/dev/null || echo "")
```
Read `$CHANGELOG_AUDIT_FILE` for audit findings; report added/flagged counts from delegation envelope. If file missing (delegation skipped), fall back to inline below.

**`notes` mode or delegation fallback**:

Search order: `CHANGELOG.md` at repo root, `docs/CHANGELOG.md`, any `CHANGELOG*` one level deep (excluding `node_modules/`, `.venv/`, `vendor/`). Store as `$CHANGELOG_FILE`.

If exists: cross-check against unreleased section. Items absent → add (same emoji format). Items in CHANGELOG not matching classified → flag for review (no auto-delete). For each REVERT_SET pair: add `🔄 Reverted: <original change description> (introduced and reverted in this release)`. If original already in CHANGELOG before revert, strike/remove from main section — unshipped change must not appear shipped. Reverted items never in highlights or migration guide.

If missing: create `CHANGELOG.md`; populate with `# Changelog` header and `## [Unreleased]` from Classify.

Always report: "N items added, M flagged for review." This phase owns CHANGELOG-format classification; Write release draft reads from it — does NOT copy. DRAFT.md uses different format.

## Extract contributors

**`prepare`/`audit` modes**: delegated in parallel (see Delegation strategy). Reload path:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
CONTRIBUTORS_FILE=$(cat "${TMPDIR:-/tmp}/release-contributors-${CSID}" 2>/dev/null || echo "")
```
Read `$CONTRIBUTORS_FILE` for formatted contributors list. If file missing (delegation skipped), fall back to inline below.

**`notes` mode or delegation fallback**:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload $RANGE (Check 41: fresh shell)
RANGE=$(cat "${TMPDIR:-/tmp}/release-range-${CSID}" 2>/dev/null || echo "")
python "${CLAUDE_PLUGIN_ROOT:-plugins/cc_oss}/bin/extract_contributors.py" --range "$RANGE"  # timeout: 5000
```

`extract_contributors.py` emits one `Name <email>` line per contributor — already deduplicated by email and bot-filtered (`[bot]`, `noreply@`). Every commit counts, including docs and typo fixes.

For each contributor, inspect commits in range (`git log "$RANGE" --no-merges --author="<email>" --oneline`) and pick up to 3 most significant contributions. Rank: new public API > major UX improvement > significant fix > internal change > docs/typo. No PR numbers, no issue links, no `(#N)` references.

Resolve GitHub handle from PR author data (`author.login` field). Match on name or email. If no PR found, omit handle.

For each resolved handle, fetch profile to check for LinkedIn URL:

```bash
gh api /users/<login> --jq '{blog: .blog, twitter: .twitter_username}' 2>/dev/null  # timeout: 6000
```

LinkedIn detected when `.blog` contains `linkedin.com`. Format: `- **Name** (@github_handle, [LinkedIn](https://linkedin.com/in/handle)) — <brief what they did>`. Omit `@handle` when unresolvable; omit LinkedIn when `.blog` absent or not LinkedIn URL.

## Identify highlights

Pick top 3–5 most significant changes from Classify. Ranking: breaking changes > new public API > major UX improvements > notable fixes. Pull concrete code example from explore-codebase diff for each. Drives Summary paragraph and Spotlights section.

## Draft migration guide

Always produce. No breaking changes → single line "No breaking changes in this release." Deprecations/removals → show before→after code examples. State in preamble: API deprecated in prior release and now removed → ❌ Removed (not Breaking).

If `migration_gaps` non-empty (from Validate migration docs): for each `[MISSING-MIGRATION]` item, add dedicated section covering that symbol with before→after example. For each `[SHALLOW]` item, expand existing coverage to add concrete upgrade instructions.

If `breaking_callers` non-empty (from Breaking-change classification): for each Breaking symbol, add a before→after section citing its external call sites (the `migration_lines`) so downstream consumers see exactly which of their call sites must change. When that phase reported `query_complete:false`, prefix the section "Affected call sites (possibly-incomplete — codemap coverage partial)".

## Generate release demo

**Only for feature releases** (≥1 🚀 Added items). Skip bug-fix-only releases.

Self-contained Python script in jupytext percent (`# %%`) format. Full story: install → setup → demonstrate each highlight → verify output.

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload Shared setup vars (Check 41: fresh shell)
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || echo "")
DEMO_OUT=".temp/release-demo-$BRANCH-$DATE.py"
mkdir -p .temp  # timeout: 5000
echo "${DEMO_OUT:-}" > "${TMPDIR:-/tmp}/release-demo-out-${CSID}"
```

Write demo to `$DEMO_OUT`. (`prepare` mode: `releases/$VERSION/demo.py` — see Phase 4.)

**Gate: demo must execute to completion before proceeding to Draft executive summary.**

<!-- branch: demo-approval — only in demo/prepare mode; isolated from notes/changelog path; ≤1 call -->
Invoke `AskUserQuestion` — "Ready to run demo script `$DEMO_OUT`?" Options: (a) Run now · (b) Review first · (c) Skip and **exclude from release artifacts**.

On option (c): mark demo excluded, skip to Draft executive summary — do NOT invoke the failure-path AskUserQuestion below.

On (a) or (b) confirmed:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
DEMO_OUT=$(cat "${TMPDIR:-/tmp}/release-demo-out-${CSID}" 2>/dev/null || echo "")
python "$DEMO_OUT"  # timeout: 600000
DEMO_EXIT=$?
echo "${DEMO_EXIT}" > "${TMPDIR:-/tmp}/release-demo-exit-${CSID}"
```

**Guard**: only proceed to failure handling when `$DEMO_EXIT -ne 0` after attempting a fix. Success (`$DEMO_EXIT = 0`) → proceed directly to Draft executive summary — no AskUserQuestion. Failure → fix and re-run (max 3 iterations total). Only after 3 failed attempts invoke `AskUserQuestion` ("Demo still failing after 3 attempts. Exclude from release and continue, or abort?"). Self-contained: package installed in current env; no live API calls or network deps; deterministic synthetic data; `# !pip install` lines are Python comments — interpreter skips.

## Draft executive summary

1–2 paragraph executive summary: what release is, why it matters, who benefits. Based on Identify highlights. Save `.temp/output-release-summary-$BRANCH-$DATE.md`.

## Write release draft

Pre-flight — verify all templates present before proceeding:

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload Shared setup vars (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/DATE" 2>/dev/null || echo "")
[ -z "$SKILL_DIR" ] && echo "Error: could not locate release skill directory" && exit 1
for tmpl in release-draft.md audit-checks.md gather-prompt.md; do # timeout: 5000
    [ -f "$SKILL_DIR/templates/$tmpl" ] || {
        echo "Missing template: $tmpl — aborting"
        exit 1
    }
done
```

Before writing, fetch last 2–3 releases to check formatting conventions:

```bash
gh release list --limit 5                                                  # timeout: 30000
LATEST_TAG=$(gh release list --limit 100 --json tagName --jq '[.[] | select(.tagName | test("rc|dev|alpha|beta"; "i") | not)] | .[0].tagName // empty') # timeout: 30000
[ -z "$LATEST_TAG" ] || [ "$LATEST_TAG" = "null" ] && echo "No releases found — using template defaults" || gh release view "$LATEST_TAG"  # timeout: 15000
```

Existing releases deviate from templates → match tone and prose style only. **Never** use `# Changelog` structure for DRAFT.md — always use `release-draft.md` structure. `gh release list` empty → use template defaults.

Fetch origin URL for full changelog link:
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")  # timeout: 3000
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/templates/release-draft.md"  # timeout: 5000
```

**DRAFT.md format guard**: must NOT start with `# Changelog`, must NOT use CHANGELOG section structure. CHANGELOG-format classification = internal working doc only — derive sections from it, don't copy verbatim.

Template (loaded above). Replace `[org]/[repo]` with actual values from `$ORIGIN_URL`. Omit empty sections.

Key difference from `prepare`: phases run inline (no subagent delegation); output to `DRAFT.md` and root `CHANGELOG.md`.

### Adversarial review

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/adversarial-review.md"  # timeout: 5000
```
Follow above and execute.

<!-- loads: modes/release-draft-template.md -->
```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
cat "$SKILL_DIR/modes/release-draft-template.md"  # timeout: 5000
```
Follow above and execute (format templates, semantic consistency review, polish, shepherd spawn, write to disk).

## Mode: prepare

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
[ -f "$SKILL_DIR/modes/prepare.md" ] || { echo "Error: modes/prepare.md not found at $SKILL_DIR/modes/prepare.md — verify oss plugin installation"; exit 1; }
cat "$SKILL_DIR/modes/prepare.md"  # timeout: 5000
```
Follow above and execute.
> Confidence block — prepare mode: end response with `## Confidence` block per CLAUDE.md output standards after prepare.md completes.

## Mode: audit

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
[ -f "$SKILL_DIR/modes/audit.md" ] || { echo "Error: modes/audit.md not found at $SKILL_DIR/modes/audit.md — verify oss plugin installation"; exit 1; }
# guard: refuse to audit already-published release
_AUDIT_VERSION=$(cat "${TMPDIR:-/tmp}/release-rest-${CSID}" 2>/dev/null | awk '{print $1}')
if [ -n "$_AUDIT_VERSION" ]; then
    if gh release view "$_AUDIT_VERSION" --json tagName --jq .tagName >/dev/null 2>&1; then  # timeout: 15000
        echo "! BLOCKED — $_AUDIT_VERSION is already a published release on GitHub. /release audit checks FORWARD readiness only."
        echo "  For retrospective analysis use: /oss:analyse  (requires oss plugin)"
        exit 1
    fi
fi
cat "$SKILL_DIR/modes/audit.md"  # timeout: 5000
```
Follow above and execute.
> Confidence block — audit mode: end response with `## Confidence` block per CLAUDE.md output standards after audit.md completes.

## Mode: demo

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
# Reload SKILL_DIR (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup-${CSID}/SKILL_DIR" 2>/dev/null || echo "")
[ -f "$SKILL_DIR/modes/demo.md" ] || { echo "Error: modes/demo.md not found at $SKILL_DIR/modes/demo.md — verify oss plugin installation"; exit 1; }
cat "$SKILL_DIR/modes/demo.md"  # timeout: 5000
```
Follow above and execute.
> Confidence block — demo mode: end response with `## Confidence` block per CLAUDE.md output standards after demo.md completes.

</workflow>

<notes>

- **Doc artifacts ≠ released product**: CHANGELOG.md, DRAFT.md, MIGRATION.md, SUMMARY.md, demo.py = communication artifacts; released product published separately via `git tag`, `gh release create`, PyPI upload.
- **AskUserQuestion usage**: spread across `notes`/`prepare`/`audit`/`demo` modes; each call in distinct branch-path (no single path has >4 sequential calls); compliant with sequential-call limit.
- **Numbers reference**: numeric limits documented with rationale in `guidelines/numbers-reference.md`; update whenever limits change
- Filter noise (CI config, dep bumps, typos) unless user-impacting
- **Public-facing content policy**: user-visible changes only. Never include: internal staff names, internal maintenance, CI/tooling, internal dep bumps, housekeeping with no user impact.
- **Contributor email privacy**: `.temp/` must be in `.gitignore` — emails from `git log --format="%aN <%aE>"` must not leak into repo.
- Public-facing output co-authored with `oss:shepherd` (requires `oss` plugin) — follow shepherd voice protocol:
  ```bash
  export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
  _OSS_SHARED=$(cat "${TMPDIR:-/tmp}/release-oss-shared-${CSID}" 2>/dev/null || echo "")
  cat "$_OSS_SHARED/shepherd-voice.md"  # timeout: 5000
  ```
- **Demo mode output**: jupytext percent format — convert with `jupytext --to notebook <file>.py`; replace placeholder URLs before publishing; Colab badge URL must point to actual notebook after upload
<!-- branch: demo-synthetic-fallback — only when real data unavailable; isolated deep in demo path -->
- **Demo real-world-only policy**: use actual project data/fixtures/API — synthetic requires explicit user approval; fallback: (1) document each failed attempt in `## Demo attempts`, (2) ask Codex if available, (3) ask user via `AskUserQuestion`, (4) synthetic only on explicit approval
- **Changelog audit non-destructive**: adds missing entries, flags extras, never removes automatically
- Follow-up chains:
  - Readiness check → `/oss:release prepare <version>` runs built-in audit first; use standalone `/oss:release audit [version]` only for readiness check without cutting release
  - Breaking changes → `/oss:analyse` (requires `oss` plugin) for ecosystem impact
  - Notes/changelog written → `gh release create` must be user-run via project tooling
  - `migration` content written → add to project docs, link from CHANGELOG entry

</notes>

<calibration>

Registered: `notes` mode — classification accuracy (change type, section assignment, noise filtering).

Future candidates (not yet registered): `prepare` (pipeline completeness), `audit` (verdict accuracy: READY/NEEDS_ATTENTION/BLOCKED), `demo` (headline feature selection, narrative quality, code cell correctness).

</calibration>
