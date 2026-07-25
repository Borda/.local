<!-- file: integration-contract.md — consumers: plugins/codemap-py/claude-skills/integration/SKILL.md, plugins/codemap-py/codex-skills/integration/SKILL.md, src/codemap_py/integration.py, tests/integration/test_integrate.py -->

# `codemap-py.integration.v1` — integration protocol contract

Reference contract for the `codemap-py integrate <check|plan|apply|sync|demo>` engine
(`src/codemap_py/integration.py`) and both runtime `integration` skill adapters. Authoritative
source: `.plans/active/plan_codemap-py-dual-runtime-package.md` §8.3 (native integration skill),
§9.3 (consumer-source and native-update ownership), §8.5 (symmetric optionality). This file does
not re-derive or contradict those sections — it fixes the marker format, consumer set, and
plan/approval/journal shapes at the level of detail an implementer or parity test needs, and points
back to §8.3/§9.3 for anything not restated here.

## Protocol identity

- Capability-protocol name: `codemap-py.integration.v1`.
- Either host runtime (Claude Code, Codex) can target Claude Code, Codex, or both via
  `--runtime {claude,codex,both}`; neither runtime's adapter invokes the other host's model.
- `codemap-py integrate` is the single pinned CLI surface both runtime `integration` skills
  wrap — the skill layer supplies interactive approval/AskUserQuestion flow, fresh-session
  instructions, and runtime CLI discovery; it never re-implements plan/approval/journal logic.

## Pinned CLI surface (delivery-plan.md, authoritative)

| Mode | Args | Mutation | Exit |
| --- | --- | --- | --- |
| `check` | `[--runtime {claude,codex,both}] [--json]` | none | 0 ok; 1 runtime/fs fail; 2 bad syntax |
| `plan` | `[--runtime ...] [--consumers <csv>] [--source {local-candidate,release}] [--out <artifact>]` | report artifact only | 0; 2 bad syntax |
| `apply` | `--plan <artifact> --approve <sha256>` | verified source checkout only | 0; 1 drift/fs; 2 bad approve/syntax |
| `sync` | `--source {local-candidate,release} --plan <artifact> --approve <sha256> [--runtime ...]` | local runtime plugin state | 0; 1 partial-fail/journal; 2 bad approve |
| `demo` | `[--runtime ...]` | disposable evidence only | 0; 1 fail |

`--approve` is valid only with an explicit mutation mode (`apply`/`sync`), a saved plan artifact,
and the SHA-256 shown to the user. It never authorizes new targets, remote publish, git/marketplace
mutation, instruction-file edits, or deletion (§8.3).

## Closed consumer set (§8.3 — explicit mapping, not a discovery registry)

| Runtime | Consumers | Provider |
| --- | --- | --- |
| Claude Code | `foundry`, `oss`, `develop`, `research` | `codemap-py` |
| Codex | `codex-rig` | `codemap-py` |

Target names and source roots are cross-checked against both marketplace manifests and plugin
manifests before any mutation. Adding a consumer requires a plan revision to this table, not a
runtime-discovered extension.

## Managed-block marker format (source-owned consumer files)

The engine owns only marked blocks and generated adapter files listed in its versioned target map
(§9.3) — inside allowlisted, version-controlled consumer source files (e.g.
`plugins/cc_foundry/skills/_shared/codemap-context.md`,
`plugins/cc_oss/skills/_shared/codemap-gates.md`, a Codex-Rig adapter module). This supersedes the
retired installed-cache injection model (`bin/inject_codemap.py` / `bin/_injection_block.py`,
whose init-write workflow is retired from the integration skill in Phase 4; the modules themselves
are retained because migration/gate machinery still imports them, and their full removal is Phase 5
legacy-cleanup work) — the marker idiom below reuses that model's
proven sentinel + version-stamp pattern, but the target is always a checked-in source file, never
an installed plugin cache path.

Marker shape (HTML-comment sentinels bound the re-injectable region; content outside the sentinels
is consumer-owned and never touched):

```text
<!-- codemap-py:integration:begin v1 sha256=<64-hex block-body sha256> -->
...engine-owned managed content...
<!-- codemap-py:integration:end -->
```

