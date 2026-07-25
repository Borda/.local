"""Authoritative nested module. Imports across packages produce real edges."""

from pkg.shadowed import impl


def run(value: int) -> int:
    """Call into ``pkg.shadowed.impl`` — a cross-package call edge."""
    return impl(value)
