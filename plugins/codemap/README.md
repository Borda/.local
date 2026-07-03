# 🗂️ codemap — Claude Code Plugin

> **Every `/develop:fix`, `/develop:refactor`, and `/oss:review` you run gets blast-radius context automatically — without you doing anything.**

codemap builds a structural index of your Python project — import graph, blast-radius scores, function call graph — and injects that context into your existing `/develop` and `/oss` skills. Run setup once; after that it is invisible infrastructure. When you ask Claude to fix `auth.py`, the agent already knows which 38 other modules import it before it touches a single line.

You do not use codemap by querying it directly. You use it by wiring it in and letting other skills pick it up.

**Python first.** The scanner uses `ast.parse` to index `.py` files. `.rst` and `docs/**/*.md` files are also scanned for Sphinx/MkDocs cross-references and included in cache-invalidation hashing — doc-only edits trigger incremental re-scans. Non-Python symbol indexing (TypeScript, Go, Rust) is planned.

______________________________________________________________________

<details>

<summary><strong>📋 Contents</strong></summary>

- [What is codemap?](#what-is-codemap)
- [Why codemap?](#why-codemap)
- [Install](#install)
- [Quick start](#quick-start)
- [Best-practice integration](#best-practice-integration)
- [Skills reference](#skills-reference)
  - [integration](#integration)
  - [scan-codebase](#scan-codebase)
  - [query-code](#query-code)
  - [rename-refs](#rename-refs)
  - [debrief-coding](#debrief-coding)
- [How it works](#how-it-works)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing / feedback](#contributing--feedback)

</details>

______________________________________________________________________

## 🤔 What is codemap?

codemap is a Claude Code plugin for Python projects. It pre-builds a structural index — who imports whom, which modules have the widest blast radius, how functions call each other — and injects that context into the `/develop` and `/oss` skills that do real code work. The index is built once; currency gates at skill-invocation time detect stale state automatically (covering `git pull`, branch switches, and uncommitted edits) and prompt for a refresh when needed. An optional post-commit hook accelerates refresh after local commits. Every skill invocation that follows starts with structural awareness already in hand.

Without codemap, every Claude Code session starts blind: the agent gropes through the codebase with Glob and Grep, burning 20–30 tool calls just to understand structure before it can do any real work. On a 200-module project those calls still miss blast-radius risks and import cycles that a structural scan would surface instantly.

codemap solves this: scan once, wire in once, then every skill that touches code benefits automatically.

______________________________________________________________________

## 🎯 Why codemap?

### Without codemap

You ask Claude to refactor `auth.py`. The agent:

1. Globs every `.py` file to find the project layout.
2. Reads files one by one to discover what imports `auth`.
3. Guesses at blast radius from the files it happened to read.
4. Starts editing, discovers mid-refactor that `middleware.py` also imports `auth`, backtracks.
5. Times out on large projects before surfacing all affected modules.

On pytorch-lightning (646 modules), plain-arm agents hit the 300-second hard timeout on three out of eight benchmark tasks.

### With codemap

After `/codemap:integration init`, your existing skills are wired in. Now when you run `/develop:refactor auth.py`, before spawning any agent the skill silently runs:

```bash
scan-query central --top 5         # which modules are highest risk overall?
scan-query rdeps mypackage.auth    # what breaks if auth changes?
```

That output is prepended to the agent spawn prompt as structural context. The agent starts the refactor already knowing full blast radius — no cold exploration, no mid-refactor surprise that `middleware.py` also imports `auth`. Across benchmark runs on pytorch-lightning, codemap consistently reduces tool calls by 50–80% while improving structural-recall metrics on import-graph tasks.

**Agentic benchmark (import-graph tasks on pytorch-lightning):** clean v0.13.2 numbers are pending a full benchmark re-run after the RC1 fix and will be published here once available.

**Real-codebase benchmark** — 44 developer tasks × 2 arms (plain vs codemap) × 3 model tiers on pytorch-lightning-master (646 modules, 8 task types). **Scope**: these are pre-implementation structural-query tasks (blast-radius enumeration, caller discovery) — end-to-end patch quality and test-pass rate are not yet measured. The benchmark is **repo-agnostic**: `tasks-bench.json` ships a `repo` header so the harness can be pointed at any Python codebase. Zero codemap timeouts; plain-arm agents hit the 300-second hard limit on several tasks.

### Three-model comparison

June 22 2026 — 44 tasks × 2 arms × 3 models, pytorch-lightning-master.

| Model      | Plain accuracy | Codemap accuracy | Accuracy lift | Safety-grade plain→codemap | Token ratio (median) | Token ratio range |
| ---------- | -------------- | ---------------- | ------------- | -------------------------- | -------------------- | ----------------- |
| Haiku 4.5  | 85.3% (29/34)  | 93.9% (31/33)    | **+9 pp**     | 5/13 → 12/13               | **0.38×**            | 0.04–68.2×†       |
| Sonnet 4.6 | 83.8% (31/37)  | 91.9% (34/37)    | **+8 pp**     | 11/13 → 12/12              | **0.22×**            | 0.05–1.21×        |
| Opus 4.6   | 86.1% (31/36)  | 91.7% (33/36)    | **+6 pp**     | 13/13 → 12/12              | **0.31×**            | 0.05–1.46×        |

Safety-grade = fraction of FN + BR tasks with explicit recall where recall ≥ 0.90. **Accuracy** = fraction of tasks where recall ≥ 0.90 (task scored correct when rdep coverage meets threshold). Token savings are model-independent; accuracy lift is model-dependent. **Single-repo caveat**: all figures on pytorch-lightning-master; gains on other Python codebases are directionally consistent but magnitude may differ.

† Haiku 68.2× is a RI-04 token spiral (error_max_turns); fixed June 23. Excluding RI-04, Haiku max is 1.82×.

> June 23 fix: Opus FN-02 and BR-03 regressions resolved (evaluator v3 — both recall→1.000); Haiku RI-02/RI-04 fixed (blocked python3/python on both arms — both recall→1.000).

#### Model-specific notes

**Haiku 4.5** — largest correctness gap between arms. Plain arm safety-grade 5/13 reflects chronic failures on FN-series (alias/lazy-import gaps) and real-issue tasks. Codemap restores 12/13. Token median 0.38× across all 44 tasks; query-type workflows median 0.28×. RI-02/RI-04 fixed June 23 (recall→1.000 after python3/python blocked). BR-07 minor regression: codemap recall=0.778 vs plain=0.889.

**Sonnet 4.6** — smallest token ratio (median 0.22×, query-type 0.14×). Accuracy parity at plain 83.8% / codemap 91.9%. FN-03 codemap extraction_failed; FT-03 codemap recall=0.500 vs plain not-scored. RI workflow cm_acc=75%. DG and SE both arms 100%.

**Opus 4.6** — token median 0.31×. Best plain accuracy (86.1%). FN-02 and BR-03 regressions fixed June 23 (recall→1.000 both arms). RI workflow cm_acc=100% (sonnet/opus succeed where haiku spirals). CQ-series: codemap lifts CQ-01/CQ-03/CQ-04/CQ-05 to 1.000 from poor plain scores.

**By series** (opus — June 23 full run, `bench-opus-20260623-023648.jsonl`):

| Series                 | plain | codemap | Notes                                                                 |
| ---------------------- | ----- | ------- | --------------------------------------------------------------------- |
| SE — symbol extraction | 5/5   | 5/5     | Both arms perfect; codemap saves 37–63% tokens                        |
| FN — call graph        | 4/5   | 3/4     | Plain misses FN-01 (0.808); FN-03 codemap extraction failed           |
| BR — blast radius      | 8/8   | 8/8     | Both arms perfect; codemap saves 49–97% tokens                        |
| RV — review assistance | 2/5   | 3/5     | RV-03/04 over-count both arms; RV-05 codemap lift (0.80 → 1.00)       |
| CQ — code quality      | —     | 5/5     | Count-based scoring (no recall); codemap hits all 5, plain unreliable |

> **FN-series is the starkest signal for haiku and opus**: plain arm burns 0.85M–4.0M tokens and fails 2–3 of 5 call-graph tasks; codemap resolves the full caller set in a single query at 4–16% of the token cost. Sonnet inverts this — strong reasoning compensates for lack of structural index on FN, but codemap execution failure on two tasks pulls safety-grade below plain.

> **Static AST limitations**: scan-query does not resolve dynamic dispatch, hook callbacks, `importlib.import_module`, lazy-loading patterns, or string-based dispatch. Calls through these mechanisms are not counted. Semble, when available, reduces tool calls further and slightly boosts erec at a modest rrec trade-off. When the semble MCP server is available, agents also get `mcp__semble__search` as an optional semantic search tool — useful when the codemap index is non-exhaustive.

> **⚠ Integration quality matters — poor wiring can make things worse.**
>
> codemap injects a rich dependency graph into every agent prompt. On weaker models or tasks with large blast-radius graphs, this extra context can overwhelm the model and cause it to fall back to grep-heavy loops — performing *worse* than plain arm. The benchmark labels this failure mode `degenerate_grep_loop`.
>
> Good integration requires three things: (1) **skill-first protocol** — the agent calls `/codemap:query-code` before any Grep/Glob; (2) **bounded call budget** — max 3 codemap queries per task; (3) **hard stop on `exhaustive: true`** — when the index says the list is complete, write the answer immediately, no more tool calls. Skipping any of these — especially ignoring the exhaustive flag — is the primary cause of regressions that flip the codemap benefit into a liability. Use `/codemap:integration init` to wire integration correctly rather than injecting context manually.

### Real-world proof: daily-work benchmark

The benchmarks above measure the **discovery phase** — enumerating callers, assessing blast radius before any code is written. The `fix_multicaller` suite extends coverage to the **edit phase**: a real signature change where all callers must be updated in one pass.

**Benchmark scope**: 7 tasks in `benchmarks/run-codemap-agentic.py` across two families. Both use archive/restore isolation — the demo codebase is copied per arm run, the agent edits the copy, and `diff -ru` is captured against the original. No git required; original codebase never mutated.

| Family                          | Tasks                          | What it tests                                                                 | Scored by                                           |
| ------------------------------- | ------------------------------ | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `fix_single` (FS-01–FS-04)      | Single-file bug fix            | Validates archive/restore isolation; `EarlyStopping`/`ModelCheckpoint` guards | Diff keyword recall (`erec`)                        |
| `fix_multicaller` (FM-01–FM-03) | Signature change + all callers | codemap `fn-rdeps` enumerates callers before editing; plain arm must grep     | Diff keyword recall (`erec`) + file recall (`rrec`) |

**FM-03 (`Strategy.setup`) is the decisive test**: adding `verbose: bool = False` to the base-class `setup` method requires updating 6 subclass overrides in `ddp.py`, `fsdp.py`, `deepspeed.py`, `model_parallel.py`, `single_xla.py`, and `xla.py`. The codemap arm runs `scan-query fn-rdeps lightning.pytorch.strategies.strategy::Strategy.setup` before any edit and gets the complete override list in one call. The plain arm must grep for `def setup` and read candidate files. Missing overrides = silent `super().setup()` signature mismatch at runtime. File recall (`rrec`) captures whether the right files were actually changed.

This is the only public Claude Code plugin benchmark that measures edit-phase caller coverage — not just structural discovery.

```bash
# Fix-multicaller: the codemap vs plain edit-assist test
python benchmarks/run-codemap-agentic.py \
    --repo-path /path/to/pytorch-lightning/src/lightning \
    --tasks "['FM-01','FM-02','FM-03']" --run-all --model haiku --report

# Fix-single: validates the archive/restore isolation mechanism
python benchmarks/run-codemap-agentic.py \
    --repo-path /path/to/pytorch-lightning/src/lightning \
    --tasks "['FS-01','FS-02','FS-03','FS-04']" --run-all --model haiku
```

______________________________________________________________________

## Integration with develop and oss plugins

codemap is not a standalone tool — its primary value is the structural context it feeds into the `/develop` and `/oss` skills that do real code work. This section documents exactly what is wired today, what each integration delivers based on benchmark data, and where the current implementation has known gaps.

### What is wired today

| Skill               | Integration type                             | What codemap provides                                                                                                                                                                         |
| ------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/develop:review`   | Active — per changed module                  | rdeps, fn-blast, mock-rdeps, uncovered, xrefs, undocumented — results injected into every dimension-agent prompt with "trust codemap, skip redundant Grep/Read"                               |
| `/oss:review`       | Active — per changed module                  | Same per-module query set as develop:review; codemap context piped to each reviewer agent                                                                                                     |
| `/develop:refactor` | Active — per affected module                 | rdeps + coupled callers; flags callers OUTSIDE refactoring scope as silent-contract-break risk                                                                                                |
| `/develop:fix`      | Active — per target function                 | `fn-rdeps` fires for direct callers of the bug's target function (`module::function` from ARGUMENTS or auto-derived from `checkpoint.md` after Step 1)                                        |
| `/develop:feature`  | Active (integration) / Passive (new surface) | Integration target (`module::function` supplied): `fn-rdeps` fires for direct callers. Module-only target: `rdeps` for importers. Net-new surface (no existing symbol): central baseline only |

### Expected benefits per skill (based on benchmark data — haiku/sonnet, 28-task suite)

| Skill task type             | Token savings (codemap vs plain) | Accuracy lift                                                                                 |
| --------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------- |
| Review (per-module impact)  | 80–90% fewer tokens              | Maintains accuracy while eliminating redundant grep walks                                     |
| Blast radius / caller count | 6–17× fewer tokens               | +40 pp (haiku: 50% → 90%) — codemap returns exact caller list in 1 call vs 150+ grep/read ops |
| Symbol location             | 20–75% fewer tokens              | No accuracy change — both find it, codemap finds it faster                                    |
| Refactor impact             | 80–90% fewer tokens              | Systematic caller coverage — plain arm misses 15–54% of callers on large functions            |

### Graceful degradation

Skills use two gates at invocation time:

- **Gate A (missing index)**: when `scan-query` is available but the index file is absent, the skill pauses and asks: (a) build the index inline via `/codemap:scan-codebase`, or (b) skip and continue without codemap context.
- **Gate B (stale index)**: when `check-index-currency` detects the index no longer matches source (changed files since last scan), the skill warns and asks: (a) rescan now, (b) continue with stale index, or (c) abort.
- **`scan-query` absent**: skill auto-degrades silently and proceeds without codemap — binary absence means the plugin is not installed, not that the source changed.

### Known gaps (challenger audit 2026-06-20)

| Gap                                                                                                                                                                | Status                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`fn-rdeps` not used** — benchmark-proven subcommand for caller accuracy invoked in zero develop/oss skill workflows; skills used `fn-blast` (transitive) instead | Fixed — `fn-rdeps` added to `/develop:review`, `/oss:review`, and the `codemap-context.md` review pipeline                                                   |
| **`/develop:fix` blast-radius dead code** — TARGET_FN/TARGET_MODULE never set → only `central --top 5` ran → no per-bug caller impact                              | Verified working — `fn-rdeps` fires via `codemap-context.md` when `module::function` format supplied; `checkpoint.md` auto-derive covers free-text ARGUMENTS |
| **`/develop:feature` blast-radius dead code** — same TARGET-unset defect as fix path                                                                               | Verified working — both TARGET_MODULE and TARGET_FN are extracted; `fn-rdeps` fires via `codemap-context.md` when TARGET_FN set                              |
| **Silent degradation** — if index missing, skills proceed at full token cost with no warning                                                                       | Fixed — `codemap-context.md` emits ⚠ warning to stderr when `scan-query` unavailable or index missing                                                        |
| **`check_injection.py` blind spot** — health check detected marker comment presence only; could not catch TARGET-unset defect or missing `fn-rdeps` wiring         | Fixed — second audit layer added: `check_fn_rdeps_wiring()` now reports whether `fn-rdeps` is wired in all required files                                    |

______________________________________________________________________

## 📦 Install

<details>

<summary><strong>Prerequisites</strong></summary>

- Claude Code installed and working
- Python 3 on PATH (standard library only — no `pip install` required)
- Git (recommended — used for staleness detection and incremental rebuilds)

</details>

**Install the plugin**

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install codemap@borda-ai-rig
```

That's it. No build step. The scanner (`scan-index`) and query CLI (`scan-query`) are plain Python scripts — they run immediately.

**Make scan-query available in your terminal (optional)**

Inside Claude Code sessions, `scan-query` and `scan-index` are on PATH automatically via the plugin's `bin/` directory. To use them in your regular terminal too, add this to `~/.zshrc` or `~/.bashrc`:

```bash
CODEMAP_TOOLS=$(ls -d "$HOME/.claude/plugins/cache/borda-ai-rig/codemap"/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$CODEMAP_TOOLS" ] && export PATH="$PATH:$CODEMAP_TOOLS"
```

Reload your shell (`source ~/.zshrc`) and `scan-query` is available everywhere. This snippet always picks up the latest installed version automatically — no version pins to maintain.

<details>

<summary><strong>Upgrade</strong></summary>

```bash
claude plugin install codemap@borda-ai-rig
```

After upgrading, re-run `/codemap:integration init` to re-apply injection blocks — the plugin cache is replaced on reinstall and any prior injections are lost.

</details>

<details>

<summary><strong>Uninstall</strong></summary>

```bash
claude plugin uninstall codemap
```

</details>

______________________________________________________________________

## ⚡ Quick start

Two commands — then forget about codemap and just use your normal skills.

**Step 1 — build the index:**

```text
/codemap:scan-codebase
```

Output:

```text
[codemap] ✓ .cache/codemap/myproject.json
[codemap]   312 modules indexed, 2 degraded

Modules: 312 indexed, 2 degraded
Symbols: 4,821 (functions, classes, methods)
Calls:   18,340 resolved call edges (v3 index)

Most central (by rdep_count):
  89  myproject.models
  41  myproject.config
  38  myproject.utils
  27  myproject.exceptions
  19  myproject.auth
```

**Step 2 — wire codemap into your installed skills:**

```text
/codemap:integration init
```

<!-- mirrors integration/SKILL.md Step I5 -->

This discovers all your installed `develop` and `oss` skills, shows a recommendation table, and injects the structural context block into each one you approve. It also offers to install a post-commit git hook so the index stays current automatically.

That is it. Now run your normal skills — codemap works silently in the background:

```text
/develop:fix auth.py         # agent already knows blast radius of auth before it starts
/develop:refactor models.py  # agent sees which 89 modules import models upfront
/oss:review                  # reviewer gets structural context on changed modules
```

If you ever want to explore structure manually, `/codemap:query-code` is there for you — but most users rarely need it.

______________________________________________________________________

## ✅ Best-practice integration

______________________________________________________________________

**Six rules that cover 95% of what you need to know:**

### 1 — Build the index once

Run `/codemap:scan-codebase` after cloning or setting up the project. The index lands in `.cache/codemap/<project>.json`. Re-run only after major structural changes or when a gate fires.

### 2 — Wire in once per project

Run `/codemap:integration init` once. This injects the structural context block into each of your `/develop` and `/oss` skills and (optionally) installs the post-commit hook. Without wiring, the index exists but no skill uses it.

### 3 — Gates are the primary safety mechanism

After wiring, two gates fire automatically at the start of each skill invocation:

- **Gate A — missing index**: fires when the index is absent. Offers to build it now, continue without codemap, or abort.
- **Gate B — stale index**: fires when `check-index-currency` detects drift (git HEAD changed, uncommitted `.py` edits, or per-file SHA-256 mismatch). Offers to rescan, continue with stale data, or skip codemap.

Gates cover what the post-commit hook misses: `git pull`, branch switches, and uncommitted edits.

### 4 — Post-commit hook is optional

The hook triggers `scan-codebase --incremental` after local commits only — a convenience accelerator, not the safety net. Gates work without it. Install via `/codemap:integration init`; skip it if you prefer manual control.

### 5 — Ambient index status (UserPromptSubmit hook)

A `UserPromptSubmit` hook fires on every user message and injects a one-line codemap status into Claude's context when an index exists at `.cache/codemap/<project>.json`. When the index is **absent**, the hook stays silent for non-Python dirs (zero output, near-zero overhead); for Python projects it emits a once-per-session bootstrap prompt (see below).

```
[codemap] .cache/codemap/rfdetr.json · 47 modules · current (git: f20fa19) · scanned: 2026-06-23
Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol.
```

When the index is **stale** (git HEAD differs from stored sha), the hook spawns `scan-index --root <scan_root>` in the background (non-blocking, 10-minute lockfile guard) so the index refreshes silently while Claude is answering. Status reads `· refresh started` on the first stale turn and `· refresh in progress` on subsequent turns until the scan completes.

When the index is **current**, the hook injects the status line only once per session (30-min TTL flag at `/tmp/codemap-preamble-<proj>`). Subsequent turns skip injection — saving ~30 tokens × N turns ≈ ~900 tokens/session. Stale index always injects regardless of TTL so the auto-refresh note always reaches the agent.

When there is **no index yet** and the project is Python (`__init__.py` at the git root or one level down, a `src/<pkg>/__init__.py` src-layout, or — failing those — a `pyproject.toml`/`setup.py` at the root), the hook emits a once-per-session directive (30-min TTL flag at `/tmp/codemap-noindex-<proj>`) asking the agent to raise an `AskUserQuestion` offering to build the index. On consent the agent runs `scan-index` in the foreground and waits for it to finish before continuing. This bootstraps first-time projects that would otherwise never self-scan — the stale auto-refresh only fires on an already-existing index, and the skill-level Gate A missing-index prompt only fires inside wired `/develop`/`/oss` skills. Non-Python dirs receive nothing.

This complements the per-skill SKILL.md injection — which handles dynamic per-PR `scan-query` output and interactive Gate A/B prompts — with a lightweight always-on preamble that reaches every turn, not just skill invocations.

### 6 — Redundant-scan guard (Pre/PostToolUse hooks)

Once `scan-query rdeps <module>` returns an **exhaustive** result, the import graph for that module is complete and authoritative — re-grepping it with `grep`/`rg` adds nothing but tokens. Benchmarks showed agents (weak tiers especially) ignoring the "stop" instruction and looping on verification greps, burning millions of input tokens at zero recall gain.

Two hooks close this mechanically: `record-exhausted.js` (PostToolUse on Bash) notes each module returned exhaustive this session; `guard-redundant-scan.js` (PreToolUse on Bash) then **denies** import-discovery greps (`grep`/`rg` for `import`/`from`) targeting an already-exhausted module, pointing the agent back to the codemap result. Scope is deliberately narrow and fail-open: only import-greps for an already-exhausted module are blocked (source reads via `cat`/`Read` are never touched), only within the same session, and any hook error allows the call. Sessions that never run codemap (no sentinel) are unaffected. Disable by removing the two `Bash`-matcher entries from `hooks/hooks.json`.

### 7 — Two-tier currency check

`check-index-currency` runs inside Gate B:

- **Tier 1** (git repos): compares stored `git_sha` vs `HEAD`; counts uncommitted `.py` changes via `git status --porcelain`. Fast — no file reads.
- **Tier 2** (no git or no stored SHA): compares per-file git blob SHA-1 (git repos) or MD5 (non-git) hashes stored at scan time against current content, with mtime pre-filtering to skip unchanged files. Catches changes in non-git workflows or when `git_sha` is absent.

______________________________________________________________________

## 🔧 Skills reference

______________________________________________________________________

### integration

**Trigger**: `/codemap:integration check | init [--approve] | demo [--repo <path|url>] [--public] [--anonymize] [--keep-clone] [--output <path>]`

Three modes. Run `init` once to wire codemap into your existing skills and agents. Run `check` anytime to verify the setup is healthy. Run `demo` to validate end-to-end that codemap is plugged in correctly and yields expected gains.

#### check mode

A fast diagnostic with no side effects. Checks:

1. `scan-query` is reachable on PATH (or found via fallback locations)
2. The index file exists for the current project
3. The index age (warns if older than 7 days)
4. A smoke test: runs `central --top 3` and verifies output
5. Which installed skill files have the codemap injection block

Each check prints `✓`, `✗`, or `⚠` with a one-line remediation hint if needed.

```text
/codemap:integration check
```

#### init mode

Interactive onboarding for the current project:

1. Builds the index if it is missing (offers to run `/codemap:scan-codebase`)
2. Discovers all installed skills and agents across all plugins
3. Scores candidates by value tier (High / Medium / Low / Skip) based on whether structural context would help them
4. Presents a recommendation table and asks which to wire in
5. Inserts the correct injection block into each selected skill or agent file
6. Offers to install a `.git/hooks/post-commit` hook for automatic incremental rebuilds

```text
/codemap:integration init
```

Pass `--approve` to apply all High and Medium recommendations non-interactively:

```text
/codemap:integration init --approve
```

`--approve` delegates injection to `bin/inject_codemap.py`, which scores each skill candidate for Python/codemap relevance (0–4), injects the context block before `## Step 1`, backs up before writing, and rolls back on failure. Run it directly for scripted or CI use:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/inject_codemap.py" \
    --plugin-root <path> [--apply] [--dry-run] [--verbose]
```

#### Manual injection

If you write custom skills or agents and want to add codemap yourself, drop this soft-check block before the first agent spawn. It runs when codemap is available and silently skips when it is not:

```bash
# Structural context (codemap — Python projects only, silent skip if absent)
PROJ=$(basename "$(git rev-parse --show-toplevel 2>/dev/null)" 2>/dev/null) || PROJ=$(basename "$PWD")
if command -v scan-query >/dev/null 2>&1 && [ -f ".cache/codemap/${PROJ}.json" ]; then
    scan-query central --top 3  # timeout: 5000
fi
# If results returned: prepend ## Structural Context (codemap) to the agent spawn prompt.
```

For skills that know the target module up front (refactor, fix), also add targeted queries:

```bash
scan-query rdeps "$TARGET_MODULE" 2>/dev/null  # timeout: 5000
scan-query deps  "$TARGET_MODULE" 2>/dev/null  # timeout: 5000
```

For agent `.md` files, add this instruction before the closing section:

```markdown
**Structural context (codemap — Python projects only)**: if `.cache/codemap/<project>.json` exists,
run `scan-query central --top 5` (and `scan-query rdeps <target_module>` when a target is known)
**before** any Glob/Grep exploration for structural information. Skip silently if the index is absent.
```

#### demo mode

End-to-end validation for a repo. Runs plumbing check, builds index if missing, executes sample tasks to populate telemetry logs, runs a plain-vs-codemap A/B to prove expected gains, and produces a final report with a link to the debrief output.

**Flags** (all optional):

| Flag                 | Effect                                                                   |
| -------------------- | ------------------------------------------------------------------------ |
| `--repo <path\|url>` | Target repo — local path or git URL; URL triggers clone gate             |
| `--public`           | Force clone gate even if current repo has `.py` files                    |
| `--anonymize`        | Forward `--anonymize` to `debrief-coding` in the final report            |
| `--keep-clone`       | Skip cleanup prompt after demo on a cloned repo                          |
| `--output <path>`    | Override report output path (default: `.reports/codemap/demo-<date>.md`) |

```text
# Validate current repo
/codemap:integration demo

# Validate with a fresh public-repo clone (gate fires first)
/codemap:integration demo --public

# Run demo on a specific repo path
/codemap:integration demo --repo /path/to/myproject

# Produce an anonymized shareable report
/codemap:integration demo --anonymize
```

**A/B caveat**: Arms are prompt-gated (not hard tool deny-list). Tool-call counts serve as cost proxy. Recall is scored against ground truth for the `psf/requests` pinned task set; other repos use cross-arm agreement as a recall proxy.

**Scenarios covered:**

1. Fresh repo, no index — demo builds it (D3) and reports module count.
2. Stale index — D2 flags stale age; D3 refreshes.
3. Skills never invoked (Sk=0) — D7 flags this and explains the diagnostic artifact.
4. Public-repo demo — D1a clone gate fires before any clone; D9 offers cleanup.
5. Anonymized report — `--anonymize` forwarded to `debrief-coding`; output safe to share.

### scan-codebase

**Trigger**: `/codemap:scan-codebase`

Builds the structural index by running `ast.parse` across every `.py` file in the project. Writes the index to `.cache/codemap/<project>.json`. Reports how many modules were indexed, how many were degraded (parse errors), and which five modules have the highest blast radius.

#### Flags

| Flag            | What it does                                                                                                                       |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| _(none)_        | Full scan — re-parses every `.py` file                                                                                             |
| `--incremental` | Re-parse only files that changed since the last scan (uses git blob SHA comparison); falls back to full scan if no v3 index exists |
| `--root <path>` | Scan a specific directory instead of the git root                                                                                  |

#### When to run

Run a full scan once when you first set up the project. After that, skill-invocation currency gates detect stale state and prompt for a rescan automatically — you rarely need to run this manually. When you do want to force a refresh, `--incremental` is fast enough for most changes. Install the optional post-commit git hook (via `/codemap:integration init`) for background auto-refresh after local commits.

#### Performance

| Project size | Full scan | Incremental (5 files changed) |
| ------------ | --------- | ----------------------------- |
| ~200 modules | ~25s      | ~75ms                         |
| ~650 modules | ~60s      | ~75ms                         |

#### Example

```text
/codemap:scan-codebase
```

```text
/codemap:scan-codebase --incremental
```

______________________________________________________________________

<a id="query-code"></a>

<details>

<summary>

### query-code — full subcommand reference

</summary>

### query-code

**Trigger**: `/codemap:query-code <subcommand> [args]`

**Auto-invokes when:** user asks about module relationships, dependency graph, callers/callees, or blast radius; phrases: "what depends on", "who calls", "imports of", "blast radius of". No prior index needed — a Step 0 pre-flight builds one automatically when it is missing and incremental-refreshes it when it already exists, before querying.

Queries the index. Step 0 keeps it fresh (full build via `/codemap:scan-codebase` if missing, `scan-index --incremental` if present), so queries run against a current index. If Python files change mid-task a stale warning may still appear on stderr; results are still returned so the agent can refresh and retry.

#### Module-level queries

These work with any v2 or v3 index.

| Subcommand          | What it answers                                                       |
| ------------------- | --------------------------------------------------------------------- |
| `rdeps <module>`    | What imports this module? (blast radius)                              |
| `deps <module>`     | What does this module import?                                         |
| `central [--top N]` | Which modules are imported by the most others? Default N=10           |
| `coupled [--top N]` | Which modules import the most others? Default N=10                    |
| `path <from> <to>`  | Shortest import chain between two modules; `null` means not connected |
| `list`              | All indexed modules with their file paths                             |

#### Symbol-level queries

Retrieve function or class source by name instead of reading the full file — dramatically fewer tokens than reading whole files — 91–95% reduction for targeted method lookups on large files (benchmark: pytorch-lightning `Trainer.fit`, 1 790 tokens with imports vs 19 824 tokens full file).

| Subcommand                       | What it answers                                                                                                            |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `symbol <name> [--with-imports]` | Source of a function, class, or method by name; add `--with-imports` to include module-level import block alongside source |
| `symbols <module>`               | All symbols in a module with type and line range                                                                           |
| `find-symbol <pattern>`          | Regex search across all symbol qualified_names in the index                                                                |

`symbol` accepts bare name (`authenticate`), qualified name (`MyClass.authenticate`), or a case-insensitive substring fallback. `find-symbol` and `symbol` cap results at 20 by default — pass `--limit 0` to retrieve all matches before counting or ranking.

Every `symbol` result includes `"stale": bool` and `"stale_reason": string | null`. When `stale: true`, the index line range no longer matches the current file — fall back to `Read(<path>)` instead. Common reasons: `"file deleted"`, `"line range past EOF"`, `"symbol name not in slice header"` (function moved or renamed since last scan). The `path` field is always valid even when `stale: true`.

#### Function-level call graph queries (v3 index)

These require a v3 index built by `/codemap:scan-codebase`. If your index is older (v2), the commands return a clear upgrade message.

| Subcommand             | What it answers                                        |
| ---------------------- | ------------------------------------------------------ |
| `fn-deps <qname>`      | What does this function call? (outgoing call edges)    |
| `fn-rdeps <qname>`     | What functions call this one? (incoming call edges)    |
| `fn-central [--top N]` | Most-called functions across the project. Default N=10 |
| `fn-blast <qname>`     | Transitive reverse-call BFS with depth levels          |

Use `module::function` format for qualified names, for example `mypackage.auth::validate_token` or `mypackage.auth::AuthMiddleware.process`.

**Call edge resolution types**: `import` = cross-module call with confirmed import scope; `local` = same-file call; `self` = `self.method()` call where the target class is known; `star` = call to a name from a star import where the source module could not be determined; `unresolved` = call target could not be matched.

#### Common flags

| Flag              | Applies to                                                                       | Effect                                                               |
| ----------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `--exclude-tests` | `rdeps`, `central`, `coupled`, `symbol`, `find-symbol`, `fn-rdeps`, `fn-central` | Drop test modules from results                                       |
| `--limit N`       | `symbol`, `find-symbol`                                                          | Max results (default 20). Use `0` for unlimited                      |
| `--with-imports`  | `symbol`                                                                         | Include module-level import block alongside each symbol's source     |
| `--root <path>`   | all commands                                                                     | Override project root for file path resolution (see scan_root below) |
| `--index <path>`  | all commands                                                                     | Explicit index file; bypasses auto-discovery                         |

#### Common patterns

```text
# Before refactoring auth.py — understand full blast radius
/codemap:query-code rdeps myproject.auth

# Before adding a dependency to models.py — see what already imports it
/codemap:query-code central --top 5

# Check if api and db are already coupled before adding a direct import
/codemap:query-code path myproject.api myproject.db

# Read just the validate_token function without loading the whole file
/codemap:query-code symbol validate_token

# Read a function and its module-level imports (for type-context analysis)
/codemap:query-code symbol --with-imports validate_token

# Find all functions whose name starts with "validate" (unlimited results)
/codemap:query-code find-symbol "^validate" --limit 0

# Check transitive impact of changing fetch_user at the function level
/codemap:query-code fn-blast myproject.db::fetch_user

# Exclude test modules from blast-radius analysis
/codemap:query-code central --exclude-tests --top 10

# Query a specific index file (monorepo with multiple projects)
/codemap:query-code central --index /path/to/.cache/codemap/subproject.json
```

</details>

______________________________________________________________________

<a id="test-impact"></a>

### test-impact

**Trigger**: `/codemap:test-impact <module::symbol | module> [--no-mocks]`

**Auto-invokes when:** user asks which tests are affected by a change, wants to skip unrelated tests, or asks about selective test runs; phrases: "which tests cover this", "what tests to rerun", "test impact of", "run only affected tests".

Identifies the minimal set of tests to rerun after changing a function or module using static analysis — no test execution required.

**Two modes:**

- `module::symbol` — BFS over reverse call graph; finds every test calling the changed function directly or transitively. Also includes tests that mock the symbol via `patch()`.
- `module` — BFS over reverse import graph; finds every test importing the module through any chain. Also includes tests that mock any symbol in the module.

```text
/codemap:test-impact myproject.auth::validate_token
/codemap:test-impact myproject.utils
/codemap:test-impact myproject.auth::validate_token --no-mocks
```

Output includes `test_files`, `via_call`/`via_mock` breakdown, and a ready-to-run `pytest_cmd`. **Limitation**: static-AST only — dynamic dispatch and hook-callback callers not covered; `not_covered` field signals this, `hint` provides grep fallback.

______________________________________________________________________

<a id="rename-refs"></a>

<details>

<summary>

### rename-refs — atomic symbol and module rename

</summary>

### rename-refs

**Trigger**: `/codemap:rename-refs symbol <old_qname> <new_qname>` or `/codemap:rename-refs module <old_module_path> <new_module_path>`

**Auto-invokes when:** user asks to rename a function, class, method, or module; phrases: "rename X to Y", "rename function", "rename class", "rename module", "move module X to Y", "update all references to X". Requires codemap index (run `/codemap:scan-codebase` first).

Atomically renames a Python symbol or module using the structural index. Finds and updates:

- Definition site (the `def` / `class` line)
- `__all__` re-exports in `__init__.py` files
- Import call sites across all callers (indexed via fn-rdeps)
- Sphinx docstring cross-refs (`:func:`, `:class:`, `:meth:`, `:mod:`, `:attr:`) in `.py` and `.rst` files

Presents a blast-radius report before applying any edits. Shows which files and call sites will change, warns if the index is non-exhaustive, and asks for confirmation before touching anything.

#### Subcommands

| Subcommand                                   | What it renames                                                                    |
| -------------------------------------------- | ---------------------------------------------------------------------------------- |
| `symbol <old_qname> <new_qname>`             | Function, class, or method. qname = bare name, qualified, or full `module::symbol` |
| `module <old_module_path> <new_module_path>` | Dotted module path. Renames file (`git mv`) + all import lines                     |

#### Flags

| Flag                     | Effect                                                                     |
| ------------------------ | -------------------------------------------------------------------------- |
| `--dry-run`              | Print all sites that would change; no edits applied                        |
| `--deprecate`            | Symbol only: keep old name as `@deprecated` alias pointing to new name     |
| `--since <ver>`          | Version when the symbol was deprecated (passed to deprecation decorator)   |
| `--removed-in <ver>`     | Version when the old name will be removed                                  |
| `--remove-if-no-callers` | Symbol only: hard-delete definition when index exhaustive and zero callers |

#### Hard limits

Two cases are outside static analysis and cannot be renamed automatically:

1. `getattr(obj, "old_name")` **dynamic dispatch** — the string has no static binding to the symbol; the skill emits a `grep` advisory so you can check manually.
2. **Cross-repo consumers** — external packages are out of scope by definition. Use `--deprecate` combined with a semver bump and CHANGELOG entry for public API renames.

#### Examples

```text
# Rename a function and update all call sites
/codemap:rename-refs symbol mypackage.auth::validate_token mypackage.auth::verify_token

# Preview what would change without editing
/codemap:rename-refs symbol MyClass MyNewClass --dry-run

# Rename with backward-compatible deprecated alias
/codemap:rename-refs symbol mypackage.utils::compute_score mypackage.utils::score --deprecate --since 2.1 --removed-in 3.0

# Rename a module (renames file + all import lines)
/codemap:rename-refs module mypackage.old_utils mypackage.utils
```

</details>

______________________________________________________________________

<a id="debrief-coding"></a>

### debrief-coding

**Trigger**: `/codemap:debrief-coding`

Reads `.cache/codemap/logs/` JSONL telemetry produced by the core CLI tools (`scan-query` and `scan-index`) and the skill-start PreToolUse hook, and writes a diagnostic usage report. Useful for debugging query patterns, investigating errors, understanding which skills drive the most queries, and preparing a shareable anonymized summary for feedback.

#### Flags

| Flag                   | Effect                                                                                                               |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `--since <YYYY-MM-DD>` | Filter to records on or after this date (default: all records)                                                       |
| `--session <id>`       | Filter to a single session UUID                                                                                      |
| `--anonymize`          | Replace qualified names (module paths, symbol names) with stable pseudonyms before reading — output is safe to share |
| `--output <path>`      | Write report to this path (default: `.reports/codemap/debrief-<date>.md`)                                            |

#### What is logged

All logs are local to `.cache/codemap/logs/` and never leave your machine.

| File                     | Layer | When written                                                           |
| ------------------------ | ----- | ---------------------------------------------------------------------- |
| `cli_<session>.jsonl`    | cli   | Every `scan-query` query and every `scan-index` build (core CLI tools) |
| `skills_<session>.jsonl` | skill | Every `/codemap:*` skill start (via PreToolUse hook)                   |

Logs are sharded per session: the SessionStart hook (`seed-session.js`) seeds the Claude Code session id into `$TMPDIR/codemap-<project>-session`, and both layers append to `<layer>_<session>.jsonl`. CLI runs outside a session (no seeded id) fall back to unsuffixed `cli.jsonl` / `skills.jsonl`. Per-session filenames keep concurrent sessions from interleaving appends.

CLI records include: `cmd` (query subcommand, or `index` for a `scan-index` build), full argv, result summary (query: count, method, exhaustive flag, not_covered list, error; index: modules_indexed, degraded, incremental), timing_ms, stderr tail if any, exit code if non-zero.

Skill records include: skill name, session UUID, intent (first 300 chars of the args string).

Logs rotate automatically at 10 MB (3 rotations). Disable logging entirely with `CODEMAP_LOGGING=false` — useful in benchmark scripts.

#### Anonymization

`--anonymize` runs `bin/anonymize.py` on every present log file before reading. Qualified names (strings containing `.` or `::`) are replaced with stable `sym_<hash>` pseudonyms using a project-local salt stored at `.cache/codemap/logs/.salt`. The salt must stay local — never share it alongside anonymized output. Without the salt, pseudonyms are not reversible.

#### Examples

```text
# Basic report of all collected telemetry
/codemap:debrief-coding

# Last week only
/codemap:debrief-coding --since 2026-06-15

# Single session trace (correlate a skill run with its scan-query calls)
/codemap:debrief-coding --session 3f2e1a90-...

# Anonymized report safe to share
/codemap:debrief-coding --anonymize --output /tmp/codemap-report.md
```

## ⚙️ How it works

### The scanner (`scan-index`)

`scan-index` is a plain Python 3 script with no external dependencies. It:

1. Walks every `.py` file under the project root, skipping common non-source directories (`.git`, `.venv`, `__pycache__`, `dist`, `build`, and others).
2. Parses each file with `ast.parse` to extract import statements and symbol definitions (classes, functions, methods with line ranges).
3. Resolves call edges per function: cross-module calls tagged as `import`, same-file calls as `local`, `self.method()` patterns as `self`, star-import calls as `star`.
4. Computes graph metrics for each module: `rdep_count` (how many project modules import this one), `dep_count` (how many modules this one imports), `rcall_count` (how many functions across the project call any function in this module).
5. Stores per-file git blob SHAs (`file_shas`) for `.py`, `.rst`, and `docs/**/*.md` files so incremental rebuilds can identify exactly which files changed.
6. Writes everything to `.cache/codemap/<project>.json` as a single JSON file.

Files that cannot be parsed (syntax errors, encoding issues) are marked `degraded` with a reason. The scan never aborts — a file that fails parsing is noted and skipped.

### The query CLI (`scan-query`)

`scan-query` is a companion Python 3 script that loads the index and answers structural questions. It checks staleness on every call by comparing current git blob SHAs against the stored `file_shas`. If files have changed, it warns to stderr and returns results anyway.

All output is JSON. This makes it easy to pipe directly into agent spawn prompts, shell scripts, or further analysis.

Every command embeds an `index` object in its output — the coverage block — so consumers know exactly how reliable the result is:

| Field             | Type      | Meaning                                                                                |
| ----------------- | --------- | -------------------------------------------------------------------------------------- |
| `method`          | string    | How the result was produced: `index-lookup`, `static-ast`, `import-graph`, `ast-flags` |
| `confidence`      | string    | `"exact"` when result is complete; `"partial"` when truncated or any symbol is stale   |
| `truncated`       | bool      | Present and `true` when `--limit` cut the result; absent otherwise                     |
| `total_available` | int       | Total matches before truncation (only present when `truncated: true`)                  |
| `not_covered`     | list[str] | Call patterns the static analysis cannot see (dynamic dispatch, hook callbacks, etc.)  |
| `hint`            | string    | Suggested grep/fallback for residual-risk verification when `not_covered` is non-empty |
| `scope`           | string    | Sub-graph or index slice the command operated on                                       |
| `total_modules`   | int       | Modules in the index at query time                                                     |
| `total_symbols`   | int       | Symbols across all modules                                                             |
| `degraded`        | int       | Modules skipped due to parse errors                                                    |
| `exhaustive`      | bool      | `true` when every module parsed successfully                                           |
| `stale`           | bool      | `true` when the index predates a recent file change                                    |

When `not_covered` is non-empty, agents surface a caveat. When `confidence="exact"`, no grep re-verification is needed.

### The index file

The index lives at `.cache/codemap/<project>.json` where `<project>` is the basename of the git root directory. It is a single flat JSON file — nothing needs to keep running. The format is versioned (`scan_version: 3` in current builds).

Key fields per module entry:

| Field            | Meaning                                                                                                                              |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `name`           | Fully qualified module name (e.g. `mypackage.auth`)                                                                                  |
| `path`           | Path to the `.py` file relative to project root                                                                                      |
| `rdep_count`     | Number of project modules that import this one (blast-radius proxy)                                                                  |
| `dep_count`      | Number of modules this one imports (coupling proxy)                                                                                  |
| `rcall_count`    | Number of functions across the project that call into this module (function-level blast-radius proxy)                                |
| `direct_imports` | List of modules this file imports                                                                                                    |
| `symbols`        | Functions, classes, and methods with line ranges and call edges                                                                      |
| `status`         | `ok` or `degraded`                                                                                                                   |
| `is_test`        | Whether the file is in a test directory                                                                                              |
| `file_shas`      | Git blob SHA or MD5 hash for incremental rebuild detection                                                                           |
| `scan_root`      | Absolute path of the project root at scan time — used by `scan-query` to resolve file paths; superseded by `--root` flag if provided |

### How agents use it

When the develop plugin (or any codemap-integrated skill) spawns an agent, it runs `scan-query central --top 5` and optionally `scan-query rdeps <target_module>` first. The JSON output is prepended to the agent's spawn prompt as a `## Structural Context (codemap)` block. The agent starts its work already knowing which modules are highest risk and what depends on its target — no cold exploration required.

If codemap is not installed, the soft-check block silently skips and the skill works exactly as before.

______________________________________________________________________

## ⚙️ Configuration

codemap has no required configuration. Everything is automatic once installed.

### Index location

The index is written to `.cache/codemap/<project>.json` at the project root by default. Set `CODEMAP_INDEX_DIR` to an absolute path to store the index elsewhere — useful when the project root is read-only, on a slow drive, or shared across machines via a home directory:

```bash
export CODEMAP_INDEX_DIR="$HOME/.codemap-cache"
```

With `CODEMAP_INDEX_DIR` set, the index lands at `$CODEMAP_INDEX_DIR/<project>.json`. All skills and bin scripts respect this variable automatically.

This directory is gitignored by default in the borda-ai-rig artifact layout. The project name is derived from `basename $(git rev-parse --show-toplevel)` — the directory name of your git root.

### Non-git projects

`scan-index` falls back to MD5 file hashes when git is not available. Staleness detection and incremental rebuilds still work; they just use file content hashes instead of git blob SHAs.

### Custom scan root

If your Python source is not at the git root, pass `--root`:

```text
/codemap:scan-codebase --root src/mypackage
```

Or from the terminal:

```bash
scan-index --root src/mypackage
```

When you specify a custom root, `scan-index` stores it as `scan_root` in the index. `scan-query` reads this field automatically so file path resolution works correctly even when you query from a different working directory — for example, querying a sub-project index from a monorepo root. To override the stored root at query time:

```bash
scan-query --root path/to/project symbol MyFunction
```

Priority chain: `--root` flag › `scan_root` in index › `git rev-parse --show-toplevel` › current directory.

### Keeping the index current

**Primary mechanism — skill-invocation currency gates**: every `/develop:*` or `/oss:*` skill run calls `check-index-currency` before spawning any agent. This two-tier check compares the stored `git_sha` against HEAD (Tier 1, git repos) or verifies per-file content hashes from the stored `file_shas` map (Tier 2, non-git or after pull/branch switch). If stale:

- **Gate A** (index missing): skill pauses and offers to build the index inline or skip.
- **Gate B** (index stale): skill warns and offers: rescan now, continue with stale index, or abort.

This catches all staleness paths the post-commit hook misses: `git pull`, branch switches, uncommitted edits, and non-git projects.

**Secondary mechanism — post-commit hook** (optional, local commits only): install once via `/codemap:integration init` and every `git commit` triggers an incremental background rebuild:

```bash
# .git/hooks/post-commit (installed by /codemap:integration init)
# codemap: incremental index rebuild — do not remove this line
if command -v scan-index >/dev/null 2>&1; then
    scan-index --incremental 2>/dev/null &
fi
```

The rebuild runs in the background — commit completes immediately, index updates silently within seconds. The hook is a convenience shortcut; skill-invocation gates are the authoritative safety net.

______________________________________________________________________

## 🔍 Troubleshooting

### "index not found" or empty results

`/codemap:query-code` now builds the index automatically on first use, so you should rarely see this. If it appears, the auto-build (Step 0) failed — confirm the project has `.py` files and `python3` is on PATH, then build manually:

```text
/codemap:scan-codebase
```

### Stale index warning

`scan-query` detected that Python files were committed after the index was built. Run an incremental rebuild:

```text
/codemap:scan-codebase --incremental
```

Or a full rebuild if you have made large structural changes:

```text
/codemap:scan-codebase
```

### scan-query not found in the terminal

You are outside a Claude Code session where the plugin `bin/` directory is not on PATH. Add it to your shell config (see [Install](#install) — the shell PATH snippet). After reloading your shell, `scan-query` should be available. You can verify with:

```bash
command -v scan-query
```

<details>

<summary>

Degraded modules in the scan report

</summary>

### Degraded modules in the scan report

Some files could not be parsed — usually generated code, files with syntax errors, or files that use Python syntax features not yet supported by the standard library `ast` module. Degraded modules are skipped but the rest of the index is fully usable. To see which files are degraded:

```bash
python -c "
import json, os, subprocess
proj = os.path.basename(subprocess.check_output(['git', 'rev-parse', '--show-toplevel']).decode().strip())
d = json.load(open(f'.cache/codemap/{proj}.json'))
for m in d['modules']:
    if m.get('status') == 'degraded':
        print(m['path'], '--', m.get('reason', 'unknown'))
"
```

Generated files (e.g. protobuf output) are expected to degrade. They are not part of your project's logical import graph.

</details>

### fn-\* commands return "upgrade required"

The function-level call graph queries (`fn-deps`, `fn-rdeps`, `fn-central`, `fn-blast`) require a v3 index. Your current index is older. Rebuild:

```text
/codemap:scan-codebase
```

### The develop plugin does not seem to use codemap

Run the integration check:

```text
/codemap:integration check
```

Look for `⚠ missing injection in:` lines pointing to specific skill files. If injection is missing, run:

```text
/codemap:integration init
```

and select the skills you want wired in.

______________________________________________________________________

<a id="contributing--feedback"></a>

## 🙏 Contributing / feedback

codemap lives in the `plugins/codemap/` directory of the Borda-AI-Rig repository.

**Found a bug or want a feature?** Open an issue in the repository. Include:

- Your Python version (`python --version`)
- The codemap version (`cat ~/.claude/plugins/cache/borda-ai-rig/codemap/*/.claude-plugin/plugin.json`)
- The error message or unexpected behavior
- The approximate size of the project you were scanning (module count from scan output)

**Want to extend codemap?**

The scanner and query CLI are standalone Python scripts in `plugins/codemap/bin/`. They have no external dependencies and are easy to read and modify. The index schema is versioned — if you add new fields, bump `SCAN_VERSION` in `scan-index` and handle the version check in `scan-query`.

Skills live in `plugins/codemap/skills/*/SKILL.md`. Adding a new skill means creating a new subdirectory with a `SKILL.md` following the existing pattern.

After any edit to agents, skills, or the index schema, update this README before committing — the plugin CLAUDE.md requires it.

**Plugin updates** propagate via the normal install path:

```bash
claude plugin install codemap@borda-ai-rig
```

After upgrading, run `/codemap:integration check` to confirm everything is still wired correctly.
