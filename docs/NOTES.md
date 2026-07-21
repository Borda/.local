# Simple documentation

MkDocs source for the [Borda's AI-Rig](https://borda.github.io/.local/) documentation site.

Product pages (`cc_foundry.md`, `cc_oss.md`, `codex-rig.md`, etc.) are small snippet wrappers that include `plugins/*/README.md`. Edit the source READMEs for product content and the wrappers only for page metadata.

## Local build

```bash
python -m pip install -r docs/requirements.txt
python -m mkdocs build          # output → site/
```

## Serve with live-reload

```bash
python -m mkdocs serve          # http://127.0.0.1:8000
```

Changes to `plugins/*/README.md`, `docs/index.md`, or `mkdocs.yml` reload automatically.

## CI

Docs deploy to GitHub Pages on every push to `main` that touches `plugins/*/README.md`, `docs/**`, or `mkdocs.yml`. Workflow: `.github/workflows/docs.yml`.
