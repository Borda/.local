#!/usr/bin/env python
"""install_post_commit_hook.py — install or append the codemap incremental rebuild hook idempotently.

Usage:
    python "${CLAUDE_PLUGIN_ROOT}/bin/install_post_commit_hook.py" --plugin-root "${CLAUDE_PLUGIN_ROOT}"

The ``--plugin-root`` argument bakes the absolute path to ``scan-index`` into the hook body so the
hook works in regular terminal commits (where the plugin bin/ dir is not on PATH).  Without it the
hook falls back to ``command -v scan-index`` (Claude Code sessions only).

Output:
    Single ✓/⚠ status line indicating install / append / already-installed result.

Exit codes:
    0 — hook present after run (created, appended, or already installed).
    1 — write failure (filesystem error).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HOOK_MARKER = "# codemap: incremental"
_VALID_PLUGIN_ROOT_RE = re.compile(r"^[a-zA-Z0-9_./-]+$")


def _make_hook_body(plugin_root: str | None) -> str:
    """Return the hook body fragment, optionally with an absolute ``scan-index`` path baked in.

    Args:
        plugin_root: Value of ``CLAUDE_PLUGIN_ROOT`` at install time.  When provided the hook
            uses the absolute path as primary invocation and ``command -v`` as fallback.  When
            ``None`` the hook uses ``command -v`` only (works inside Claude Code sessions).

    Returns:
        Multi-line shell fragment starting with a newline (suitable for appending).

    Raises:
        ValueError: if ``plugin_root`` contains characters outside ``[a-zA-Z0-9_./-]`` — only
            this charset is safe inside double-quoted shell strings; anything else allows command
            injection via the embedded hook body.

    Examples:
        >>> body = _make_hook_body(None)
        >>> "command -v scan-index" in body
        True
        >>> body_abs = _make_hook_body("/some/path")
        >>> "/some/path/bin/scan-index" in body_abs
        True
        >>> "command -v scan-index" in body_abs  # fallback still present
        True
    """
    if plugin_root and not _VALID_PLUGIN_ROOT_RE.match(str(plugin_root)):
        raise ValueError(f"plugin_root contains disallowed characters (only a-zA-Z0-9_./- allowed): {plugin_root}")
    if plugin_root:
        scan = f"{plugin_root}/bin/scan-index"
        return (
            "\n# codemap: incremental index rebuild — do not remove this line\n"
            f'if [ -x "{scan}" ]; then\n'
            f'    "{scan}" --incremental >> /tmp/codemap-hook.log 2>&1 &\n'
            "elif command -v scan-index >/dev/null 2>&1; then\n"
            "    scan-index --incremental >> /tmp/codemap-hook.log 2>&1 &\n"
            "fi\n"
        )
    return (
        "\n# codemap: incremental index rebuild — do not remove this line\n"
        "if command -v scan-index >/dev/null 2>&1; then\n"
        "    scan-index --incremental >> /tmp/codemap-hook.log 2>&1 &\n"
        "fi\n"
    )


# Backward-compatible module-level constants (plugin_root=None form).
HOOK_BODY = _make_hook_body(None)
HOOK_FILE_NEW = "#!/bin/sh" + _make_hook_body(None)

COMPATIBLE_SHEBANGS: frozenset[str] = frozenset(
    {
        "#!/bin/sh",
        "#!/bin/bash",
        "#!/usr/bin/env bash",
        "#!/usr/bin/env sh",
        "#!/bin/zsh",
        "#!/usr/bin/env zsh",
        "",
    }
)


def resolve_hooks_dir(cwd: Path | None = None, timeout: int = 5) -> Path:
    """Resolve the git hooks directory honouring ``core.hooksPath``.

    Args:
        cwd: working directory to query (defaults to the current process cwd).
        timeout: Subprocess timeout in seconds for the git config call (default: 5).

    Returns:
        Absolute or repo-relative path to the hooks directory.
    """
    try:
        completed = subprocess.run(
            ["git", "config", "core.hooksPath"],
            capture_output=True,
            text=True,
            cwd=str(cwd) if cwd is not None else None,
            check=False,
            timeout=timeout,
        )
        configured = completed.stdout.strip()
        if completed.returncode == 0 and configured:
            return Path(configured)
    except (OSError, FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return Path(".git/hooks")


def hook_already_installed(hook_file: Path) -> bool:
    """Return ``True`` if ``hook_file`` exists and contains the codemap marker.

    Args:
        hook_file: path to the post-commit hook.

    Returns:
        Whether the marker line is present (exact substring match).

    Examples:
        >>> import tempfile, os
        >>> from pathlib import Path
        >>> with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        ...     _ = fh.write("#!/bin/sh\\n# codemap: incremental\\n")
        ...     path = Path(fh.name)
        >>> hook_already_installed(path)
        True
        >>> hook_already_installed(Path("/nonexistent/path/post-commit-xyz"))
        False
        >>> os.unlink(path)
    """
    if not hook_file.is_file():
        return False
    try:
        return HOOK_MARKER in hook_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def shebang_warning(hook_file: Path) -> str | None:
    """Return a warning message if the existing hook's shebang is non-standard.

    Args:
        hook_file: path to the existing hook file.

    Returns:
        Warning string when interpreter is unusual; ``None`` for compatible (or missing) shebang.
    """
    try:
        with hook_file.open("r", encoding="utf-8", errors="replace") as fh:
            first_line = fh.readline().rstrip("\n")
    except OSError:
        return None
    if first_line in COMPATIBLE_SHEBANGS:
        return None
    if not first_line.startswith("#!"):
        return None
    return f"⚠ post-commit hook uses unusual interpreter: {first_line} — appending anyway; verify compatibility"


def install_hook(hook_file: Path, plugin_root: str | None = None) -> tuple[int, list[str]]:
    """Install, append, or no-op the codemap post-commit hook.

    Args:
        hook_file: target hook path.
        plugin_root: value of ``CLAUDE_PLUGIN_ROOT`` at install time.  When provided, the hook
            body uses the absolute ``scan-index`` path so the hook runs outside Claude Code
            sessions (e.g. regular terminal commits).

    Returns:
        Tuple of ``(exit_code, status_lines)``. ``status_lines`` contains the lines to print
        (no trailing newlines).
    """
    if hook_already_installed(hook_file):
        return 0, [f"✓ post-commit hook: already installed ({hook_file})"]

    hook_body = _make_hook_body(plugin_root)
    hook_file_new = "#!/bin/sh" + hook_body

    if hook_file.exists():
        lines: list[str] = []
        warning = shebang_warning(hook_file)
        if warning is not None:
            lines.append(warning)
        try:
            with hook_file.open("a", encoding="utf-8") as fh:
                fh.write(hook_body)
        except OSError as exc:
            return 1, [f"✗ post-commit hook: failed to append to {hook_file}: {exc}"]
        lines.append(f"✓ post-commit hook: appended to {hook_file}")
        return 0, lines

    try:
        hook_file.parent.mkdir(parents=True, exist_ok=True)
        hook_file.write_text(hook_file_new, encoding="utf-8")
        hook_file.chmod(0o755)
    except OSError as exc:
        return 1, [f"✗ post-commit hook: failed to create {hook_file}: {exc}"]
    return 0, [f"✓ post-commit hook: created {hook_file}"]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: optional argv override for testing.

    Returns:
        Process exit code (0 = hook present, 1 = write failure).
    """
    parser = argparse.ArgumentParser(
        description="Install or append the codemap incremental rebuild post-commit hook idempotently.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Subprocess timeout in seconds for git config call (default: 5).",
    )
    parser.add_argument(
        "--plugin-root",
        default=None,
        help=(
            "Value of CLAUDE_PLUGIN_ROOT at install time.  Bakes the absolute scan-index path "
            "into the hook so it runs outside Claude Code sessions (regular terminal commits)."
        ),
    )
    args = parser.parse_args(argv)

    hooks_dir = resolve_hooks_dir(timeout=args.timeout)
    hook_file = hooks_dir / "post-commit"
    exit_code, lines = install_hook(hook_file, plugin_root=args.plugin_root)
    sys.stdout.write("\n".join(lines) + "\n")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
