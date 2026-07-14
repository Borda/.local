# Python/PyPI Release Checklist

Release notes format + CHANGELOG generation: use `/oss:release` skill. CI publish YAML: see `oss:cicd-steward` agent `<trusted_publishing>` section.

## Pre-release

```markdown
[ ] All tests pass on CI (including integration, not just unit)
[ ] CHANGELOG has entry for this version with date
[ ] Version bumped in pyproject.toml (and __init__.py if duplicated)
[ ] Deprecations for this version cycle are removed (if major)
[ ] Docs built locally without errors (mkdocs build / sphinx-build)
[ ] No dev dependencies leaked into main dependencies
```

## Setting Up Trusted Publishing (one-time, per project)

Trusted Publishing uses GitHub OpenID Connect (OIDC) — no `API_TOKEN` or `TWINE_PASSWORD` secret needed.

1. **Create PyPI environment in GitHub** Settings → Environments → New environment → name it `pypi`. Add deployment protection rule (require reviewer) for safety.

2. **Register Trusted Publisher on PyPI** PyPI project → Manage → Publishing → Add new pending publisher:

   - Owner: `<your-github-org-or-username>`
   - Repository: `<repo-name>`
   - Workflow filename: `publish.yml`
   - Environment: `pypi`

3. **Verify `pyproject.toml` metadata complete** PyPI requires minimum: `[project]` with `name`, `version`, `description`, `requires-python`, `[project.urls]` with `Homepage`.

4. **Create GitHub release** Tag commit (`git tag vX.Y.Z && git push --tags`), create GitHub release from tag. `publish.yml` triggers on `release: published`, handles rest.

> Confirm with user before pushing tags (CLAUDE.md push safety rule)

## Post-release

```markdown
[ ] Published to PyPI (twine upload / trusted publisher workflow completed)
[ ] Verify PyPI page renders correctly (README, classifiers)
[ ] Test install: pip install <package>==<version> in fresh env
[ ] Close milestone on GitHub
[ ] Announce in relevant channels if major/minor
[ ] Update docs site if self-hosted
```

## GitHub Security Features Checklist

```markdown
[ ] Dependabot security alerts enabled (Settings → Security → Dependabot alerts)
[ ] Secret scanning enabled (Settings → Security → Secret scanning)
[ ] Branch protection: require PR review + CI pass for main
[ ] CODEOWNERS file for critical paths (src/, pyproject.toml)
[ ] Security policy: SECURITY.md with responsible disclosure instructions
```
