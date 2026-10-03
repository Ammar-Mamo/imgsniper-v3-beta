"""
Round 14: real-time feedback for the long phases that used to print nothing.

A real 75581-image similarity run showed a completely dead console -- no CPU, no
memory, nothing in Task Manager -- for minutes at a time, twice:

  * right after the deletion confirmation, while ``select_best_file()`` walked
    all 23666 groups and opened every image three times (dimensions, the
    resolution boost, then the EXIF date), and
  * right after "Total processed", while the report was being written.

Both phases were doing honest, necessary work on a USB hard disk; the console
simply said nothing, so the user could not tell "thinking" from "dead" and
started pressing keys (see ``console_input`` for what that cost).

Nothing here changes any decision, order or result -- it only makes work that
was already happening VISIBLE. Every helper degrades to a no-op when no console
is supplied, so callers and test suites that pass ``console=None`` behave
exactly as they did before.
"""

from contextlib import contextmanager

from rich.progress import (BarColumn, Progress, SpinnerColumn, TextColumn,
                           TimeElapsedColumn)


def standard_progress(console) -> Progress:
    """The project's one progress style: identical columns to every detector."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    )


class _NullTask:
    """Stands in for a Rich task when there is no console to draw on."""

    def advance(self, *_args, **_kwargs):
        """No-op."""


class _NullProgress:
    """A Progress stand-in so ``console=None`` callers need no branching."""

    def add_task(self, *_args, **_kwargs):
        return _NullTask()

    def update(self, *_args, **_kwargs):
        """No-op."""

    def advance(self, *_args, **_kwargs):
        """No-op."""


@contextmanager
def track(console, description: str, total: int):
    """Yield ``(progress, task_id)`` for a loop with a KNOWN item count.

    Usage::

        with track(console, i18n.get('common.selecting_best'), len(groups)) as (p, t):
            for g in groups:
                ...
                p.advance(t)
    """
    if console is None:
        null = _NullProgress()
        yield null, null.add_task(description, total=total)
        return

    with standard_progress(console) as progress:
        try:
            total = max(0, int(total or 0))
        except (TypeError, ValueError):
            total = 0
        yield progress, progress.add_task(description, total=total)


class _LiveCounter:
    """Spinner plus a growing count, for a walk whose total is unknown."""

    def __init__(self, progress, task_id):
        self._progress = progress
        self._task = task_id
        self.count = 0

    def bump(self, step: int = 1) -> None:
        """Report `step` more items found so far."""
        self.count += step
        self._progress.update(self._task, completed=self.count)


@contextmanager
def live_counter(console, description: str):
    """Yield a counter with no percentage -- the total is not known upfront.

    A directory walk cannot say "of how many", but it can absolutely say
    "41230 files so far", which is the difference between a live tool and a
    frozen one.
    """
    if console is None:
        yield _LiveCounter(_NullProgress(), None)
        return

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TextColumn("{task.completed}"),
        TimeElapsedColumn(),
        console=console,
    )
    with progress:
        yield _LiveCounter(progress, progress.add_task(description, total=None))
