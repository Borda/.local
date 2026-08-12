"""Shared paid-stage lifecycle and approval-token contracts."""

from __future__ import annotations

import pytest

from benchmarks._bench_common.paid_lifecycle import paid_approval_matches, paid_approval_token


def test_paid_approval_token_shortens_presentation_without_changing_scope_identity() -> None:
    """Human confirmation uses 16 hex characters while stored scope stays complete."""
    scope_sha256 = "0123456789abcdef" * 4

    assert paid_approval_token(scope_sha256) == "0123456789abcdef"
    assert len(scope_sha256) == 64


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        pytest.param("0123456789abcdef", True, id="canonical-prefix"),
        pytest.param("0123456789abcdef0", True, id="longer-prefix"),
        pytest.param("0123456789abcdef" * 4, True, id="legacy-full-hash"),
        pytest.param("0123456789abcde", False, id="too-short"),
        pytest.param("0123456789abcdef" * 4 + "0", False, id="too-long"),
        pytest.param("0123456789abcdeg", False, id="non-hex"),
        pytest.param("0123456789ABCDEf", False, id="uppercase"),
        pytest.param("1123456789abcdef", False, id="different-scope"),
        pytest.param(None, False, id="missing"),
    ],
)
def test_paid_approval_matching_is_prefix_bounded_and_fail_closed(received: str | None, expected: bool) -> None:
    """Only lowercase matching prefixes of at least 64 bits authorize the current scope."""
    scope_sha256 = "0123456789abcdef" * 4

    assert paid_approval_matches(received, scope_sha256) is expected


def test_paid_approval_token_rejects_noncanonical_scope_hash() -> None:
    """Presentation cannot conceal malformed or incomplete scope identity."""
    with pytest.raises(ValueError, match="64 lowercase hexadecimal"):
        paid_approval_token("not-a-scope")
