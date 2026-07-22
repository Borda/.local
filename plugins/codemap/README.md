# 🗂️ codemap — Claude Code Plugin

> **Every `/develop:fix`, `/develop:refactor`, `/oss:review` run gets blast-radius context automatic — you do nothing.**

codemap builds structural index of Python project — import graph, blast-radius scores, function call graph — injects context into existing `/develop` and `/oss` skills. Setup once; after that, invisible infrastructure. Ask Claude fix `auth.py` — agent already knows which 38 other modules import it before touching single line.

No direct querying. Wire in once, let other skills pick it up.

**Python first.** Scanner uses `ast.parse` to index `.py` files. `.rst` and `docs/**/*.md` also scanned for Sphinx/MkDocs cross-refs, included in cache-invalidation hashing — doc-only edits trigger incremental re-scans. Non-Python symbol indexing (TypeScript, Go, Rust) planned.

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

Claude Code plugin for Python projects. Pre-builds structural index — who imports whom, which modules widest blast radius, how functions call each other — injects context into `/develop` and `/oss` skills doing real code work. Index built once; currency gates at skill-invocation time detect stale state auto (covers `git pull`, branch switches, uncommitted edits), prompt refresh when needed. Optional post-commit hook accelerates refresh after local commits. Every skill invocation starts with structural awareness in hand.

Without codemap, every session starts blind: agent gropes through codebase with Glob and Grep, burns 20–30 tool calls just understanding structure before real work. On 200-module project those calls still miss blast-radius risks and import cycles structural scan surfaces instant.

codemap fix: scan once, wire in once, every code-touching skill benefits auto.

______________________________________________________________________

## 🎯 Why codemap?

### Without codemap

Ask Claude refactor `auth.py`. Agent:

1. Globs every `.py` file for project layout.
2. Reads files one by one to find what imports `auth`.
3. Guesses blast radius from files it happened to read.
4. Starts editing, discovers mid-refactor `middleware.py` also imports `auth`, backtracks.
5. Times out on large projects before surfacing all affected modules.

On pytorch-lightning (646 modules), plain-arm agents hit 300-second hard timeout on three of eight benchmark tasks.

### With codemap

After `/codemap:integration init`, existing skills wired. Run `/develop:refactor auth.py` — before spawning any agent, skill silent runs:

```bash
scan-query central --top 5         # which modules are highest risk overall?
scan-query rdeps mypackage.auth    # what breaks if auth changes?
```

Output prepended to agent spawn prompt as structural context. Agent starts refactor knowing full blast radius — no cold exploration, no mid-refactor surprise that `middleware.py` also imports `auth`. Across benchmark runs on pytorch-lightning, codemap cuts tool calls 50–80% while improving structural-recall metrics on import-graph tasks.

**Agentic benchmark (import-graph tasks on pytorch-lightning):** clean v0.13.2 numbers pending full benchmark re-run after RC1 fix; published here once available.

**Real-codebase benchmark** — 44 developer tasks × 2 arms (plain vs codemap) × 3 model tiers on pytorch-lightning-master (646 modules, 8 task types). **Scope**: pre-implementation structural-query tasks (blast-radius enumeration, caller discovery) — end-to-end patch quality and test-pass rate not yet measured. Benchmark **repo-agnostic**: `tasks-bench.json` ships `repo` header so harness points at any Python codebase. Zero codemap timeouts; plain-arm agents hit 300-second hard limit on several tasks.

### Three-model comparison

June 22 2026 — 44 tasks × 2 arms × 3 models, pytorch-lightning-master.

| Model      | Plain accuracy | Codemap accuracy | Accuracy lift | Safety-grade plain→codemap | Token ratio (median) | Token ratio range |
| ---------- | -------------- | ---------------- | ------------- | -------------------------- | -------------------- | ----------------- |
| Haiku 4.5  | 85.3% (29/34)  | 93.9% (31/33)    | **+9 pp**     | 5/13 → 12/13               | **0.38×**            | 0.04–68.2×†       |
| Sonnet 4.6 | 83.8% (31/37)  | 91.9% (34/37)    | **+8 pp**     | 11/13 → 12/12              | **0.22×**            | 0.05–1.21×        |
| Opus 4.6   | 86.1% (31/36)  | 91.7% (33/36)    | **+6 pp**     | 13/13 → 12/12              | **0.31×**            | 0.05–1.46×        |

Safety-grade = fraction of FN + BR tasks with explicit recall where recall ≥ 0.90. **Accuracy** = fraction of tasks where recall ≥ 0.90 (task correct when rdep coverage meets threshold). Token savings model-independent; accuracy lift model-dependent. **Single-repo caveat**: all figures on pytorch-lightning-master; gains on other Python codebases directionally consistent, magnitude may differ.

† Haiku 68.2× = RI-04 token spiral (error_max_turns); fixed June 23. Excluding RI-04, Haiku max 1.82×.

> June 23 fix: Opus FN-02 and BR-03 regressions resolved (evaluator v3 — both recall→1.000); Haiku RI-02/RI-04 fixed (blocked python3/python on both arms — both recall→1.000).

#### Model-specific notes

**Haiku 4.5** — largest correctness gap between arms. Plain arm safety-grade 5/13 reflects chronic failures on FN-series (alias/lazy-import gaps) and real-issue tasks. Codemap restores 12/13. Token median 0.38× across all 44 tasks; query-type workflows median 0.28×. RI-02/RI-04 fixed June 23 (recall→1.000 after python3/python blocked). BR-07 minor regression: codemap recall=0.778 vs plain=0.889.

**Sonnet 4.6** — smallest token ratio (median 0.22×, query-type 0.14×). Accuracy parity: plain 83.8% / codemap 91.9%. FN-03 codemap extraction_failed; FT-03 codemap recall=0.500 vs plain not-scored. RI workflow cm_acc=75%. DG and SE both arms 100%.

**Opus 4.6** — token median 0.31×. Best plain accuracy (86.1%). FN-02 and BR-03 regressions fixed June 23 (recall→1.000 both arms). RI workflow cm_acc=100% (sonnet/opus succeed where haiku spirals). CQ-series: codemap lifts CQ-01/CQ-03/CQ-04/CQ-05 to 1.000 from poor plain scores.

**By series** (opus — June 23 full run, `bench-opus-20260623-023648.jsonl`):

| Series                 | plain | codemap | Notes                                                                 |
| ---------------------- | ----- | ------- | --------------------------------------------------------------------- |
| SE — symbol extraction | 5/5   | 5/5     | Both arms perfect; codemap saves 37–63% tokens                        |
| FN — call graph        | 4/5   | 3/4     | Plain misses FN-01 (0.808); FN-03 codemap extraction failed           |
| BR — blast radius      | 8/8   | 8/8     | Both arms perfect; codemap saves 49–97% tokens                        |
| RV — review assistance | 2/5   | 3/5     | RV-03/04 over-count both arms; RV-05 codemap lift (0.80 → 1.00)       |
| CQ — code quality      | —     | 5/5     | Count-based scoring (no recall); codemap hits all 5, plain unreliable |

