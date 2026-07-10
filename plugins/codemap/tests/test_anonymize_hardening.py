"""Hardening tests for anonymize.py — free-text scrubbing, export separation, salt safety.

Covers the behaviours added by the "anonymize hardening" task, kept apart from the
pre-existing anonymize test file:

- ``error`` / ``stderr`` free-text fields: qualified names embedded in prose are
  pseudonymized token-by-token while surrounding text survives.
- ``not_covered`` lists: each element scrubbed individually (qualified elements
  hashed, plain diagnostic labels untouched).
- Export-dir separation: the default output target is the dedicated export dir,
  never the salt directory.
- Salt safety: writing into any directory that holds a ``.salt`` file is refused
  with a nonzero exit code.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import anonymize

_SALT = b"x" * 32
_BIN = Path(anonymize.__file__)


# ---------------------------------------------------------------------------
# Free-text error / stderr scrubbing
# ---------------------------------------------------------------------------


def test_error_string_with_module_name_is_hashed() -> None:
    """A module name embedded in a free-text error is replaced; prose survives."""
    record = {"cmd": "rdeps", "result": {"error": "module pkg.auth.core not indexed"}}
    out = anonymize.anonymize_record(record, _SALT)
    scrubbed = out["result"]["error"]
    assert "pkg.auth.core" not in scrubbed
    assert scrubbed.startswith("module sym_")
    assert scrubbed.endswith(" not indexed")


def test_error_double_colon_qualname_is_hashed() -> None:
    """A ``module::symbol`` token in error prose is pseudonymized."""
    record = {"result": {"error": "call to pkg.auth::login failed at line 3"}}
    out = anonymize.anonymize_record(record, _SALT)
    scrubbed = out["result"]["error"]
    assert "pkg.auth::login" not in scrubbed
    assert "sym_" in scrubbed
    assert scrubbed.endswith(" failed at line 3")


def test_error_with_multiple_qualnames_hashes_each() -> None:
    """Every qualified token in one error string is replaced independently."""
    record = {"result": {"error": "pkg.a.b calls pkg.c.d but pkg.c.d is missing"}}
    out = anonymize.anonymize_record(record, _SALT)
    scrubbed = out["result"]["error"]
    assert "pkg.a.b" not in scrubbed
    assert "pkg.c.d" not in scrubbed
    # Repeated original -> identical pseudonym (stable within salt).
    first = anonymize._pseudo("pkg.a.b", _SALT)
    second = anonymize._pseudo("pkg.c.d", _SALT)
    assert scrubbed == f"{first} calls {second} but {second} is missing"


def test_error_without_qualname_unchanged() -> None:
    """Free text with no qualified names passes through verbatim."""
    record = {"result": {"error": "index is not valid json"}}
    out = anonymize.anonymize_record(record, _SALT)
    assert out["result"]["error"] == "index is not valid json"


def test_stderr_field_is_hashed() -> None:
    """A qualified name in a captured stderr/traceback field is pseudonymized."""
    record = {"stderr": "Traceback: pkg.auth.core.login raised ValueError"}
    out = anonymize.anonymize_record(record, _SALT)
    scrubbed = out["stderr"]
    assert "pkg.auth.core.login" not in scrubbed
    assert "sym_" in scrubbed
    assert scrubbed.startswith("Traceback: sym_")


def test_stderr_nested_in_result_is_hashed() -> None:
    """A ``stderr`` field nested inside ``result`` is scrubbed too."""
    record = {"result": {"stderr": "error in module.sub.func"}}
    out = anonymize.anonymize_record(record, _SALT)
    assert "module.sub.func" not in out["result"]["stderr"]
    assert "sym_" in out["result"]["stderr"]


def test_non_string_error_field_left_alone() -> None:
    """A non-string ``error`` value (e.g. bool/None) is not treated as free text."""
    record = {"result": {"error": None, "count": 3}}
    out = anonymize.anonymize_record(record, _SALT)
    assert out["result"]["error"] is None
    assert out["result"]["count"] == 3


# ---------------------------------------------------------------------------
# not_covered list scrubbing
# ---------------------------------------------------------------------------


def test_not_covered_list_hashed_per_element() -> None:
    """Qualified ``not_covered`` elements are hashed; plain labels are preserved."""
    record = {
        "result": {
            "not_covered": ["importlib.import_module", "lazy-loading", "pkg.mod::fn"],
        }
    }
    out = anonymize.anonymize_record(record, _SALT)
    nc = out["result"]["not_covered"]
    assert nc[0].startswith("sym_")  # importlib.import_module -> qualified -> hashed
    assert nc[1] == "lazy-loading"  # plain label preserved
    assert nc[2].startswith("sym_")  # pkg.mod::fn -> qualified -> hashed
    assert "importlib.import_module" not in nc
    assert "pkg.mod::fn" not in nc


def test_not_covered_stable_per_element() -> None:
    """Each ``not_covered`` element maps to the same pseudonym as a standalone name."""
    record = {"result": {"not_covered": ["pkg.a.b"]}}
    out = anonymize.anonymize_record(record, _SALT)
    assert out["result"]["not_covered"][0] == anonymize._pseudo("pkg.a.b", _SALT)


def test_not_covered_top_level_list() -> None:
    """A ``not_covered`` list at the record top level is scrubbed as well."""
    record = {"not_covered": ["a.b.c", "dynamic-dispatch"]}
    out = anonymize.anonymize_record(record, _SALT)
    assert out["not_covered"][0].startswith("sym_")
    assert out["not_covered"][1] == "dynamic-dispatch"


def test_not_covered_non_string_elements_survive() -> None:
    """Non-string ``not_covered`` elements are passed through untouched."""
    record = {"result": {"not_covered": [42, None, "pkg.a.b"]}}
    out = anonymize.anonymize_record(record, _SALT)
    nc = out["result"]["not_covered"]
    assert nc[0] == 42
    assert nc[1] is None
    assert nc[2].startswith("sym_")


# ---------------------------------------------------------------------------
# Regression: existing fields still anonymized
# ---------------------------------------------------------------------------


def test_args_module_still_anonymized() -> None:
    """The pre-existing args-payload pseudonymization is unaffected by hardening."""
    record = {"cmd": "rdeps", "args": {"module": "pkg.auth"}}
    out = anonymize.anonymize_record(record, _SALT)
    assert out["args"]["module"].startswith("sym_")
    assert out["cmd"] == "rdeps"


# ---------------------------------------------------------------------------
# Output-path resolution and export separation
# ---------------------------------------------------------------------------


def test_default_out_dir_is_export_not_salt_dir() -> None:
    """The default resolved output lives under the export dir, never the log/salt dir."""
    resolved = anonymize._resolve_output(Path("logs/cli.jsonl"), None, None)
    assert resolved == Path(anonymize.DEFAULT_OUT_DIR) / "cli-anon.jsonl"
    assert "export" in anonymize.DEFAULT_OUT_DIR
    assert "logs" not in resolved.parent.name


def test_explicit_out_dir_used() -> None:
    """An explicit --out-dir places the derived '-anon' file inside it."""
    resolved = anonymize._resolve_output(Path("logs/skills.jsonl"), "my-export", None)
    assert resolved == Path("my-export") / "skills-anon.jsonl"


def test_explicit_output_wins() -> None:
    """An explicit --output overrides --out-dir derivation."""
    resolved = anonymize._resolve_output(Path("logs/cli.jsonl"), "ignored", "out/custom.jsonl")
    assert resolved == Path("out/custom.jsonl")


def test_cli_default_target_has_no_salt(tmp_path: Path) -> None:
    """End-to-end: default export target is created and separate from the salt dir."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    src = log_dir / "cli.jsonl"
    src.write_text('{"cmd":"rdeps","args":{"module":"pkg.auth"}}\n')
    salt_file = log_dir / ".salt"  # salt sits in the log dir, as in production
    export_dir = tmp_path / "export"

    rc = anonymize.main(["--input", str(src), "--out-dir", str(export_dir), "--salt", str(salt_file)])
    assert rc == 0
    out_file = export_dir / "cli-anon.jsonl"
    assert out_file.exists()
    assert not (export_dir / ".salt").exists()  # salt never copied into export dir
    record = json.loads(out_file.read_text().strip())
    assert record["args"]["module"].startswith("sym_")


