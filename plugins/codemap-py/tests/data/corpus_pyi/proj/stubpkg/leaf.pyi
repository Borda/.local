# Scenario: stub-only module inside a stub-only package.
# Expected: stub_only=true; dotted name resolves as "stubpkg.leaf".
from typing import Protocol

class Leaf(Protocol):
    value: int
