#!/usr/bin/env python3
"""Generate Python deprecation wrapper code for codemap:rename-refs.

Given symbol type (function/method/class), old name, new name, and optional
version strings, outputs the Python source code to stdout.  The caller inserts
this block immediately after the new definition in the source file.

Requires pyDeprecate (``pip install pyDeprecate``).

Two modes:

**Auto** — supply ``--type``, ``--old-name``, ``--new-name`` (and optionally
``--since`` / ``--removed-in``); the script builds the full decorator line.

**Explicit** — supply ``--decorator "@deprecated(...)"`` (the full decorator
line, already built by the caller) plus ``--old-name``.  The script adds the
correct import statement and the stub definition.

Usage::

    # auto mode — function/method
    python gen_deprecation_wrapper.py \\
        --type function --old-name foo --new-name bar \\
        --since 1.2.0 --removed-in 2.0.0

    # auto mode — class
    python gen_deprecation_wrapper.py \\
        --type class --old-name OldCls --new-name NewCls

    # explicit mode (skill or user supplies full decorator line)
    python gen_deprecation_wrapper.py \\
        --decorator "@deprecated(target=bar, deprecated_in='1.0', remove_in='2.0')" \\
        --old-name foo
"""

from __future__ import annotations

import argparse
import keyword
import re
import sys
import textwrap


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_identifier(name: str, field: str) -> None:
    """Raise ValueError if *name* is not a safe Python identifier.

    Args:
        name: value to validate.
        field: parameter name (for error messages).

    Raises:
        ValueError: when *name* is not a valid Python identifier, is a keyword,
            or is empty.

    Examples:
        >>> _validate_identifier("my_func", "old_name")  # no exception
        >>> _validate_identifier("", "old_name")
        Traceback (most recent call last):
            ...
        ValueError: Invalid Python identifier for old_name: ''
        >>> _validate_identifier("class", "old_name")
        Traceback (most recent call last):
            ...
        ValueError: Invalid Python identifier for old_name: 'class'
    """
    if not name or not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"Invalid Python identifier for {field}: {name!r}")


def _validate_version(ver: str, field: str) -> None:
    """Raise ValueError if *ver* is not a safe version string.

    Accepts ``"?"`` (unknown placeholder) and ``X.Y[.Z]`` numeric forms.

    Args:
        ver: version string to validate.
        field: parameter name (for error messages).

    Raises:
        ValueError: when *ver* is not ``"?"`` and does not match numeric version pattern.

    Examples:
        >>> _validate_version("?", "since")  # no exception
        >>> _validate_version("1.2", "since")  # no exception
        >>> _validate_version("1.2.3", "since")  # no exception
        >>> _validate_version("bad-version", "since")
        Traceback (most recent call last):
            ...
        ValueError: Invalid version string for since: 'bad-version'
    """
    if ver == "?":
        return
    if not re.fullmatch(r"\d+(\.\d+)+", ver):
        raise ValueError(f"Invalid version string for {field}: {ver!r}")


# ---------------------------------------------------------------------------
# Import inference
# ---------------------------------------------------------------------------

_IMPORT_MAP = {
    "deprecated_class": "from deprecate import deprecated_class",
    "deprecated": "from deprecate import deprecated",
}


def _import_for_decorator(decorator: str) -> str:
    """Return the ``from deprecate import ...`` line for *decorator*.

    >>> _import_for_decorator("@deprecated_class(target=New, deprecated_in='1.0', remove_in='2.0')")
    'from deprecate import deprecated_class'
    >>> _import_for_decorator("@deprecated(target=bar, deprecated_in='1.0', remove_in='2.0')")
    'from deprecate import deprecated'
    """
    for key, import_line in _IMPORT_MAP.items():
        if key in decorator:
            return import_line
    raise ValueError(
        f"Cannot infer import — decorator does not contain 'deprecated' or 'deprecated_class': {decorator!r}"
    )


# ---------------------------------------------------------------------------
# Code generators
# ---------------------------------------------------------------------------


def gen_function_wrapper(old_name: str, new_name: str, since: str, removed_in: str) -> str:
    """Return ``@deprecated`` block for a function or method (auto mode).

    Args:
        old_name: bare name of the symbol being deprecated.
        new_name: bare name of the replacement symbol.
        since: ``deprecated_in`` version string (e.g. ``"1.2.0"``).
        removed_in: ``remove_in`` version string (e.g. ``"2.0.0"``).

    Returns:
        Python source string ready to insert after the new definition.

    Raises:
        ValueError: if *old_name* or *new_name* are not valid Python identifiers,
            or if *since*/*removed_in* are not valid version strings.

    Examples:
        >>> code = gen_function_wrapper("old_fn", "new_fn", "1.0", "2.0")
        >>> "deprecated" in code and "old_fn" in code and "new_fn" in code
        True
        >>> "remove_in" in code and "warnings" not in code
        True
    """
    _validate_identifier(old_name, "old_name")
    _validate_identifier(new_name, "new_name")
    _validate_version(since, "since")
    _validate_version(removed_in, "removed_in")
    decorator = f'@deprecated(target={new_name}, deprecated_in="{since}", remove_in="{removed_in}")'
    return gen_wrapper_from_decorator(decorator, old_name, removed_in)


