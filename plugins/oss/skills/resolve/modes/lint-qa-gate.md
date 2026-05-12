<!-- oss:resolve Step 9 — executed via: Read $_OSS_RESOLVE/modes/lint-qa-gate.md; execute -->
<!-- Input: $RUN_DIR, $BASE_REF_MERGE, current working tree after Step 8 -->
<!-- Output: lint fixes committed (if any), or BLOCKING_ISSUES found -->

## Step 9: Lint and QA gate

```bash
RUN_DIR=".reports/resolve/$(date -u +%Y-%m-%dT%H-%M-%SZ)"  # IMPORTANT: expand $RUN_DIR to its literal value in each prompt string below — agents receive text, not shell context; un-expanded $RUN_DIR means literal string in instructions
mkdir -p "$RUN_DIR" # timeout: 5000
# Compute BASE_REF merge base for accurate diff range in agent prompts
BASE_REF_MERGE=$(git merge-base HEAD "origin/$BASE_REF" 2>/dev/null || echo "origin/$BASE_REF")
```

Spawn both in parallel:

```text
Agent(subagent_type="foundry:linting-expert", maxTurns=15, prompt="Review all files changed in the current branch since $BASE_REF_MERGE (expand to literal SHA before spawning). List every lint/type violation. Apply inline fixes for any that are auto-fixable. Write your full findings to $RUN_DIR/linting-expert-step9.md using the Write tool, then return ONLY a compact JSON envelope: {fixed: N, remaining: N, files: [...]}.")

Agent(subagent_type="foundry:qa-specialist", maxTurns=15, prompt="Review all files changed in the current branch since $BASE_REF_MERGE (expand to literal SHA before spawning) for correctness, edge cases, and regressions. Flag any blocking issues (bugs, broken contracts, missing test coverage for the changed logic). Write your full findings to $RUN_DIR/qa-specialist-step9.md using the Write tool, then return ONLY a compact JSON envelope: {blocking: N, warnings: N, issues: [...]}.")
```

> **Health monitoring**: synchronous. No response ~15 min → surface partial results from `$RUN_DIR` ⏱.

- `foundry:linting-expert` made file changes → commit:

```bash
git add $(git diff HEAD --name-only)                          # timeout: 3000
git commit -m "$(cat <<'EOF'
lint: auto-fix violations after resolve cycle

---
Co-authored-by: Claude Code <noreply@anthropic.com>
EOF
)"  # timeout: 3000
```

- Blocking issues from `foundry:qa-specialist` → fix (via Codex or inline edit), re-run qa-specialist once to confirm; issues remaining after one fix pass → **stop workflow — do not proceed to Step 10 (push)**; surface all remaining blocking issues in report; print: `⛔ QA gate blocked push — review findings above, fix errors, then re-run /resolve or push manually after fixing.`
- Warnings (non-blocking) → record in report; do not block push

Revoke commit authorization:

```bash
rm -f "$SENTINEL"  # timeout: 3000
```