- `v1` — block schema version (`BLOCK_SCHEMA_VERSION`), integer, bumped when the managed-block
  content shape changes (supersedes the retired cache-injection model's `BLOCK_VERSION`).
- `sha256=<64-hex>` — full SHA-256 of the exact managed body the engine last wrote; `apply`
  recomputes the on-disk body hash and compares it against this stamp (and its plan before-state
  hash) to detect drift/foreign edits before touching anything (§9.3 step 1: "validate ... current
  block version/hash, and clean overlap"). The full digest is self-authenticating — a body edited
  out of band no longer matches its own stamp.
- A file with sentinels present but a hash that doesn't match any version the engine generated is a
  **foreign/modified marker** — `apply` refuses it (§8.3: "refuse foreign/modified markers").
- A file with no sentinels present is a first-time wiring target, handled by `plan`'s ordered-ops
  list, not by `apply`'s replace-in-place path.
- One managed block per file per consumer contract; multiple codemap-py capabilities in the same
  consumer file (if ever needed) would require distinct sentinel names, not nested/overlapping
  regions — out of scope for `0.25.2`.

## Plan artifact shape

`plan` persists (§8.3 step 1):

- schema/protocol version (`codemap-py.integration.v1`);
- operation ID;
- exact targets (consumer + file path + marker hash expected);
- source/runtime before-state hashes;
- desired versions/refs/package hashes;
- exact argv arrays for every native CLI invocation `sync` would run;
- ordered operations (source-wire ops before runtime-install ops, per consumer);
- rollback identities (the previous verified state to restore per target);
- expected post-state;
- the plan's own SHA-256 (the value `--approve` binds to).

`plan` never mutates source or runtime state — it only writes this artifact. `--consumers <csv>`
narrows the target set to a subset of the closed consumer table above; an unknown consumer name is
a `2`-class syntax error, not a silently-ignored no-op.

## Approval binding

- Approval binds the plan's SHA-256, not the plan's logical content — any edit to the plan artifact
  invalidates the SHA-256 the user approved, so `apply`/`sync` must re-verify the artifact's hash
  against `--approve` before doing anything else.
- Immediately before **every** individual mutation (not just once at the start), the engine
  revalidates the target and its before-state; drift since planning invalidates the approval for
  that target and stops (§8.3).

## Apply (`apply --plan <artifact> --approve <sha256>`)

- Atomically updates current-version managed blocks in allowlisted consumer source files only.
- Refuses: foreign/modified markers, path escapes outside the target repo, symlinks, installed-
  cache roots (never writes into `~/.claude/plugins/cache/...` or equivalent), dirty git overlap on
  the target file, or an unverified product identity.
- Source writes retain before-images and use per-file atomic replacement (§9.3).
- Leaves changes unstaged and uncommitted; reports the exact native reinstall/update commands the
  user would run next (§9.3) — `apply` never runs those commands itself.
- Maintainer/source-checkout operation; an end user installing immutable releases normally uses
  `check`, `sync`, and `demo` — `sync` never rewrites consumer source (§8.3).

## Sync (`sync --source {local-candidate,release} --plan <artifact> --approve <sha256> [--runtime ...]`)

- Executes only the approved native plugin-manager argv recorded in the plan; verifies selected
  package hashes and active roots; journals ordered partial failure; never mutates source or global
  instructions.
- Two source modes, no implicit "latest":
  - `local-candidate` — build a deterministic package + disposable local marketplace from the
    verified source checkout, bind its hashes in the plan, install only those bytes. Development/CI
    only; never claims an unpushed Git marketplace contains local changes.
  - `release` — select an immutable Git ref + release-set manifest, verify marketplace and package
    hashes, install only that published identity.
- Refuses when: an applied source tree was not built into the selected local candidate; installed
  bytes don't match the selected candidate/release hash; a mutable/default-branch source is
  presented as rollback/release evidence.
- Coordinated `--runtime both` order: refresh/register the Codex marketplace, then
  `codex plugin add codemap-py@<marketplace>`, then `codex plugin add codex-rig@<marketplace>` —
  provider-then-consumer order is bound in the approved plan alongside the independently verified
  previous/absent rollback identity per product. Either standalone install order (provider-only,
  consumer-only) must still work outside coordinated sync (§8.5 symmetric optionality).
- Never invokes Codex Rig's global-instructions installer (`install_global_agents.py`) and never
  writes `${CODEX_HOME}/AGENTS.md` — that managed block stays exclusively owned by Codex Rig's own
  `sync` (`scripts/sync_codex.py`); a coordinated `codemap-py integrate sync` yields a base
  `codex-rig` plugin without that block (§8.3).
- Never calls `git push`, remote marketplace mutation, release publication, or direct installed-
  cache edits — "push" in this contract means only (1) update allowlisted source-owned consumer
  integration, and (2) install/reinstall those built plugin versions via native runtime CLIs (§8.3).

## Check (`check [--runtime {claude,codex,both}] [--json]`)

- Zero-write, always. Reports: installed/active versions, roots, protocol compatibility, Codex
  Rig-owned global-instruction status when publicly verifiable, fallback state, shared-index
  identity, runtime-log isolation.
- Codex Rig global-instructions status: only `absent`, `present`, or `authenticated` from bytes it
  can verify directly. `stale` is reportable only through a versioned, Codex-Rig-owned read-only
  status contract; otherwise staleness is `unavailable`, never guessed (§8.3, §8.4).
- Reports `split_index_roots` when the two runtime environments resolve different index paths —
  never copies, merges, or silently picks one (plan §4.4).
- An absent consumer or provider is a successful named state, not an error — `check`/`plan` reject
  unknown runtimes/consumers as a `2`-class syntax error, but a known, simply-not-installed consumer
  is reported as `absent`.

## Demo (`demo [--runtime ...]`)

- Runs `check` plus representative plain-vs-structural-context workflows; records the
  protocol/version/evidence used. Disposable evidence only, unless a separate approval is given for
  anything durable.

## State machine (journaled)

```text
planned → approved → applying:<target> → verified:<target> → complete
                                         ↘ rollback-started → rollback-succeeded → (done)
                                                             ↘ rollback-failed → recovery-required
```

- `planned` — `plan` has written the artifact; nothing approved yet.
- `approved` — `--approve <sha256>` has matched the plan's hash; mutation may begin.
- `applying:<target>` — one specific target (a consumer file or a runtime install step) is mid-
  mutation; the engine holds this state only for the duration of that one atomic operation.
- `verified:<target>` — post-state identity/hash check passed for that target.
- `complete` — every target in the plan reached `verified:<target>`.
- `rollback-started` / `rollback-succeeded` / `rollback-failed` — entered only when a later target
  fails after an earlier target already succeeded; rollback actions are exactly and only what the
  approved plan's rollback-identities section contains — no improvised recovery.
- `recovery-required` — terminal failure state when rollback itself cannot be verified; the report
  names exact successful/failed targets plus bounded manual recovery commands. This state is never
  auto-cleared — a human must resolve it.

First-target success followed by second-target failure stops immediately; the engine does not
continue attempting remaining targets (§8.3 step 5). Completion or rollback is claimed only after
post-state identity/hash verification — never on the optimistic assumption that a command
succeeded because it exited zero (§8.3 step 6).

## Journal and evidence

- The journal and before-images live in a task-specific integration report, exclude
  credentials/tokens, and are never written inside a plugin cache (§8.3).
- Cross-runtime mutation (`--runtime both`) is never described as atomic — each runtime's steps are
  individually journaled and individually verified.

## Symmetric optionality (§8.5 — binding on this contract's own behavior)

- `codemap-py`'s five non-integration skills and the `integration check`/`plan` inspection paths
  never import, locate, install, or require Codex Rig or a `cc_*` plugin.
- `integration check` may inspect declared consumers; absence is a successful named state unless
  the user explicitly requests a mutation targeting that consumer.
- Install/update order is unconstrained: provider-first, consumer-first, provider-only, and
  consumer-only are all valid; uninstalling or disabling either side never corrupts the other
  side's package state, project index, logs, configuration, or skill roster.
- Packaging metadata declares no hard dependency between `codemap-py` and Codex Rig or any `cc_*`
  plugin in either direction.

## Confidence

**Score**: 0.87 — moderate ⚠
orchestrator may re-run with the specific gap addressed
**Gaps**:
- The managed-block marker format (sentinel comment + `<schema>.<block-hash>` stamp) is this file's
  own design proposal, not a value copied from an already-implemented `0.25.2` source — the plan
  text (§9.3) specifies *behavioral* requirements ("marked blocks," "current block version/hash,"
  "clean overlap") but does not spell out a literal marker string. I derived the format by reusing
  the proven sentinel/version-stamp idiom from the retired `bin/_injection_block.py`
  (`BEGIN_SENTINEL`/`END_SENTINEL`/`BLOCK_VERSION`) and adapting it to hash-based drift detection
  since the target moved from installed-cache files to source-controlled ones. Slice A
  (`src/codemap_py/integration.py`, owned by Codex) is the actual implementation authority; if its
  marker format differs, this file needs a follow-up edit to match, not the other way around.
- `sync`'s exact `codex plugin add`/`marketplace upgrade` argv forms are stated per delivery-plan.md
  and plan §8.3 text (current `codex-cli 0.145.0` precedents); I did not independently re-probe the
  Codex CLI in this session — the plan itself flags these as "re-probed and hash-bound in the saved
  plan" at implementation time, which this contract inherits as a forward reference, not fresh
  verification.

**Refinements**: 0 passes.
