"""Shield the ``.pyi`` scope-extension fixture project from pytest collection.

The ``proj/`` subtree is scanner *input*, not test code: ``scan-index`` reads it as files (import discovery, AST
extraction) via an explicit root path — pytest must never import it. ``pyproject.toml`` runs ``--doctest-modules`` with
``testpaths=["plugins"]``, so without this guard pytest would import every ``proj/**/*.py`` fixture as a doctest module.
``.pyi`` files are not collected by pytest, but the authoritative ``.py`` siblings and package ``__init__.py`` files
are, hence the ``*.py`` ignore. Mirrors ``tests/corpus/conftest.py``.

``*`` in an fnmatch pattern spans ``/``, so a single top-level pattern shields the whole nested tree; verified with
``pytest --collect-only`` at authoring time.
"""

collect_ignore_glob = ["*.py"]
