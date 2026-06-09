"""Tests for dev_parse_args.py — develop-skill flag parser."""

from __future__ import annotations

import pytest

from dev_parse_args import FlagSpec, extract_flags, parse_specs, run


# ---------------------------------------------------------------------------
# parse_specs
# ---------------------------------------------------------------------------


class TestParseSpecs:
    """parse_specs converts token list into FlagSpec objects."""

    def test_bool_spec(self):
        """--bool produces FlagSpec with correct fields."""
        specs = parse_specs(["--bool", "semble", "SEMBLE_ENABLED", "false"])
        assert specs == [FlagSpec(kind="bool", flag="semble", var="SEMBLE_ENABLED", default="false")]

    def test_neg_bool_spec(self):
        """--neg-bool produces FlagSpec with neg-bool kind."""
        specs = parse_specs(["--neg-bool", "no-challenge", "CHALLENGE_ENABLED", "true"])
        assert specs == [FlagSpec(kind="neg-bool", flag="no-challenge", var="CHALLENGE_ENABLED", default="true")]

    def test_codemap_spec(self):
        """--codemap takes only VAR + DEFAULT (no FLAG token)."""
        specs = parse_specs(["--codemap", "CODEMAP_RAW", "auto"])
        assert specs == [FlagSpec(kind="codemap", flag="", var="CODEMAP_RAW", default="auto")]

    def test_int_spec(self):
        """--int spec stored with default as string."""
        specs = parse_specs(["--int", "max-depth", "MAX_DEPTH", "3"])
        assert specs == [FlagSpec(kind="int", flag="max-depth", var="MAX_DEPTH", default="3")]

    def test_str_spec(self):
        """--str spec with empty default."""
        specs = parse_specs(["--str", "plan", "PLAN_FILE", ""])
        assert specs == [FlagSpec(kind="str", flag="plan", var="PLAN_FILE", default="")]

    def test_multiple_specs(self):
        """Multiple specs parsed in order."""
        specs = parse_specs(
            [
                "--bool",
                "team",
                "TEAM_MODE",
                "false",
                "--codemap",
                "CODEMAP_RAW",
                "auto",
            ]
        )
        assert len(specs) == 2
        assert specs[0].kind == "bool"
        assert specs[1].kind == "codemap"

    def test_unknown_keyword_exits(self):
        """Unknown spec keyword calls sys.exit(1)."""
        with pytest.raises(SystemExit) as exc:
            parse_specs(["--unknown", "foo", "BAR", "baz"])
        assert exc.value.code == 1

    def test_insufficient_tokens_exits(self):
        """Too few tokens after keyword calls sys.exit(1)."""
        with pytest.raises(SystemExit) as exc:
            parse_specs(["--bool", "semble"])
        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# extract_flags — bool / neg-bool
# ---------------------------------------------------------------------------


class TestBoolFlags:
    """Boolean and negated-boolean flag extraction."""

    def test_bool_present(self):
        """--semble present → true."""
        specs = parse_specs(["--bool", "semble", "S", "false"])
        vals, clean = extract_flags("--semble fix auth.py", specs)
        assert vals["S"] == "true"
        assert clean == "fix auth.py"

    def test_bool_absent(self):
        """--semble absent → default."""
        specs = parse_specs(["--bool", "semble", "S", "false"])
        vals, clean = extract_flags("fix auth.py", specs)
        assert vals["S"] == "false"
        assert clean == "fix auth.py"

    def test_neg_bool_present(self):
        """--no-challenge present → false."""
        specs = parse_specs(["--neg-bool", "no-challenge", "CHALLENGE", "true"])
        vals, clean = extract_flags("--no-challenge fix auth.py", specs)
        assert vals["CHALLENGE"] == "false"
        assert clean == "fix auth.py"

    def test_neg_bool_absent(self):
        """--no-challenge absent → default."""
        specs = parse_specs(["--neg-bool", "no-challenge", "CHALLENGE", "true"])
        vals, clean = extract_flags("fix auth.py", specs)
        assert vals["CHALLENGE"] == "true"
        assert clean == "fix auth.py"


# ---------------------------------------------------------------------------
# extract_flags — codemap
# ---------------------------------------------------------------------------


class TestCodemapFlag:
    """Codemap paired-flag extraction with double-condition guard."""

    def test_codemap_absent(self):
        """Neither flag → auto."""
        specs = parse_specs(["--codemap", "CODEMAP_RAW", "auto"])
        vals, _ = extract_flags("fix auth.py", specs)
        assert vals["CODEMAP_RAW"] == "auto"

    def test_codemap_strict(self):
        """--codemap only → strict."""
        specs = parse_specs(["--codemap", "CODEMAP_RAW", "auto"])
        vals, clean = extract_flags("--codemap fix auth.py", specs)
        assert vals["CODEMAP_RAW"] == "strict"
        assert clean == "fix auth.py"

    def test_no_codemap_off(self):
        """--no-codemap → off."""
        specs = parse_specs(["--codemap", "CODEMAP_RAW", "auto"])
        vals, clean = extract_flags("--no-codemap fix auth.py", specs)
        assert vals["CODEMAP_RAW"] == "off"
        assert clean == "fix auth.py"

    def test_both_no_codemap_wins(self):
        """--codemap + --no-codemap together → off (--no-codemap wins)."""
        specs = parse_specs(["--codemap", "CODEMAP_RAW", "auto"])
        vals, clean = extract_flags("--codemap --no-codemap fix auth.py", specs)
        assert vals["CODEMAP_RAW"] == "off"
        assert clean == "fix auth.py"


