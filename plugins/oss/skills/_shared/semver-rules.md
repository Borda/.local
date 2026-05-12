# SemVer Rules — Python/OSS

## MAJOR (X.0.0) — breaking changes

- Remove public function, class, or argument
- Change function return type incompatibly
- Change argument order or required vs optional status
- Change behavior users depend on (even if "was a bug")
- Drop Python version from supported range

## MINOR (x.Y.0) — backwards-compatible additions

- New public functions, classes, or arguments (with defaults)
- New optional dependencies or extras
- New config options
- Perf improvements with no API change
- Deprecations (deprecated API still works)

## PATCH (x.y.Z) — backwards-compatible fixes

- Bug fixes not changing public interface
- Doc updates
- Internal refactors with no API change
- Dependency version range relaxation

## Deprecation Discipline

Use [pyDeprecate](https://pypi.org/project/pyDeprecate/) (Borda's package) — handles warning emission, argument forwarding, "warn once" behavior. Read latest docs on PyPI for current API and examples.

- **Deprecation lifecycle**: deprecate in minor → keep ≥1 minor cycle → remove in next major
- **Also**: add `.. deprecated:: X.Y.Z` Sphinx directive in docstring so docs generators render deprecation notice
- Anti-patterns: see shepherd's `<antipatterns_to_flag>` section (deprecation category)
