"""Tests for install_post_commit_hook bin script.

Covers create / append / idempotency paths, shebang warnings, and the ``core.hooksPath`` override.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


import install_post_commit_hook as iph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_repo(tmp_path: Path) -> Path:
    """Initialise a git repo under ``tmp_path`` and return the worktree path."""
    subprocess.run(
        ["git", "init", "--quiet"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# hook_already_installed
# ---------------------------------------------------------------------------


class TestHookAlreadyInstalled:
    """Cover marker detection inside an existing hook file."""

    def test_returns_true_when_marker_present(self, tmp_path: Path):
        """File containing ``# codemap: incremental`` is treated as installed."""
        hook = tmp_path / "post-commit"
        hook.write_text("#!/bin/sh\n# codemap: incremental rebuild\necho hi\n", encoding="utf-8")
        assert iph.hook_already_installed(hook) is True

    def test_returns_false_when_marker_absent(self, tmp_path: Path):
        """File without the marker is not detected as installed."""
        hook = tmp_path / "post-commit"
        hook.write_text("#!/bin/sh\necho unrelated\n", encoding="utf-8")
        assert iph.hook_already_installed(hook) is False

    def test_returns_false_when_file_missing(self, tmp_path: Path):
        """Missing file returns False without raising."""
        assert iph.hook_already_installed(tmp_path / "missing-hook") is False


# ---------------------------------------------------------------------------
# shebang_warning
# ---------------------------------------------------------------------------


class TestShebangWarning:
    """Cover the compatible-vs-unusual shebang branches."""

    @pytest.mark.parametrize(
        "shebang",
        ["#!/bin/sh", "#!/bin/bash", "#!/usr/bin/env bash", "#!/usr/bin/env zsh", ""],
    )
    def test_returns_none_for_compatible_shebangs(self, tmp_path: Path, shebang: str):
        """All compatible shebangs (and missing one) produce no warning."""
        hook = tmp_path / "post-commit"
        body = "echo hi\n"
        hook.write_text((shebang + "\n" if shebang else "") + body, encoding="utf-8")
        assert iph.shebang_warning(hook) is None

    def test_warns_for_unusual_interpreter(self, tmp_path: Path):
        """Non-shell shebang (e.g. python) yields a warning string."""
        hook = tmp_path / "post-commit"
        hook.write_text("#!/usr/bin/env python3\nprint('x')\n", encoding="utf-8")
        warning = iph.shebang_warning(hook)
        assert warning is not None
        assert "unusual interpreter" in warning
        assert "#!/usr/bin/env python3" in warning


# ---------------------------------------------------------------------------
# install_hook
# ---------------------------------------------------------------------------


class TestInstallHook:
    """Cover create / append / idempotency outcomes of the install routine."""

    def test_creates_new_hook_when_missing(self, tmp_path: Path):
        """Absent hook file → created with executable bit + canonical body."""
        hook = tmp_path / "hooks" / "post-commit"
        exit_code, lines = iph.install_hook(hook)
        assert exit_code == 0
        assert hook.is_file()
        content = hook.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/sh")
        assert iph.HOOK_MARKER in content
        assert "scan-index --incremental" in content
        # Executable for owner.
        assert hook.stat().st_mode & 0o100
        assert any("created" in line for line in lines)

    def test_appends_to_existing_hook_without_marker(self, tmp_path: Path):
        """Existing compatible hook → appended; original content preserved."""
        hook = tmp_path / "post-commit"
        original = "#!/bin/sh\necho pre-existing\n"
        hook.write_text(original, encoding="utf-8")
        exit_code, lines = iph.install_hook(hook)
        assert exit_code == 0
        content = hook.read_text(encoding="utf-8")
        assert content.startswith(original)
        assert iph.HOOK_MARKER in content
        assert any("appended" in line for line in lines)

    def test_idempotent_when_marker_already_present(self, tmp_path: Path):
        """Marker present → no write, status line says already installed."""
        hook = tmp_path / "post-commit"
        body = "#!/bin/sh\n# codemap: incremental rebuild\n"
        hook.write_text(body, encoding="utf-8")
        mtime_before = hook.stat().st_mtime
        exit_code, lines = iph.install_hook(hook)
        assert exit_code == 0
        assert hook.read_text(encoding="utf-8") == body
        assert hook.stat().st_mtime == mtime_before
        assert any("already installed" in line for line in lines)

    def test_append_path_surfaces_shebang_warning(self, tmp_path: Path):
        """Unusual shebang on existing file → warning line precedes appended status."""
        hook = tmp_path / "post-commit"
        hook.write_text("#!/usr/bin/env python3\nprint('x')\n", encoding="utf-8")
        exit_code, lines = iph.install_hook(hook)
        assert exit_code == 0
        assert any("unusual interpreter" in line for line in lines)
        assert any("appended" in line for line in lines)


# ---------------------------------------------------------------------------
# resolve_hooks_dir
# ---------------------------------------------------------------------------


