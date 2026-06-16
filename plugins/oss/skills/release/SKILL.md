---
name: release
description: "Prepare release communication and check readiness. Main mode: notes with optional flags --changelog, --summary, --migration; range as v1->v2. Other modes: prepare (full pipeline: audit → all artifacts), audit (pre-release readiness: blockers, docs alignment, version consistency, CVEs), demo (story-telling release notebook in jupytext # %% format)."
when_to_use: |
  TRIGGER when: user requests release notes, CHANGELOG entry, migration guide, internal summary, release readiness audit, or release demo; phrases: "draft release notes", "prepare release", "audit release readiness", "generate CHANGELOG for v1->v2", "release demo notebook".
  SKIP: actual git tagging or PyPI/registry upload (use `git tag`, `gh release create`, `twine upload` directly); release communication for a non-Python project where this skill's pytest-centric audit assumptions do not apply; PR-level review (use `/oss:review`); thread/issue analysis (use `/oss:analyse`).
argument-hint: "[notes] [v1->v2] [--changelog] [--summary] [--migration] | prepare <version> | audit [version] | demo [range]"
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, TaskList, TaskCreate, TaskUpdate, Agent, AskUserQuestion
model: sonnet
effort: high
---

<objective>

Prepare release communication from changes. Output adapts to audience — user-facing notes, CHANGELOG entry, internal summary, migration guide.

**All outputs are documentation artifacts** (CHANGELOG.md, DRAFT.md, MIGRATION.md, SUMMARY.md, demo.py). The released product is code/package published separately via project tooling (`git tag`, `gh release create`, PyPI upload). This skill prepares communication; it does not perform the release.

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

**Sequential enforcement**: never begin phase until prior marked `completed`. On failure (empty range, git error, demo fail), stop and report — no downstream phases.

## Delegation strategy

In `prepare` and `audit` modes, delegate gather/explore/validate to subagent via file-based handoff (CLAUDE.md §2) — these phases produce large output bloating main context:

1. Pre-compute gather file path and create dir:
   ```bash
   # BRANCH and DATE defined in Shared setup block below — see next section
   GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
   mkdir -p .temp  # timeout: 5000
   ```
2. Assert variables before spawning:
   ```bash
   [ -n "$GATHER_FILE" ] && [ -n "$REPO_ROOT" ] && [ -n "$RANGE" ] || { echo "Error: GATHER_FILE, REPO_ROOT, or RANGE is empty — verify Shared setup and Gather changes completed"; exit 1; }  # timeout: 5000
   ```
   Spawn `Agent(subagent_type="foundry:sw-engineer")` — expand `$REPO_ROOT`, `$RANGE`, `$GATHER_FILE` to literal values before spawning:
   ```text
   Agent(subagent_type="foundry:sw-engineer", prompt="Working directory: <REPO_ROOT>. Run all git commands from that directory (use: git -C <REPO_ROOT> <cmd> or cd <REPO_ROOT> first). For git range <RANGE>:
   Run gather phase: git log, git diff --stat, gh pr list.
   Run classify phase: classify the NET state at HEAD, not each intermediate commit. When multiple commits within the range touch the same API or feature (add then modify, add then remove, add then rewrite), describe only what exists in HEAD — do not include features that were added and later undone within the same range regardless of whether the removal was an explicit revert commit or a follow-up PR. When an entry survives (net-effect non-zero), collect ALL PR numbers that contributed to its final state under the SAME category — never attribute to only the initial or last PR. Group under one bullet with cumulated PR refs ONLY when all contributing PRs classify into the same section (both Added, both Changed, both Fixed); when a PR fixes a bug or changes behavior in a feature added by an earlier PR in the same range, that fix gets its own 🔧 Fixed or 🌱 Changed entry — never folded into Added. Exception: trivial fixes (one-line cleanup, doc tweak inside new code with no standalone user-visible effect) fold into the parent Added bullet.
   Run explore phase: top 3–5 most significant changed files (read actual diffs).
   Run truth check phase: for each item classified as 🚀 Added or ⚠️ Breaking Changes that names a specific symbol (function, class, method, config key, CLI flag), verify the symbol is actually DEFINED in the codebase at HEAD — not just mentioned in a comment, docstring, or leftover reference. Prefer codemap over grep: first check if the codemap index is available (`scan-query list 2>/dev/null | wc -l` — non-zero = available), then run `scan-query find-symbol '^<symbol>$' 2>/dev/null`; empty output = absent. When codemap unavailable, fall back to definition-pattern grep: `git -C <REPO_ROOT> grep -wl 'def <symbol>\|class <symbol>' HEAD -- '*.py' 2>/dev/null` for Python, then `git -C <REPO_ROOT> grep -wl '<symbol>' HEAD -- '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null` for other languages. If both return nothing the symbol is absent — remove it from the classified section entirely and log 'REMOVED: <item> — symbol not found in HEAD'. Repeat for any newly revealed dependencies. Track count of removed items (unconfirmed_total) and how many were in ⚠️ Breaking Changes (unconfirmed_breaking).
   Write full findings — commit list, verified-only classified change table, diff excerpts, and REMOVED log — to <GATHER_FILE> using the Write tool.
   Return ONLY: {\"status\":\"done\",\"file\":\"<GATHER_FILE>\",\"changes\":N,\"breaking\":N,\"unconfirmed\":N,\"unconfirmed_breaking\":N,\"confidence\":0.N}")
   ```
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

When `unconfirmed > 0`, surface removed items as notification (not a gate — already removed). Read the REMOVED log from `$GATHER_FILE`:

   ```bash
   if [ "${UNCONFIRMED:-0}" -gt 0 ] 2>/dev/null; then
       REMOVED_ITEMS=$(grep '^REMOVED:' "$GATHER_FILE" | head -20)  # timeout: 3000
       echo "Truth check removed ${UNCONFIRMED} unverified claim(s) from release notes (not found in HEAD):"
       echo "$REMOVED_ITEMS"
   fi
   ```

   Pass `$GATHER_FILE` path to artifact phase — do NOT read gather file into main context; the REMOVED log grep above is the sole sanctioned exception.

`notes` and `demo` modes: skip delegation — single-pass; run gather/explore/validate inline. **Size guard**: estimate commit count with `git rev-list --count ${RANGE:-${LAST_TAG:-HEAD~20}..HEAD} 2>/dev/null`. If >50, delegate to `foundry:sw-engineer` subagent same as prepare mode — inline gather with >50 commits causes context flood. Define `GATHER_FILE` before spawning so the envelope-validation block above can resolve the path:

```bash
GATHER_FILE=".temp/release-gather-$BRANCH-$DATE.md"
mkdir -p .temp  # timeout: 5000
```

## Mode Detection

Parse `$ARGUMENTS` by first token:

```bash
read FIRST REST <<<"$ARGUMENTS"

