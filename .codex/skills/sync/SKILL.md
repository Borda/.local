---
name: sync
description: Minimal codex-native sync loop. Use to keep project and home Codex configs aligned and report drift.
---

# Sync

Run a dry-run-first project/home Codex configuration sync loop. This skill reports drift by default; writes outside the repository only after explicit approval.

## Input Schema

```json
{
  "mode": "check|apply",
  "source": "project|home",
  "targets": [
    "skills",
    "agents",
    "config",
    "calibration",
    "docs",
    "shared"
  ],
  "done_when": "drift is reported and approved sync actions are applied safely"
}
```

## Workflow

### 01: Create run directory

```bash
TS=$(date -u +%Y-%m-%dT%H-%M-%SZ)
OUT_DIR=".reports/codex/sync/$TS"
mkdir -p "$OUT_DIR/backup"
```

### 02: Compare project and home targets

```bash
find .codex -maxdepth 4 -type f | sort >"$OUT_DIR/project-files.txt"
find "$HOME/.codex" -maxdepth 4 -type f | sort >"$OUT_DIR/home-files.txt" 2>/dev/null || true
```

Write `$OUT_DIR/drift.md` with:

- identical files
- project-only files
- home-only files
- changed files with hashes
- recommended direction per file

### 03: Enforce dry-run default

`mode=check` never writes outside `.reports/codex/sync/<timestamp>/`.

### 04: For `mode=apply`, require explicit approval and allowlist

Allowed targets:

- `.codex/config.toml`
- `.codex/AGENTS.md`
- `.codex/README.md`
- `.codex/skills/**/SKILL.md`
- `.codex/skills/_shared/**`
- `.codex/agents/*.toml`
- `.codex/calibration/**`

Safety rules:

- back up each overwritten home file to `$OUT_DIR/backup/`
- never delete home-only files automatically
- never overwrite when both sides changed and no direction is explicit
- never sync secrets or local credentials

### 05: Apply approved actions only

Record every copy in `$OUT_DIR/actions.md` with source hash and destination hash.

### 06: Validate after sync

```bash
diff -qr .codex "$HOME/.codex" >"$OUT_DIR/post-sync-diff.txt" 2>&1 || true
git diff --check >"$OUT_DIR/review.txt" 2>&1 || true
```

### 07: Decide gate result and write `.reports/codex/sync/<timestamp>/result.json`

## Fail-Fast Rules

1. Home `.codex` missing in `apply` mode => fail unless user requested bootstrap.
2. Apply requested without explicit direction and allowlist => fail.
3. Attempted deletion of home-only files => fail.
4. Backup missing before overwrite => fail.
5. Secrets detected in sync target => fail.
6. Result artifact missing => fail.

## Quality Gates

Required checks:

- `review`: drift matrix, action log, backup log, and `git diff --check`.

Conditional checks:

- `tests`: run calibration when synced files affect skills, agents, or calibration behavior.

## Calibration Hooks

Update calibration when sync policy changes:

- behavioral cases: unsafe home overwrite, missing backup, home-only deletion, stale project/home drift
- benchmark patterns: `sync`

## Output Contract

Use shared gate schema from `../_shared/quality-gates.md`.

Minimum artifact payload:

```json
{
  "status": "pass|fail",
  "checks_run": [
    "review"
  ],
  "checks_failed": [],
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "confidence": 0.0,
  "artifact_path": ".reports/codex/sync/<timestamp>/result.json"
}
```