> **FN-series = starkest signal for haiku and opus**: plain arm burns 0.85M–4.0M tokens, fails 2–3 of 5 call-graph tasks; codemap resolves full caller set in one query at 4–16% token cost. Sonnet inverts — strong reasoning compensates for missing structural index on FN, but codemap execution failure on two tasks pulls safety-grade below plain.

> **Static AST limitations**: scan-query does not resolve dynamic dispatch, hook callbacks, `importlib.import_module`, lazy-loading patterns, or string-based dispatch. Calls through these not counted. Semble, when available, cuts tool calls further, slight erec boost at modest rrec trade-off. When semble MCP server available, agents also get `mcp__semble__search` as optional semantic search — useful when codemap index non-exhaustive.

> **⚠ Integration quality matters — poor wiring can make things worse.**
>
> codemap injects rich dependency graph into every agent prompt. On weaker models or tasks with large blast-radius graphs, extra context can overwhelm model, cause fallback to grep-heavy loops — performing *worse* than plain arm. Benchmark labels this failure mode `degenerate_grep_loop`.
>
> Good integration needs three things: (1) **skill-first protocol** — agent calls `/codemap:query-code` before any Grep/Glob; (2) **bounded call budget** — max 3 codemap queries per task; (3) **hard stop on `query_complete: true`** — when index says list complete for query direction, write answer immediate, no more tool calls. `query_complete` direction-scoped: `deps`/`symbols` query on healthy module can be complete while another file degraded, but `rdeps`/`central`/`path` require zero degraded files. Legacy `exhaustive` field mirrors `query_complete` for one deprecation cycle. Skipping any — especially ignoring completeness flag — primary cause of regressions flipping codemap benefit into liability. Use `/codemap:integration init` to wire correct, not manual context injection.

### Real-world proof: daily-work benchmark

Benchmarks above measure **discovery phase** — enumerating callers, assessing blast radius before code written. `fix_multicaller` suite extends coverage to **edit phase**: real signature change where all callers must update in one pass.

**Benchmark scope**: 7 tasks in `benchmarks/run-codemap-agentic.py` across two families. Both use archive/restore isolation — demo codebase copied per arm run, agent edits copy, `diff -ru` captured against original. No git required; original codebase never mutated.

| Family                          | Tasks                          | What it tests                                                                 | Scored by                                           |
| ------------------------------- | ------------------------------ | ----------------------------------------------------------------------------- | --------------------------------------------------- |
| `fix_single` (FS-01–FS-04)      | Single-file bug fix            | Validates archive/restore isolation; `EarlyStopping`/`ModelCheckpoint` guards | Diff keyword recall (`erec`)                        |
| `fix_multicaller` (FM-01–FM-03) | Signature change + all callers | codemap `fn-rdeps` enumerates callers before editing; plain arm must grep     | Diff keyword recall (`erec`) + file recall (`rrec`) |

**FM-03 (`Strategy.setup`) = decisive test**: adding `verbose: bool = False` to base-class `setup` method requires updating 6 subclass overrides in `ddp.py`, `fsdp.py`, `deepspeed.py`, `model_parallel.py`, `single_xla.py`, `xla.py`. Codemap arm runs `scan-query fn-rdeps lightning.pytorch.strategies.strategy::Strategy.setup` before any edit, gets complete override list in one call. Plain arm must grep `def setup`, read candidate files. Missing overrides = silent `super().setup()` signature mismatch at runtime. File recall (`rrec`) captures whether right files actually changed.

Only public Claude Code plugin benchmark measuring edit-phase caller coverage — not just structural discovery.

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

codemap not standalone tool — primary value = structural context fed into `/develop` and `/oss` skills doing real code work. This section documents what wired today, what each integration delivers per benchmark data, where current implementation has known gaps.

### What is wired today