# Range-first detection: if FIRST looks like a range (contains -> or ..),
# force notes mode. Without this, "/release v1->v2 --changelog" would embed --changelog
# inside the range string, silently ignoring the flag.
# Also check full ARGUMENTS for spaced-arrow form "v1 -> v2".
if [[ "$FIRST" == *"->"* ]] || [[ "$FIRST" == *".."* ]] || [[ "$ARGUMENTS" == *"->"* ]] || [[ "$ARGUMENTS" == *".."* ]]; then
    MODE="notes"
    REST="$ARGUMENTS"   # reuse full ARGUMENTS so flag loop discovers the complete range and all flags
    FIRST="notes"
fi
```

| First token | Mode | Routing |
| --- | --- | --- |
| `prepare` | prepare | **Shared setup** first, then **Mode: prepare** |
| `audit` | audit | **Shared setup** first, then **Mode: audit** |
| `demo` | demo | **Shared setup** first, then **Mode: demo** |
| `notes` | notes | Parse flags and range from `$REST`; run all phases |
| *(bare range)* | notes | Falls through after `FIRST` rewritten |
| *(none)* | notes | `RANGE=""`, no flags; run all phases |

After matching `notes`, parse flags from `$REST`:

```bash
DO_CHANGELOG=false; DO_SUMMARY=false; DO_MIGRATION=false; RANGE=""
# Detect spaced-arrow form ("v1 -> v2") BEFORE the flag loop — otherwise the loop
# overwrites RANGE three times and ends with RANGE="v2" (lower bound lost).
_SPACED_RANGE=$(echo "$REST" | grep -oE '[^ ]+[[:space:]]*->[[:space:]]*[^ ]+' | head -1)
if [ -n "$_SPACED_RANGE" ]; then
    RANGE=$(echo "$_SPACED_RANGE" | tr -d '[:space:]')  # collapse spaces around ->
    # Strip the spaced range from REST so the flag loop below doesn't re-process its tokens
    REST=$(echo "$REST" | sed "s|$_SPACED_RANGE||")
fi
for arg in $REST; do
  case "$arg" in
    --changelog)  DO_CHANGELOG=true ;;
    --summary)    DO_SUMMARY=true ;;
    --migration)  DO_MIGRATION=true ;;
    *)            [ -z "$RANGE" ] && RANGE="$arg" ;;  # don't overwrite spaced-range form
  esac
done
# Convert v1->v2 shorthand to git range notation
RANGE="${RANGE/->/../}"
```

**Unsupported flag check** — after extracting supported flags, scan `$ARGUMENTS` for remaining `--<token>` tokens. If found: print `! Unknown flag(s): \`--<token>\`. Supported: \`--changelog\`, \`--summary\`, \`--migration\`.` then invoke `AskUserQuestion` — (a) **Abort** (stop, re-invoke) · (b) **Continue ignoring** (skip, proceed). On Abort: stop.

## Shared setup

Run this first — cold-start fallback (sets `$_OSS_SHARED`):

