---
name: integration
description: |
  Adapter over `codemap-py integrate` — audit, plan, source-wire, locally sync, and demonstrate the
  codemap-py integration with its supported consumers. Trigger with `/codemap-py:integration
  check|plan|apply|sync|demo [--runtime {claude,codex,both}] ...`. Default (no args) is `check`.
  Skip for: running a structural query (use `/codemap-py:query-code`); explicit standalone index
  rebuild (use `/codemap-py:scan-codebase`).
argument-hint: "check [--runtime {claude,codex,both}] [--json] | plan [--runtime ...] [--consumers <csv>] [--source {local-candidate,release}] [--out <artifact>] | apply --plan <artifact> --approve <sha256> | sync --source {local-candidate,release} --plan <artifact> --approve <sha256> [--runtime ...] | demo [--runtime ...]"
effort: medium
allowed-tools: Bash, AskUserQuestion
model: sonnet
---

<objective>

Runtime adapter over the `codemap-py integrate` engine (`src/codemap_py/integration.py`). Claude Code
can target Claude Code, Codex, or both; this skill never invokes the other runtime's model, only its
native plugin-manager CLI.

Five modes, matching the pinned CLI surface exactly (never the retired `check|init|demo` model):

| Mode | Args | Mutation | Exit |
| --- | --- | --- | --- |
| `check` | `[--runtime {claude,codex,both}] [--json]` | none | 0 ok; 1 runtime/fs fail; 2 bad syntax |
| `plan` | `[--runtime ...] [--consumers <csv>] [--source {local-candidate,release}] [--out <artifact>]` | report artifact only | 0; 2 bad syntax |
| `apply` | `--plan <artifact> --approve <sha256>` | verified source checkout only | 0; 1 drift/fs; 2 bad approve/syntax |
| `sync` | `--source {local-candidate,release} --plan <artifact> --approve <sha256> [--runtime ...]` | local runtime plugin state | 0; 1 partial-fail/journal; 2 bad approve |
| `demo` | `[--runtime ...]` | disposable evidence only | 0; 1 fail |

`--approve` is valid only with an explicit mutation mode (`apply`/`sync`), a saved plan artifact, and
the SHA-256 shown to the user for that plan. It never authorizes new targets, remote publication, Git
history/remote mutation, marketplace-file editing, user instruction-file editing, or data deletion.

Closed integration/reinstall set: Claude consumers `foundry`, `oss`, `develop`, `research` (provider
`codemap-py`); Codex consumer `codex-rig` (provider `codemap-py`). This is an explicit mapping
cross-checked against both marketplace manifests and plugin manifests before any mutation — not a
discovery/extension registry. `--runtime codex` scopes to the `codex-rig` consumer only; `--runtime
claude` to the four Claude consumers; `--runtime both` (or omitted) to all five.

Safety invariants (enforced by the shared engine, not this skill — surfaced here so the user sees the
contract):

- `plan` records schema/protocol version, op ID, exact targets, before-state hashes, desired
  versions/refs/hashes, exact argv, ordered ops, rollback identities, expected post-state, and a plan
  SHA-256.
- Every mutation revalidates target + before-state immediately before acting; drift invalidates the
  approval.
- Source writes use before-images and atomic per-file replace; `apply` refuses foreign/modified
  markers, path escapes, symlinks, installed-cache roots, dirty working-tree overlap, and unverified
  product identity.
- `sync` refuses applying a plan whose source isn't actually built into the selected candidate, whose
  installed bytes don't match the selected hash, or that names a mutable/default-branch source as
  release/rollback evidence. No implicit "latest".
- First-target success + second-target failure stops immediately; rollback only performs actions the
  approved plan already contains. Completion and rollback are both claimed only after a post-state
  hash verification.
- "Push" here means two local operations only: (1) updating allowlisted, version-controlled consumer
  source integration from the `codemap-py.integration.v1` contract, and (2) installing/reinstalling
  those built plugin versions in the user's local runtime(s) via native CLI operations. It never means
  `git push`, remote marketplace mutation, release publication, or direct installed-cache edits.

NOT for: running a structural query (use `/codemap-py:query-code`); explicit standalone index rebuild
(use `/codemap-py:scan-codebase`).

</objective>

<inputs>

