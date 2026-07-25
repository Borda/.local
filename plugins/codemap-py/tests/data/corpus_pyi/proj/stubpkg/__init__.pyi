# Scenario: stub-only PACKAGE — __init__.pyi with no __init__.py sibling.
# Expected: package "stubpkg" indexed once with stub_only=true; src-root
# detection must recognise it as a package even though only __init__.pyi exists.
from stubpkg.leaf import Leaf as Leaf

__all__: list[str]