```bash
_OSS_SHARED=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/resolve_shared_path.py" oss skills/_shared 2>/dev/null)  # timeout: 5000
# Persist $_OSS_SHARED across Bash blocks (Check 41: fresh shell loses vars)
echo "${_OSS_SHARED:-}" > "${TMPDIR:-/tmp}/release-oss-shared"
# loads: oss-shared-resolver.md
# Then: Read $_OSS_SHARED/oss-shared-resolver.md and execute its contents
```

Extracted to `bin/release_setup.py` — resolves `SKILL_DIR`, `REPO_ROOT`, `BRANCH`, `DATE`, `LAST_TAG`, `CHERRY_PICK_SUBJECTS`, `SOURCE_TAG_REF`. Writes each var under `${TMPDIR:-/tmp}/release-setup/`; stable-branch banner and "no stable tag" warnings go to stderr.

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/release_setup.py"  # timeout: 10000
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup/SKILL_DIR" 2>/dev/null || echo "")
REPO_ROOT=$(cat "${TMPDIR:-/tmp}/release-setup/REPO_ROOT" 2>/dev/null || echo "")
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup/DATE" 2>/dev/null || echo "")
LAST_TAG=$(cat "${TMPDIR:-/tmp}/release-setup/LAST_TAG" 2>/dev/null || echo "")
CHERRY_PICK_SUBJECTS=$(cat "${TMPDIR:-/tmp}/release-setup/CHERRY_PICK_SUBJECTS" 2>/dev/null || echo "")
SOURCE_TAG_REF=$(cat "${TMPDIR:-/tmp}/release-setup/SOURCE_TAG_REF" 2>/dev/null || echo "")
[ -z "$REPO_ROOT" ] && { echo "Error: release_setup.py failed — REPO_ROOT empty; verify oss plugin installation"; exit 1; }
```

When no stable tags exist, `LAST_TAG` resolves to the initial commit — surface this to the user via `AskUserQuestion` ("No stable tags found. Range base is initial commit — proceed?") before any phase that consumes the range. Options: (a) Proceed with initial commit as base · (b) Abort — stop release process. If user selects (b): stop immediately, print "Release aborted — no stable tags found; create a tag first with `git tag v0.1.0`" and exit.

## Gather changes

Find common base tag across ALL branches via `git tag --list` sorted by version, then `git merge-base HEAD <tag-commit>`. Use as range lower bound when current branch has no direct tag ancestry.

```bash
# Reload Shared setup vars (Check 41: fresh shell)
LAST_TAG=$(cat "${TMPDIR:-/tmp}/release-setup/LAST_TAG" 2>/dev/null || echo "")
CHERRY_PICK_SUBJECTS=$(cat "${TMPDIR:-/tmp}/release-setup/CHERRY_PICK_SUBJECTS" 2>/dev/null || echo "")
RANGE="${RANGE:-$LAST_TAG..HEAD}"
[ -z "$RANGE" ] && echo "Error: could not determine commit range" && exit 1
# Persist $RANGE across Bash blocks (Check 41: fresh shell loses vars)
echo "${RANGE:-}" > "${TMPDIR:-/tmp}/release-range"

# Quote "$RANGE" throughout — tags can carry unusual characters (e.g. `v1.2-rc.1+build.42`)
git log "$RANGE" --oneline --no-merges # timeout: 3000
git log "$RANGE" --no-merges --format="--- %H%n%B" # timeout: 3000
git diff --stat "$(echo "$RANGE" | sed 's/\.\.\./\ /;s/\.\./\ /')" # timeout: 3000

# Default-branch detection: prefer gh, then git remote show origin; never hardcode `main`
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

Cross-reference commit bodies against PR descriptions — canonical source of truth for *why* change was made. `BREAKING CHANGE:` footer = breaking change regardless of PR label.

**Detect revert pairs**: scan `git log $RANGE --no-merges --format="%H %s"` for subjects beginning with `Revert "`. For each: extract original subject, search range for matching commit. Both found → `REVERT_SET` pair (net effect zero).

Record all `REVERT_SET` pairs before Classify. Commits in `REVERT_SET` excluded from standard sections; collected for 🔄 Reverted. If only revert is in range (original predates range) → classify as ❌ Removed (or ⚠️ Breaking Changes if API surface changed without prior deprecation) — NOT 🔄 Reverted; net user effect is non-zero.

## Explore codebase

For top 3–5 significant changes (features, breaking, major behavior), read actual diff or changed files:

```bash
git diff "$RANGE" -- <file>    # timeout: 3000
git show <commit>:<file>       # timeout: 3000
```

Goal: understand new APIs, parameters, behavior — so notes describe real functionality, not just commit subjects. Skip for trivial changes (typos, dep bumps, CI config).

## Validate docs

Check public API surface in docs/ (or README) matches diff. Flag any public symbol added/renamed/removed in Gather changes but absent from docs. Report: `- [MISSING/STALE] <symbol> in <doc-file>`. Empty list = docs aligned.

