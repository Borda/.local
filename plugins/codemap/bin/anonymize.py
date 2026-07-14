#!/usr/bin/env python
"""anonymize.py — replace qualified names in codemap JSONL logs with salted pseudonyms.

Pseudonyms are stable within a project (same salt + same name → same pseudonym)
but opaque to anyone without the salt file. Never share the salt alongside the
anonymized log — the salt lives only at ``--salt`` path (default local to project).

Anonymized ``-anon.jsonl`` files are written to a dedicated export directory
(``--out-dir``, default ``.cache/codemap/export/``) that is deliberately separate
from the salt directory. Writing anonymized output into any directory that holds a
``.salt`` file is refused outright: a recipient handed both the output and the salt
could reverse every pseudonym.

Usage:
    python anonymize.py --input cli.jsonl
    python anonymize.py --input skills.jsonl --out-dir .cache/codemap/export [--salt PATH]
    python anonymize.py --input cli.jsonl --output /explicit/path/cli-anon.jsonl

Exit codes:
    0 — success
    1 — input file not found
    2 — refused: output directory contains a salt file
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

#: Default directory for anonymized ``-anon.jsonl`` output. Deliberately distinct
#: from the log/salt directory so anonymized shards are never written next to the
#: salt that would make their pseudonyms reversible.
DEFAULT_OUT_DIR = ".cache/codemap/export"

#: Filename that, when present in a target directory, marks it as salt-bearing.
#: Writing anonymized output beside this file would let a recipient of both the
#: output and the salt reverse every pseudonym — so it is refused.
SALT_FILENAME = ".salt"

#: Exit code returned when the resolved output directory holds a salt file.
_EXIT_UNSAFE_OUT_DIR = 2

#: Matches a qualified-name token embedded in free text: an identifier followed by
#: at least one ``.`` or ``::`` separator plus a further identifier (e.g. ``pkg.auth``,
#: ``pkg.auth::login``, ``mod::Class.method``). Lets error/stderr prose be scrubbed
#: token-by-token without swallowing the surrounding words or punctuation.
_QUALIFIED_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|::)[A-Za-z_][A-Za-z0-9_]*)+")

#: Record fields whose string values are free-text that may embed qualified names
#: inline (error messages, captured ``stderr``/tracebacks). Scrubbed per-token,
#: preserving surrounding prose, rather than replaced wholesale.
_FREE_TEXT_FIELDS = ("error", "stderr")


def _load_salt(salt_file: Path) -> bytes:
    """Load salt from file, creating it with a fresh random value if absent.

    Args:
        salt_file: Path to the salt file (hex-encoded 32 bytes).

    The salt file is created 0o600 (owner read/write only): the module guarantees
    pseudonyms are "opaque to anyone without the salt", so a world/group-readable
    salt on a multi-user host or shared CI runner would let any local user reverse
    every pseudonym. ``O_CREAT | O_EXCL`` also closes the exists→create race — a
    concurrent writer that wins the create is deferred to by re-reading the file.

    Returns:
        32-byte salt as raw bytes.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     s = _load_salt(pathlib.Path(d) / ".salt")
        ...     len(s) == 32 and s == _load_salt(pathlib.Path(d) / ".salt")
        True
    """
    if salt_file.exists():
        return bytes.fromhex(salt_file.read_text().strip())
    salt = secrets.token_bytes(32)
    salt_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(salt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # A concurrent writer created the salt between our exists-check and open;
        # defer to it rather than overwrite so both processes share one salt.
        return bytes.fromhex(salt_file.read_text().strip())
    with os.fdopen(fd, "w") as f:
        if hasattr(os, "fchmod"):
            os.fchmod(f.fileno(), 0o600)  # exact 0o600 regardless of the process umask
        f.write(salt.hex())
    return salt


def _pseudo(value: str, salt: bytes) -> str:
    """Return a stable salted pseudonym for a qualified name.

    Args:
        value: The original symbol or module name.
        salt: Per-project random salt.

    Returns:
        Short pseudonym string starting with ``sym_``.

    Examples:
        >>> s = b'x' * 32
        >>> p = _pseudo("pkg.auth::login", s)
        >>> p.startswith("sym_") and len(p) == 16
        True
        >>> _pseudo("pkg.auth::login", s) == _pseudo("pkg.auth::login", s)
        True
    """
    digest = hashlib.sha256(salt + value.encode()).hexdigest()[:12]
    return f"sym_{digest}"


def _is_qualified(v: str) -> bool:
    """Return True if v looks like a qualified Python name (contains . or ::).

    Args:
        v: String to check.

    Returns:
        Whether v appears to be a qualified name.

    Examples:
        >>> _is_qualified("pkg.auth")
        True
        >>> _is_qualified("pkg::login")
        True
        >>> _is_qualified("short")
        False
    """
    return "." in v or "::" in v


def _anonymize_text(text: str, salt: bytes) -> str:
    """Replace every qualified-name token embedded in free text with its pseudonym.

    Unlike :func:`_anonymize_value`, which pseudonymizes a string only when the
    *whole* value is a qualified name, this scans inside prose (error messages,
    captured stderr / tracebacks) and rewrites each qualified token found while
    leaving the surrounding words and punctuation intact.

    Args:
        text: Free-text string that may contain zero or more qualified names.
        salt: Per-project salt bytes.

    Returns:
        The text with each qualified-name token replaced by its ``sym_`` pseudonym.

    Examples:
        >>> s = b'x' * 32
        >>> out = _anonymize_text("module pkg.auth::login not indexed", s)
        >>> "pkg.auth::login" in out
        False
        >>> out.startswith("module sym_") and out.endswith(" not indexed")
        True
        >>> _anonymize_text("no qualified names here", s)
        'no qualified names here'
    """
    return _QUALIFIED_TOKEN_RE.sub(lambda m: _pseudo(m.group(0), salt), text)


def _anonymize_value(v: object, salt: bytes) -> object:
    """Recursively replace qualified names with pseudonyms.

    Args:
        v: Any JSON-compatible value.
        salt: Per-project salt.

    Returns:
        Value with qualified strings replaced.
    """
    if isinstance(v, str) and _is_qualified(v):
        return _pseudo(v, salt)
    if isinstance(v, dict):
        return {k: _anonymize_value(val, salt) for k, val in v.items()}
    if isinstance(v, list):
        return [_anonymize_value(item, salt) for item in v]
    return v


def _scrub_special_fields(v: object, salt: bytes) -> object:
    """Recursively scrub free-text (``error``/``stderr``) and ``not_covered`` fields.

    Walks any nested dict/list structure. For dict keys in :data:`_FREE_TEXT_FIELDS`
    the string value is scrubbed token-by-token (see :func:`_anonymize_text`), so
    qualified names embedded in error messages and captured stderr are pseudonymized
    while their surrounding prose survives. For a ``not_covered`` key holding a list,
    each element is scrubbed individually: qualified-name elements become pseudonyms,
    plain diagnostic labels (e.g. ``lazy-loading``) pass through unchanged.

    This complements — and is applied alongside — :func:`_anonymize_value`, which
    handles whole-value qualified names in the ``args`` payload.

    Args:
        v: Any JSON-compatible value (record, nested dict, list, or scalar).
        salt: Per-project salt bytes.

    Returns:
        A new value with the special fields scrubbed; non-special data unchanged.

    Examples:
        >>> s = b'x' * 32
        >>> out = _scrub_special_fields({"error": "boom in pkg.auth"}, s)
        >>> out["error"].startswith("boom in sym_")
        True
        >>> nc = _scrub_special_fields({"not_covered": ["a.b", "lazy-loading"]}, s)
        >>> nc["not_covered"][0].startswith("sym_"), nc["not_covered"][1]
        (True, 'lazy-loading')
    """
    if isinstance(v, dict):
        scrubbed: dict = {}
        for key, val in v.items():
            if key in _FREE_TEXT_FIELDS and isinstance(val, str):
                scrubbed[key] = _anonymize_text(val, salt)
            elif key == "not_covered" and isinstance(val, list):
                scrubbed[key] = [_anonymize_text(e, salt) if isinstance(e, str) else e for e in val]
            else:
                scrubbed[key] = _scrub_special_fields(val, salt)
        return scrubbed
    if isinstance(v, list):
        return [_scrub_special_fields(item, salt) for item in v]
    return v


def anonymize_record(record: dict, salt: bytes) -> dict:
    """Anonymize one JSONL log record in-place (returns new dict).

    Replaces qualified names in ``args``, ``argv``, ``intent``, and ``target``
    fields. In addition, scrubs qualified names embedded in the free-text
    ``error`` / ``stderr`` fields and hashes each element of any ``not_covered``
    list, wherever those fields appear (including nested inside ``result``).
    Leaves all other fields (timestamps, counts, flags) unchanged.

    Args:
        record: Parsed log record.
        salt: Per-project salt bytes.

    Returns:
        New dict with qualified names replaced by pseudonyms.

    Examples:
        >>> s = b'x' * 32
        >>> r = anonymize_record({"cmd": "rdeps", "args": {"module": "pkg.auth"}}, s)
        >>> r["args"]["module"].startswith("sym_")
        True
        >>> r["cmd"]
        'rdeps'
        >>> e = anonymize_record({"result": {"error": "module pkg.auth not indexed"}}, s)
        >>> "pkg.auth" in e["result"]["error"]
        False
    """
    out = _scrub_special_fields(record, salt)
    assert isinstance(out, dict)  # a dict in always yields a dict out
    if "args" in out and isinstance(out["args"], dict):
        out["args"] = _anonymize_value(out["args"], salt)
    if "argv" in out and isinstance(out["argv"], list):
        out["argv"] = [_pseudo(a, salt) if isinstance(a, str) and _is_qualified(a) else a for a in out["argv"]]
    for field in ("intent", "target"):
        if field in out and isinstance(out[field], str) and _is_qualified(out[field]):
            out[field] = _pseudo(out[field], salt)
    return out


def _dir_has_salt(directory: Path) -> bool:
    """Return True if ``directory`` contains a salt file.

    Args:
        directory: Directory to inspect (may not yet exist).

    Returns:
        Whether a :data:`SALT_FILENAME` file lives directly in the directory.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     _dir_has_salt(pathlib.Path(d))
        False
        >>> with tempfile.TemporaryDirectory() as d:
        ...     _ = (pathlib.Path(d) / ".salt").write_text("00")
        ...     _dir_has_salt(pathlib.Path(d))
        True
    """
    return (directory / SALT_FILENAME).exists()


def _resolve_output(input_path: Path, out_dir: str | None, explicit_output: str | None) -> Path:
    """Resolve the anonymized output path from CLI flags.

    An explicit ``--output`` wins when given. Otherwise the file is named
    ``<input-stem>-anon.jsonl`` inside ``out_dir`` (default :data:`DEFAULT_OUT_DIR`).

    Args:
        input_path: The source log file.
        out_dir: ``--out-dir`` value, or None to use the default export directory.
        explicit_output: ``--output`` value, or None to derive from ``out_dir``.

    Returns:
        The resolved destination path (not yet created).

    Examples:
        >>> import pathlib
        >>> _resolve_output(pathlib.Path("logs/cli.jsonl"), None, None).as_posix()
        '.cache/codemap/export/cli-anon.jsonl'
        >>> _resolve_output(pathlib.Path("logs/cli.jsonl"), "exp", None).as_posix()
        'exp/cli-anon.jsonl'
        >>> _resolve_output(pathlib.Path("logs/cli.jsonl"), None, "out/x.jsonl").as_posix()
        'out/x.jsonl'
    """
    if explicit_output is not None:
        return Path(explicit_output)
    base = out_dir if out_dir is not None else DEFAULT_OUT_DIR
    return Path(base) / f"{input_path.stem}-anon.jsonl"


def process(input_path: Path, output_path: Path, salt: bytes) -> tuple[int, int]:
    """Anonymize all records in input_path and write to output_path.

    Args:
        input_path: Source JSONL file.
        output_path: Destination JSONL file (overwritten if exists).
        salt: Per-project salt bytes.

    Returns:
        ``(records_processed, records_skipped)`` tuple.

    Examples:
        >>> import tempfile, pathlib
        >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        ...     _ = f.write('{"cmd":"rdeps","args":{"module":"pkg.auth"}}\\n')
        ...     tmp = pathlib.Path(f.name)
        >>> out = tmp.with_suffix('.out.jsonl')
        >>> process(tmp, out, b'x' * 32)
        (1, 0)
        >>> out.unlink(); tmp.unlink()
    """
    processed = skipped = 0
    with input_path.open() as fin, output_path.open("w") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                anon = anonymize_record(record, salt)
                fout.write(json.dumps(anon, separators=(",", ":")) + "\n")
                processed += 1
            except Exception:  # noqa: BLE001
                skipped += 1
    return processed, skipped


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser for the anonymize CLI."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Source JSONL log file")
    parser.add_argument(
        "--output",
        default=None,
        help="Explicit destination path (overrides --out-dir); still refused if its directory holds a salt file",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help=f"Directory for the '<input>-anon.jsonl' output (default {DEFAULT_OUT_DIR}; never the salt directory)",
    )
    parser.add_argument(
        "--salt",
        default=".cache/codemap/logs/.salt",
        help="Salt file path (created with random value if absent; keep local — never share)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the anonymize CLI.

    Args:
        argv: Override ``sys.argv[1:]`` (mainly for testing).

    Returns:
        0 on success; 1 if input not found; 2 if the output directory holds a salt file.
    """
    args = _build_parser().parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"anonymize: input not found: {input_path}", file=sys.stderr)
        return 1

    output_path = _resolve_output(input_path, args.out_dir, args.output)
    out_dir = output_path.parent
    if _dir_has_salt(out_dir):
        print(
            f"anonymize: refusing to write into {out_dir} — it contains a '{SALT_FILENAME}' file; "
            f"anonymized output beside the salt is reversible. Use --out-dir (default {DEFAULT_OUT_DIR}).",
            file=sys.stderr,
        )
        return _EXIT_UNSAFE_OUT_DIR

    salt = _load_salt(Path(args.salt))
    out_dir.mkdir(parents=True, exist_ok=True)
    processed, skipped = process(input_path, output_path, salt)
    print(f"anonymize: {processed} records → {output_path}" + (f" ({skipped} skipped)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
