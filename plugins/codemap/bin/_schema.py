"""Index data contract shared between scan-index (writer) and scan-query (reader).

Both scripts import via sys.path.insert on __file__'s directory — this file must
live alongside them in bin/.

consumers: bin/scan-index, bin/scan-query — imported as Python module; not a standalone executable
"""

from __future__ import annotations

from enum import Enum
from typing import TypedDict

# Increment when the index JSON structure changes incompatibly.
SCAN_VERSION: int = 10

# Per-feature minimum index versions.
# v4 and v5 were design epochs shipped together in one release (SCAN_VERSION 4–10).
# Each feature checks its own constant via _require_feature() in scan-query.
MOCK_PATCHES_MIN_VER: int = 4  # v4.1 — mock_patches, mock_rdep_count, fn_rdep_test_count
UNCOVERED_MIN_VER: int = 4  # v4.2 — fn_rdep_test_count per symbol
IMPORT_GROUPS_MIN_VER: int = 4  # v4.3 — import_groups
DOCSTRING_MIN_VER: int = 4  # v4.4 — has_docstring, docstring_first_line
SPHINX_XREFS_MIN_VER: int = 5  # v4.5 — sphinx_xrefs, sphinx_xref_count
DEAD_SYMBOL_MIN_VER: int = 6  # v4.6 — dead-symbol query; requires sphinx_xref_count (v4.5)
MODULE_ALIASES_MIN_VER: int = 7  # v5.1 — module_aliases at index root
SUBPROCESS_CALLS_MIN_VER: int = 8  # v5.2 — subprocess_calls per module, subprocess_rdep_count at root
FIXTURE_GRAPH_MIN_VER: int = 9  # v5.3 — fixture_uses per test module, fixture_exports per conftest
COVERAGE_MIN_VER: int = 10  # v5.4 — coverage_pct, covered_by per symbol (requires --with-coverage build)


class Resolution(str, Enum):
    """Resolution kind for a call edge. Inherits str so json.dump serialises values as plain strings."""

    IMPORT = "import"
    LOCAL = "local"
    SELF = "self"
    BUILTIN = "builtin"
    STAR = "star"
    UNRESOLVED = "unresolved"


# Resolutions that represent calls within the project (exclude builtins, star, unresolved).
VALID_CALL_RESOLUTIONS: frozenset[str] = frozenset({Resolution.IMPORT, Resolution.LOCAL, Resolution.SELF})


class Symbol(TypedDict, total=False):
    name: str
    qualified_name: str
    type: str  # "class" | "function" | "method"
    start_line: int
    end_line: int
    calls: list[dict]  # v3 call edges — absent in v2 indexes
    fn_rdep_test_count: int  # v4.1 — count of callers whose source module has is_test=True
    mock_rdep_count: int  # v4.1 — count of test files mocking this symbol via patch()
    has_docstring: bool  # v4.4 — True when ast.get_docstring(node) is not None
    docstring_first_line: str | None  # v4.4 — first non-empty line, stripped, ≤80 chars; None when absent
    coverage_pct: (
        float  # v5.4 — fraction of symbol's lines measured (0.0–1.0); absent when index built without --with-coverage
    )
    covered_by: list[str] | None  # v5.4 — test node IDs that executed this symbol; null when --cov-context not used
