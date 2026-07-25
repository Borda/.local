# `.pyi` scope-extension fixtures

Scanner *input* for the `.pyi` module-collision work (plan §2.1). `proj/` is a self-contained fixture project root; a test points `scan-index --root` at it and asserts the collision matrix. `conftest.py` shields the `.py` fixtures from pytest's `--doctest-modules` collection. Nothing here is imported by a test.

Content is deterministic — do not add timestamps, randomness, or machine paths.

## Scenario map (`proj/`)

| Path                                                        | Scenario                                           | Expected classification                                                              |
| ----------------------------------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `pkg/__init__.py` + `pkg/__init__.pyi`                      | package init, authoritative `.py` present          | `.py` indexed as `pkg`; `.pyi` → `shadowed_stub`                                     |
| `pkg/shadowed.py` + `pkg/shadowed.pyi`                      | sibling module, authoritative `.py` present        | `.py` indexed as `pkg.shadowed`; `.pyi` → `shadowed_stub`                            |
| `pkg/stub_only.pyi`                                         | module stub, no `.py` sibling                      | indexed once, `stub_only=true`, decls+imports, no call edges                         |
| `typed/__init__.py` + `typed/interfaces.pyi`                | declarations-only stub with rich imports           | `interfaces` → `stub_only=true`                                                      |
| `stubpkg/__init__.pyi`                                      | package whose init is stub-only (no `__init__.py`) | package `stubpkg` indexed once, `stub_only=true`                                     |
| `stubpkg/leaf.pyi`                                          | module inside a stub-only package                  | `stubpkg.leaf`, `stub_only=true`                                                     |
| `nested/__init__.py` + `nested/core.py` + `nested/core.pyi` | nested authoritative module + shadow stub          | `.py` indexed as `nested.core`; `.pyi` → `shadowed_stub`; `run()` call edge survives |
| `nested/proto.pyi`                                          | stub-only module in an authoritative package       | `nested.proto`, `stub_only=true`                                                     |

## Not committed here (constructed at test runtime)

Platform case-fold collisions (`mod.py` vs `MOD.pyi`) cannot be committed on a case-insensitive filesystem (macOS/Windows default) and git refuses the pair. The collision test builds these in a tempdir and asserts identical fail/degrade on every OS, never selection by directory order (plan §2.1 final bullet).
