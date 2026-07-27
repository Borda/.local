# bin/ — codemap-py runtime executables

This directory ships the runtime surface a project author or a Claude/Codex skill actually invokes: the interpreter-resolving launchers, the index builder and query engine, a handful of maintenance and analysis helpers used by skills and debrief tooling, and a set of internal compatibility shims. Everything here is installed as-is into the package (see `../scripts/README.md` for how the package is built and validated) and is addressed either by bare name on `PATH`, or via `${CLAUDE_PLUGIN_ROOT}/bin/<script>` from inside a skill.

**Language policy.** Python is the default for this directory, minimum version 3.10, per the plugin-wide `bin/` convention; the one exception is `setup_scan_env.sh`, which stays in bash for path/env-resolution glue ahead of a Python subprocess call. In practice `codemap_py_entry.py` (invoked by the `codemap-py` / `codemap-py.cmd` launchers) enforces a narrower runtime bound of its own — CPython 3.11 up to, but excluding, 3.15 — and resolves the interpreter to use before importing anything from the `codemap_py` package. All meaningful logic (scanning, querying, CLI dispatch) lives in the importable `src/codemap_py` package; the scripts under this directory are thin launchers, deterministic argument/path transforms, or session-scoped temp-file glue — no branching business logic lives here.

## Contents

