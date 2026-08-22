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
- <concise final check that materially validates the committed change, with its result>

Residual limits:
- <remaining risk, warning, deferred work, or "None known">

---

Co-authored-by: Codex <codex@openai.com>
```

Rules:

- Creating a new commit does not authorize rewriting an existing commit. Never run `git commit --amend`, `git rebase`, `git reset`, squash, fixup, or an equivalent history rewrite unless the user explicitly requests that exact history operation. Never infer rewrite permission from a commit, cleanup, or commit-diet request.
- First line: Conventional Commit.
- `<type>` lowercase: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, or `perf`.
- Prefer specific lowercase `<scope>`: `api`, `cli`, `config`, `tests`, `docs`, `ci`, `deps`, `packaging`, `models`, `data`, or `utils`.
- `<title>` imperative, concise, under 72 characters when practical.
- Body: always include the four exact headings `Changes:`, `Impact:`, `Verification:`, and `Residual limits:` in that order.
- `Changes:` must list every meaningful behavioral, interface, workflow, policy, test, documentation, packaging, or operational change included in the commit. Name the affected surface and describe the resulting behavior; a filename-only inventory is insufficient.
- `Impact:` must state the concrete user, developer, runtime, compatibility, or maintenance effect for each change or tightly related group of changes. Generic impact claims such as "improves UX" or "makes things better" are insufficient.
- `Verification:` includes only final checks that materially validate the committed surfaces or their acceptance contract, each with a concrete result. Consolidate closely related checks and report a required broad gate once using its final outcome. Do not list exploratory probes, failure-first reproductions, setup or environment diagnostics, repeated reruns, superseded failures, or unrelated repository-wide gates. State an exact not-run reason only for a material change-specific acceptance gate; never imply that an unexecuted check passed.
- `Residual limits:` must list warnings, deferred work, and remaining uncertainty, or contain exactly `- None known` when no material limit remains.
- Extensive means complete and auditable, not padded: omit pure lint/format churn, generated cache, typo-only edits, and verification chronology unless they are the whole change; combine tightly related details without hiding distinct effects.
- As an application of the general approval contract, keep a multiline local commit message complete but outside the approval command: create a unique private temporary directory outside the worktree under the platform temp root, require directory mode 0700 where supported, reject symlink path components, atomically create and write the secret-free message with LF bytes and mode 0600 where supported, read it back, show the user its exact contents and absolute path, then run `rtk git commit --cleanup=verbatim -F <absolute-message-file>`. Never shorten or omit required detail to reduce the approval prompt.
- Treat the commit as a one-time state-changing command and omit `prefix_rule`. Its short plain-English reason states only that the reviewed message will create one commit from the staged index, run local hooks, and advance local `HEAD` without network, remote mutation, history rewrite, or extra staging; it must not repeat the command, flags, message-file path, message body, or full approval brief. After success, compare the committed UTF-8 message with the reviewed file after normalizing only one terminal LF on both sides, then remove the verified file and directory. On denial, failure, or mismatch, do not retry automatically or change the index; retain the file for recovery and report its path and cleanup state.
- Keep `---` before trailer. End with exactly:

`Co-authored-by: Codex <codex@openai.com>`

## Required User-Facing Commit Summary

After creating or describing commits, report each commit separately with its hash and title, then concise bullets grouped by:

- **Behavior**: what changed and the user-visible or methodological impact.
- **Affected surfaces**: the principal components, workflows, or packages changed; do not dump an unexplained filename list.
- **Verification**: concise final change-specific tests, lint, build, package, or manifest checks and their results; omit exploratory, repeated, superseded, and unrelated checks.
- **Residual limits**: skipped gates, warnings, deferred work, or remaining uncertainty; state `none known` when verified and no material limit remains.

For multiple commits, also state why the boundary exists. The user-facing summary may condense the commit body, but it must preserve every material behavior, impact, verification result, and residual limit. Never claim a check passed without concrete execution evidence.
