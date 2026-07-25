"""Authoritative implementation. Its ``shadowed.pyi`` sibling is a shadowed_stub."""

from typing import TYPE_CHECKING


def impl(value: int) -> int:
    """Return ``value`` doubled — a real body, so it contributes a call edge."""
    return _double(value)


def _double(value: int) -> int:
    return value + value


if TYPE_CHECKING:  # pragma: no cover - import guard only
    from pkg.stub_only import Marker as Marker
