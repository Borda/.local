"""Tests for ``bin/read_state_field.py`` — dotted-path JSON field reader.

Covers:
* Top-level field lookup
* Nested dotted field lookup (canonical: ``config.metric.direction``)
* Default returned when any segment is missing
* CLI exit codes: missing file → exit 2; unreadable JSON → exit 1
* End-to-end subprocess invocation guarding the shebang + ``__main__`` wiring
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "read_state_field.py"
_spec = importlib.util.spec_from_file_location("research_read_state_field", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

read_field = _mod.read_field
main = _mod.main


def _write_state(path: Path, payload: object) -> Path:
    """Write ``payload`` as JSON to ``path`` and return ``path`` for chaining."""
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestReadFieldPure:
    """Unit tests for the pure ``read_field()`` function."""

    def test_top_level_field(self) -> None:
        """Single segment resolves to top-level value."""
        assert read_field({"status": "completed"}, "status") == "completed"

    def test_nested_dotted_field(self) -> None:
        """Canonical case: ``config.metric.direction``."""
        data = {"config": {"metric": {"direction": "higher"}}}
        assert read_field(data, "config.metric.direction") == "higher"

    def test_default_when_segment_missing(self) -> None:
        """Default returned when intermediate key is absent."""
        data = {"config": {"metric": {}}}
        assert read_field(data, "config.metric.direction", default="higher") == "higher"

    def test_default_when_terminal_not_dict(self) -> None:
        """Scalar at intermediate position stops traversal — default returned."""
        data = {"a": "scalar"}
        assert read_field(data, "a.b", default="fallback") == "fallback"

    def test_numeric_terminal_coerced_to_string(self) -> None:
        """Non-string terminal value is converted via ``str()``."""
        assert read_field({"n": 42}, "n") == "42"

    @pytest.mark.parametrize("dotted_path", ["", ".", "a.", ".a", "a..b"])
    def test_invalid_dotted_path_raises(self, dotted_path: str) -> None:
        """Empty dotted paths and empty path segments are rejected explicitly."""
        with pytest.raises(ValueError, match="non-empty"):
            read_field({"a": 1}, dotted_path)


class TestMainCli:
    """In-process ``main()`` tests using ``capsys``."""

    def test_reads_nested_field(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """End-to-end: nested field printed on stdout."""
        state = _write_state(tmp_path / "state.json", {"config": {"metric": {"direction": "lower"}}})
        rc = main([str(state), "config.metric.direction"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "lower"

    def test_default_returned_when_missing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Verify command-line option behavior.

        The ``--default`` value is printed when the field is absent.
        """
        state = _write_state(tmp_path / "state.json", {"config": {}})
        rc = main([str(state), "config.metric.direction", "--default", "higher"])
        assert rc == 0
        assert capsys.readouterr().out.strip() == "higher"

    def test_empty_default_when_missing_and_no_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Confirm a missing field without ``--default`` prints an empty line."""
        state = _write_state(tmp_path / "state.json", {})
        rc = main([str(state), "missing"])
        assert rc == 0
        assert capsys.readouterr().out == "\n"

    def test_exit_one_when_state_file_missing(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Non-existent state file → exit 1 (file error per spec)."""
        rc = main([str(tmp_path / "nope.json"), "any.field"])
        assert rc == 1
        assert "not a regular file" in capsys.readouterr().err

    def test_exit_one_on_malformed_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """Unparsable JSON → exit 1."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        rc = main([str(bad), "any.field"])
        assert rc == 1
        assert "cannot read" in capsys.readouterr().err

    def test_exit_one_when_top_level_not_object(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        """JSON list at top level → exit 1 (must be an object)."""
        state = _write_state(tmp_path / "list.json", [1, 2, 3])
        rc = main([str(state), "any"])
        assert rc == 1
        assert "not an object" in capsys.readouterr().err


class TestSubprocessIntegration:
    """End-to-end subprocess check: missing file path → exit 1 contract."""

    def test_missing_file_subprocess(self, tmp_path: Path) -> None:
        """Invoke via subprocess to exercise the shebang + ``__main__`` wiring.

        Spec: ``Exit 1 on file/parse error`` — missing file routes through the
        file-validation branch and returns exit 1.
        """
        missing = tmp_path / "missing.json"
        result = subprocess.run(
            [sys.executable, str(_SCRIPT), str(missing), "a.b"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1
        assert "not a regular file" in result.stderr
