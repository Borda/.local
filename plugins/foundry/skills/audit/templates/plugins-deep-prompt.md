**Deep plugin audit — find ALL gaps, no scope constraint.**

Reviewing plugin files: skill SKILL.md, agent .md, shared .md, rule .md, plugin.json manifests. Apply all checks below AND any other issues found — scope constraint intentionally absent. Bash correctness checks: apply only when file has bash code blocks; skip silently otherwise.

**Standard structural checks:**

- **Purpose and logical coherence**: role clear? Scope right — not too broad, not too narrow? New user know when to reach for it vs similar?
- **Structural completeness**: required sections present, tags balanced, step numbering sequential
- **Cross-reference validity**: every agent/skill name mentioned must exist on disk. Cross-reference against Step 2 inventory. Name absent = **broken cross-reference** (critical). No conditional language — by Step 3, inventory known.
- **Verbosity and duplication**: bloated steps, repeated instructions, copy-paste between files
- **Content freshness**: outdated model names, stale version pins, deprecated API references
- **Hardcoded user paths**: any `/Users/` or `/home/<name>/` absolute path — must be `.claude/`, `~/`, or `git rev-parse --show-toplevel`. Flag every occurrence at medium severity regardless of context (negative examples not exempt).
- **Infinite loops**: follow-up chains creating cycles (flag, don't auto-fix)
- **Example value vs. token cost**: inline examples restating surrounding prose, trivial cases, or better served by project-local file

**Bash operational correctness** (files with bash code blocks only; skip otherwise):

- **Pipe exit code capture**: any `cmd 2>&1 | tail -N` or `cmd 2>&1 | head -N` followed by `$?`, `GATE_EXIT=$?`, or `EXIT=$?` — `$?` captures tail/head exit (always 0), not actual command. Must use `${PIPESTATUS[0]}` or `set -o pipefail`. Severity: **critical**.
- **SKIP variable guard missing**: `SKIP_X=1` set in detection block but runner commands lack explicit `[ "${SKIP_X:-0}" -ne 1 ] &&` guard. Comments without code guards are cosmetic only. Severity: **critical**.
- **Missing exit on genuine failure**: detecting "all retries failed" / "GENUINE FAILURE" but execution continues instead of `exit 1`. Severity: **critical**.
- **Agent filename convention mismatch**: spawn prompt instructs agents to write to plugin-prefixed filename (`foundry:sw-engineer.md`) but consolidator reads bare-name pattern (`sw-engineer.md`) — filenames never match, all findings silently dropped. Severity: **high**.
- **TEST_CMD with pytest-specific flags**: `$TEST_CMD` (may resolve to `tox` or `make test`) used with `--tb`, `--co`, `::node_id`, `--cov=`, `--doctest-modules` without separate `PYTEST_CMD` derivation — tox/make reject these flags. Severity: **high**.
- **Optional dependency invoked without availability check**: calling `/oss:review`, `/codex:*`, or any optional plugin without first checking it installed. Severity: **high**.
- **TARGET / key variable unset in else branch**: conditional variable assignment where `else` branch omits assignment, leaving variable empty downstream. Severity: **high**.
- **Destructive op without confirmation note**: `git checkout HEAD -- <file>`, `git reset --hard`, or any irreversible file op presented as "just run this" with no "confirm with user before running" note. Severity: **high**.
- **pytest-cov checked with wrong python**: `python -c "import pytest_cov"` bypasses project virtualenv; must use `$RUNNER python -c "import pytest_cov"`. Severity: **medium**.

**Inter-skill handoff and spawn quality:**

- **--plan receiver missing**: skill documents `--plan <path>` handoff from `/develop:plan` but has no Step 1 handler that reads file and skips codebase exploration. Severity: **high**.
- **Spawn context completeness**: agent spawned with no target files, no expected output format, no relevant context — agent cannot do useful work. Severity: **high** (silent failures look like success).
- **File-handoff protocol**: when 2+ parallel agents write findings, verify each writes full output to file AND returns only compact JSON envelope. Missing either half breaks aggregation. Severity: **high**.

**Agent files within plugins**: for `agents/*.md` files, apply all structural checks (purpose, cross-references, NOT-for coverage, model tier, verbosity, paths, loops). Bash checks don't apply to agent files.

**Manifest files** (`plugin.json`): check required fields (`name`, `version`, `description`, `author`), valid semver, and `description` accurately reflects current capabilities.

**No scope constraint**: report every issue at any severity. Findings outside above categories valid — use judgment. Goal: maximum recall, not precision.