| Skill               | Integration type                             | What codemap provides                                                                                                                                                                         |
| ------------------- | -------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/develop:review`   | Active — per changed module                  | rdeps, fn-blast, mock-rdeps, uncovered, xrefs, undocumented — results injected into every dimension-agent prompt with "trust codemap, skip redundant Grep/Read"                               |
| `/oss:review`       | Active — per changed module                  | Same per-module query set as develop:review; codemap context piped to each reviewer agent                                                                                                     |
| `/develop:refactor` | Active — per affected module                 | rdeps + coupled callers; flags callers OUTSIDE refactoring scope as silent-contract-break risk                                                                                                |
| `/develop:fix`      | Active — per target function                 | `fn-rdeps` fires for direct callers of bug's target function (`module::function` from ARGUMENTS or auto-derived from `checkpoint.md` after Step 1)                                            |
| `/develop:feature`  | Active (integration) / Passive (new surface) | Integration target (`module::function` supplied): `fn-rdeps` fires for direct callers. Module-only target: `rdeps` for importers. Net-new surface (no existing symbol): central baseline only |

### Expected benefits per skill (based on benchmark data — haiku/sonnet, 28-task suite)

| Skill task type             | Token savings (codemap vs plain) | Accuracy lift                                                                                 |
| --------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------- |
| Review (per-module impact)  | 80–90% fewer tokens              | Maintains accuracy, kills redundant grep walks                                                |
| Blast radius / caller count | 6–17× fewer tokens               | +40 pp (haiku: 50% → 90%) — codemap returns exact caller list in 1 call vs 150+ grep/read ops |
| Symbol location             | 20–75% fewer tokens              | No accuracy change — both find it, codemap faster                                             |
| Refactor impact             | 80–90% fewer tokens              | Systematic caller coverage — plain arm misses 15–54% of callers on large functions            |

### Graceful degradation

Skills use two gates at invocation time:

- **Gate A (missing index)**: `scan-query` available but index file absent — skill pauses, asks: (a) build index inline via `/codemap:scan-codebase`, or (b) skip, continue without codemap context.
- **Gate B (stale index)**: `check-index-currency` detects index no longer matches source (changed files since last scan) — skill warns, asks: (a) rescan now, (b) continue with stale index, or (c) abort.
- **`scan-query` absent**: skill auto-degrades silent, proceeds without codemap — binary absence means plugin not installed, not source changed.

### Known gaps (challenger audit 2026-06-20)

| Gap                                                                                                                                                                | Status                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **`fn-rdeps` not used** — benchmark-proven subcommand for caller accuracy invoked in zero develop/oss skill workflows; skills used `fn-blast` (transitive) instead | Fixed — `fn-rdeps` added to `/develop:review`, `/oss:review`, and `codemap-context.md` review pipeline                                                       |
| **`/develop:fix` blast-radius dead code** — TARGET_FN/TARGET_MODULE never set → only `central --top 5` ran → no per-bug caller impact                              | Verified working — `fn-rdeps` fires via `codemap-context.md` when `module::function` format supplied; `checkpoint.md` auto-derive covers free-text ARGUMENTS |
| **`/develop:feature` blast-radius dead code** — same TARGET-unset defect as fix path                                                                               | Verified working — both TARGET_MODULE and TARGET_FN extracted; `fn-rdeps` fires via `codemap-context.md` when TARGET_FN set                                  |
| **Silent degradation** — index missing → skills proceed at full token cost, no warning                                                                             | Fixed — `codemap-context.md` emits ⚠ warning to stderr when `scan-query` unavailable or index missing                                                        |
| **`check_injection.py` blind spot** — health check detected marker comment presence only; could not catch TARGET-unset defect or missing `fn-rdeps` wiring         | Fixed — second audit layer added: `check_fn_rdeps_wiring()` now reports whether `fn-rdeps` wired in all required files                                       |

______________________________________________________________________

## 📦 Install

<details>

<summary><strong>Prerequisites</strong></summary>

- Claude Code installed, working
- Python 3 on PATH (standard library only — no `pip install`)
- Git (recommended — used for staleness detection, incremental rebuilds)

</details>

**Install the plugin**

```bash
claude plugin marketplace add Borda/AI-Rig
claude plugin install codemap@borda-ai-rig
```

That's it. No build step. Scanner (`scan-index`) and query CLI (`scan-query`) plain Python scripts — run immediate.

**Make scan-query available in your terminal (optional)**

Inside Claude Code sessions, `scan-query` and `scan-index` on PATH auto via plugin `bin/` directory. For regular terminal too, add to `~/.zshrc` or `~/.bashrc`:

```bash
CODEMAP_TOOLS=$(ls -d "$HOME/.claude/plugins/cache/borda-ai-rig/codemap"/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$CODEMAP_TOOLS" ] && export PATH="$PATH:$CODEMAP_TOOLS"
```

Reload shell (`source ~/.zshrc`), `scan-query` available everywhere. Snippet always picks latest installed version — no version pins to maintain.

<details>

<summary><strong>Upgrade</strong></summary>

```bash
claude plugin install codemap@borda-ai-rig
```

After upgrade, re-run `/codemap:integration init` to re-apply injection blocks — plugin cache replaced on reinstall, prior injections lost.

</details>

<details>

<summary><strong>Uninstall</strong></summary>

```bash
claude plugin uninstall codemap
```

</details>

______________________________________________________________________

## ⚡ Quick start

Two commands — then forget codemap, use normal skills.

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

Discovers all installed `develop` and `oss` skills, shows recommendation table, injects structural context block into each you approve. Also offers post-commit git hook install so index stays current auto.

Done. Run normal skills — codemap works silent in background:

```text
/develop:fix auth.py         # agent already knows blast radius of auth before it starts
/develop:refactor models.py  # agent sees which 89 modules import models upfront
/oss:review                  # reviewer gets structural context on changed modules
```

Want manual structure exploration — `/codemap:query-code` there. Most users rarely need it.

______________________________________________________________________

## ✅ Best-practice integration

______________________________________________________________________

**Six rules cover 95% of what you need:**

### 1 — Build the index once

Run `/codemap:scan-codebase` after clone or project setup. Index lands in `.cache/codemap/<project>.json`. Re-run only after major structural changes or when gate fires.

### 2 — Wire in once per project

Run `/codemap:integration init` once. Injects structural context block into each `/develop` and `/oss` skill, (optional) installs post-commit hook. Without wiring, index exists but no skill uses it.

### 3 — Gates are the primary safety mechanism

After wiring, two gates fire auto at start of each skill invocation:

- **Gate A — missing index**: fires when index absent. Offers: build now, continue without codemap, or abort.
- **Gate B — stale index**: fires when `check-index-currency` detects drift (git HEAD changed, uncommitted `.py` edits, or per-file SHA-256 mismatch). Offers: rescan, continue with stale data, or skip codemap.

Gates cover what post-commit hook misses: `git pull`, branch switches, uncommitted edits.

### 4 — Post-commit hook is optional

Hook triggers `scan-codebase --incremental` after local commits only — convenience accelerator, not safety net. Gates work without it. Install via `/codemap:integration init`; skip for manual control.

### 5 — Ambient index status (UserPromptSubmit hook)

`UserPromptSubmit` hook fires every user message, injects one-line codemap status into Claude context when index exists at `.cache/codemap/<project>.json`. Index **absent**: hook silent for non-Python dirs (zero output, near-zero overhead); Python projects get once-per-session bootstrap prompt (below).

```
[codemap] .cache/codemap/rfdetr.json · 47 modules · current (git: f20fa19) · scanned: 2026-06-23
Prefer scan-query over file reads: rdeps, fn-rdeps, fn-blast, xrefs, symbol.
```

Index **stale** (git HEAD differs from stored sha): hook spawns `scan-index --incremental --root <scan_root>` in background (incremental — 41ms–1.7s measured; scan-index falls back to a full scan when the on-disk index predates v3) (non-blocking, 10-minute lockfile guard) — index refreshes silent while Claude answers. Status reads `· refresh started` first stale turn, `· refresh in progress` subsequent turns until scan completes.

Separate: `scan-query` self-heals at query time. On stale index, runs **bounded** inline `scan-index --incremental` (skipped when more than 50 `.py` files changed or scan exceeds 10 s wall-clock cap), answers from refreshed graph — edge added by just-committed change visible next query. Heal skipped or unavailable: query still answers, honest flagged `stale: true`. Pass `--no-heal` to disable inline heal.

Index **current**: hook injects status line once per session (30-min TTL flag at `/tmp/codemap-preamble-<proj>`). Subsequent turns skip injection — saves ~30 tokens × N turns ≈ ~900 tokens/session. Stale index always injects regardless of TTL so auto-refresh note always reaches agent.

**No index yet** + project is Python (`__init__.py` at git root or one level down, `src/<pkg>/__init__.py` src-layout, or — failing those — `pyproject.toml`/`setup.py` at root): hook emits once-per-session directive (30-min TTL flag at `/tmp/codemap-noindex-<proj>`) asking agent raise `AskUserQuestion` offering index build. On consent, agent runs `scan-index` foreground, waits for finish before continuing. Bootstraps first-time projects that would never self-scan — stale auto-refresh only fires on existing index, skill-level Gate A missing-index prompt only fires inside wired `/develop`/`/oss` skills. Non-Python dirs get nothing.

Complements per-skill SKILL.md injection — which handles dynamic per-PR `scan-query` output and interactive Gate A/B prompts — with lightweight always-on preamble reaching every turn, not just skill invocations.

### 6 — Redundant-scan guard (Pre/PostToolUse hooks)

Once `scan-query rdeps <module>` returns **`query_complete`** result (legacy alias `exhaustive`), import graph for that module complete and authoritative — re-grepping with `grep`/`rg` adds nothing but tokens. Benchmarks showed agents (weak tiers especially) ignoring "stop" instruction, looping verification greps, burning millions of input tokens at zero recall gain.

Two hooks close this mechanical: `record-exhausted.js` (PostToolUse on Bash) notes each module returned complete this session (matches `query_complete: true` or legacy `exhaustive: true`); `guard-redundant-scan.js` (PreToolUse on Bash) then **denies** import-discovery greps (`grep`/`rg` for `import`/`from`) targeting already-complete module, points agent back to codemap result. Scope deliberate narrow and fail-open: only import-greps for already-complete module blocked (source reads via `cat`/`Read` never touched), only same session, any hook error allows call. Sessions never running codemap (no sentinel) unaffected. Disable by removing two `Bash`-matcher entries from `hooks/hooks.json`.

Because `query_complete` direction-scoped, guard only ever arms for `rdeps`/`fn-rdeps` (global-in) results, marked complete only when zero files degraded — false `complete` can never block exact grep that would surface hidden edge.

### 7 — Two-tier currency check

`check-index-currency` runs inside Gate B:

- **Tier 1** (git repos): compares stored `git_sha` vs `HEAD`; counts uncommitted `.py` changes via `git status --porcelain`. Fast — no file reads.
- **Tier 2** (no git or no stored SHA): compares per-file git blob SHA-1 (git repos) or MD5 (non-git) hashes stored at scan time against current content, mtime pre-filtering skips unchanged files. Catches changes in non-git workflows or when `git_sha` absent.

______________________________________________________________________

## 🔧 Skills reference

______________________________________________________________________

### integration

**Trigger**: `/codemap:integration check | init [--approve] | demo [--repo <path|url>] [--public] [--anonymize] [--keep-clone] [--output <path>]`

Three modes. `init` once — wires codemap into existing skills and agents. `check` anytime — verifies setup healthy. `demo` — validates end-to-end codemap plugged in correct, yields expected gains.

#### check mode

Fast diagnostic, no side effects. Checks:

1. `scan-query` reachable on PATH (or via fallback locations)
2. Index file exists for current project
3. Index age (warns if older than 7 days)
4. Smoke test: runs `central --top 3`, verifies output
5. Which installed skill files have codemap injection block

Each check prints `✓`, `✗`, or `⚠` with one-line remediation hint if needed.

```text
/codemap:integration check
```

#### init mode

Interactive onboarding for current project:

1. Builds index if missing (offers `/codemap:scan-codebase`)
2. Discovers all installed skills and agents across all plugins
3. Scores candidates by value tier (High / Medium / Low / Skip) — would structural context help
4. Presents recommendation table, asks which to wire in
5. Inserts correct injection block into each selected skill or agent file
6. Offers `.git/hooks/post-commit` hook install for automatic incremental rebuilds

```text
/codemap:integration init
```

Pass `--approve` to apply all High and Medium recommendations non-interactive:

```text
/codemap:integration init --approve
```

`--approve` delegates injection to `bin/inject_codemap.py` — scores each skill candidate for Python/codemap relevance (0–4), injects context block before `## Step 1`, backs up before writing, rolls back on failure. Run direct for scripted or CI use:

```bash
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/inject_codemap.py" \
    --plugin-root <path> [--apply] [--dry-run] [--verbose]
```

#### Manual injection

Write custom skills or agents, want codemap yourself — injection block single source of truth in `bin/_injection_block.py` (`BLOCK` constant). `init` and `check` both import it; hand-written variant drifts, fails `check`. Print canonical block, paste before first agent spawn:

```bash
# timeout: 5000
python -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin'); import _injection_block as b; sys.stdout.write(b.BLOCK)"
```

Block:

- detects index with `command -v scan-query` + `.cache/codemap/<project>.json` check (silent skip when absent);
- runs `scan-query central --top 3` for global baseline;
- runs one targeted query when you set `TARGET_MODULE` / `TARGET_FN` first — `fn-rdeps` for known function, else `rdeps` for known module;
- prints `codemap_evidence:` line summarising retrieval reliability;
- carries `codemap-block: vN` version stamp so `check` reports OUTDATED after block upgrade.

Full query map lives in `skills/_shared/codemap-context.md`. For agent `.md` files (no `$ARGUMENTS`): add instruction running `scan-query central --top 5` plus `scan-query rdeps <target_module>` when target derivable from task, before any Glob/Grep exploration; skip silent when index absent.

**Durability**: injecting into plugin's own cache file (under `~/.claude/plugins/cache/`) wiped on next `claude plugin install` — Claude Code has no project-local override for single plugin file, plugin skills namespace-isolated. After upgrade, run `/codemap:integration check` (reports wiped blocks MISSING, or OUTDATED when block version changed), re-run `init` to re-inject. Personal skills and agents under `.claude/skills/`, `~/.claude/skills/`, `.claude/agents/` are project/user files, not cache — survive upgrades untouched; prefer them when same skill exists both places.

#### demo mode

End-to-end validation for repo. Runs plumbing check, builds index if missing, executes sample tasks to populate telemetry logs, runs plain-vs-codemap A/B proving expected gains, produces final report with link to debrief output.

**Flags** (all optional):

| Flag                   | Effect                                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------------------------ |
| `--repo <path\|url>`   | Target repo — local path or git URL; URL triggers clone gate                                                 |
| `--public`             | Force clone gate even if current repo has `.py` files                                                        |
| `--anonymize`          | Forward `--anonymize` to `debrief-coding` in final report                                                    |
| `--probe-skill <name>` | Probe specific user skill (priority: this arg > develop/oss list > synthetic); report states which probe ran |
| `--keep-clone`         | Skip cleanup prompt after demo on cloned repo                                                                |
| `--output <path>`      | Override report output path (default: `.reports/codemap/demo-<date>.md`)                                     |

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

**A/B caveat**: arms prompt-gated (not hard tool deny-list). Tool-call counts serve as cost proxy. Recall scored against ground truth for `psf/requests` pinned task set; other repos use cross-arm agreement as recall proxy.

**Scenarios covered:**

1. Fresh repo, no index — demo builds it (D3), reports module count.
2. Stale index — D2 flags stale age; D3 refreshes.
3. Skills never invoked (Sk=0) — D7 flags this, explains diagnostic artifact.
4. Public-repo demo — D1a clone gate fires before any clone; D9 offers cleanup.
5. Anonymized report — `--anonymize` forwarded to `debrief-coding`; output safe to share.

### scan-codebase

**Trigger**: `/codemap:scan-codebase`

Builds structural index — runs `ast.parse` across every `.py` file in project. Writes index to `.cache/codemap/<project>.json`. Reports modules indexed, modules degraded (parse errors), five highest-blast-radius modules.

#### Flags

| Flag            | What it does                                                                                                         |
| --------------- | -------------------------------------------------------------------------------------------------------------------- |
| _(none)_        | Full scan — re-parses every `.py` file                                                                               |
| `--incremental` | Re-parse only files changed since last scan (git blob SHA comparison); falls back to full scan if no v3 index exists |
| `--root <path>` | Scan specific directory instead of git root                                                                          |

#### When to run

Full scan once at project setup. After that, skill-invocation currency gates detect stale state, prompt rescan auto — rarely need manual run. Want forced refresh — `--incremental` fast enough for most changes. Install optional post-commit git hook (via `/codemap:integration init`) for background auto-refresh after local commits.

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

#### Excluding paths from the index

Scanner always skips built-in noise directories (`.git`, `.venv`, `node_modules`, build/cache dirs, agent/tooling scratch dirs like `.claude`, `.temp`, `.reports`, `.plans`, generated `site`/`_site`). Anything else to keep out — vendored copy of another project, generated code, large fixtures tree — declare in either of two places at project root:

- **`pyproject.toml`** under `[tool.codemap]` table:

  ```toml
  [tool.codemap]
  exclude = ["vendored-project", "generated/*.py"]
  ```

- **`.codemapignore`** — one pattern per line, `#` starts comment:

  ```text
  # keep the bundled upstream copy out of the index
  pytorch-lightning-master
  generated/*.py
  ```

Entry with no `/` or glob character (`*`, `?`, `[`, `]`) = **directory name**, pruned anywhere in tree (like built-ins). Entry with path separator or glob character = **`fnmatch` pattern** matched against each file path relative to project root. Excluded paths dropped from both module list and change-detection hash set — never trigger incremental rebuilds.

Built-in prune: besides the named `SKIP_DIRS` (venv, build, dist, node_modules, caches, …), **every dot-directory** (`.sandbox`, `.agents`, any `.name`) is pruned generically — dot-dirs are never part of a project's import space but can hold whole vendored checkouts (a `.sandbox/` tree once contributed 646 of 928 indexed modules and dominated centrality). The staleness diff applies the same rule, so dot-dir files never re-enter as permanently "added".

Monorepos with several source roots declare them explicit:

```toml
[tool.codemap]
src_roots = ["libs/core/src", "services/api/src"]
```

Module names derive from **first-listed matching root** (file under `libs/core/src/pkg_a/mod.py` indexed as `pkg_a.mod`), declaration order doubles as collision priority. Without `src_roots`, single-root auto-detection behaves as before.

Index records what excluded, effective source roots, name collisions in three meta keys:

- `excluded_roots` — list of `{"pattern", "kind": "dir"|"glob", "source": "pyproject.toml"|".codemapignore", "count"}`, where `count` = number of `.py` files entry removed.
- `src_roots` — list of effective source-root paths (posix, relative to project root); empty for flat repo, no configured roots.
- `collisions` — two files resolve to same dotted module name (e.g. duplicate package tree **not** excluded) — only one indexed. Each record `{"name", "kept", "dropped": [...]}`. Kept path chosen deterministic: path under configured source root wins (earlier-listed `src_roots` beat later), then path under detected source root, then shortest path, then lexicographic — same file always wins regardless of filesystem walk order.

______________________________________________________________________

<a id="query-code"></a>

<details>

<summary>

### query-code — full subcommand reference

</summary>

### query-code

**Trigger**: `/codemap:query-code <subcommand> [args]`

**Auto-invokes when:** user asks about module relationships, dependency graph, callers/callees, or blast radius; phrases: "what depends on", "who calls", "imports of", "blast radius of". No prior index needed — Step 0 pre-flight builds one auto when missing, incremental-refreshes when present, before querying.

Queries index. Step 0 keeps fresh (full build via `/codemap:scan-codebase` if missing, `scan-index --incremental` if present) — queries run against current index. Python files change mid-task — stale warning may still appear on stderr; results still returned so agent can refresh, retry.

When Step 0 builds, prints one line — `[codemap] index built in <N>s` — build cost visible, separable from query time. Set `SCAN_NO_AUTOBUILD=1` to opt out of auto-building entirely: present index queried as-is, no refresh; missing index makes Step 0 stop with clear message pointing at `/codemap:scan-codebase`, no silent build.

#### Module-level queries

Work with any v2 or v3 index.

| Subcommand                                    | What it answers                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `rdeps <module>`                              | What imports this module? (blast radius)                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `deps <module>`                               | What does this module import?                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `central [--top N]`                           | Which modules imported by most others? Default N=10                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| `coupled [--top N]`                           | Which modules import most others? Default N=10                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `path <from> <to>`                            | Shortest import chain between two modules; `null` (with `reason: "no-import-path"`, exit 0) means not connected                                                                                                                                                                                                                                                                                                                                                                      |
| `list [--limit N]`                            | Indexed modules with file paths; capped at N (default 100, `0` = all). Emits `total` and `shown` so truncation visible                                                                                                                                                                                                                                                                                                                                                               |
| `batch <file\|->`                             | Many queries in one process from JSON array of `{cmd, args}`; see [batch mode](#batch-mode)                                                                                                                                                                                                                                                                                                                                                                                          |
| `diff-impact [--base REF] [--diff-file PATH]` | Blast radius of a change set: changed modules + symbols, per-module `rdeps`/`coupled`, per-symbol `fn-rdeps`, union `test-impact`, risk tiers (HIGH ≥5 importers / MODERATE 1–4 / LOW 0) — one JSON, one coverage block. Default diffs working tree against `HEAD`; `--base` accepts any ref or range; `--diff-file` (path or `-` for stdin) reads a unified diff (e.g. `gh pr diff` output) instead of local git — PR-review mode where the change is not in the local object store |

#### Symbol-level queries

Retrieve function or class source by name instead of reading full file — dramatic fewer tokens than whole files — 91–95% reduction for targeted method lookups on large files (benchmark: pytorch-lightning `Trainer.fit`, 1 790 tokens with imports vs 19 824 tokens full file).

| Subcommand                       | What it answers                                                                                                          |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `symbol <name> [--with-imports]` | Source of function, class, or method by name; add `--with-imports` to include module-level import block alongside source |
| `symbols <module>`               | All symbols in module with type and line range                                                                           |
| `find-symbol <pattern>`          | Regex search across all symbol qualified_names in index                                                                  |

`symbol` accepts bare name (`authenticate`), qualified name (`MyClass.authenticate`), or case-insensitive substring fallback. `find-symbol` and `symbol` cap results at 20 default — pass `--limit 0` to retrieve all matches before counting or ranking.

Every `symbol` result includes `"stale": bool` and `"stale_reason": string | null`. When `stale: true`, index line range no longer matches current file — fall back to `Read(<path>)` instead. Common reasons: `"file deleted"`, `"line range past EOF"`, `"symbol name not in slice header"` (function moved or renamed since last scan). `path` field always valid even when `stale: true`.

> **! BREAKING (path output)**: legitimate "no path exists" result now returns `{"path": null, "reason": "no-import-path"}` at exit 0 — former `"error": "No import path found."` key gone. Genuine failures (unknown module) still use non-zero `"error"` contract — consumers can finally distinguish "no path" from "query failed". Anything branching on old `error` key for no-path case must read `reason` (or test `path === null`) instead.

#### Function-level call graph queries (v3 index)

Require v3 index built by `/codemap:scan-codebase`. Older index (v2) — commands return clear upgrade message.

| Subcommand             | What it answers                                     |
| ---------------------- | --------------------------------------------------- |
| `fn-deps <qname>`      | What does this function call? (outgoing call edges) |
| `fn-rdeps <qname>`     | What functions call this one? (incoming call edges) |
| `fn-central [--top N]` | Most-called functions across project. Default N=10  |
| `fn-blast <qname>`     | Transitive reverse-call BFS with depth levels       |

Use `module::function` format for qualified names, e.g. `mypackage.auth::validate_token` or `mypackage.auth::AuthMiddleware.process`.

`fn-rdeps` reports **`unique_caller_count`** alongside `count`. Both = number of *distinct* calling symbols — caller list deduplicated; caller invoking target from several call sites counted once. Explicit field name exists so consumers don't misread value as call-site edge total; `count` retained for backward compat, always equals `unique_caller_count`.

**Call edge resolution types**: `import` = cross-module call with confirmed import scope; `local` = same-file call; `self` = `self.method()` call where target class known; `star` = call to name from star import where source module undetermined; `unresolved` = call target unmatched.

#### Common flags

| Flag                 | Applies to                                                                       | Effect                                                                                                                                                                                                    |
| -------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--exclude-tests`    | `rdeps`, `central`, `coupled`, `symbol`, `find-symbol`, `fn-rdeps`, `fn-central` | Drop test modules from results                                                                                                                                                                            |
| `--limit N`          | `symbol`, `find-symbol`, `list`                                                  | Max results (default 20; `list` default 100). `0` = unlimited                                                                                                                                             |
| `--with-imports`     | `symbol`                                                                         | Include module-level import block alongside each symbol's source                                                                                                                                          |
| `--root <path>`      | all commands                                                                     | Override project root for **file-path resolution only** — no re-scan, no index re-target. Disagreeing with index `scan_root` yields `root_mismatch: true` + `query_complete: false` (see scan_root below) |
| `--index <path>`     | all commands                                                                     | Explicit index file; bypasses auto-discovery. Must resolve inside CWD or git root, else exits `{"error": "index path outside project root"}`                                                              |
| `--verbose-coverage` | all commands                                                                     | Force full coverage block on every query, disabling once-per-session diet (see [coverage diet](#coverage-block-diet))                                                                                     |

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

<a id="batch-mode"></a>

#### batch mode

`batch` runs many queries inside single `scan-query` process — pays process-spawn and coverage-block cost once, not per call. Reads JSON array of `{cmd, args}` objects from file path or stdin (`-`), runs each request through same code path as standalone form, returns results keyed by input order under one shared coverage block:

```bash
echo '[{"cmd":"rdeps","args":["myproject.auth"]},{"cmd":"fn-blast","args":["myproject.db::fetch_user"]}]' \
    | scan-query batch -
```

Response shape: `{"batch": [{"ok": bool, "index": N, "cmd": "...", "result": {...}}, ...], "count": N, "index": <shared coverage block>}`. Request that fails parse or errors yields per-item `{"ok": false, ...}` object — one bad query never aborts batch. `batch` cannot nest inside `batch`. This is the form `/develop:review` and `/oss:review` pre-flight uses to collect every per-module query in one call.

<a id="coverage-block-diet"></a>

#### coverage block diet

Every query result carries `index` coverage block. Session-invariant fields (module counts, degraded file list, star-import count, etc.) identical across queries — after **first** query of Claude Code session, `scan-query` emits **compact** block carrying only per-query honesty signals — `query_complete`, `stale`, `root_mismatch`, plus `compact: true`, and (only when result incomplete) `degraded` count and `note` explaining why. Session identity from hook-written marker at `<git-root>/.cache/codemap/current-session`; marker missing, unparsable, or stale — every query emits full block (fail-verbose). Pass `--verbose-coverage` to force full block every query.

______________________________________________________________________

<a id="test-impact"></a>

### test-impact

**Trigger**: `/codemap:test-impact <module::symbol | module> [--no-mocks]`

**Auto-invokes when:** user asks which tests affected by change, wants skip unrelated tests, or asks about selective test runs; phrases: "which tests cover this", "what tests to rerun", "test impact of", "run only affected tests".

Identifies minimal test set to rerun after changing function or module — static analysis, no test execution.

**Two modes:**

- `module::symbol` — BFS over reverse call graph; finds every test calling changed function direct or transitive. Also includes tests mocking symbol via `patch()`.
- `module` — BFS over reverse import graph; finds every test importing module through any chain. Also includes tests mocking any symbol in module.

```text
/codemap:test-impact myproject.auth::validate_token
/codemap:test-impact myproject.utils
/codemap:test-impact myproject.auth::validate_token --no-mocks
```

Output includes `test_files`, `via_call`/`via_mock` breakdown, ready-to-run `pytest_cmd`. **Limitation**: static-AST only — dynamic dispatch and hook-callback callers not covered; `not_covered` field signals this, `hint` provides grep fallback.

______________________________________________________________________

<a id="rename-refs"></a>

<details>

<summary>

### rename-refs — atomic symbol and module rename

</summary>

### rename-refs

**Trigger**: `/codemap:rename-refs symbol <old_qname> <new_qname>` or `/codemap:rename-refs module <old_module_path> <new_module_path>`

**Auto-invokes when:** user asks rename function, class, method, or module; phrases: "rename X to Y", "rename function", "rename class", "rename module", "move module X to Y", "update all references to X". Requires codemap index (run `/codemap:scan-codebase` first).

Atomic rename of Python symbol or module via structural index. Finds and updates:

- Definition site (`def` / `class` line)
- `__all__` re-exports in `__init__.py` files
- Import call sites across all callers (indexed via fn-rdeps)
- Sphinx docstring cross-refs (`:func:`, `:class:`, `:meth:`, `:mod:`, `:attr:`) in `.py` and `.rst` files

Presents blast-radius report before applying any edits. Shows which files and call sites change, warns if index non-exhaustive, asks confirmation before touching anything.

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
| `--since <ver>`          | Version when symbol deprecated (passed to deprecation decorator)           |
| `--removed-in <ver>`     | Version when old name removed                                              |
| `--remove-if-no-callers` | Symbol only: hard-delete definition when index exhaustive and zero callers |

#### Hard limits

Two cases outside static analysis, cannot rename auto:

1. `getattr(obj, "old_name")` **dynamic dispatch** — string has no static binding to symbol; skill emits `grep` advisory for manual check.
2. **Cross-repo consumers** — external packages out of scope by definition. Use `--deprecate` plus semver bump and CHANGELOG entry for public API renames.

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

Reads `.cache/codemap/logs/` JSONL telemetry from core CLI tools (`scan-query`, `scan-index`) and skill-start PreToolUse hook, writes diagnostic usage report. Useful for debugging query patterns, investigating errors, understanding which skills drive most queries, preparing shareable anonymized summary for feedback.

#### Flags

| Flag                   | Effect                                                                                                            |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `--since <YYYY-MM-DD>` | Filter to records on or after this date (default: all records)                                                    |
| `--session <id>`       | Filter to single session UUID                                                                                     |
| `--anonymize`          | Replace qualified names (module paths, symbol names) with stable pseudonyms before reading — output safe to share |
| `--output <path>`      | Write report to this path (default: `.reports/codemap/debrief-<date>.md`)                                         |

#### What is logged

All logs local to `.cache/codemap/logs/`, never leave machine.

| File                     | Layer | When written                                                                                                                                      |
| ------------------------ | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cli_<session>.jsonl`    | cli   | Every `scan-query` query and every `scan-index` build (core CLI tools)                                                                            |
| `skills_<session>.jsonl` | skill | Every `/codemap:*` skill start (via PreToolUse hook)                                                                                              |
| `tools_<session>.jsonl`  | tool  | Every `Grep` / `Read` / `Glob` call plus search-shaped `Bash` commands (`rg`/`grep` at a command position) via PostToolUse hook `log-tool-use.js` |

Logs sharded per session: SessionStart hook (`seed-session.js`) seeds Claude Code session id into `$TMPDIR/codemap-<project>-session`, all layers append to `<layer>_<session>.jsonl`. CLI runs outside session (no seeded id) fall back to unsuffixed `cli.jsonl` / `skills.jsonl` / `tools.jsonl`. Per-session filenames keep concurrent sessions from interleaving appends.

CLI records include: `cmd` (query subcommand, or `index` for `scan-index` build), plugin version `v` (from `.claude-plugin/plugin.json` — lets debrief split before/after across releases), optional `source` (from `CODEMAP_TELEMETRY_SOURCE`, e.g. `bench` for demo/benchmark runs so debrief separates scripted load from organic usage), full argv, result summary (query: count, method, exhaustive flag, `completeness_reason` veto slug, not_covered list, error; index: modules_indexed, degraded, incremental), timing_ms, stderr tail if any, exit code if non-zero.

Skill records include: skill name, session UUID, intent (first 300 chars of args string).

Tool records include: `tool` (`Grep`|`Read`|`Glob`|`Bash`), plugin version `v`, session UUID, `target` (Grep/Glob pattern or search path, Read file_path, Bash command truncated to 200 chars). Bash commands are logged only when search-shaped (`rg`/`grep`/`egrep`/`fgrep` at a command position, excluding `scan-query` wrappers) — in harness configs without native Grep/Glob tools all search volume flows through Bash, and without this row the grep-reduction baseline is unmeasurable. Measure raw grep/read volume per session — signal codemap context injection aims to reduce. The same hook nudges once per file per session: the 3rd Read of one non-test `.py` file prints a one-line hint that structural queries (`symbol --with-imports`, `rdeps`, `fn-rdeps`) may be cheaper. `log-tool-use.js` hook never reads `tool_response` (no parse of search/read output) — per-call cost sub-millisecond; opt out with `CODEMAP_LOGGING=false`.

Debrief joins tool layer against cli layer measuring **avoidance events** (`bin/join_avoidance.py`): Grep/Read/Glob on module within time window (default 10 min) *after* `query_complete: true` answer already covered that module = leak — agent re-derived what index had answered. Join uses same word-boundary module matching as live `guard-redundant-scan.js` hook — offline rate measures exactly what online guard meant to deny. High avoidance rate = dead-chain signal: queries succeed, downstream behavior ignores them.

Logs rotate auto at 10 MB (3 rotations). Disable logging entirely with `CODEMAP_LOGGING=false` — useful in benchmark scripts.

#### Anonymization

`--anonymize` runs `bin/anonymize.py` on every present log file before reading. Qualified names (strings containing `.` or `::`) replaced with stable `sym_<hash>` pseudonyms using project-local salt stored at `.cache/codemap/logs/.salt`. Scrubbing reaches into free-text `error` and `stderr` fields (each embedded qualified name pseudonymized in place, surrounding prose preserved), hashes every element of `not_covered` lists. Anonymized `-anon.jsonl` files written to dedicated export directory (`--out-dir`, default `.cache/codemap/export/`) kept separate from salt: `anonymize.py` refuses (nonzero exit) to write into any directory already containing `.salt` file — recipient handed both could reverse pseudonyms. Salt must stay local — never share alongside anonymized output. Without salt, pseudonyms not reversible.

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

`scan-index` = plain Python 3 script, no external dependencies. It:

1. Walks every `.py` file under project root, skipping common non-source directories (`.git`, `.venv`, `__pycache__`, `dist`, `build`, others).
2. Parses each file with `ast.parse` — extracts import statements and symbol definitions (classes, functions, methods with line ranges).
3. Resolves call edges per function: cross-module calls tagged `import`, same-file calls `local`, `self.method()` patterns `self`, star-import calls `star`.
4. Computes graph metrics per module: `rdep_count` (how many project modules import this one), `dep_count` (how many modules this one imports), `rcall_count` (how many functions across project call any function in this module).
5. Stores per-file git blob SHAs (`file_shas`) for `.py`, `.rst`, `docs/**/*.md` files — incremental rebuilds identify exactly which files changed.
6. Writes everything to `.cache/codemap/<project>.json` as single JSON file.

Files that cannot parse (syntax errors, encoding issues) marked `degraded` with reason. Scan never aborts — file failing parse noted, skipped.

### The query CLI (`scan-query`)

`scan-query` = companion Python 3 script — loads index, answers structural questions. Checks staleness every call: compares current git blob SHAs against stored `file_shas`. Files changed — warns to stderr, returns results anyway.

All output JSON. Easy pipe into agent spawn prompts, shell scripts, further analysis.

Every command embeds `index` object in output — coverage block — so consumers know exact result reliability:

| Field             | Type      | Meaning                                                                             |
| ----------------- | --------- | ----------------------------------------------------------------------------------- |
| `method`          | string    | How result was produced: `index-lookup`, `static-ast`, `import-graph`, `ast-flags`  |
| `confidence`      | string    | `"exact"` when result complete; `"partial"` when truncated or any symbol stale      |
| `truncated`       | bool      | Present and `true` when `--limit` cut result; absent otherwise                      |
| `total_available` | int       | Total matches before truncation (only present when `truncated: true`)               |
| `not_covered`     | list[str] | Call patterns static analysis cannot see (dynamic dispatch, hook callbacks, etc.)   |
| `hint`            | string    | Suggested grep/fallback for residual-risk verification when `not_covered` non-empty |
| `scope`           | string    | Sub-graph or index slice command operated on                                        |
| `total_modules`   | int       | Modules in index at query time                                                      |
| `total_symbols`   | int       | Symbols across all modules                                                          |
| `degraded`        | int       | Modules skipped due to parse errors                                                 |
| `exhaustive`      | bool      | `true` when every module parsed successfully                                        |
| `stale`           | bool      | `true` when index predates recent file change                                       |

`not_covered` non-empty — agents surface caveat. `confidence="exact"` — no grep re-verification needed.

### The index file

Index lives at `.cache/codemap/<project>.json` — `<project>` = basename of git root directory. Single flat JSON file — nothing keeps running. Format versioned (`scan_version: 3` in current builds).

Key fields per module entry:

| Field            | Meaning                                                                                                                          |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `name`           | Fully qualified module name (e.g. `mypackage.auth`)                                                                              |
| `path`           | Path to `.py` file relative to project root                                                                                      |
| `rdep_count`     | Number of project modules importing this one (blast-radius proxy)                                                                |
| `dep_count`      | Number of modules this one imports (coupling proxy)                                                                              |
| `rcall_count`    | Number of functions across project calling into this module (function-level blast-radius proxy)                                  |
| `direct_imports` | List of modules this file imports                                                                                                |
| `symbols`        | Functions, classes, methods with line ranges and call edges                                                                      |
| `status`         | `ok` or `degraded`                                                                                                               |
| `is_test`        | Whether file in test directory                                                                                                   |
| `file_shas`      | Git blob SHA or MD5 hash for incremental rebuild detection                                                                       |
| `scan_root`      | Absolute path of project root at scan time — used by `scan-query` to resolve file paths; superseded by `--root` flag if provided |

### How agents use it

When develop plugin (or any codemap-integrated skill) spawns agent, runs `scan-query central --top 5` and optionally `scan-query rdeps <target_module>` first. JSON output prepended to agent spawn prompt as `## Structural Context (codemap)` block. Agent starts work knowing which modules highest risk, what depends on target — no cold exploration.

codemap not installed — soft-check block silent skips, skill works exact as before.

______________________________________________________________________

## ⚙️ Configuration

No required configuration. Everything automatic once installed.

### Index location

Index written to `.cache/codemap/<project>.json` at project root by default. Set `CODEMAP_INDEX_DIR` to absolute path to store elsewhere — useful when project root read-only, on slow drive, or shared across machines via home directory:

```bash
export CODEMAP_INDEX_DIR="$HOME/.codemap-cache"
```

With `CODEMAP_INDEX_DIR` set, index lands at `$CODEMAP_INDEX_DIR/<project>.json`. All skills and bin scripts respect variable auto.

Set `SCAN_NO_AUTOBUILD=1` to disable query-time auto-build: `/codemap:query-code` and `/codemap:test-impact` then use existing index exact as-is (no incremental refresh), refuse to build missing one — fail with message naming variable and manual `/codemap:scan-codebase` command. Useful in CI or benchmarks where build cost must stay out of measured query path.

Directory gitignored by default in borda-ai-rig artifact layout. Project name derived from `basename $(git rev-parse --show-toplevel)` — directory name of git root.

### Non-git projects

`scan-index` falls back to MD5 file hashes when git unavailable. Staleness detection and incremental rebuilds still work — use file content hashes instead of git blob SHAs.

### Custom scan root

Python source not at git root — pass `--root`:

```text
/codemap:scan-codebase --root src/mypackage
```

Or from terminal:

```bash
scan-index --root src/mypackage
```

Custom root specified — `scan-index` stores it as `scan_root` in index. `scan-query` reads field auto — file path resolution works correct even querying from different working directory, e.g. querying sub-project index from monorepo root. Override stored root at query time:

```bash
scan-query --root path/to/project symbol MyFunction
```

Priority chain: `--root` flag › `scan_root` in index › `git rev-parse --show-toplevel` › current directory.

`--root` only changes where file paths resolve — never re-scans or re-targets index. Root queried against (`--root`, or CWD git root) disagrees with index stored `scan_root` — index describes *different* project: `scan-query` sets `root_mismatch: true` in coverage block, forces `query_complete: false`, prints warning to stderr. Re-scan current root, or point `--root` at tree index was built for.

### Keeping the index current

**Primary mechanism — skill-invocation currency gates**: every `/develop:*` or `/oss:*` skill run calls `check-index-currency` before spawning any agent. Two-tier check: stored `git_sha` vs HEAD (Tier 1, git repos), or per-file content hashes from stored `file_shas` map (Tier 2, non-git or after pull/branch switch). If stale:

- **Gate A** (index missing): skill pauses, offers build inline or skip.
- **Gate B** (index stale): skill warns, offers: rescan now, continue with stale index, or abort.

Catches all staleness paths post-commit hook misses: `git pull`, branch switches, uncommitted edits, non-git projects.

**Secondary mechanism — post-commit hook** (optional, local commits only): install once via `/codemap:integration init`, every `git commit` triggers incremental background rebuild:

```bash
# .git/hooks/post-commit (installed by /codemap:integration init)
# codemap:start — managed block, do not edit between start/end
# codemap: incremental index rebuild — do not remove this line
if command -v scan-index >/dev/null 2>&1; then
    scan-index --incremental 2>/dev/null &
fi
# codemap:end
```

Rebuild runs in background — commit completes immediate, index updates silent within seconds. Managed block bounded by `# codemap:start`/`# codemap:end` sentinels: reinstalling replaces in place (upgrading body across plugin versions) while preserving surrounding user hook content — re-running installer idempotent. Hook = convenience shortcut; skill-invocation gates = authoritative safety net.

______________________________________________________________________

## 🔍 Troubleshooting

### "index not found" or empty results

`/codemap:query-code` now builds index auto on first use — rarely see this. If appears, auto-build (Step 0) failed — confirm project has `.py` files and `python3` on PATH, build manual:

```text
/codemap:scan-codebase
```

### Stale index warning

`scan-query` detected Python files committed after index built. Run incremental rebuild:

```text
/codemap:scan-codebase --incremental
```

Or full rebuild after large structural changes:

```text
/codemap:scan-codebase
```

### scan-query not found in the terminal

Outside Claude Code session — plugin `bin/` directory not on PATH. Add to shell config (see [Install](#install) — shell PATH snippet). After shell reload, `scan-query` available. Verify:

```bash
command -v scan-query
```

<details>

<summary>

Degraded modules in the scan report

</summary>

### Degraded modules in the scan report

Some files could not parse — usually generated code, syntax errors, or Python syntax features not yet supported by standard library `ast` module. Degraded modules skipped, rest of index fully usable. See which files degraded:

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

Generated files (e.g. protobuf output) expected to degrade. Not part of project's logical import graph.

</details>

### fn-\* commands return "upgrade required"

Function-level call graph queries (`fn-deps`, `fn-rdeps`, `fn-central`, `fn-blast`) require v3 index. Current index older. Rebuild:

```text
/codemap:scan-codebase
```

### The develop plugin does not seem to use codemap

Run integration check:

```text
/codemap:integration check
```

Look for `⚠ missing injection in:` lines pointing to specific skill files. Injection missing — run:

```text
/codemap:integration init
```

and select skills to wire in.

______________________________________________________________________

<a id="contributing--feedback"></a>

## 🙏 Contributing / feedback

codemap lives in `plugins/codemap/` directory of Borda-AI-Rig repository.

**Found bug or want feature?** Open issue in repository. Include:

- Python version (`python --version`)
- codemap version (`cat ~/.claude/plugins/cache/borda-ai-rig/codemap/*/.claude-plugin/plugin.json`)
- Error message or unexpected behavior
- Approximate project size scanned (module count from scan output)

**Want to extend codemap?**

Scanner and query CLI = standalone Python scripts in `plugins/codemap/bin/`. No external dependencies, easy to read and modify. Index schema versioned — adding new fields, bump `SCAN_VERSION` in `scan-index`, handle version check in `scan-query`.

Skills live in `plugins/codemap/skills/*/SKILL.md`. New skill = new subdirectory with `SKILL.md` following existing pattern.

After any edit to agents, skills, or index schema — update this README before committing; plugin CLAUDE.md requires it.

**Plugin updates** propagate via normal install path:

```bash
claude plugin install codemap@borda-ai-rig
```

After upgrade, run `/codemap:integration check` to confirm everything still wired correct.
