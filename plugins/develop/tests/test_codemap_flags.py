"""Tests for ``bin/codemap_flags.py`` — CODEMAP_ENABLED flag resolver.

Covers:
* ``--no-codemap`` → ``off``
* ``--codemap`` (without ``--no-``) → ``strict``
* no recognized flag → ``auto``
* precedence: ``--no-codemap`` wins over ``--codemap``
* main() always exits 0; CRLF-free stdout
* Windows-portability invariants
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "codemap_flags.py"
_spec = importlib.util.spec_from_file_location("develop_codemap_flags", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

resolve_codemap_flag = _mod.resolve_codemap_flag
main = _mod.main


class TestPortabilityInvariants:
    """Source-level Windows-portability checks."""

    def test_no_tmp_literal_in_source(self) -> None:
        """Script must not hardcode ``/tmp``."""
        assert "/tmp" not in _SCRIPT.read_text(encoding="utf-8")

    def test_stdout_reconfigure_present(self) -> None:
        """``sys.stdout.reconfigure(...)`` must be called in ``main()``."""
        assert "sys.stdout.reconfigure" in _SCRIPT.read_text(encoding="utf-8")

    def test_shebang_env_python(self) -> None:
        """Shebang must be ``#!/usr/bin/env python`` (not ``python3``)."""
        assert _SCRIPT.read_text(encoding="utf-8").splitlines()[0] == "#!/usr/bin/env python"

    def test_no_utcnow(self) -> None:
        """``datetime.utcnow()`` deprecated in 3.12 — must not appear in source."""
        assert "utcnow" not in _SCRIPT.read_text(encoding="utf-8")


class TestResolveCodemapFlag:
    """Unit tests for ``resolve_codemap_flag()``."""

    @pytest.mark.parametrize(
        "args_string,expected",
        [
            ("--no-codemap", "off"),
            ("--codemap", "strict"),
            ("", "auto"),
            ("--other-flag", "auto"),
            ("--no-codemap --codemap", "off"),  # --no-codemap takes precedence
            ("--codemap --no-codemap", "off"),  # order irrelevant; --no- wins
            ("some text --codemap more text", "strict"),
            ("some text --no-codemap more text", "off"),
        ],
    )
    def test_flag_resolution(self, args_string: str, expected: str) -> None:
        """Flag resolution matches expected output for each argument string."""
        assert resolve_codemap_flag(args_string) == expected


class TestMain:
    """Integration tests for ``main()``."""

    @pytest.mark.parametrize(
        "args,expected_out",
        [
            (["--no-codemap"], "off"),
            (["--codemap"], "strict"),
            ([], "auto"),
            (["--other"], "auto"),
            (["--no-codemap --codemap"], "off"),
        ],
    )
    def test_main_output(self, args: list[str], expected_out: str, capsys: pytest.CaptureFixture[str]) -> None:
        """``main()`` prints correct flag value and always exits 0."""
        rc = main(args)
        assert rc == 0
        assert capsys.readouterr().out.strip() == expected_out

    def test_output_has_no_crlf(self, capsys: pytest.CaptureFixture[str]) -> None:
        """stdout must not contain CRLF (Windows text-mode regression guard)."""
        main(["--codemap"])
        assert "\r" not in capsys.readouterr().out
