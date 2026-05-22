"""Tests for ``bin/resolve_proj_index.py`` — PROJ name + INDEX path resolver.

Covers:
* ``compute_proj_index()`` uses git root basename when inside a repo
* Falls back to CWD basename outside a repo
* INDEX path is ``<root>/.cache/scan/<proj>.json``
* ``--check`` exits 1 when index absent; exits 0 and prints ✓ when present
* ``main()`` without ``--check`` always exits 0
* Windows-portability invariants: no ``/tmp``, ``sys.stdout.reconfigure`` present,
  ``shell=True`` absent
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "resolve_proj_index.py"
_spec = importlib.util.spec_from_file_location("codemap_resolve_proj_index", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

compute_proj_index = _mod.compute_proj_index
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

    def test_no_shell_true(self) -> None:
        """``subprocess`` calls must not use ``shell=True``."""
        assert "shell=True" not in _SCRIPT.read_text(encoding="utf-8")


class TestComputeProjIndex:
    """Unit tests for ``compute_proj_index()``."""

    def test_cwd_fallback_uses_basename(self, tmp_path: Path) -> None:
        """Falls back to CWD basename when git rev-parse fails."""
        work = tmp_path / "my-project"
        work.mkdir()
        proj, _ = compute_proj_index(cwd=work)
        assert proj == "my-project"

    def test_index_path_structure(self, tmp_path: Path) -> None:
        """Index path is ``<root>/.cache/scan/<proj>.json``."""
        work = tmp_path / "my-project"
        work.mkdir()
        proj, index = compute_proj_index(cwd=work)
        assert index == work / ".cache" / "scan" / f"{proj}.json"

    def test_git_root_basename_used_when_available(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses git root dirname when subprocess returns a valid path."""
        repo_root = tmp_path / "my-repo"
        repo_root.mkdir()
        sub = repo_root / "subdir"
        sub.mkdir()

        def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            """Return a fake git rev-parse result."""
            result: subprocess.CompletedProcess = subprocess.CompletedProcess(cmd, 0)
            result.stdout = str(repo_root) + "\n"
            result.stderr = ""
            return result

        monkeypatch.setattr(_mod.subprocess, "run", mock_run)
        proj, index = compute_proj_index(cwd=sub)
        assert proj == "my-repo"
        assert index == repo_root / ".cache" / "scan" / "my-repo.json"

    def test_git_failure_falls_back_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Falls back to CWD basename when git subprocess raises CalledProcessError."""
        work = tmp_path / "my-project"
        work.mkdir()

        def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            """Simulate git failure."""
            raise subprocess.CalledProcessError(128, cmd)

        monkeypatch.setattr(_mod.subprocess, "run", mock_run)
        proj, _ = compute_proj_index(cwd=work)
        assert proj == "my-project"


class TestMain:
    """Integration tests for ``main()``."""

    def test_no_check_always_exits_0(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Without ``--check``, main always exits 0."""
        (tmp_path / "proj").mkdir()
        monkeypatch.chdir(tmp_path / "proj")
        rc = main([])
        assert rc == 0

    def test_check_exits_1_when_index_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check`` exits 1 and prints ✗ when index file does not exist."""
        work = tmp_path / "myproj"
        work.mkdir()
        monkeypatch.chdir(work)

        def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            raise subprocess.CalledProcessError(128, cmd)

        monkeypatch.setattr(_mod.subprocess, "run", mock_run)
        rc = main(["--check"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "✗" in out

    def test_check_exits_0_when_index_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """``--check`` exits 0 and prints ✓ when index file exists."""
        work = tmp_path / "myproj"
        work.mkdir()
        monkeypatch.chdir(work)

        def mock_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:  # type: ignore[type-arg]
            raise subprocess.CalledProcessError(128, cmd)

        monkeypatch.setattr(_mod.subprocess, "run", mock_run)
        index = work / ".cache" / "scan" / "myproj.json"
        index.parent.mkdir(parents=True)
        index.write_text("{}", encoding="utf-8")
        rc = main(["--check"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "✓" in out

    def test_output_has_no_crlf(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """stdout must not contain CRLF (Windows text-mode regression guard)."""
        work = tmp_path / "proj"
        work.mkdir()
        monkeypatch.chdir(work)
        main([])
        assert "\r" not in capsys.readouterr().out