- **$ARGUMENTS**: optional — one of:
  - Omitted or `check` — audit installed/active versions, roots, protocol compatibility, and
    Codex-Rig global-instruction status; zero-write.
  - `plan` — persist a report artifact (targets, argv, hashes, rollback identities, plan SHA-256);
    never mutates.
  - `apply` — atomically update current-version managed blocks in allowlisted consumer source files
    from an approved plan.
  - `sync` — install/reinstall the approved plan's targets in local runtime(s) via native plugin-
    manager CLIs.
  - `demo` — run `check` plus representative plain-vs-structural-context workflows; disposable evidence only.

</inputs>

<workflow>

## Step 1: Resolve mode

Parse `$ARGUMENTS` (case-insensitive): starts with `check` or empty → check mode; `plan` → plan mode;
`apply` → apply mode; `sync` → sync mode; `demo` → demo mode. Anything else → `AskUserQuestion`:
"Unrecognized command `$ARGUMENTS`. Which of the five modes did you mean?" Options: (a) `check`, (b)
`plan`, (c) `apply`, (d) `sync`, (e) `demo` — wait for the reply before proceeding.

## Step 2: Run the mode

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" integrate check [--runtime <r>] [--json]  # timeout: 15000
```

**`check`** — reports installed/active versions, roots, protocol compatibility, Codex-Rig-owned
global-instruction status when publicly available (`absent|present|authenticated` from verifiable
bytes only — `stale` only via a versioned Codex-Rig-owned read-only status contract, otherwise
`unavailable`, never guessed), fallback state, shared-index identity, and runtime-log isolation. Never
invokes `install_global_agents.py`, never writes `${CODEX_HOME}/AGENTS.md`. Print the human-readable
form by default; pass `--json` only when the result feeds further reasoning in this session.

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" integrate plan [--runtime <r>] [--consumers <csv>] [--source <s>] [--out <artifact>]  # timeout: 15000
```

**`plan`** — writes a report artifact only; no mutation. The CLI prints the artifact path, op count,
and plan SHA-256 to stdout — relay all three to the user verbatim; do not paraphrase the hash.

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" integrate apply --plan <artifact> --approve <sha256>  # timeout: 30000
```

**`apply`** — requires `--plan` and `--approve <sha256>` matching the plan just shown. Before running
it, print the plan summary and SHA-256 in chat and call `AskUserQuestion`: "Apply this plan? (targets:
<consumers>, plan SHA-256: <sha256>)" — options (a) Approve — run `apply` with this exact SHA-256, (b)
Cancel. Never construct or pass `--approve` on the user's behalf without this explicit confirmation.
Maintainer/source-checkout operation — an end user installing immutable releases normally uses
`check`, `sync`, and `demo`; `apply` never runs the native reinstall commands it reports, and `sync`
never rewrites consumer source.

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" integrate sync --source <s> --plan <artifact> --approve <sha256> [--runtime <r>]  # timeout: 60000
```

**`sync`** — same approval gate as `apply` (print plan summary + SHA-256, `AskUserQuestion` before
passing `--approve`), plus `--source {local-candidate,release}`. After a successful sync that
installs/reinstalls a Claude consumer or `codemap-py` itself, tell the user: "Run `/reload-plugins` (or
start a fresh session) before relying on the updated plugin — this session's tool list was resolved
before the update." When `--runtime` included `codex` and `codex-rig`/`codemap-py` were synced, add the
Codex-specific note: "Start a new Codex session before relying on the updated plugin there too."

```bash
"${CLAUDE_PLUGIN_ROOT:-plugins/codemap-py}/bin/codemap-py" integrate demo [--runtime <r>]  # timeout: 20000
```

**`demo`** — runs `check` plus representative plain-vs-structural-context workflows and records the
protocol/version/evidence used; disposable unless the user separately approves a mutation. The
contrast between the plain and structural runs is the evidence — a single structural query alone does
not satisfy this mode. Print the report path the CLI returns.

## Step 3: Report

Print exit code meaning plainly: `0` success, `1` runtime/filesystem failure or partial-sync journal
state (see the mode table), `2` bad syntax or invalid approval. On `1` during `sync`, report the
journaled state (`planned → approved → applying:<t> → verified:<t> → complete`, or
`rollback-started → rollback-succeeded|rollback-failed → recovery-required`) and, for
`recovery-required`, the bounded manual recovery commands the engine reported — never invent recovery
steps beyond what was reported.

</workflow>
