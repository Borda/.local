# Commit Response Template

Use this output format when the user asks to commit or asks for a commit summary.

## Required Commit Message Shape

Always compose the commit message in this shape:

```text
<type>(<scope>): <title>

- <notable change with description and impact>
- <notable change with description and impact>

---

Co-authored-by: Codex <codex@openai.com>
```

Rules:

- Use Conventional Commit style for the first line.
- Keep `<type>` lowercase, such as `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, or `perf`.
- Use a specific lowercase `<scope>` when possible, such as `api`, `cli`, `config`, `tests`, `docs`, `ci`, `deps`, `packaging`, `models`, `data`, or `utils`.
- Keep `<title>` imperative, concise, and under 72 characters when practical.
- The body must be a bullet list of notable changes only.
- Ignore pure linting, formatting-only churn, generated cache files, and typo-only edits unless they are the whole change.
- Keep the `---` separator before the co-author trailer.
- End with exactly this Git trailer:

`Co-authored-by: Codex <codex@openai.com>`
