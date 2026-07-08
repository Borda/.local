---
description: Git commit conventions and safety rules — applies globally
paths:
  - '**'
---

## Commit & Push — Hard Constraints (stub)

> Full protocol in `_full/git-commit.md` (diff-gathering, large-diff subagent summarization, tier tables, grouped-commit flow, sentinel details). **MANDATORY before drafting any commit message or pushing**: resolve + Read it:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/git-commit.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/foundry/rules/_full/git-commit.md"  # timeout: 5000
> ```

Always-on constraints (apply even without reading full rule):

- Subject `type(scope): detail` ≤50 chars; classify ALL changes from `git diff HEAD` + `git diff --stat HEAD` into tiers — subject names highest-tier change; **never draft from session memory**
- No line wrapping in body; no GitHub auto-links (`#N`, `@name`); no non-VCS paths (`/tmp/`, `~/.claude/`)
- Co-author trailers on EVERY commit, after `---` separator: `Co-authored-by: claude[bot] <209825114+claude[bot]@users.noreply.github.com>`; add `Co-authored-by: OpenAI Codex <codex@openai.com>` when Codex shaped the outcome
- **Never commit autonomously** — valid signals only: in-message instruction, documented skill workflow step, or same-turn AskUserQuestion confirmation; default branch ALWAYS requires AskUserQuestion; `commit-guard.js` sentinels enforce (never bypass)
- Detect default branch dynamically — never hardcode `main`/`master`
- Never `git add -A` / `git add .` (stage by name); never `--no-verify`; never `--no-gpg-sign` unless user asks
- Push needs its own signal ("commit this" ≠ "push this"); force-push to default branch forbidden even if asked
- History safety: prefer `git revert` over `reset --hard`; prefer merge commits over rebase