# ---------------------------------------------------------------------------
# Salt-safety refusal
# ---------------------------------------------------------------------------


def test_dir_has_salt_detects_file(tmp_path: Path) -> None:
    """_dir_has_salt is True only when a .salt file is present."""
    assert not anonymize._dir_has_salt(tmp_path)
    (tmp_path / ".salt").write_text("00")
    assert anonymize._dir_has_salt(tmp_path)


def test_refuse_when_out_dir_contains_salt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Writing into a directory that already holds a .salt file is refused (exit 2)."""
    src = tmp_path / "cli.jsonl"
    src.write_text('{"cmd":"rdeps","args":{"module":"pkg.auth"}}\n')
    unsafe_dir = tmp_path / "logs"
    unsafe_dir.mkdir()
    (unsafe_dir / ".salt").write_text("00" * 32)
    salt_file = tmp_path / "keep" / ".salt"

    rc = anonymize.main(["--input", str(src), "--out-dir", str(unsafe_dir), "--salt", str(salt_file)])
    assert rc == anonymize._EXIT_UNSAFE_OUT_DIR
    assert not (unsafe_dir / "cli-anon.jsonl").exists()  # nothing written
    err = capsys.readouterr().err
    assert "refusing to write" in err
    assert ".salt" in err


def test_refuse_when_explicit_output_dir_contains_salt(tmp_path: Path) -> None:
    """The salt refusal also applies when an explicit --output targets a salt dir."""
    src = tmp_path / "cli.jsonl"
    src.write_text('{"cmd":"rdeps"}\n')
    unsafe_dir = tmp_path / "logs"
    unsafe_dir.mkdir()
    (unsafe_dir / ".salt").write_text("00" * 32)
    salt_file = tmp_path / "keep" / ".salt"

    rc = anonymize.main(
        [
            "--input",
            str(src),
            "--output",
            str(unsafe_dir / "cli-anon.jsonl"),
            "--salt",
            str(salt_file),
        ]
    )
    assert rc == anonymize._EXIT_UNSAFE_OUT_DIR
    assert not (unsafe_dir / "cli-anon.jsonl").exists()


def test_cli_subprocess_refusal_exit_code(tmp_path: Path) -> None:
    """Running the script as a subprocess returns a nonzero exit on salt collision."""
    src = tmp_path / "cli.jsonl"
    src.write_text('{"cmd":"rdeps"}\n')
    unsafe_dir = tmp_path / "logs"
    unsafe_dir.mkdir()
    (unsafe_dir / ".salt").write_text("00" * 32)

    proc = subprocess.run(
        [
            sys.executable,
            str(_BIN),
            "--input",
            str(src),
            "--out-dir",
            str(unsafe_dir),
            "--salt",
            str(tmp_path / "keep" / ".salt"),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert proc.returncode == anonymize._EXIT_UNSAFE_OUT_DIR
    assert "refusing to write" in proc.stderr
