# Commit Response Template

Use when user asks to commit or for a commit summary.

## Required Commit Message Shape

Always use:

```text
<type>(<scope>): <title>

Changes:
- <what changed, including the affected surface and resulting behavior>
- <what changed, including the affected surface and resulting behavior>

Impact:
- <concrete user, developer, runtime, compatibility, or maintenance effect>
- <concrete user, developer, runtime, compatibility, or maintenance effect>

Verification:
- <exact check and result, or explicit not-run reason>

Residual limits:
- <remaining risk, warning, deferred work, or "None known">

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
- Body: always include the four exact headings `Changes:`, `Impact:`, `Verification:`, and `Residual limits:` in that order.
- `Changes:` must list every meaningful behavioral, interface, workflow, policy, test, documentation, packaging, or operational change included in the commit. Name the affected surface and describe the resulting behavior; a filename-only inventory is insufficient.
- `Impact:` must state the concrete user, developer, runtime, compatibility, or maintenance effect for each change or tightly related group of changes. Generic impact claims such as "improves UX" or "makes things better" are insufficient.
- `Verification:` must list every relevant executed check with its concrete result. State an exact not-run reason for any material omitted gate; never imply that an unexecuted check passed.
- `Residual limits:` must list warnings, deferred work, and remaining uncertainty, or contain exactly `- None known` when no material limit remains.
- Extensive means complete and auditable, not padded: omit pure lint/format churn, generated cache, and typo-only edits unless they are the whole change; combine tightly related details without hiding distinct effects.
- Keep `---` before trailer. End with exactly:

`Co-authored-by: Codex <codex@openai.com>`

## Required User-Facing Commit Summary

After creating or describing commits, report each commit separately with its hash and title, then concise bullets grouped by:

- **Behavior**: what changed and the user-visible or methodological impact.
- **Affected surfaces**: the principal components, workflows, or packages changed; do not dump an unexplained filename list.
- **Verification**: exact tests, lint, build, package, or manifest checks run and their results.
- **Residual limits**: skipped gates, warnings, deferred work, or remaining uncertainty; state `none known` when verified and no material limit remains.

For multiple commits, also state why the boundary exists. The user-facing summary may condense the commit body, but it must preserve every material behavior, impact, verification result, and residual limit. Never claim a check passed without concrete execution evidence.
