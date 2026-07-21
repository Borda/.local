"""Tests for check_cli_flag_drift — SKILL.md flag vs argparse drift detector (Check 42)."""

from __future__ import annotations

from pathlib import Path

import pytest

from check_cli_flag_drift import (
    DriftFinding,
    command_scope,
    extract_argparse_flags,
    find_drift,
    iter_argparse_scripts,
    main,
)


def _make_script(base: Path, plugin: str, name: str, body: str) -> Path:
    """Write a bin/ script under ``base/<plugin>/bin/<name>`` and return its path."""
    bin_dir = base / plugin / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(body)
    return path


def _make_skill(base: Path, plugin: str, skill: str, body: str) -> Path:
    """Write a SKILL.md under ``base/<plugin>/skills/<skill>/SKILL.md`` and return it."""
    skill_dir = base / plugin / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(body)
    return path


_ARGPARSE_BODY = (
    "import argparse\n"
    "def main():\n"
    "    p = argparse.ArgumentParser()\n"
    "    p.add_argument('--real')\n"
    "    p.add_argument('-r', '--recurse')\n"
)


# ---------------------------------------------------------------------------
# extract_argparse_flags
# ---------------------------------------------------------------------------


class TestExtractArgparseFlags:
    def test_collects_long_and_short_flags(self) -> None:
        flags = extract_argparse_flags(_ARGPARSE_BODY)
        assert flags == {"--real", "-r", "--recurse"}

    def test_none_when_no_add_argument(self) -> None:
        assert extract_argparse_flags("x = 1\n") is None

    def test_positional_only_yields_empty_set(self) -> None:
        assert extract_argparse_flags("p.add_argument('target')\n") == set()

    def test_remainder_passthrough_returns_none(self) -> None:
        src = "import argparse\np.add_argument('extras', nargs=argparse.REMAINDER)\n"
        assert extract_argparse_flags(src) is None

    def test_ellipsis_nargs_returns_none(self) -> None:
        assert extract_argparse_flags("p.add_argument('extras', nargs='...')\n") is None


# ---------------------------------------------------------------------------
# command_scope
# ---------------------------------------------------------------------------


class TestCommandScope:
    def test_single_line_flags(self) -> None:
        scope = command_scope(["x --a --b"], 0, 1)
        assert "--a" in scope and "--b" in scope

    def test_follows_line_continuation(self) -> None:
        scope = command_scope(["x --a \\", "  --b"], 0, 1)
        assert "--a" in scope and "--b" in scope

    def test_stops_at_next_uncontinued_line(self) -> None:
        scope = command_scope(["x --a", "other --b"], 0, 1)
        assert "--a" in scope and "--b" not in scope

    def test_truncates_at_pipe_boundary(self) -> None:
        scope = command_scope(["x --a | grep --b"], 0, 1)
        assert "--a" in scope and "--b" not in scope


# ---------------------------------------------------------------------------
# iter_argparse_scripts
# ---------------------------------------------------------------------------


class TestIterArgparseScripts:
    def test_maps_basename_to_flags(self, tmp_path: Path) -> None:
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        scripts = iter_argparse_scripts(tmp_path)
        assert scripts == {"tool.py": {"--real", "-r", "--recurse"}}

    def test_skips_underscore_private(self, tmp_path: Path) -> None:
        _make_script(tmp_path, "myplugin", "_helper.py", _ARGPARSE_BODY)
        assert iter_argparse_scripts(tmp_path) == {}

    def test_skips_non_argparse_script(self, tmp_path: Path) -> None:
        _make_script(tmp_path, "myplugin", "plain.py", "print('hi')\n")
        assert iter_argparse_scripts(tmp_path) == {}


# ---------------------------------------------------------------------------
# find_drift
# ---------------------------------------------------------------------------


class TestFindDrift:
    def test_drift_flag_is_detected(self, tmp_path: Path) -> None:
        """A documented flag not in the script's argparse is a finding."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --ghost\n')
        findings = find_drift(tmp_path)
        assert [f.flag for f in findings] == ["--ghost"]
        assert findings[0].script == "tool.py"

    def test_real_flag_not_flagged(self, tmp_path: Path) -> None:
        """A flag the script's argparse actually defines is never a finding."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --real\n')
        assert find_drift(tmp_path) == []

    def test_script_flag_never_mentioned_not_flagged(self, tmp_path: Path) -> None:
        """A real argparse flag absent from all SKILL.md is not a finding (accuracy, not completeness)."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", "This skill does things.\n")
        assert find_drift(tmp_path) == []

    def test_prose_mention_contributes_no_flags(self, tmp_path: Path) -> None:
        """A bare backtick reference (no invocation) never anchors a flag."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", "`tool.py` runs. Then `git log --ghost`.\n")
        assert find_drift(tmp_path) == []

    def test_piped_command_flags_not_attributed(self, tmp_path: Path) -> None:
        """Flags after a pipe belong to the piped command, not the script."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" | grep --color\n')
        assert find_drift(tmp_path) == []

    def test_short_flag_in_docs_not_flagged(self, tmp_path: Path) -> None:
        """A single-dash short option near an invocation is ignored (collides with shell operators)."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" -q\n')
        assert find_drift(tmp_path) == []

    def test_bash_test_operators_not_flagged(self, tmp_path: Path) -> None:
        """Bash test operators (-z, -f, -n) on a continued command line are never findings."""
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        body = 'X=$(python "${ROOT}/bin/tool.py" --real) \\\n  && [ -z "$X" ] && [ -f out ]\n'
        _make_skill(tmp_path, "myplugin", "sk", body)
        assert find_drift(tmp_path) == []

    def test_remainder_script_never_drifts(self, tmp_path: Path) -> None:
        """A passthrough (nargs=REMAINDER) script accepts arbitrary flags — no drift."""
        body = "import argparse\np.add_argument('extras', nargs=argparse.REMAINDER)\n"
        _make_script(tmp_path, "myplugin", "pass.py", body)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/pass.py" --anything\n')
        assert find_drift(tmp_path) == []

    def test_finding_is_dataclass(self, tmp_path: Path) -> None:
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --ghost\n')
        assert isinstance(find_drift(tmp_path)[0], DriftFinding)


# ---------------------------------------------------------------------------
# no execution / import of target scripts
# ---------------------------------------------------------------------------


class TestNoExecution:
    def test_target_script_side_effect_never_triggered(self, tmp_path: Path) -> None:
        """The checker must AST-parse, never import/execute, the target script."""
        sentinel = tmp_path / "SIDE_EFFECT"
        body = (
            "import argparse\n"
            f"open({str(sentinel)!r}, 'w').write('x')\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--real')\n"
        )
        _make_script(tmp_path, "myplugin", "tool.py", body)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --ghost\n')
        find_drift(tmp_path)
        assert not sentinel.exists()


# ---------------------------------------------------------------------------
# main (CLI)
# ---------------------------------------------------------------------------


class TestMain:
    def test_exit_0_when_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --real\n')
        rc = main(["--plugins-dir", str(tmp_path)])
        assert rc == 0
        assert "✓" in capsys.readouterr().out

    def test_exit_1_when_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _make_script(tmp_path, "myplugin", "tool.py", _ARGPARSE_BODY)
        _make_skill(tmp_path, "myplugin", "sk", 'python "${ROOT}/bin/tool.py" --ghost\n')
        rc = main(["--plugins-dir", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        assert "⚠ 42" in out and "--ghost" in out

    def test_exit_2_bad_dir(self) -> None:
        rc = main(["--plugins-dir", "/nonexistent/path/does/not/exist"])
        assert rc == 2

    def test_exit_2_default_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert main([]) == 2
