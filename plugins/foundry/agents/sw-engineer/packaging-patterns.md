<!-- file: packaging-patterns.md — consumers: agents/sw-engineer.md (<oss_patterns> trigger) -->

## src Layout (mandatory for libraries)

```text
mypackage/
├── src/
│   └── mypackage/
│       ├── __init__.py   # export public API + __all__
│       ├── _internal.py  # private, underscore-prefixed
│       └── module.py
├── tests/
├── pyproject.toml
└── README.md
```

## Deprecation (mandatory for public API changes)

Use `typing_extensions.deprecated` (PEP 702) —
verify current project preference with maintainer or `oss:shepherd` (requires `oss` plugin) for full release patterns.
Prefer dedicated library over raw `warnings.warn` — handles argument forwarding, "warn once" deduplication, automatic call delegation.

**Key rules**: set `deprecated_in` + `remove_in`, add `.. deprecated:: X.Y.Z` Sphinx directive in docstring.

## API Stability

- Mark experimental APIs with `# experimental: API may change without notice`
- Use `__version__` in `__init__.py`: `__version__ = "1.2.3"`
- SemVer: MAJOR.MINOR.PATCH — breaking changes only in MAJOR
- Never remove public API without deprecation cycle spanning ≥1 minor release
- **Rename with backward compat**: assign `OldName = NewName` as deprecated alias for one major cycle, then remove
