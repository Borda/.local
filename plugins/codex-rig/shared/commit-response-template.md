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

- First line: Conventional Commit.
- `<type>` lowercase: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, or `perf`.
- Prefer specific lowercase `<scope>`: `api`, `cli`, `config`, `tests`, `docs`, `ci`, `deps`, `packaging`, `models`, `data`, or `utils`.
- `<title>` imperative, concise, under 72 characters when practical.
- Body: notable-change bullets only; omit pure lint/format churn, generated cache, and typo-only edits unless they are whole change.
- Keep `---` before trailer. End with exactly:

`Co-authored-by: Codex <codex@openai.com>`