**Doc weight check** — for each 🚀 Added change identifying a significant new entity (new public skill, new command, new agent, new submodule, new mode): compute **doc weight** for that feature and 2–3 comparable existing features of same nature (same task type, mode category, conceptual peer) in relevant README or docs file.

Doc weight = `header_score + coverage_score + example_score`:
- `header_score`: H2 = 3, H3 = 2, H4/deeper = 1, no heading = 0
- `coverage_score`: `min(non_blank_lines_in_section / 5, 5)` — lines from feature heading to next same-or-higher heading
- `example_score`: fenced code blocks in section, capped at 3

Weight ratio = `new_feature_weight / mean(comparable_weights)`. Flag UNDERTREATED when ratio < 0.5.
Report: `- [UNDERTREATED] <feature> in <doc-file> — weight N vs peers M1/M2 (ratio R)`. Collect as `doc_proportionality` list in findings.

## Classify each change

**Net-state principle**: classify only HEAD state, not the development journey. When multiple commits touch the same API/feature, describe only the net final state. A feature added then removed within the range has net effect zero — omit from release notes.

**PR accumulation**: when a net-surviving entry (effect non-zero) was touched by multiple PRs within the range, list ALL contributing PR numbers in that entry — not only the initial PR or the last. **Scope: same category only.** Two PRs merge under one bullet only when both classify into the SAME section per the table below (e.g. both Added, both Changed, both Fixed). A later PR that fixes a bug or changes behavior in a feature introduced earlier in the same range is NOT a co-contributor to the Added entry — it gets its own 🔧 Fixed or 🌱 Changed entry with its own PR ref. **Test before merging**: classify each PR independently using the category table; merge only PRs that land in the same section AND describe the same user-visible thing. **Trivial-fix exception**: a fix or doc tweak with no standalone user-visible effect folds into the parent Added bullet per the Same-release feature+fix dedup rule below. When in doubt: separate entries are safer than over-merge — users scanning 🔧 Fixed must not miss fixes hidden inside Added bullets.

Section order (fixed — never reorder): 🚀 Added → ⚠️ Breaking Changes → 🌱 Changed → 🗑️ Deprecated → ❌ Removed → 🔧 Fixed → 🔒 Security → 🔄 Reverted

| Category | Output section | What goes here |
| --- | --- | --- |
| **New Features** | 🚀 Added | User-visible additions |
| **Breaking Changes** | ⚠️ Breaking Changes | Existing code **stops working immediately** after upgrade — API removed or signature changed with **no prior deprecation period**. Prior release deprecated it → classify as ❌ Removed instead. Must be 100% certain it no longer works and users had no warning. |
| **Improvements** | 🚀 Added or 🌱 Changed | Enhancements to existing behavior |
| **Performance** | 🚀 Added or 🔧 Fixed or 🌱 Changed | Speed/memory improvements. Use 🔧 Fixed for regression correction, 🚀 Added for new optimization feature, 🌱 Changed for efficiency refactor. **Quantitative claims** ("2× faster", "50% less memory") require evidence from PR body or benchmark artifacts — unsubstantiated claims → rewrite to "improved performance" without number (see `guidelines/numbers-reference.md`). |
| **Deprecations** | 🗑️ Deprecated | Old API **still works** this release but scheduled for removal — emits warning, replacement exists |
| **Removals** | ❌ Removed | Previously deprecated API now gone — marked 🗑️ Deprecated in prior release, users had warning. Not ⚠️ Breaking Changes. |
| **Bug Fixes** | 🔧 Fixed | Correctness fixes |
| **Security** | 🔒 Security | Security fixes and vulnerability patches — omit CVE numbers in public notes; link to advisory if public. Also classify here: any fix whose commit body contains security-intent keywords ("security hardening", "timing attack", "side-channel", "exploitable", "vulnerability", "injection", "mitigation") regardless of CVE assignment or `fix:` commit type prefix. Dependency updates that address a CVE belong here — OMIT-INTERNAL does NOT apply to security fixes regardless of "no logic changes" or "no code changes" body signals. |
| **Internal** | *(omit)* | Refactors, CI/tooling, deps, code cleanup, developer-facing housekeeping — omit unless directly user-impacting |
| **Reverted** | 🔄 Reverted | Introduced AND reverted within range (REVERT_SET pairs) — net effect zero; list as "Reverted: <original description>"; do NOT classify original in any other section; omit from highlights, demo, migration guide |

**Same-release feature+fix dedup** — 🔧 Fixed targeting code introduced in same release = behavior never shipped = not a real fix. Fold into 🚀 Added prose or omit. Test: "did users ever see broken behavior?" No → collapse into feature entry.

**Unintentionally-working behavior** — accidental behavior users relied on → 🔧 Fixed or 🌱 Changed, NOT Internal. Note: "behavior was not intentionally supported; now [formalized/changed/removed]."

