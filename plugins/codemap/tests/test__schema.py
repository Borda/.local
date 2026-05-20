"""Tests for ``bin/_schema.py`` — index data contract: version, enum values, call-resolution set."""

from __future__ import annotations

import _schema
from _schema import SCAN_VERSION, Resolution, VALID_CALL_RESOLUTIONS


class TestResolutionEnum:
    """Resolution enum: string inheritance, expected members, value spelling."""

    def test_all_members_inherit_str(self) -> None:
        """Every Resolution member must be usable as a plain string (json.dumps relies on this)."""
        for member in Resolution:
            assert isinstance(member, str)

    def test_import_value(self) -> None:
        """IMPORT serialises to 'import'."""
        assert Resolution.IMPORT == "import"

    def test_local_value(self) -> None:
        """LOCAL serialises to 'local'."""
        assert Resolution.LOCAL == "local"

    def test_self_value(self) -> None:
        """SELF serialises to 'self'."""
        assert Resolution.SELF == "self"

    def test_builtin_value(self) -> None:
        """BUILTIN serialises to 'builtin'."""
        assert Resolution.BUILTIN == "builtin"

    def test_star_value(self) -> None:
        """STAR serialises to 'star'."""
        assert Resolution.STAR == "star"

    def test_unresolved_value(self) -> None:
        """UNRESOLVED serialises to 'unresolved'."""
        assert Resolution.UNRESOLVED == "unresolved"

    def test_complete_member_set(self) -> None:
        """Exactly six resolution kinds — adding/removing one must update this test."""
        expected = {"import", "local", "self", "builtin", "star", "unresolved"}
        assert {m.value for m in Resolution} == expected


class TestValidCallResolutions:
    """VALID_CALL_RESOLUTIONS: type, contents, exclusions."""

    def test_is_frozenset(self) -> None:
        """Must be a frozenset — immutable, safe to share across modules."""
        assert isinstance(VALID_CALL_RESOLUTIONS, frozenset)

    def test_includes_import(self) -> None:
        """IMPORT represents cross-module calls — must be in the valid set."""
        assert Resolution.IMPORT in VALID_CALL_RESOLUTIONS

    def test_includes_local(self) -> None:
        """LOCAL represents same-file calls — must be in the valid set."""
        assert Resolution.LOCAL in VALID_CALL_RESOLUTIONS

    def test_includes_self(self) -> None:
        """SELF represents method-to-method calls — must be in the valid set."""
        assert Resolution.SELF in VALID_CALL_RESOLUTIONS

    def test_excludes_builtin(self) -> None:
        """BUILTIN calls are outside the project graph — must be excluded."""
        assert Resolution.BUILTIN not in VALID_CALL_RESOLUTIONS

    def test_excludes_star(self) -> None:
        """STAR imports are unresolvable — must be excluded."""
        assert Resolution.STAR not in VALID_CALL_RESOLUTIONS

    def test_excludes_unresolved(self) -> None:
        """UNRESOLVED calls carry no graph information — must be excluded."""
        assert Resolution.UNRESOLVED not in VALID_CALL_RESOLUTIONS

    def test_size(self) -> None:
        """Exactly three valid resolutions."""
        assert len(VALID_CALL_RESOLUTIONS) == 3


class TestScanVersion:
    """SCAN_VERSION: type and positivity."""

    def test_is_int(self) -> None:
        """Version must be a plain Python int."""
        assert isinstance(SCAN_VERSION, int)

    def test_is_positive(self) -> None:
        """Version must be a positive number (≥1)."""
        assert SCAN_VERSION >= 1


def test_doctests_pass() -> None:
    """Doctest examples in _schema must not regress."""
    import doctest

    results = doctest.testmod(_schema, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
