---
description: Public GitHub is read-only — forbids all writes (issues, PRs, releases, gists, repos) via gh CLI or curl mutations
paths:
  - '**/*'
---

## Public GitHub — Read-Only (stub)

Claude + all agents (subagents, skills, teammates) **read-only** on public GitHub.
Hard constraint — not suggestion.

Any write/mutate command on any public/external GitHub repo is **permanently forbidden** — issue/PR/release/gist create-comment-edit-close-merge-delete, `gh repo fork`/`gh repo create`, `gh api ... --method POST/PATCH/PUT/DELETE`, `gh api graphql` mutations, and all curl write verbs (`-X POST/PATCH/PUT`). Read ops (`gh *list`, `gh *view`, `gh pr diff/checks`, `gh api graphql` reads, `WebFetch` on github.com) stay permitted.

> Full protocol in `_full/public-github.md` (exhaustive permitted/forbidden command enumerations). Read when a command's read/write status is unclear:
>
> ```bash
> RULE_FULL="$(ls -td ~/.claude/plugins/cache/borda-ai-rig/foundry/*/rules/_full/public-github.md 2>/dev/null | head -1)"; [ -z "$RULE_FULL" ] && RULE_FULL="plugins/cc_foundry/rules/_full/public-github.md"  # timeout: 5000
> ```

### When user says "write/file/post/submit X to GitHub"

Interpret as: **draft X for user review**.
- Show draft in terminal
- Call `AskUserQuestion` tool before any external GitHub action — tool call must appear in response as actual tool invocation. Non-compliant forms that do NOT satisfy this: prose questions ("Should I post this?"), bracketed simulations ("[AskUserQuestion would be invoked here]"), backtick inline text (`` `AskUserQuestion(questions=[...])` `` in prose), compliance notes ("In a live session I would call AskUserQuestion here"), intent narration ("I would call AskUserQuestion"). Only executing tool satisfies this.
- Never delegate to subagent assuming it will invoke AskUserQuestion — orchestrator must invoke AskUserQuestion itself in same response turn as actual tool call (same requirement as above), before dispatching any agent with GitHub write intent.