**Borderline keep/drop** — Include when users could have relied on it or silent breakage possible; exclude when no observable effect. When included: propagate consistently across ALL downstream docs (CHANGELOG, DRAFT.md, MIGRATION.md if breaking, SUMMARY.md if significant) — no partial mentions. Note: "Previously undefined — now [X]. Users relying on this: [action]."

**Self-correction discipline**: present only final corrected table — no intermediate classifications.

**Breaking vs Deprecated vs Removed**: old call still works (even with warning) → Deprecated, never Breaking. API deprecated in prior release and now removed → Removed, never Breaking — users had fair warning. Breaking = upgrade causes immediate failures with **no prior deprecation period** between two consecutive versions. **Prior-deprecation body-signal**: if commit body contains "deprecated in vX", "previously deprecated", "was deprecated", "emits DeprecationWarning since", or "deprecated since" — treat as Removed regardless of `feat!:` or `BREAKING CHANGE:` markers; cross-version deprecation history in body overrides commit type prefix. **Bug fixed to match documented spec**: if behavior changes from buggy to correct (matching docs) but users relied on the buggy behavior, classify as 🌱 Changed (not 🔧 Fixed) and note the behavioral impact explicitly — use ⚠️ Breaking Changes only if the bug was load-bearing and fixing it causes widespread breakage.

**OMIT-INTERNAL body-signal override**: if commit body contains any of — "No code changes", "no user-facing changes", "internal only", "no public API changes", "internal buffer changes only", "internal restructure" — OR all changed file paths restricted to `.github/`, `ci/`, `scripts/`, `Makefile`, `*.yml` under `.github/` — classify as Internal regardless of `fix:`, `feat:`, `perf:`, `chore:` conventional commit prefix. For `perf:` commits: if body contains unsubstantiated language ("should be faster", "might improve", "potentially") without a benchmark artifact reference, rewrite claim to "improved X performance" without number rather than including the unsubstantiated claim verbatim. Conventional commit type is a hint, not a classification gate. **Exception**: BREAKING CHANGE footer or confirmed user-visible breakage always overrides OMIT-INTERNAL — "Always include: breaking changes" takes priority over body-signal omission.

Filter out: merge commits, dep bumps, CI/tooling config, comment typos, internal refactors, housekeeping with no user impact. **New CLI function/command with no change to usage or observable behavior** → Internal; do NOT promote to 🚀 Added. Test: "can an end user get a different result than before?" No → Internal. Never include internal staff names. Always include: breaking changes, behavior changes, new API surface.

**Cherry-pick annotation (stable-branch mode)**: when `$CHERRY_PICK_SUBJECTS` set (gather phase, stable/bug-fix branches), check each commit's subject against it. Match → backport from `$SOURCE_TAG_REF`; append "(backported from $SOURCE_TAG_REF)". No match → original to this stable branch; no annotation. Note: subject-text matching is heuristic — verify manually for generic subjects (e.g., "Fix typo", "Update deps") that could false-positive.

## Truth check

Gate — runs after Classify, before Audit changelog. Classifications derived from commit history must be confirmed against HEAD before entering release notes.

**Scope**: apply to 🚀 Added, ⚠️ Breaking Changes, 🌱 Changed that name a symbol (function, class, CLI flag, config key). Skip: 🔧 Fixed (absence not greppable), 🔒 Security, 🗑️ Deprecated (still present), ❌ Removed (confirmed absent), 🔄 Reverted (already excluded).

**For each in-scope classified change** — prefer codemap over grep (immune to false positives from comments, docstrings, migration stubs):

```bash
# Step 1: check codemap index (installed by /codemap:scan-codebase)
CODEMAP_OK=$(scan-query list 2>/dev/null | wc -l)  # timeout: 5000
# Non-zero = index loaded; 0 or error = fall back to grep

# Step 2a (codemap): structural symbol lookup
scan-query find-symbol '^<symbol_name>$' 2>/dev/null  # timeout: 5000

# Step 2b (fallback): definition-pattern grep — skips comments and leftovers
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null || \
  git grep -wl "<symbol_name>" HEAD -- '*.ts' '*.js' '*.go' '*.rs' 2>/dev/null  # timeout: 3000

# For removals / breaking changes — confirm absent at HEAD
git grep -wl "def <symbol_name>\|class <symbol_name>" HEAD -- '*.py' 2>/dev/null && echo "PRESENT (unexpected)" || echo "ABSENT (confirmed)"  # timeout: 3000

# For behavior changes — confirm changed code path at HEAD
git show HEAD:<changed_file> | grep -n "<distinguishing_pattern>"  # timeout: 3000
```

**Outcomes per item**:
- Confirmed present → keep; note "truth-checked"
- Not found in HEAD → remove entirely; log: `[REMOVED] <description> — symbol not found in HEAD`
- Cannot determine → keep; add "(not HEAD-verified)" qualifier

**Gate loop** (max 3 iterations):

