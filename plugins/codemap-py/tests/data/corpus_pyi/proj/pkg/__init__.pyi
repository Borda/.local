# Scenario: package __init__ shadowed by an authoritative __init__.py.
# Expected: reported as shadowed_stub; NOT indexed as a second "pkg" module.
from pkg.shadowed import impl as impl

__all__: list[str]