- [User-facing launchers](#user-facing-launchers) — `codemap-py`, `codemap-py.cmd`, `scan-index`, `scan-query`, `check-index-currency`
- [Maintenance and analysis helpers](#maintenance-and-analysis-helpers) — `anonymize.py`, `check_index_smoke.py`, `scan-stats.py`, `smoke_test_index.py`, `resolve_proj_index.py`, `resolve_index_env.py`, `locate_scan_query.py`, `join_avoidance.py`, `gen_deprecation_wrapper.py`, `parse_scan_args.py`, `parse_deprecate_args.py`, `setup_scan_env.sh`
- [Internal `sys.modules` shims](#internal-sysmodules-shims) — `_exclusions.py`, `_index_identity.py`, `_runtime_log.py`, `_rwgate.py`, `_schema.py`, `_telemetry.py`

## User-facing launchers

### `codemap-py`

**Purpose.** The POSIX shell launcher and primary CLI entry point on macOS and Linux. Probes for an eligible CPython (an explicit `$CODEMAP_PYTHON`, and if it fails its own version probe the launcher fails hard rather than falling through; otherwise `python3` then `python` on `PATH`), then `exec`s `../scripts/codemap_py_entry.py` with every argument forwarded unchanged. No Bash dependency, no install step, no shell-command mode — it is a `#!/bin/sh` script.

**Usage.**

```
codemap-py <subcommand> [args...]
```

Exits `127` with a diagnostic on stderr when no eligible interpreter is found.

**How-to.**

```bash
./bin/codemap-py doctor --json
```

**When-to-use.** This is the command a project author or a skill runs after install — `doctor`, `index`, `query`, and every other `codemap_py.cli` subcommand go through here on POSIX systems.

### `codemap-py.cmd`

**Purpose.** The Windows batch-file mirror of `codemap-py`: probes `CODEMAP_PYTHON`, then falls back through `py -3`, `python.exe`, and `python3.exe`, running `..\scripts\codemap_py_entry.py` with all arguments forwarded. Windows never depends on Bash, so this is a self-contained `@echo off` script rather than a port of the POSIX shell logic.

**Usage.**

```
codemap-py.cmd <subcommand> [args...]
```

Exits `127` with a diagnostic on stderr when no eligible interpreter is found.

**How-to.**

```bat
codemap-py.cmd doctor --json
```

**When-to-use.** The Windows equivalent of `codemap-py` — invoked from `cmd.exe` or PowerShell wherever the POSIX launcher would be used on macOS/Linux.

### `scan-index`

**Purpose.** Thin launcher over `codemap_py.graph.main`. Builds the codemap structural index for a project: scans every Python file (import graph, per-symbol call graph, docstrings, mock patches, dynamic/subprocess imports, Sphinx/MkDocs cross-references, pytest fixture graph, optional coverage annotation) and writes `.cache/codemap/<project>.json` (or `$CODEMAP_INDEX_DIR/<project>.json` when that variable is set). File discovery and single-file AST parsing live in `codemap_py.scanner`; cross-module graph construction, coverage, and the `scan()` / `incremental_scan()` orchestration live in `codemap_py.graph` — this script only wires `src/` onto `sys.path` and delegates.

**Usage.**

```
scan-index [--root PATH] [--incremental] [--with-coverage PATH] [--timeout N]
```

- `--root PATH` — project root (default: git root or cwd).
- `--incremental` — re-parse only files changed since the last scan (requires an existing v3+ index).
- `--with-coverage PATH` — path to a `.coverage` SQLite file (v5.4+); attaches per-symbol `coverage_pct` / `covered_by` fields (requires `coverage>=7.4`).
- `--timeout N` — hard timeout in seconds; `0` (default) means no limit. Uses `SIGALRM`, so Unix only.

**How-to.**

```bash
bin/scan-index --root . --incremental
```

**When-to-use.** Run once per project to build the initial index, and again (with `--incremental` once one exists) whenever the index needs a refresh — typically driven by the `scan-codebase` skill rather than invoked bare, but safe to run directly.

### `scan-query`

**Purpose.** Thin launcher for the codemap query engine, wrapping `codemap_py.query.main`. Provides the full read-side command surface against an existing index: `deps`/`rdeps`/`central`/`coupled`/`path` for module-level import relationships, `symbol`/`symbols`/`find-symbol` for source lookup, `fn-deps`/`fn-rdeps`/`fn-central`/`fn-blast` for the function-level call graph, `test-impact` and the fixture/mock/subprocess queries for test-graph analysis, `coverage`/`coverage-gap`/`undocumented`/ `uncovered` for quality signals, `dead-symbols`/`dead-modules`/`xrefs` for dead-code and doc cross-reference checks, `diff-impact` for git-change blast radius, and `batch` for running many queries in one process against a single shared coverage block. `codemap_py.cli` (the `codemap-py query` dispatcher) does not shell out to this file — it calls `codemap_py.query.main` in-process under its own read lease; this launcher exists for direct invocation and for tests that exercise the standalone script.

**Usage.**

```
scan-query [--index PATH] [--root PATH] [--timeout N] [--no-heal] [--verbose-coverage] <subcommand> ...
```

Run `scan-query --help` or `scan-query <subcommand> --help` for the full, current flag and subcommand reference — the subcommand roster above is summarized from that output and from `codemap_py.query`'s own module docstring, not reproduced flag-by-flag here.

**How-to.**

```bash
bin/scan-query rdeps pkg.auth
bin/scan-query fn-blast pkg.auth::login
```

**When-to-use.** Any ad-hoc structural question against an already-built index — "what imports this module," "what calls this function," "which tests cover this," "what's the blast radius of this diff" — whether asked interactively or from a skill/agent that has already confirmed the index is current.

### `check-index-currency`

**Purpose.** Verifies that an on-disk codemap index still matches the current source tree, using a two-tier check that prefers reporting a false "stale" over missing a real one. Tier 1 (git repo present): compares the index's stored `git_sha` against `HEAD` and flags any dirty tracked `.py` files. Tier 2 (no git, or no stored `git_sha`): compares stored per-file hashes against current file content, using an mtime pre-filter before falling back to a git blob SHA-1 or MD5 recompute.

**Usage.**

```
check-index-currency --index-path <path> [--root <path>] [--field <name>]
```

- `--index-path <path>` (required) — path to the codemap index JSON file.
- `--root <path>` — project root (default: git toplevel or cwd).
- `--field <name>` — print only the named field from the result JSON (e.g. `--field status`), useful for `STATUS=$(check-index-currency ... --field status)` in a bash block.

Output is a single JSON object: `{"status": "current"|"stale"|"no_index", "reason": "<text>", "changed_count": N}`. Exit `0` current, `1` stale, `2` no_index, `3` argument error.

**How-to.**

```bash
bin/check-index-currency --index-path .cache/codemap/myproj.json --field status
```

**When-to-use.** As a preflight before trusting any `scan-query` answer, or before a skill decides whether to re-run `scan-index` — the two-tier design means it stays cheap (git-SHA compare) in the common case and only falls back to per-file hashing when there is no git history to compare against.

## Maintenance and analysis helpers

### `anonymize.py`

**Purpose.** Replaces qualified names (anything containing `.` or `::`) in codemap JSONL telemetry logs with stable, salted pseudonyms, so a log can be shared without exposing real module/symbol names. Pseudonyms are stable within a project (same salt + same name → same pseudonym) but opaque without the salt file, which is created `0o600` and must never be shipped alongside the anonymized output. Writing into a directory that itself holds the salt file (`.salt`) is refused outright, since a recipient of both could reverse every pseudonym.

**Usage.**

```
python anonymize.py --input <log.jsonl> [--output PATH] [--out-dir DIR] [--salt PATH]
```

- `--input` (required) — source JSONL log file.
- `--output` — explicit destination path, overriding `--out-dir`; still refused if its directory holds a salt file.
- `--out-dir` — directory for `<input-stem>-anon.jsonl` (default `.cache/codemap/export`), deliberately distinct from the salt directory.
- `--salt` — salt file path (default `.cache/codemap/logs/.salt`), created with a fresh random value if absent.

Exit `0` success, `1` input not found, `2` refused (output directory contains a salt file).

**How-to.**

```bash
python bin/anonymize.py --input .cache/codemap/logs/cli_abc123.jsonl
```

**When-to-use.** Before attaching or sharing codemap telemetry logs outside the local machine — debrief reports, bug reports, or any external hand-off — so qualified symbol/module names are pseudonymized first.

### `check_index_smoke.py`

**Purpose.** Wraps `smoke_test_index.py`: invokes it with `--index-path` / `--max-age-hours`, projects the result down to `{"ok": bool, "stale": bool, "age_hours": N}` (preserving an `error` field when present, sanitized to 256 ASCII characters), and derives the exit code from those projected fields rather than trusting the child process's own return code. Exists so a `SKILL.md` bash block can read `ok`/`stale` from compact JSON without needing `jq`.

**Usage.**

```
python check_index_smoke.py --index-path <path> [--max-age-hours <N>]
```

`--max-age-hours` defaults to `24`. Output is a single JSON line, e.g. `{"ok":true,"stale":false,"age_hours":2.31}`, or with an `error` field on failure. Exit `0` ok and fresh, `1` failed or stale or no output, `2` invalid arguments.

**How-to.**

```bash
python "${CLAUDE_PLUGIN_ROOT}/bin/check_index_smoke.py" --index-path .cache/codemap/myproj.json
```

**When-to-use.** From within a skill's bash block, whenever a compact, jq-free ok/stale/age check on the index is needed before proceeding.

### `scan-stats.py`

**Purpose.** Prints a human-readable codemap index summary: module and degraded-module counts, total symbol count, total resolved call-edge count (v3+ index only), and the five most central modules by reverse-dependency count. Unusually, its project root is read from the `SCAN_ARGS` environment variable rather than argv — `argparse` here only handles `-h`/`--help` — so callers pass `--root` through `SCAN_ARGS`, matching the calling convention used by the `scan-codebase` skill.

**Usage.**

```
SCAN_ARGS="--root <dir>" scan-stats.py
```

Exit `0` summary printed (or "No modules indexed."), `1` index file missing or oversized, `2` `--root` escapes the project root or `CODEMAP_INDEX_DIR` resolves outside allowed cache roots.

**How-to.**

```bash
SCAN_ARGS="--root ." python bin/scan-stats.py
```

**When-to-use.** A quick human-readable health check right after a scan — module/symbol counts and the most central modules — without writing a query by hand.

### `smoke_test_index.py`

**Purpose.** The lower-level validator behind `check_index_smoke.py`: opens the index path and `json.load`s it, rejecting a missing, unreadable, non-object, or empty index, then compares filesystem mtime against wall clock and flags staleness above `--max-age-hours` (default 24). Emits the raw, unprojected result.

**Usage.**

```
python smoke_test_index.py --index-path <path> [--max-age-hours N]
```

Output: `{"ok": true, "stale": false, "age_hours": 2.31, "path": "<path>"}`, or with an `error` field, e.g. `{"ok": false, "stale": false, "age_hours": null, "path": "<path>", "error": "index file not found"}`. Exit `0` ok and not stale, `1` invalid or stale.

**How-to.**

```bash
python bin/smoke_test_index.py --index-path .cache/codemap/myproj.json
```

**When-to-use.** Call directly when the raw `{ok, stale, age_hours, path[, error]}` object is wanted without `check_index_smoke.py`'s exit-code projection and sanitization layer — otherwise prefer `check_index_smoke.py` from a skill.

### `resolve_proj_index.py`

**Purpose.** Computes the canonical `(PROJ, INDEX)` pair: `PROJ` is the git root's basename (or the cwd's basename outside a repo), and `INDEX` is `<git-root-or-cwd>/.cache/codemap/<proj>.json` by default, or `$CODEMAP_INDEX_DIR/<proj>.json` when that variable is set.

**Usage.**

```
python resolve_proj_index.py [--check]
```

Without `--check`: two lines on stdout, `PROJ` then `INDEX` path. With `--check`: the same two lines plus a third status line, `✓ index: exists` or `✗ index: not found`. Exit `0` success, `1` `--check` given and index missing, `2` bad/missing argument.

**How-to.**

```bash
python bin/resolve_proj_index.py --check
```

**When-to-use.** Whenever a script or skill needs the project name and index path without re-implementing the git-root-or-cwd plus `CODEMAP_INDEX_DIR` resolution logic itself — it is the canonical resolver that `resolve_index_env.py` shells out to.

### `resolve_index_env.py`

**Purpose.** Calls `resolve_proj_index.py`, reads `PROJ` (line 1) and `INDEX` (line 2) from its stdout, and writes each to `<tmpdir>/${prefix}-resolve-{proj,index}-<CSID>` for the caller to read back with `IFS= read -r`, rather than the `eval "$(...)"` anti-pattern. `CLAUDE_PLUGIN_ROOT` is validated before use (must be absolute and either inside the plugin cache subtree or ending in `plugins/codemap`) to prevent arbitrary subprocess execution; `TMPDIR` is honored only when absolute and owned by the current user.

**Usage.**

```
python resolve_index_env.py [--check-exists] [--output-prefix STR]
```

- `--check-exists` — verify the `INDEX` file exists; exit `1` with a stderr message if missing (temp files are still written for diagnostics).
- `--output-prefix STR` — prefix for the temp file names (default `codemap`); must match `[a-zA-Z0-9_-]+`. Use `codemap-<proj>` to scope per-project and avoid concurrent collisions.

Exit `0` success, `1` resolver produced no output or (with `--check-exists`) the index is missing, `2` unknown flag, `3` unsafe `CLAUDE_PLUGIN_ROOT` or `--output-prefix`.

**How-to.**

```bash
export CSID="${CLAUDE_CODE_SESSION_ID:-$PPID}"
python "${CLAUDE_PLUGIN_ROOT:-plugins/codemap}/bin/resolve_index_env.py" --output-prefix "codemap-myproj"
IFS= read -r PROJ < "${TMPDIR:-/tmp}/codemap-myproj-resolve-proj-${CSID}" 2>/dev/null || PROJ=""
IFS= read -r INDEX < "${TMPDIR:-/tmp}/codemap-myproj-resolve-index-${CSID}" 2>/dev/null || INDEX=""
```

**When-to-use.** From a `SKILL.md` bash block that needs `PROJ`/`INDEX` in shell variables without resorting to `eval "$(...)"`.

### `locate_scan_query.py`

**Purpose.** Resolves the `scan-query` executable via a three-tier fallback cascade: (1) `scan-query` on `PATH`; (2) `${CLAUDE_PLUGIN_ROOT}/bin/scan-query`, with a containment check rejecting a symlink that escapes the plugin root; (3) a glob over `~/.claude/plugins/cache/*/codemap/*/bin/scan-query`, picking the newest semver directory. Prints the resolved absolute path and nothing else.

**Usage.**

```
locate_scan_query.py
```

No positional arguments besides `-h`/`--help`. Exit `0` found and executable, `1` not found, `2` bad argument.

**How-to.**

```bash
SQ=$(python bin/locate_scan_query.py)
```

**When-to-use.** Whenever a script or a cross-plugin consumer needs to invoke `scan-query` but cannot assume it is on `PATH` — e.g. a skill in a different plugin that shells out to the installed codemap-py cache.

### `join_avoidance.py`

**Purpose.** Joins `tools_*.jsonl` (Grep/Read/Glob tool calls, from `log-tool-use.js`) against `cli_*.jsonl` (codemap CLI answers) to count *avoidance events* — a tool call that re-derived by hand what codemap had already answered completely (`query_complete: true`) within a preceding time window. A high avoidance rate is a dead-chain signal: either the redundant-scan guard is not firing, the injected context is not being read, or the model is ignoring both. The module-match rule is ported from `guard-redundant-scan.js` so this offline join counts exactly the greps the online guard was meant to deny.

**Usage.**

```
python join_avoidance.py --logs <dir> | (--cli FILE [--tools FILE]) [--window-min N] [--json]
```

- `--logs <dir>` — log directory holding `cli_*`/`tools_*`/`skills_*` shards (default resolution mode).
- `--cli FILE` / `--tools FILE` — explicit JSONL files, overriding `--logs` per layer.
- `--window-min N` — minutes an answer may precede a re-deriving tool call and still count as leaked (default 10).
- `--json` — emit a single-line JSON object instead of the text report.

Exit `0` success (including "no avoidance events" or "no logs found"), `2` neither `--logs` nor a `--cli`/`--tools` pair given.

**How-to.**

```bash
python bin/join_avoidance.py --logs .cache/codemap/logs --json
```

**When-to-use.** When debriefing codemap adoption or effectiveness — is the redundant-scan guard actually preventing the greps it exists to prevent, and if not, which sessions or skills are leaking.

### `gen_deprecation_wrapper.py`

**Purpose.** Generates the Python source for a `pyDeprecate` deprecation wrapper — the correct `from deprecate import ...` line, the decorator, and a stub `def`/`class` — for the `codemap:rename-refs --deprecate` code path. Two modes: **auto**, where the script builds the decorator line from `--type`/`--old-name`/`--new-name`/`--since`/`--removed-in`; and **explicit**, where the caller supplies a complete `--decorator` line and the script only infers the import and builds the stub.

**Usage.**

```
python gen_deprecation_wrapper.py --type {function,method,class} --old-name X --new-name Y [--since V] [--removed-in V]
python gen_deprecation_wrapper.py --decorator "@deprecated(...)" --old-name X [--removed-in V]
```

Prints the generated Python source to stdout. Exits `1` with a stderr message on a malformed decorator (e.g. containing newlines/control characters) or an unrecognized `--type`.

**How-to.**

```bash
python bin/gen_deprecation_wrapper.py --type function --old-name foo --new-name bar --since 1.2.0 --removed-in 2.0.0
```

**When-to-use.** Internal helper for the `codemap:rename-refs` skill's `--deprecate` path; also usable standalone when hand-crafting a deprecation stub for a rename that wasn't done through the skill.

### `parse_scan_args.py`

**Purpose.** Extracts `--root` and `--incremental` from a single raw `$ARGUMENTS` string (as passed by a Claude skill), without handing a blob that may itself start with `--` to `argparse`'s own flag matcher. Supports three output modes: default (shell-quoted tokens for `eval`), `--nul-output` (NUL-delimited tokens written to a TMPDIR-contained file, for safe `while IFS= read -r -d ''` consumption), and `--print-root` (just the resolved `--root` value, or `.`).

**Usage.**

```
parse_scan_args.py "$ARGUMENTS" [--nul-output <file>] [--print-root]
```

Exit `0` always on parsed input; `1` if `--nul-output`'s path validation fails (must resolve inside `TMPDIR`).

**How-to.**

```bash
python bin/parse_scan_args.py "--root . --incremental" --print-root
```

**When-to-use.** Internal helper for the `scan-codebase` skill (via `setup_scan_env.sh`) — not typically invoked directly by a user, though nothing prevents it.

### `parse_deprecate_args.py`

**Purpose.** Extracts `--deprecate` / `--no-deprecate` and an optional decorator value from a raw `$ARGUMENTS` string, then writes `DEPRECATE` (`"true"`/`"false"`) and `DEPRECATE_DECORATOR` to two pid-qualified temp files rather than printing shell assignments for `eval`. The pid suffix (`-<pid>`) defeats predictable-name symlink attacks; since the pid is not knowable to the calling shell in advance, the script prints the two resolved paths so the caller can `cat` exactly those files.

**Usage.**

```
python parse_deprecate_args.py --arguments="$ARGUMENTS"
```

The `--arguments=` form (equals sign, no space) is required so a value beginning with `--` (the literal payload `--deprecate`) survives argparse's flag detection. Prints two lines: the flag-file path, then the decorator-file path. Exit `0` always.

**How-to.**

```bash
OUT=$(python "${CLAUDE_PLUGIN_ROOT}/bin/parse_deprecate_args.py" --arguments="--deprecate=@deprecated")
FLAG_FILE=$(printf '%s\n' "$OUT" | sed -n 1p)
DEC_FILE=$(printf '%s\n' "$OUT" | sed -n 2p)
DEPRECATE=$(cat "$FLAG_FILE" 2>/dev/null || echo "false")
```

**When-to-use.** Internal helper for the `codemap:rename-refs` skill, which needs `DEPRECATE`/`DEPRECATE_DECORATOR` in-shell without an `eval "$(...)"`.

### `setup_scan_env.sh`

**Purpose.** Consolidates the per-invocation setup previously inlined in `scan-codebase/SKILL.md`: derives `PROJ_SLUG` (hostname short-name plus repo basename, sanitized to alphanumerics/dashes), validates that the `scan-index` binary exists at `$CLAUDE_PLUGIN_ROOT/bin/scan-index`, runs `parse_scan_args.py` against the raw `$ARGUMENTS` string, derives `PROJ_NAME` (basename of `--root` when given, else the git-root/cwd basename), drops a sentinel tmpfile when `--incremental` was requested but no prior index exists (so the skill can report the silent full-scan fallback), and writes both a sourceable `KEY=VAL` state file and the individual per-`PROJ_SLUG` tmpfiles consumed by later skill steps.

**Usage.**

```
setup_scan_env.sh --arguments "$ARGUMENTS"
```

Prints the state-file path on stdout. Exit `0` success, `1` `scan-index` binary missing, `2` `parse_scan_args.py` failed, `3` bad CLI arguments.

**How-to.**

```bash
STATE_FILE=$(bin/setup_scan_env.sh --arguments "--root . --incremental")
source "$STATE_FILE"
```

**When-to-use.** Sourced by the `scan-codebase` skill's first step to collapse several previously-inlined bash blocks into one call; it is a plain shell script and can be run standalone for debugging, but is not meant for routine interactive use.

## Internal `sys.modules` shims

Six single-purpose files — `_exclusions.py`, `_index_identity.py`, `_runtime_log.py`, `_rwgate.py`, `_schema.py`, `_telemetry.py` — exist purely as import compatibility shims for code that historically imported them as bare module names (e.g. `import _schema`) after inserting `bin/` onto its own `sys.path`. Each shim follows the same pattern: prepend `<plugin-root>/src` to `sys.path`, import the real implementation module from `codemap_py`, then replace its own entry in `sys.modules` with that real module — so every attribute access, including private internals a test monkeypatches, reaches the one authoritative implementation rather than a divergent shadow copy. None of them is a standalone executable; none has meaningful logic of its own to invoke.

### `_exclusions.py`

**Purpose.** Shim for `codemap_py.scanner`, specifically its exclusion rules (`SKIP_DIRS`, `Exclusions`, `_load_exclusions`, `_match_exclusion`, `is_excluded`, `load_src_roots`) that `scan-query` must apply identically to how `scan-index`'s writer side applies them.

**Usage.** Imported as a bare module name: `import _exclusions`, after the importer has put `bin/` on `sys.path`.

**How-to.** Not run directly; consumed internally by `bin/scan-query`.

**When-to-use.** Internal shim — not invoked directly.

### `_index_identity.py`

**Purpose.** Shim for `codemap_py.index_paths`.

**Usage.** Imported as a bare module name: `import _index_identity`.

**How-to.** Not run directly; consumed indirectly through the `codemap_py` package (including by `_runtime_log.py`) and by tests.

**When-to-use.** Internal shim — not invoked directly.

### `_runtime_log.py`

**Purpose.** Shim for `codemap_py.runtime_log`.

**Usage.** Imported as a bare module name: `import _runtime_log`.

**How-to.** Not run directly; consumed by tests exercising the bare-name import path.

**When-to-use.** Internal shim — not invoked directly.

### `_rwgate.py`

**Purpose.** Shim for `codemap_py.rwgate`, the cross-process read/write gate. Consumers include cross-process worker scripts that insert this directory onto `sys.path` and `import _rwgate` fresh in a new process, so private internals (`_RELEASE_TIMEOUT`, `_registry_for`, ...) that a test monkeypatches must mutate the one real gate state rather than a divergent copy.

**Usage.** Imported as a bare module name: `import _rwgate`.

**How-to.** Not run directly; consumed by tests and cross-process worker scripts.

**When-to-use.** Internal shim — not invoked directly.

### `_schema.py`

**Purpose.** Shim for `codemap_py.schema`.

**Usage.** Imported as a bare module name: `import _schema`.

**How-to.** Not run directly; consumed internally by `bin/scan-index` and `bin/scan-query`.

**When-to-use.** Internal shim — not invoked directly.

### `_telemetry.py`

**Purpose.** Shim for `codemap_py.telemetry`, including its module-global `_PLUGIN_VERSION` cache that a test monkeypatches.

**Usage.** Imported as a bare module name: `import _telemetry`.

**How-to.** Not run directly; consumed internally by `bin/scan-index` and `bin/scan-query`.

**When-to-use.** Internal shim — not invoked directly.