1. Truth-check — verify each 🚀 Added / ⚠️ Breaking Changes symbol present in HEAD
2. Remove unverified — drop items whose symbol absent; log `REMOVED: <item>`
3. Re-run on updated set — catches cascading deps; clean → proceed; still unverified → loop
4. After 3 iterations → surface all remaining unverified claims; proceed without them

Runs before Identify highlights — highlights and demo must never reference unverified items.

## Audit changelog

Search order: `CHANGELOG.md` at repo root, `docs/CHANGELOG.md`, any `CHANGELOG*` one level deep (excluding `node_modules/`, `.venv/`, `vendor/`). Store as `$CHANGELOG_FILE`.

If exists: cross-check against unreleased section. Items absent → add (same emoji format). Items in CHANGELOG not matching classified → flag for review (no auto-delete). For each REVERT_SET pair: add `🔄 Reverted: <original change description> (introduced and reverted in this release)`. If original already in CHANGELOG before revert, strike/remove from main section — unshipped change must not appear shipped. Reverted items never in highlights or migration guide.

If missing: create `CHANGELOG.md`; populate with `# Changelog` header and `## [Unreleased]` from Classify.

Always report: "N items added, M flagged for review." This phase owns CHANGELOG-format classification; Write release draft reads from it — does NOT copy. DRAFT.md uses different format.

## Extract contributors

```bash
# Reload $RANGE (Check 41: fresh shell)
RANGE=$(cat "${TMPDIR:-/tmp}/release-range" 2>/dev/null || echo "")
git log "$RANGE" --no-merges --format="%aN <%aE>%n%(trailers:key=Co-authored-by,valueonly)" \
  | grep -v '^$' | sort -u  # timeout: 3000
```

Deduplicate by email. Exclude bot accounts (e.g. `[bot]`, `noreply@`). Every commit counts, including docs and typo fixes.

For each contributor, inspect commits in range (`git log "$RANGE" --no-merges --author="<email>" --oneline`) and pick up to 3 most significant contributions. Rank by: new public API > major UX improvement > significant fix > internal change > docs/typo. No PR numbers, no issue links, no `(#N)` references.

Resolve GitHub handle from PR author data (`author.login` field). Match on name or email. If no PR found, omit handle.

For each resolved handle, fetch profile to check for LinkedIn URL:

```bash
gh api /users/<login> --jq '{blog: .blog, twitter: .twitter_username}' 2>/dev/null  # timeout: 6000
```

LinkedIn detected when `.blog` contains `linkedin.com`. Format: `- **Name** (@github_handle, [LinkedIn](https://linkedin.com/in/handle)) — <brief what they did>`. Omit `@handle` when unresolvable; omit LinkedIn when `.blog` absent or not LinkedIn URL.

## Identify highlights

Pick top 3–5 most significant changes from Classify. Ranking: breaking changes > new public API > major UX improvements > notable fixes. For each, pull concrete code example from explore-codebase diff. These spotlights drive Summary paragraph and Spotlights section.

## Draft migration guide

Always produce. No breaking changes → single line "No breaking changes in this release." Deprecations/removals → show before→after code examples. State in preamble: API deprecated in prior release and now removed → ❌ Removed (not Breaking).

## Generate release demo

**Only for feature releases** (≥1 🚀 Added items). Skip for bug-fix-only releases.

Self-contained Python script in jupytext percent (`# %%`) format. Full story: install → setup → demonstrate each highlight → verify output.

```bash
# Reload Shared setup vars (Check 41: fresh shell)
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup/DATE" 2>/dev/null || echo "")
DEMO_OUT=".temp/release-demo-$BRANCH-$DATE.py"
mkdir -p .temp  # timeout: 5000
echo "${DEMO_OUT:-}" > "${TMPDIR:-/tmp}/release-demo-out"
```

Write demo to `$DEMO_OUT`. (`prepare` mode: `releases/$VERSION/demo.py` — see Phase 4.)

**Gate: demo must execute to completion before proceeding to Draft executive summary.**

Invoke `AskUserQuestion` — "Ready to run demo script `$DEMO_OUT`?" Options: (a) Run now · (b) Review first · (c) Skip and **exclude from release artifacts**.

On (a) or (b) confirmed:
```bash
DEMO_OUT=$(cat "${TMPDIR:-/tmp}/release-demo-out" 2>/dev/null || echo "")
python "$DEMO_OUT"  # timeout: 600000
DEMO_EXIT=$?; echo "$DEMO_EXIT" > ${TMPDIR:-/tmp}/release-demo-exit
```
If fails: fix and re-run (max 3 iterations). On third failure invoke `AskUserQuestion` ("Demo still failing. Exclude from release and continue, or abort release?"). Self-contained: package installed in current env; no live API calls or network deps; deterministic synthetic data; `# !pip install` lines are Python comments — interpreter skips.

## Draft executive summary

1–2 paragraph executive summary: what this release is, why it matters, who benefits. Based on Identify highlights. Save to `.temp/output-release-summary-$BRANCH-$DATE.md`.

## Write release draft

Pre-flight — verify all templates present before proceeding:

