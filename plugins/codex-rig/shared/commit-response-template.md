# Commit Response Template

Use when user asks to commit or for a commit summary.

## Required Commit Message Shape

Always use:

```text
<type>(<scope>): <title>

- <notable change with description and impact>
- <notable change with description and impact>

---

Co-authored-by: Codex <codex@openai.com>
```

Rules:

- Creating a new commit does not authorize rewriting an existing commit. Never run `git commit --amend`,
  `git rebase`, `git reset`, squash, fixup, or an equivalent history rewrite unless the user explicitly requests
  that exact history operation. Never infer rewrite permission from a commit, cleanup, or commit-diet request.
- First line: Conventional Commit.
- `<type>` lowercase: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, or `perf`.
- Prefer specific lowercase `<scope>`: `api`, `cli`, `config`, `tests`, `docs`, `ci`, `deps`, `packaging`, `models`, `data`, or `utils`.
- `<title>` imperative, concise, under 72 characters when practical.
- Body: notable-change bullets only; omit pure lint/format churn, generated cache, and typo-only edits unless they are whole change.
- Keep `---` before trailer. End with exactly:

`Co-authored-by: Codex <codex@openai.com>`

## Required User-Facing Commit Summary

After creating or describing commits, report each commit separately with its hash and title, then concise bullets grouped by:

- **Behavior**: what changed and the user-visible or methodological impact.
- **Affected surfaces**: the principal components, workflows, or packages changed; do not dump an unexplained filename list.
- **Verification**: exact tests, lint, build, package, or manifest checks run and their results.
- **Residual limits**: skipped gates, warnings, deferred work, or remaining uncertainty; state `none known` when verified and no material limit remains.

For multiple commits, also state why the boundary exists. Keep the Git commit message concise; the user-facing summary carries the fuller evidence and impact record. Never claim a check passed without concrete execution evidence.
