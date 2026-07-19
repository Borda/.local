---
name: manage
description: Minimal codex-native management loop. Use to create, update, or remove Codex agents/skills/config entries with guardrails.
---

# Manage

Guarded Codex config management for agents, skills, rules, and local config.

The installed plugin tree is immutable input. Resolve requested targets against the consuming project or an explicit
user-approved external scope; never edit this skill's plugin cache, packaged role cards, shared helpers, runtime
assets, or package manifests. Codex Rig agent links are managed only by the bundled `agent-shims` workflow, not by
this general-purpose skill.

## Input Schema

```json
{
  "intent": "create|update|delete|rename|add-permission|remove-permission",
  "target": "required agent, skill, rule, config key, or path",
  "change": "required description or spec path",
  "done_when": "target and all references are updated or explicitly left unchanged"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/manage/$TS"
mkdir -p "$OUT_DIR"
```

In each later Bash block, replace `<run-directory-created-in-step-01>` with the exact path created in step 01.

### 02: Parse intent and target

Intents:

- `create`: scaffold a new skill/agent/rule/config entry.
- `update`: edit an existing target.
- `rename`: move target and update references.
- `delete`: remove target only after dependency scan.
- `add-permission` / `remove-permission`: modify permission policy with rationale.

Unknown intent => fail before edit.

### 03: Resolve owned files and blast radius

```bash
OUT_DIR="<run-directory-created-in-step-01>"
find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/inventory.txt"
rg -n "$TARGET" .codex AGENTS.md >"$OUT_DIR/references.txt" 2>/dev/null || true
```

Write `$OUT_DIR/ownership.md`: exact edited and intentionally untouched files.

Resolve the current skill path and reject any target whose canonical path is inside the same installed plugin root.
Reject generated `codex-rig-*.toml` targets here even when they are outside the cache; report the dedicated lifecycle
workflow as the only permitted owner.

### 04: Run safety gates before editing

Deletion safety required for `delete` and `rename`.

- Delete/rename: no unresolved references or explicit migration plan.
- Permission changes: reason, use case, risk note.
- Public behavior change: consider docs/routing/calibration.
- Versioned calibration fixtures are committed-history markers: compare current value to `git show HEAD:<path>`; while uncommitted, advance at most one step from last committed value.
- Home sync out of scope unless explicitly requested.

### 05: Apply the smallest reversible edit

Keep generated structure in the consuming project's `.codex/` unless the user explicitly approves another root.
Never infer that the source repository is present from the installed cache layout.

### 06: Propagate references

For behavior changes, update relevant descriptions, mappings, routing text, calibration notes in same patch. List intentionally stale references in `$OUT_DIR/unresolved-references.md`.

For broad changes with separable config, docs, calibration, or verification workstreams, route through
`delegation-lead` and shared specialist orchestration. Use the lowest-cost capable canonical role per bounded
workstream. Accept delegated change only after the handover gate proves ownership, objective evidence, applicable
checks, visible unresolved limits, and parent-owned final acceptance.

### 07: Run shared quality gates

Inspect `run-gates.sh --help`. Supply real affected-surface commands and explicit reasons for every inapplicable gate; never use `true` as skip reason. Review includes clean diff check.

### 08: Write mandatory result artifact

Manage artifacts include `ownership.md`; follow `../../shared/helper-cli-contract.md`. Write with `MANAGE_METADATA`, validate as `manage`, promote only validated candidate.

## Fail-Fast Rules

1. Missing intent or target => fail.
2. Delete/rename with unresolved references => fail.
3. Permission/config change without rationale => fail.
4. Behavior change without routing/docs/calibration decision => fail.
5. Result artifact missing => fail.
6. Target resolves inside the installed plugin root => fail without editing.
7. Target is a generated `codex-rig-*.toml` role link => fail and route to the dedicated lifecycle workflow.

## Quality Gates

Required:

- `review`: inventory diff, reference scan, `git diff --check`.
- `artifact`: `ownership.md`, gate logs, result JSON pass shared validator.

Conditional:

- `lint`/`format`: when generated Python, TOML, shell, or Markdown formatters available.
- `tests`: calibration or smoke checks for changed skills/agents when behavior changes.

## Calibration Hooks

Behavior-changing management edits update or explicitly review:

- `.codex/config.toml`
- `.codex/calibration/benchmarks.json`
- `.codex/calibration/behavioral-cases.json`
- `.codex/skills/_shared/native-skill-contract.md`

For versioned calibration artifact changes, calculate version from last commit, not dirty worktree. If `HEAD` has `1.3`, all next-commit uncommitted edits stay `1.3` or `1.4`: one version step only; do not bump to `1.5`, `1.6`, etc. before a commit.

Commit-output management also keeps `.codex/skills/_shared/commit-response-template.md` aligned with required message shape:

```text
<type>(<scope>): <title>

Co-authored-by: Codex <codex@openai.com>
```

## Output Contract

Use shared gate schema from `../../shared/quality-gates.md`.

Minimum artifact payload template: `result-template.json`.