```bash
# Reload Shared setup vars (Check 41: fresh shell)
SKILL_DIR=$(cat "${TMPDIR:-/tmp}/release-setup/SKILL_DIR" 2>/dev/null || echo "")
BRANCH=$(cat "${TMPDIR:-/tmp}/release-setup/BRANCH" 2>/dev/null || echo "")
DATE=$(cat "${TMPDIR:-/tmp}/release-setup/DATE" 2>/dev/null || echo "")
[ -z "$SKILL_DIR" ] && echo "Error: could not locate release skill directory" && exit 1
for tmpl in release-draft.md audit-checks.md; do # timeout: 5000
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
ORIGIN_URL=$(git remote get-url origin 2>/dev/null || echo "")  # timeout: 3000
```

**DRAFT.md format guard**: must NOT start with `# Changelog`, must NOT use CHANGELOG section structure. CHANGELOG-format classification = internal working doc only — derive sections from it, don't copy verbatim.

Read template from `$SKILL_DIR/templates/release-draft.md`. Replace `[org]/[repo]` with actual values from `$ORIGIN_URL`. Omit empty sections.

Key difference from `prepare`: phases run inline (no subagent delegation); output to `DRAFT.md` and root `CHANGELOG.md`.

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

### Adversarial review

Read `$SKILL_DIR/modes/adversarial-review.md` and execute.

### Semantic consistency review

Runs on full draft after adversarial review, before writing to disk. Check for each:

| Check | What to look for | Flag format |
| --- | --- | --- |
| **Double-mention** | Same concept named twice under different labels (e.g. "async functions" and "async generators" as separate entries for the same change) | `DUPLICATE: "<A>" and "<B>" describe the same change — merge or drop one` |
| **Impossible fix** | 🔧 Fixed entry whose subject was introduced in this same release (can't fix what was never shipped) | `IMPOSSIBLE-FIX: "<entry>" — feature added this release, can't be a fix` |
| **Causation non sequitur** | "X: Y" where Y doesn't explain or follow from X | `NON-SEQUITUR: "<X>: <Y>" — Y doesn't explain X` |
| **Contradictory claim** | Headline or first sentence asserts X; immediate caveat or next sentence denies X | `CONTRADICTION: "<headline>" contradicted by "<caveat>"` |
| **Verbatim duplication** | Identical or near-identical sentence appearing in ≥2 sections (Summary, Spotlight, Notable changes, Migration guide) | `VERBATIM-DUP: "<sentence>" appears in <section A> and <section B>` |
| **Misclassified scope** | Internal-only change (dead code removal, doc reformat, test-only, CI config) appearing in user-facing section | `SCOPE: "<entry>" is internal-only — move to Internal or remove` |

For each finding: emit one flag line with location (`§<section-name>`, item text). Collect all findings before taking action — do not fix inline during scan.

**After scan**: zero findings → proceed to Polish. Findings present → list all; fix each; re-scan once; proceed only when clean.

### Polish and write to disk

Read `$SKILL_DIR/guidelines/writing-rules.md` and follow. If absent, proceed without style guidelines.

Dispatch shepherd for public-facing voice/tone review before writing to disk. Check availability first:

```bash
SHEPHERD_AVAILABLE=$(python "${CLAUDE_PLUGIN_ROOT:-plugins/oss}/bin/check_agent.py" oss shepherd 2>/dev/null)  # timeout: 5000
# IMPORTANT: expand $SHEPHERD_DIR to literal value before inserting into spawn prompt
SHEPHERD_DIR=".temp/release-shepherd-$(git branch --show-current 2>/dev/null | tr '/' '-' || echo 'main')-$(date +%Y-%m-%d)"
mkdir -p "$SHEPHERD_DIR"  # timeout: 5000
```

If `$SHEPHERD_AVAILABLE` equals `true`:
```bash
_OSS_SHARED=$(cat "${TMPDIR:-/tmp}/release-oss-shared" 2>/dev/null || echo "")
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
- **notes** (always): shepherd review → write to `DRAFT.md` at repo root. **Overwrite guard** — if `DRAFT.md` non-empty, invoke `AskUserQuestion` ("DRAFT.md already exists — overwrite, append, or abort?") with: (a) **Overwrite** · (b) **Append** (after `---` separator) · (c) **Abort**. Skip prompt only when DRAFT.md is empty or missing. Notify: `→ written to DRAFT.md` / `→ appended to DRAFT.md` / `→ DRAFT.md unchanged — aborted`.
- **`--changelog`** (if set): no shepherd (structured, internal) → invoke `AskUserQuestion`: "Ready to prepend to `$CHANGELOG_FILE`?" Options: (a) Proceed · (b) Preview only. On (b): display content, stop. On (a): derive `VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "")` and `VERSION_BARE="${VERSION#v}"`. **Idempotency check**: if `$CHANGELOG_FILE` already contains the version header in any supported form (`grep -qF "## [${VERSION_BARE}]" "$CHANGELOG_FILE"` for Keep-a-Changelog `## [1.2.0]`, OR `grep -qF "## [${VERSION}]" "$CHANGELOG_FILE"` for `## [v1.2.0]`, OR `grep -qE "^## v?${VERSION_BARE}([^0-9.]|$)" "$CHANGELOG_FILE"` for `## v1.2.0` / `## 1.2.0`) → skip prepend, notify `→ CHANGELOG.md already contains version header — prepend skipped`; otherwise prepend after `# Changelog` heading (create if missing). Notify: `→ prepended to CHANGELOG.md`
- **`--summary`** (if set): no shepherd (internal) → Draft executive summary saved to `.temp/output-release-summary-$BRANCH-$DATE.md` — confirm written. Notify: `→ saved to .temp/output-release-summary-<branch>-<date>.md`
- **`--migration`** (if set): shepherd review (public-facing) → save to `.temp/output-release-migration-$BRANCH-$DATE.md`. Notify: `→ saved to .temp/output-release-migration-<branch>-<date>.md`

