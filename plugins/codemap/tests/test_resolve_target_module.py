"""Tests for ``bin/resolve_target_module.py`` — path-to-dotted-module conversion."""

from __future__ import annotations

import sys

import pytest


import resolve_target_module  # noqa: E402
from resolve_target_module import main, resolve_target_module as resolve  # noqa: E402


# ---------------------------------------------------------------------------
# resolve_target_module() — pure function
# ---------------------------------------------------------------------------


class TestPipelineTransforms:
    """Each stage of the transform pipeline applied individually."""

    def test_strips_leading_dot_slash(self) -> None:
        assert resolve("./foo/bar.py") == "foo.bar"

    def test_strips_src_prefix(self) -> None:
        assert resolve("src/foo/bar.py") == "foo.bar"

    def test_strips_dot_slash_then_src(self) -> None:
        assert resolve("./src/foo/bar.py") == "foo.bar"

    def test_strips_py_suffix(self) -> None:
        assert resolve("foo/bar.py") == "foo.bar"

    def test_replaces_slash_with_dot(self) -> None:
        assert resolve("foo/bar/baz.py") == "foo.bar.baz"


class TestModuleNameVariants:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("src/foo/bar.py", "foo.bar"),
            ("tests/test_x.py", "tests.test_x"),
            ("pkg/sub/mod.py", "pkg.sub.mod"),
            ("./pkg/sub/mod.py", "pkg.sub.mod"),
            ("./src/pkg/sub/mod.py", "pkg.sub.mod"),
        ],
    )
    def test_common_paths(self, path: str, expected: str) -> None:
        assert resolve(path) == expected


class TestDunderInit:
    """``__init__.py`` keeps the literal ``__init__`` segment — only ``.py`` is stripped."""

    def test_top_level_init(self) -> None:
        assert resolve("pkg/__init__.py") == "pkg.__init__"

    def test_nested_init(self) -> None:
        assert resolve("src/pkg/sub/__init__.py") == "pkg.sub.__init__"


class TestAlreadyDotted:
    def test_dotted_input_unchanged(self) -> None:
        # No leading ./ or src/, no .py, no slash → string passes through verbatim.
        assert resolve("foo.bar") == "foo.bar"

    def test_dotted_with_py_suffix(self) -> None:
        # Edge case: literal "foo.bar.py" is treated as a file; the .py is stripped.
        assert resolve("foo.bar.py") == "foo.bar"


class TestFallback:
    """When the transform empties the string, fall back to ``Path(input).stem``."""

    def test_empty_input(self) -> None:
        assert resolve("") == ""

    def test_src_only_input(self) -> None:
        # "src/" → "" after strip_src + strip_py + slash-replace; fallback is Path("src/").stem == "src".
        assert resolve("src/") == "src"

    def test_dot_slash_only(self) -> None:
        # "./" → "" after strip; Path("./").stem == "".
        assert resolve("./") == ""


class TestStandaloneAndAbsolute:
    def test_standalone_filename(self) -> None:
        assert resolve("standalone.py") == "standalone"

    def test_bare_name_no_extension(self) -> None:
        assert resolve("foo") == "foo"

    def test_absolute_path(self) -> None:
        # Absolute paths produce a leading "." (because the leading "/" becomes ".").
        # This mirrors the original sed pipeline behaviour exactly — callers must pass
        # repo-relative paths.
        assert resolve("/abs/foo/bar.py") == ".abs.foo.bar"


# ---------------------------------------------------------------------------
# main() — CLI entry point
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_with_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main(["src/foo/bar.py"])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == "foo.bar"

    def test_main_with_empty_arg(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main([""])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == ""

    def test_main_with_no_args(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == ""

    def test_main_uses_sys_argv_when_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["resolve_target_module.py", "tests/test_x.py"])
        rc = main()
        out = capsys.readouterr().out
        assert rc == 0
        assert out.strip() == "tests.test_x"


# ---------------------------------------------------------------------------
# Doctest hookup
# ---------------------------------------------------------------------------


def test_doctests_pass() -> None:
    import doctest

    results = doctest.testmod(resolve_target_module, verbose=False)
    assert results.failed == 0, f"{results.failed} doctest(s) failed"
