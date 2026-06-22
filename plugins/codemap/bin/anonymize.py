#!/usr/bin/env python
"""anonymize.py — replace qualified names in codemap JSONL logs with salted pseudonyms.

Pseudonyms are stable within a project (same salt + same name → same pseudonym)
but opaque to anyone without the salt file. Never share the salt alongside the
anonymized log — the salt lives only at ``--salt`` path (default local to project).

Usage:
    python anonymize.py --input cli.jsonl --output cli-anon.jsonl
    python anonymize.py --input skills.jsonl --output skills-anon.jsonl [--salt PATH]

Exit codes:
    0 — success
    1 — input file not found
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path


def _load_salt(salt_file: Path) -> bytes:
    """Load salt from file, creating it with a fresh random value if absent.

    Args:
        salt_file: Path to the salt file (hex-encoded 32 bytes).

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
    salt_file.write_text(salt.hex())
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


def anonymize_record(record: dict, salt: bytes) -> dict:
    """Anonymize one JSONL log record in-place (returns new dict).

    Replaces qualified names in ``args``, ``argv``, ``intent``, and ``target``
    fields. Leaves all other fields (timestamps, counts, flags) unchanged.

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
    """
    out = dict(record)
    if "args" in out and isinstance(out["args"], dict):
        out["args"] = _anonymize_value(out["args"], salt)
    if "argv" in out and isinstance(out["argv"], list):
        out["argv"] = [_pseudo(a, salt) if isinstance(a, str) and _is_qualified(a) else a for a in out["argv"]]
    for field in ("intent", "target"):
        if field in out and isinstance(out[field], str) and _is_qualified(out[field]):
            out[field] = _pseudo(out[field], salt)
    return out


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


def main(argv: list[str] | None = None) -> int:
    """Entry point for the anonymize CLI.

    Args:
        argv: Override ``sys.argv[1:]`` (mainly for testing).

    Returns:
        0 on success, 1 if input not found.
    """
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Source JSONL log file")
    parser.add_argument("--output", required=True, help="Destination anonymized JSONL file")
    parser.add_argument(
        "--salt",
        default=".cache/codemap/logs/.salt",
        help="Salt file path (created with random value if absent; keep local — never share)",
    )
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"anonymize: input not found: {input_path}", file=sys.stderr)
        return 1

    salt = _load_salt(Path(args.salt))
    output_path = Path(args.output)
    processed, skipped = process(input_path, output_path, salt)
    print(f"anonymize: {processed} records → {output_path}" + (f" ({skipped} skipped)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
