"""Corpus module: syntax accepted by every supported CPython (3.10 through 3.14).

Frozen grammar baseline. scan-index must index this module identically on every
matrix cell — it never degrades. Do not add post-3.11 syntax here.
"""

from __future__ import annotations

import functools


class Shape:
    """A trivial class with a method, for symbol extraction."""

    def __init__(self, sides: int) -> None:
        self.sides = sides

    def describe(self) -> str:
        return f"shape with {self.sides} sides"


@functools.lru_cache(maxsize=None)
def classify(n: int) -> str:
    """Use a match statement (3.10+), the version-distinctive syntax for this file."""
    match n:
        case 0:
            return "zero"
        case _ if n % 2 == 0:
            return "even"
        case _:
            return "odd"


def total(values: list[int]) -> int:
    return sum(v for v in values if v > 0)