def gen_class_wrapper(old_name: str, new_name: str, since: str, removed_in: str) -> str:
    """Return ``@deprecated_class`` block for a class (auto mode).

    Args:
        old_name: bare name of the class being deprecated.
        new_name: bare name of the replacement class.
        since: ``deprecated_in`` version string.
        removed_in: ``remove_in`` version string.

    Returns:
        Python source string ready to insert after the new definition.

    Raises:
        ValueError: if *old_name* or *new_name* are not valid Python identifiers,
            or if *since*/*removed_in* are not valid version strings.

    Examples:
        >>> code = gen_class_wrapper("OldCls", "NewCls", "1.0", "2.0")
        >>> "deprecated_class" in code and "OldCls" in code and "NewCls" in code
        True
        >>> "warnings" not in code
        True
    """
    _validate_identifier(old_name, "old_name")
    _validate_identifier(new_name, "new_name")
    _validate_version(since, "since")
    _validate_version(removed_in, "removed_in")
    decorator = f'@deprecated_class(target={new_name}, deprecated_in="{since}", remove_in="{removed_in}")'
    return gen_wrapper_from_decorator(decorator, old_name, removed_in)


def gen_wrapper_from_decorator(decorator: str, old_name: str, removed_in: str = "?") -> str:
    """Build wrapper block from an explicit *decorator* line (explicit mode).

    Infers the correct import statement from the decorator name.  Chooses
    ``def`` stub for ``@deprecated`` and ``class`` stub for ``@deprecated_class``.

    Args:
        decorator: full decorator line, e.g. ``"@deprecated(target=bar, ...)"``
        old_name: bare name of the symbol to deprecate.
        removed_in: version string for the comment header.

    Returns:
        Python source string ready to insert after the new definition.

    Raises:
        ValueError: if *decorator* contains neither ``deprecated`` nor
            ``deprecated_class``, or if *old_name* is not a valid Python identifier.

    Examples:
        >>> code = gen_wrapper_from_decorator(
        ...     "@deprecated(target=bar, deprecated_in='1.0', remove_in='2.0')", "foo"
        ... )
        >>> "from deprecate import deprecated" in code
        True
        >>> "def foo(*args, **kwargs): ..." in code
        True
        >>> code = gen_wrapper_from_decorator(
        ...     "@deprecated_class(target=Bar, deprecated_in='1.0', remove_in='2.0')", "Foo"
        ... )
        >>> "from deprecate import deprecated_class" in code
        True
        >>> "class Foo: ..." in code
        True
    """
    _validate_identifier(old_name, "old_name")
    import_line = _import_for_decorator(decorator)
    stub = f"class {old_name}: ..." if "deprecated_class" in decorator else f"def {old_name}(*args, **kwargs): ..."
    return textwrap.dedent(f"""\
        # Deprecated alias — remove after {removed_in} release
        {import_line}


        {decorator}
        {stub}
    """)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate(
    symbol_type: str,
    old_name: str,
    new_name: str,
    since: str = "?",
    removed_in: str = "?",
) -> str:
    """Return deprecation wrapper Python source code (auto mode).

    Args:
        symbol_type: ``"function"``, ``"method"``, or ``"class"``
        old_name: bare symbol name being deprecated (e.g. ``validate_token``)
        new_name: bare replacement symbol name (e.g. ``validate_access_token``)
        since: ``deprecated_in`` version string; default ``"?"`` when unknown
        removed_in: ``remove_in`` version string; default ``"?"`` when unknown

    Returns:
        Multi-line Python source string, ready to insert after the new definition.

    Raises:
        ValueError: if *symbol_type* is not one of the three accepted values.

    Examples:
        >>> "deprecated" in generate("function", "old", "new")
        True
        >>> "deprecated_class" in generate("class", "Old", "New")
        True
        >>> 'deprecated_in="0.9"' in generate("method", "m", "n", since="0.9", removed_in="1.0")
        True
    """
    if symbol_type in ("function", "method"):
        return gen_function_wrapper(old_name, new_name, since, removed_in)
    if symbol_type == "class":
        return gen_class_wrapper(old_name, new_name, since, removed_in)
    raise ValueError(f"Unknown symbol_type {symbol_type!r}. Expected: function, method, class")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Output Python deprecation wrapper code to stdout.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # --- shared ---
    parser.add_argument("--old-name", required=True, help="Bare old symbol name")
    parser.add_argument("--removed-in", default="?", help="remove_in version for comment header (default: ?)")
    # --- auto mode ---
    parser.add_argument(
        "--type",
        dest="symbol_type",
        choices=["function", "method", "class"],
        help="Auto mode: symbol type",
    )
    parser.add_argument("--new-name", help="Auto mode: bare replacement symbol name")
    parser.add_argument("--since", default="?", help="Auto mode: deprecated_in version (default: ?)")
    # --- explicit mode ---
    parser.add_argument(
        "--decorator",
        help='Explicit mode: full decorator line, e.g. "@deprecated(target=bar, ...)"',
    )
    args = parser.parse_args()

    try:
        if args.decorator:
            code = gen_wrapper_from_decorator(args.decorator, args.old_name, args.removed_in)
        elif args.symbol_type and args.new_name:
            code = generate(args.symbol_type, args.old_name, args.new_name, args.since, args.removed_in)
        else:
            parser.error("Provide either --decorator OR both --type and --new-name.")
            return
    except ValueError as exc:
        print(f"! {exc}", file=sys.stderr)
        sys.exit(1)

    print(code, end="")


if __name__ == "__main__":
    main()
