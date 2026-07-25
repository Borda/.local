# Scenario: declarations-only stub with imports, no .py sibling.
# Expected: stub_only=true; imports (os, collections.abc, typing) recorded so
# import edges resolve, class/function declarations recorded, zero call edges.
import os
from collections.abc import Iterable
from typing import Protocol, overload

class Repository(Protocol):
    root: os.PathLike[str]

    def items(self) -> Iterable[str]: ...

@overload
def load(source: str) -> Repository: ...
@overload
def load(source: os.PathLike[str]) -> Repository: ...