class TestResolveHooksDir:
    """Cover the ``core.hooksPath`` override and the git-absent fallback."""

    def test_default_when_no_override(self, tmp_path: Path):
        """Plain repo (no ``core.hooksPath`` configured) → ``.git/hooks``."""
        _init_repo(tmp_path)
        assert iph.resolve_hooks_dir(cwd=tmp_path) == Path(".git/hooks")

    def test_honours_core_hookspath_override(self, tmp_path: Path):
        """``git config core.hooksPath`` value is returned verbatim."""
        _init_repo(tmp_path)
        custom = tmp_path / "custom-hooks"
        custom.mkdir()
        subprocess.run(
            ["git", "config", "core.hooksPath", str(custom)],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        assert iph.resolve_hooks_dir(cwd=tmp_path) == custom

    def test_falls_back_when_git_unavailable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """If git binary missing on PATH, falls back to ``.git/hooks``."""
        monkeypatch.setenv("PATH", "")
        assert iph.resolve_hooks_dir(cwd=tmp_path) == Path(".git/hooks")


# ---------------------------------------------------------------------------
# _make_hook_body
# ---------------------------------------------------------------------------


class TestMakeHookBody:
    """Cover the hook body generator with and without a baked plugin root."""

    def test_without_plugin_root_uses_command_v(self):
        """No plugin_root → body uses ``command -v scan-index`` only."""
        body = iph._make_hook_body(None)
        assert "command -v scan-index" in body
        assert "/bin/scan-index" not in body

    def test_with_plugin_root_bakes_absolute_path(self):
        """plugin_root provided → absolute ``scan-index`` path appears as primary check."""
        body = iph._make_hook_body("/my/plugin/root")
        assert "/my/plugin/root/bin/scan-index" in body

    def test_with_plugin_root_retains_command_v_fallback(self):
        """Baked-path form still includes ``command -v`` as fallback."""
        body = iph._make_hook_body("/some/root")
        assert "command -v scan-index" in body

    def test_marker_present_in_both_forms(self):
        """HOOK_MARKER is present regardless of plugin_root."""
        assert iph.HOOK_MARKER in iph._make_hook_body(None)
        assert iph.HOOK_MARKER in iph._make_hook_body("/x")


# ---------------------------------------------------------------------------
# install_hook with plugin_root
# ---------------------------------------------------------------------------


class TestInstallHookWithPluginRoot:
    """Cover the plugin_root path in install_hook."""

    def test_creates_hook_with_baked_path(self, tmp_path: Path):
        """New hook created with --plugin-root bakes the absolute scan-index path."""
        hook = tmp_path / "hooks" / "post-commit"
        exit_code, lines = iph.install_hook(hook, plugin_root="/my/plugin")
        assert exit_code == 0
        content = hook.read_text(encoding="utf-8")
        assert "/my/plugin/bin/scan-index" in content
        assert "command -v scan-index" in content  # fallback present

    def test_appends_hook_with_baked_path(self, tmp_path: Path):
        """Existing hook appended with baked path when plugin_root supplied."""
        hook = tmp_path / "post-commit"
        hook.write_text("#!/bin/sh\necho existing\n", encoding="utf-8")
        exit_code, _ = iph.install_hook(hook, plugin_root="/abs/path")
        assert exit_code == 0
        content = hook.read_text(encoding="utf-8")
        assert "/abs/path/bin/scan-index" in content


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


class TestMain:
    """End-to-end CLI behaviour via ``main(argv)`` inside a real git repo."""

    def test_main_creates_hook_in_fresh_repo(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """First run in a fresh repo creates ``.git/hooks/post-commit``."""
        repo = _init_repo(tmp_path)
        monkeypatch.chdir(repo)
        rc = iph.main([])
        out = capsys.readouterr().out
        assert rc == 0
        hook = repo / ".git" / "hooks" / "post-commit"
        assert hook.is_file()
        assert iph.HOOK_MARKER in hook.read_text(encoding="utf-8")
        assert "created" in out

    def test_main_with_plugin_root_bakes_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """``--plugin-root`` bakes absolute scan-index path into created hook."""
        repo = _init_repo(tmp_path)
        monkeypatch.chdir(repo)
        rc = iph.main(["--plugin-root", "/baked/root"])
        capsys.readouterr()
        assert rc == 0
        hook = repo / ".git" / "hooks" / "post-commit"
        content = hook.read_text(encoding="utf-8")
        assert "/baked/root/bin/scan-index" in content

    def test_main_is_idempotent_on_second_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        """Re-running on an already-installed hook reports already installed without modifying."""
        repo = _init_repo(tmp_path)
        monkeypatch.chdir(repo)
        assert iph.main([]) == 0
        capsys.readouterr()  # discard first-run output
        hook = repo / ".git" / "hooks" / "post-commit"
        before = hook.read_text(encoding="utf-8")
        mtime_before = hook.stat().st_mtime
        rc = iph.main([])
        out = capsys.readouterr().out
        assert rc == 0
        assert "already installed" in out
        assert hook.read_text(encoding="utf-8") == before
        assert hook.stat().st_mtime == mtime_before
