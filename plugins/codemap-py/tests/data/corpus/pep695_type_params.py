"""Corpus module: PEP 695 type parameter syntax (new in CPython 3.12).

Parses on 3.12+, is a SyntaxError on 3.10 and 3.11. scan-index degrades this module (status="degraded") on any
interpreter whose grammar predates 3.12 and indexes it normally on 3.12+. The frozen-grammar test asserts that
degradation tracks the running interpreter's grammar. Do not "fix" this file — its post-3.11 syntax is the point.
"""

from __future__ import annotations


def first[T](items: list[T]) -> T:
    return items[0]


class Box[T]:
    def __init__(self, value: T) -> None:
        self.value = value


type IntOrStr = int | str
