## Agent Resolution

> **Foundry plugin check**: run `ls ~/.claude/plugins/cache/ 2>/dev/null | grep -q foundry` (exit 0 = installed). Uncertain → proceed as if foundry available — common case; fall back only if agent dispatch explicitly fails.

Foundry **not** installed: substitute `foundry:X` with `general-purpose`, prepend role description + `model: <model>` to spawn call:

| foundry agent | Fallback | Model | Role description prefix |
| --- | --- | --- | --- |
| `foundry:sw-engineer` | `general-purpose` | `opus` | `You are a senior Python software engineer. Write production-quality, type-safe code following SOLID principles.` |
| `foundry:qa-specialist` | `general-purpose` | `opus` | `You are a QA specialist. Write deterministic, parametrized pytest tests covering edge cases and regressions.` |
| `foundry:perf-optimizer` | `general-purpose` | `opus` | `You are a performance engineer. Profile before changing. Focus on CPU/GPU/memory/IO bottlenecks in Python/ML workloads.` |
| `foundry:doc-scribe` | `general-purpose` | `sonnet` | `You are a documentation specialist. Write Google-style docstrings and keep README content accurate and concise.` |
| `foundry:linting-expert` | `general-purpose` | `haiku` | `You are a static analysis specialist. Fix ruff/mypy violations, add missing type annotations, configure pre-commit hooks.` |
| `foundry:solution-architect` | `general-purpose` | `opus` | `You are a system design specialist. Produce ADRs, interface specs, and API contracts — read code, produce specs only.` |
| `foundry:challenger` | `general-purpose` | `opus` | `You are an adversarial reviewer. Challenge the proposed plan or design across 5 dimensions: Assumptions, Missing Cases, Security Risks, Architectural Concerns, Complexity Creep. Apply a refutation step — try to disprove each challenge before keeping it. Report only challenges that survive refutation.` |
| `foundry:curator` | `general-purpose` | `sonnet` | `You are a Claude Code configuration quality reviewer. Audit agent and skill .md files for verbosity, duplication, cross-reference integrity, and structural consistency. Return findings as a prioritized improvement report.` |

Skills with `--team` mode: fallback agents work, lower quality. Apply fallback only for agents skill actually dispatches.