**Human gate** — stop and hand off after writing files. GitHub release must be created with project-level tooling (`gh release create`). See `$_OSS_SHARED/release-checklist.md` for exact release steps.

End response with `## Confidence` block per CLAUDE.md output standards.

## Mode: prepare

```bash
[ -f "$SKILL_DIR/modes/prepare.md" ] || { echo "Error: modes/prepare.md not found at $SKILL_DIR/modes/prepare.md — verify oss plugin installation"; exit 1; }
```
Read `$SKILL_DIR/modes/prepare.md` and execute.

## Mode: audit

```bash
[ -f "$SKILL_DIR/modes/audit.md" ] || { echo "Error: modes/audit.md not found at $SKILL_DIR/modes/audit.md — verify oss plugin installation"; exit 1; }
# Forward-readiness guard: refuse to audit an already-published release.
_AUDIT_VERSION=$(echo "$REST" | awk '{print $1}')
if [ -n "$_AUDIT_VERSION" ]; then
    if gh release view "$_AUDIT_VERSION" --json tagName --jq .tagName >/dev/null 2>&1; then  # timeout: 15000
        echo "! BLOCKED — $_AUDIT_VERSION is already a published release on GitHub. /release audit checks FORWARD readiness only."
        echo "  For retrospective analysis use: /oss:analyse  (requires oss plugin)"
        exit 1
    fi
fi
```
Read `$SKILL_DIR/modes/audit.md` and execute.

## Mode: demo

```bash
[ -f "$SKILL_DIR/modes/demo.md" ] || { echo "Error: modes/demo.md not found at $SKILL_DIR/modes/demo.md — verify oss plugin installation"; exit 1; }
```
Read `$SKILL_DIR/modes/demo.md` and execute.

</workflow>

<notes>

- **Doc artifacts ≠ released product**: CHANGELOG.md, DRAFT.md, MIGRATION.md, SUMMARY.md, demo.py are communication artifacts; the released product is published separately via `git tag`, `gh release create`, PyPI upload.
- **Numbers reference**: numeric limits documented with rationale in `guidelines/numbers-reference.md`; update whenever limits change
- Filter noise (CI config, dep bumps, typos) unless user-impacting
- **Public-facing content policy**: user-visible changes only. Never include: internal staff names, internal maintenance, CI/tooling, internal dep bumps, housekeeping with no user impact.
- **Contributor email privacy**: `.temp/` must be in `.gitignore` — emails from `git log --format="%aN <%aE>"` must not leak into repo.
- Public-facing output co-authored with `oss:shepherd` (requires `oss` plugin) — follow `$_OSS_SHARED/shepherd-voice.md`
- **Demo mode output**: jupytext percent format — convert with `jupytext --to notebook <file>.py`; replace placeholder URLs before publishing; Colab badge URL must point to actual notebook after upload
- **Demo real-world-only policy**: use actual project data/fixtures/API — synthetic requires explicit user approval; fallback: (1) document each failed attempt in `## Demo attempts`, (2) ask Codex if available, (3) ask user via `AskUserQuestion`, (4) synthetic only on explicit approval
- **Changelog audit non-destructive**: adds missing entries, flags extras, never removes automatically
- Follow-up chains:
  - Readiness check → `/release prepare <version>` runs built-in audit first; use standalone `/release audit [version]` only for readiness check without cutting release
  - Breaking changes → `/oss:analyse` (requires `oss` plugin) for ecosystem impact
  - Notes/changelog written → `gh release create` must be user-run via project tooling
  - `migration` content written → add to project docs and link from CHANGELOG entry

</notes>

<calibration>

Registered: `notes` mode — classification accuracy (change type, section assignment, noise filtering).

Future candidates (not yet registered): `prepare` (pipeline completeness), `audit` (verdict accuracy: READY/NEEDS_ATTENTION/BLOCKED), `demo` (headline feature selection, narrative quality, code cell correctness).

</calibration>
