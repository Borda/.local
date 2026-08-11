"""Shared terminal formatting and Rich progress construction."""

from __future__ import annotations

from typing import Any


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