# ---------------------------------------------------------------------------
# extract_flags — int / str
# ---------------------------------------------------------------------------


class TestValueFlags:
    """Integer and string flag extraction."""

    def test_int_space_form(self):
        """--max-depth 5 → 5."""
        specs = parse_specs(["--int", "max-depth", "MAX_DEPTH", "3"])
        vals, clean = extract_flags("--max-depth 5 fix auth.py", specs)
        assert vals["MAX_DEPTH"] == "5"
        assert clean == "fix auth.py"

    def test_int_eq_form(self):
        """--max-depth=5 → 5."""
        specs = parse_specs(["--int", "max-depth", "MAX_DEPTH", "3"])
        vals, clean = extract_flags("--max-depth=5 fix auth.py", specs)
        assert vals["MAX_DEPTH"] == "5"
        assert clean == "fix auth.py"

    def test_int_absent_default(self):
        """--max-depth absent → default."""
        specs = parse_specs(["--int", "max-depth", "MAX_DEPTH", "3"])
        vals, _ = extract_flags("fix auth.py", specs)
        assert vals["MAX_DEPTH"] == "3"

    def test_int_non_integer_exits(self):
        """Non-integer value for --int flag exits with code 2."""
        specs = parse_specs(["--int", "max-depth", "MAX_DEPTH", "3"])
        with pytest.raises(SystemExit) as exc:
            extract_flags("--max-depth notanumber", specs)
        assert exc.value.code == 2

    def test_str_space_form(self):
        """--plan path/to/file.md → value extracted."""
        specs = parse_specs(["--str", "plan", "PLAN_FILE", ""])
        vals, clean = extract_flags("--plan .plans/active/plan.md fix auth.py", specs)
        assert vals["PLAN_FILE"] == ".plans/active/plan.md"
        assert clean == "fix auth.py"

    def test_str_eq_form(self):
        """--plan=path/to/file.md → value extracted."""
        specs = parse_specs(["--str", "plan", "PLAN_FILE", ""])
        vals, clean = extract_flags("--plan=.plans/active/plan.md fix auth.py", specs)
        assert vals["PLAN_FILE"] == ".plans/active/plan.md"
        assert clean == "fix auth.py"

    def test_str_absent_empty_default(self):
        """--str absent → empty string default."""
        specs = parse_specs(["--str", "plan", "PLAN_FILE", ""])
        vals, _ = extract_flags("fix auth.py", specs)
        assert vals["PLAN_FILE"] == ""

    def test_str_ci_run(self):
        """--ci-run value extracted correctly."""
        specs = parse_specs(["--str", "ci-run", "CI_RUN_ID", ""])
        vals, clean = extract_flags("--ci-run 12345678 fix auth.py", specs)
        assert vals["CI_RUN_ID"] == "12345678"
        assert clean == "fix auth.py"


# ---------------------------------------------------------------------------
# run — output format
# ---------------------------------------------------------------------------


class TestRunOutput:
    """run() emits shell-eval-safe KEY=VALUE lines."""

    def test_single_quote_wrapping(self):
        """All values wrapped in single quotes."""
        out = run("fix auth.py", ["--bool", "semble", "SEMBLE_ENABLED", "false"])
        assert "SEMBLE_ENABLED='false'" in out
        assert "CLEAN_ARGS='fix auth.py'" in out

    def test_clean_args_last_line(self):
        """CLEAN_ARGS is always the last emitted line."""
        out = run("fix auth.py", ["--bool", "semble", "SEMBLE_ENABLED", "false"])
        last = out.strip().splitlines()[-1]
        assert last.startswith("CLEAN_ARGS=")

    def test_whitespace_normalised_in_clean_args(self):
        """Multiple spaces in stripped args collapsed to single space."""
        out = run("  --semble   fix   auth.py  ", ["--bool", "semble", "S", "false"])
        assert "CLEAN_ARGS='fix auth.py'" in out

    def test_shell_single_quote_escaping(self):
        """Single quotes in values are escaped for shell safety."""
        out = run("it's a test", [])
        assert r"CLEAN_ARGS='it'\''" in out or "CLEAN_ARGS='it'\\''s a test'" in out

    def test_combined_flags(self):
        """Multiple flags parsed together; clean args contains remainder."""
        out = run(
            "--no-challenge --codemap --semble fix auth.py",
            [
                "--neg-bool",
                "no-challenge",
                "CHALLENGE_ENABLED",
                "true",
                "--bool",
                "semble",
                "SEMBLE_ENABLED",
                "false",
                "--codemap",
                "CODEMAP_RAW",
                "auto",
            ],
        )
        assert "CHALLENGE_ENABLED='false'" in out
        assert "SEMBLE_ENABLED='true'" in out
        assert "CODEMAP_RAW='strict'" in out
        assert "CLEAN_ARGS='fix auth.py'" in out

    def test_no_specs_passthrough(self):
        """No specs → only CLEAN_ARGS emitted with original args."""
        out = run("fix auth.py", [])
        assert out.strip() == "CLEAN_ARGS='fix auth.py'"
