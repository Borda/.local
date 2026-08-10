"""Regression checks for rich shipped Python module documentation."""

from __future__ import annotations

import ast
import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SECTIONS = ("## Purpose", "## Scope", "## Usage", "## Outputs", "## Failure", "## Used by")
MINIMUM_DOCSTRING_CHARACTERS = 700
MINIMUM_SECTION_CHARACTERS = 140


def production_modules() -> list[Path]:
    """Return every shipped Python module except test modules."""
    return sorted(path for path in PLUGIN_ROOT.rglob("*.py") if "tests" not in path.parts)


def test_every_shipped_python_module_explains_its_role() -> None:
    """Require purpose, scope, usage, and caller context at module entry."""
    missing: dict[str, list[str]] = {}
    for module in production_modules():
        document = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        docstring = ast.get_docstring(document, clean=False) or ""
        absent = [section for section in REQUIRED_SECTIONS if section not in docstring]
        for section in REQUIRED_SECTIONS:
            match = re.search(
                rf"^{re.escape(section)}\s*$\n(?P<body>.*?)(?=^## |\Z)", docstring, re.MULTILINE | re.DOTALL
            )
            if match is None:
                continue
            body = match.group("body").strip()
            sentence_count = len(re.findall(r"[.!?](?:\s|$)", body))
            if len(body) < MINIMUM_SECTION_CHARACTERS or sentence_count < 2:
                absent.append(f"expanded {section} section")
        if len(docstring) < MINIMUM_DOCSTRING_CHARACTERS:
            absent.append(f"at least {MINIMUM_DOCSTRING_CHARACTERS} characters")
        if absent:
            missing[module.relative_to(PLUGIN_ROOT).as_posix()] = absent
    assert not missing, f"missing required module-docstring sections: {missing}"
