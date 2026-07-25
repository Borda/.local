"""Regular package: an authoritative ``__init__.py`` shadows ``__init__.pyi``."""

from pkg.shadowed import impl

__all__ = ["impl"]
