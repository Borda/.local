---
description: Public GitHub is read-only — forbids all writes (issues, PRs, releases, gists, repos) via gh CLI or curl mutations
paths:
  - '**/*'
---

## Public GitHub — Read-Only

Claude + all agents (subagents, skills, teammates) **read-only** on public GitHub.
Hard constraint — not suggestion.

### Permitted (read)

- `gh issue list`, `gh issue view`
- `gh pr list`, `gh pr view`, `gh pr diff`, `gh pr checks`
- `gh repo view`, `gh release list`, `gh release view`
- `gh run list`, `gh run view`
- `gh api graphql` (read queries only)
- `gh api search/*`
- `WebFetch` on `github.com`, `raw.githubusercontent.com`

### Forbidden (write) — enforced via deny list

Any write command on any public/external GitHub repo **permanently forbidden**, including:

- `gh issue create`, `gh issue comment`, `gh issue edit`, `gh issue close`, `gh issue delete`
- `gh pr create`, `gh pr comment`, `gh pr edit`, `gh pr merge`, `gh pr close`, `gh pr review`
- `gh release create`, `gh release edit`, `gh release delete`, `gh release upload`
- `gh repo fork`, `gh repo create`
- `gh gist create`, `gh gist edit`, `gh gist delete`
- `gh api <any-path>` with `--method POST/PATCH/PUT/DELETE` — all API mutations regardless of path
- `gh api graphql` with mutation operations (createIssue, createPullRequest, addComment, etc.) — GraphQL mutations are write ops, forbidden
- All curl write methods denied globally; curl read-only (GET only)
  - `curl -X POST`, `curl --request POST`, `curl -X PATCH`, `curl --request PATCH`, `curl -X PUT`, `curl --request PUT`

### When user says "write/file/post/submit X to GitHub"

Interpret as: **draft X for user review**.
- Show draft in terminal
- Call the `AskUserQuestion` tool before any external GitHub action — the tool call must appear in the response as an actual tool invocation. Non-compliant forms that do NOT satisfy this requirement: prose questions ("Should I post this?"), bracketed simulations ("[AskUserQuestion would be invoked here]"), backtick inline text (`` `AskUserQuestion(questions=[...])` `` in prose), compliance notes ("In a live session I would call AskUserQuestion here"), and intent narration ("I would call AskUserQuestion"). Only executing the tool satisfies this requirement.
- Never delegate to a subagent assuming it will invoke AskUserQuestion — the orchestrator must invoke AskUserQuestion itself in the same response turn as an actual tool call (same requirement as above), before dispatching any agent with GitHub write intent.
