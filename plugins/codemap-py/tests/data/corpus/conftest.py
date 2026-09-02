"""Shield the frozen-grammar corpus from pytest collection.

The corpus deliberately contains post-3.11 syntax (PEP 695 type parameters, PEP 701 f-string quote reuse). pytest runs
with ``--doctest-modules`` and ``testpaths=["plugins"]`` (see the repo ``pyproject.toml``), so without this guard pytest
would try to import every ``corpus/*.py`` as a doctest module and raise a collection-time SyntaxError on the 3.10 and
3.11 matrix cells. The corpus is consumed only by ``test_grammar.py``, which reads the files as text and feeds them to a
subprocess ``scan-index`` — it never imports them. Ignoring the whole directory here keeps the intentional syntax out of
the collector's path.
"""

collect_ignore_glob = ["*.py"]
