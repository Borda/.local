"""Corpus module: PEP 701 nested f-strings reusing the quote character (new in CPython 3.12).

Nesting an f-string inside another f-string's replacement field with the same quote
character parses on 3.12+ and is a SyntaxError ("f-string: expecting '}'") on 3.10 and
3.11. Same contract as the PEP 695 module: scan-index degrades this module wherever the
running grammar predates 3.12. Do not rewrite the f-strings to be 3.11-compatible — the
post-3.11 syntax is deliberate.

Note: a single-level quote-reuse such as ``f"{"a"}, {b}"`` can, depending on surrounding
tokens, re-tokenize into something a pre-3.12 parser still accepts; the nested form below
is a reliable pre-3.12 SyntaxError, which is why it is used here.
"""

from __future__ import annotations


def render(x: int) -> str:
    return f"{f"{x}"}"


def label(rows: list[str]) -> str:
    return f"{f"{len(rows)}"} rows"
