"""Shared terminal formatting and Rich progress construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any


ARM_ROW_STYLES = {
    "A_plain": "yellow",
    "B_auto": "cyan",
    "B_direct": "cyan",
    "B_direct_required": "cyan",
    "C_skill": "magenta",
    "C_skill_required": "magenta",
    "C_strict": "magenta",
}


def format_artifact_block(**artifacts: str | Path) -> str:
    """Format two or more durable artifact paths as a scannable terminal block.

    Args:
        **artifacts: Ordered artifact labels and their persisted paths.

    Returns:
        Plain, ANSI-free terminal text with one labeled artifact per line.

    Raises:
        ValueError: If fewer than two artifacts are supplied.
    """
    if len(artifacts) < 2:
        raise ValueError("an artifact block requires at least two labeled paths")
    return "ARTIFACTS:\n" + "\n".join(f" - {label}={path}" for label, path in artifacts.items())


def format_quality(quality: float | None) -> str:
    """Format a score in a six-character column.

    Args:
        quality: Score in the benchmark's continuous [0, 1] range, if available.
    Returns:
        A six-character display value such as ``"1.000 "`` or ``"0.258 "``.
    """
    score = "?" if quality is None else f"{float(quality):.3f}"
    return score.ljust(6)


def fmt_tok(v: float) -> str:
    """Format a token count with a k/M unit suffix.

    Millions get one decimal (``1.5M``); anything ``>=1000`` becomes ``k`` (``937.6k``);
    smaller counts print raw (``842``). Used for both input and output token columns so
    they read consistently across runners.

    Args:
        v: Token count.

    Returns:
        Formatted count, e.g. ``"1.5M"``, ``"937.6k"``, or ``"842"``.

    Examples:
        >>> fmt_tok(1_500_000)
        '1.5M'
        >>> fmt_tok(937_600)
        '937.6k'
        >>> fmt_tok(842)
        '842'
    """
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}M"
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    return f"{int(v)}"


def fmt_time(seconds: float) -> str:
    """Format an elapsed duration as ``2m5s`` (minutes + seconds).

    The minute part is dropped below one minute (``45s``); seconds are rounded to the nearest
    integer. Used for the per-run and progress time columns so they read consistently across runners.

    Args:
        seconds: Elapsed wall-clock seconds.

    Returns:
        ``"<m>m<s>s"`` at or above a minute, else ``"<s>s"``.

    Examples:
        >>> fmt_time(125)
        '2m5s'
        >>> fmt_time(45.4)
        '45s'
        >>> fmt_time(0)
        '0s'
    """
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m{secs}s" if minutes else f"{secs}s"


def print_arm_row(row: str, arm: str, *, console: Any) -> None:
    """Render one benchmark arm row with Rich color only on interactive terminals.

    Args:
        row: Fully formatted plain-text result row.
        arm: Canonical benchmark arm label.
        console: Rich console configured by the provider runner.

    Raises:
        ValueError: If the row uses an unknown benchmark arm.
    """
    try:
        style = ARM_ROW_STYLES[arm]
    except KeyError as exc:
        raise ValueError(f"unknown benchmark arm {arm!r}") from exc
    if console.is_terminal:
        console.print(row, style=style, markup=False, highlight=False, soft_wrap=True)
        return
    print(row)


def make_progress(console: Any):
    """Build the standard five-column rich ``Progress`` used by every runner's live bar.

    ``rich`` is imported lazily so this module stays importable where rich is optional
    (the CLI runner guards its rich import).

    Args:
        console: The rich ``Console`` to render into.

    Returns:
        A configured ``rich.progress.Progress`` (spinner · description · bar · percent).
    """
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    )
