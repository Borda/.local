"""Rename-migration invariants for the codemap -> codemap-py identity.

Asserts the repository never carries both plugin identities at once, that both
marketplace catalogs advertise ``codemap-py`` only, that an install-shaped plugin
cache holding BOTH the legacy and renamed identities resolves to ``codemap-py``
alone (and the dual state is detectable), and that the legacy ``.cache/codemap/``
index layout is retained (the resolver is unchanged, so existing indexes keep
resolving after the rename).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PLUGIN_ROOT.parents[1]
_BIN = _PLUGIN_ROOT / "bin"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))

import _index_identity  # noqa: E402  (needs the bin path insert above)
import check_injection  # noqa: E402  (needs the bin path insert above)


def _seed_plugin_cache(home: Path, entries: dict[str, str]) -> Path:
    """Create install-shaped ``borda-ai-rig/<plugin>/<version>`` cache dirs; return the cache base."""
    cache = home / ".claude" / "plugins" / "cache"
    for plugin, version in entries.items():
        (cache / "borda-ai-rig" / plugin / version).mkdir(parents=True)
    return cache


def _plugin_names(marketplace: Path) -> set[str]:
    """Return the set of plugin ``name`` entries in a marketplace catalog."""
    catalog = json.loads(marketplace.read_text(encoding="utf-8"))
    return {entry["name"] for entry in catalog.get("plugins", [])}


# --- dual-identity ban -----------------------------------------------------


def test_repo_tracks_exactly_one_plugin_identity() -> None:
    """Exactly one of plugins/codemap or plugins/codemap-py exists on disk."""
    legacy = _REPO_ROOT / "plugins" / "codemap"
    renamed = _REPO_ROOT / "plugins" / "codemap-py"
    assert renamed.is_dir()
    assert not legacy.exists()


@pytest.mark.parametrize(
    "marketplace_rel",
    [
        pytest.param(".claude-plugin/marketplace.json", id="claude-marketplace"),
        pytest.param(".agents/plugins/marketplace.json", id="codex-marketplace"),
    ],
)
def test_marketplace_advertises_codemap_py_only(marketplace_rel: str) -> None:
    """Marketplace catalogs list codemap-py and never the legacy codemap name."""
    names = _plugin_names(_REPO_ROOT / marketplace_rel)
    assert "codemap-py" in names
    assert "codemap" not in names


# --- legacy cache path retained --------------------------------------------


def test_index_subdir_is_legacy_cache_codemap() -> None:
    """The resolver's index subdir constant is still ``.cache/codemap``."""
    assert _index_identity.INDEX_SUBDIR == Path(".cache", "codemap")


def test_resolver_places_index_under_legacy_cache(tmp_path: Path) -> None:
    """A default resolution nests the index under ``.cache/codemap`` for a root."""
    identity = _index_identity.resolve_index(root=tmp_path, index_dir_override=None)
    assert identity.index_dir.parts[-2:] == (".cache", "codemap")
    assert identity.index_path.name == f"{tmp_path.name}.json"


# --- install-shaped dual-identity ban --------------------------------------


def test_resolver_selects_codemap_py_when_both_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With BOTH legacy and renamed plugin caches present, the shipped resolver picks codemap-py."""
    home = tmp_path / "home"
    _seed_plugin_cache(home, {"codemap": "1.0.0", "codemap-py": "0.25.0"})
    monkeypatch.setenv("HOME", str(home))
    resolved = check_injection.resolve_plugin_root(None)
    assert resolved is not None
    assert resolved.parent.name == "codemap-py"
    assert resolved.name == "0.25.0"


def test_shipped_detect_dual_identity_fires_when_both_cached(tmp_path: Path) -> None:
    """The shipped ``check_injection.detect_dual_identity`` names the violation when both coexist."""
    cache_base = _seed_plugin_cache(tmp_path / "home", {"codemap": "1.0.0", "codemap-py": "0.25.0"})
    assert check_injection.detect_dual_identity(cache_base) == "dual_plugin_identity"


def test_shipped_detect_dual_identity_clean_when_only_renamed_cached(tmp_path: Path) -> None:
    """The shipped detector is silent when only codemap-py is cached."""
    cache_base = _seed_plugin_cache(tmp_path / "home", {"codemap-py": "0.25.0"})
    assert check_injection.detect_dual_identity(cache_base) is None
