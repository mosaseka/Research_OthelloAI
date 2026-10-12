"""Small, dependency-free CUI progress reporting helpers.

``ProgressReporter`` keeps an interactive terminal on one line.  When stdout
is redirected to a file or captured by a job runner, it emits timestamp-free,
periodic lines instead so that the resulting log remains readable.

Typical use::

    with ProgressReporter(total=len(records), label="records") as progress:
        for record in records:
            process(record)
            progress.advance()

The output stream and monotonic clock are injectable.  This makes the class
safe to use in tests without sleeping or depending on terminal capabilities.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
import sys
import time
from typing import Generic, TextIO, TypeVar


T = TypeVar("T")
_UNSET = object()


def _duration(seconds: float | None) -> str:
    """Format a non-negative duration without depending on wall-clock time."""

    if seconds is None:
        return "--:--"
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _rate(value: float) -> str:
    if value >= 100:
        return f"{value:.0f}"
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


class ProgressReporter(Generic[T]):
    """Report loop progress to an interactive terminal or redirected log.

    Args:
        total: Expected item count.  ``None`` supports streams of unknown size.
        label: Short description of the work or unit being counted.
        phase: Optional phase name, for example ``"verify"`` or ``"epoch 2"``.
        interval: Minimum seconds between ordinary renders.  A value of zero
            renders on every update.
        quiet: Suppress all output while retaining the same callable API.
        stream: Destination, normally stderr for training diagnostics.
        clock: Monotonic seconds provider; injectable for deterministic tests.
        tty: Override terminal detection.  ``None`` calls ``stream.isatty()``.
        bar_width: Width of the interactive progress bar.
        initial: Initial completed item count.
    """

    def __init__(
        self,
        total: int | None = None,
        *,
        label: str = "items",
        phase: str | int | None = None,
        interval: float = 1.0,
        quiet: bool = False,
        stream: TextIO | None = None,
        clock: Callable[[], float] = time.monotonic,
        tty: bool | None = None,
        bar_width: int = 24,
        initial: int = 0,
    ) -> None:
        if total is not None and total < 0:
            raise ValueError("total must be non-negative or None")
        if initial < 0:
            raise ValueError("initial must be non-negative")
        if interval < 0:
            raise ValueError("interval must be non-negative")
        if bar_width < 4:
            raise ValueError("bar_width must be at least 4")

        self.total = total
        self.label = str(label)
        self.phase = None if phase is None else str(phase)
        self.interval = float(interval)
        self.quiet = bool(quiet)
        self.stream = stream if stream is not None else sys.stderr
        self.clock = clock
        self.bar_width = int(bar_width)
        self.count = int(initial)

        if tty is None:
            isatty = getattr(self.stream, "isatty", None)
            try:
                self.is_tty = bool(isatty()) if callable(isatty) else False
            except (OSError, ValueError):
                self.is_tty = False
        else:
            self.is_tty = bool(tty)

        self._started_at = float(self.clock())
        self._last_render_at: float | None = None
        self._last_width = 0
        self._closed = False

    @property
    def elapsed(self) -> float:
        return max(0.0, float(self.clock()) - self._started_at)

    @property
    def rate(self) -> float:
        elapsed = self.elapsed
        return self.count / elapsed if elapsed > 0 else 0.0

    def _prefix(self) -> str:
        parts = []
        if self.phase:
            parts.append(f"[{self.phase}]")
        if self.label:
            parts.append(self.label)
        return " ".join(parts)

    def _bar(self) -> str:
        if self.total is None:
            # A moving marker communicates activity without pretending that an
            # unknown-length stream has a measurable completion percentage.
            span = self.bar_width - 1
            cycle = 2 * span
            offset = self.count % cycle if cycle else 0
            position = offset if offset <= span else cycle - offset
            cells = ["."] * self.bar_width
            cells[position] = ">"
            return "[" + "".join(cells) + "]"

        fraction = 1.0 if self.total == 0 else self.count / self.total
        fraction = min(1.0, max(0.0, fraction))
        filled = int(fraction * self.bar_width)
        return "[" + "#" * filled + "." * (self.bar_width - filled) + "]"

    def _line(self, now: float) -> str:
        elapsed = max(0.0, now - self._started_at)
        rate = self.count / elapsed if elapsed > 0 else 0.0
        if self.total is None:
            count_text = f"{self.count}"
            eta = None
        else:
            fraction = 1.0 if self.total == 0 else self.count / self.total
            percentage = min(100.0, max(0.0, 100.0 * fraction))
            count_text = f"{self.count}/{self.total} ({percentage:5.1f}%)"
            if self.count >= self.total:
                eta = 0.0
            elif rate > 0:
                eta = (self.total - self.count) / rate
            else:
                eta = None

        fields = []
        prefix = self._prefix()
        if prefix:
            fields.append(prefix)
        if self.is_tty:
            fields.append(self._bar())
        fields.extend(
            (
                count_text,
                f"{_rate(rate)} items/s",
                f"{_duration(elapsed)} elapsed",
                f"{_duration(eta)} ETA",
            )
        )
        return " | ".join(fields)

    def render(self, *, force: bool = False, final: bool = False) -> bool:
        """Render if the interval elapsed; return whether output was written."""

        if self.quiet or self._closed:
            return False
        now = float(self.clock())
        if (
            not force
            and self._last_render_at is not None
            and now - self._last_render_at < self.interval
        ):
            return False

        line = self._line(now)
        if self.is_tty:
            padding = " " * max(0, self._last_width - len(line))
            ending = "\n" if final else ""
            self.stream.write("\r" + line + padding + ending)
            self._last_width = 0 if final else len(line)
        else:
            self.stream.write(line + "\n")
        self.stream.flush()
        self._last_render_at = now
        return True

    def update(
        self,
        current: int | None = None,
        *,
        advance: int = 1,
        label: str | None = None,
        phase: str | int | None = None,
        force: bool = False,
    ) -> bool:
        """Set or increment the completed count and render when due.

        Supplying ``current`` selects absolute-count mode and ignores the
        default ``advance`` value.  Counts are allowed to exceed ``total`` so
        the display can expose an inaccurate estimate rather than hiding it.
        """

        if self._closed:
            return False
        next_count = self.count + advance if current is None else current
        if next_count < 0:
            raise ValueError("progress count must be non-negative")
        self.count = int(next_count)
        if label is not None:
            self.label = str(label)
        if phase is not None:
            self.phase = str(phase)
        return self.render(force=force)

    def advance(self, amount: int = 1, *, force: bool = False) -> bool:
        return self.update(advance=amount, force=force)

    def set_phase(
        self,
        phase: str | int | None,
        *,
        label: str | None = None,
        total: int | None | object = _UNSET,
        reset: bool = False,
        force: bool = True,
    ) -> bool:
        """Change the visible phase and optionally its label, total, and count."""

        if self._closed:
            return False
        self.phase = None if phase is None else str(phase)
        if label is not None:
            self.label = str(label)
        if total is not _UNSET:
            if total is not None and (not isinstance(total, int) or total < 0):
                raise ValueError("total must be a non-negative integer or None")
            self.total = total
        if reset:
            self.count = 0
            self._started_at = float(self.clock())
            self._last_render_at = None
        return self.render(force=force)

    def finish(self, current: int | None = None) -> None:
        """Write a final state and terminate an interactive line safely."""

        if self._closed:
            return
        if current is not None:
            if current < 0:
                raise ValueError("progress count must be non-negative")
            self.count = int(current)
        self.render(force=True, final=True)
        self._closed = True

    close = finish

    def __enter__(self) -> "ProgressReporter[T]":
        self.render(force=True)
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.finish()


def track(
    iterable: Iterable[T],
    *,
    total: int | None = None,
    label: str = "items",
    phase: str | int | None = None,
    interval: float = 1.0,
    quiet: bool = False,
    stream: TextIO | None = None,
    clock: Callable[[], float] = time.monotonic,
    tty: bool | None = None,
) -> Iterator[T]:
    """Yield an iterable while reporting one completed item per iteration.

    When ``total`` is omitted, ``len(iterable)`` is used when available.  Empty
    iterables still produce a valid final report and never divide by zero.
    """

    if total is None:
        try:
            total = len(iterable)  # type: ignore[arg-type]
        except TypeError:
            pass
    with ProgressReporter[T](
        total,
        label=label,
        phase=phase,
        interval=interval,
        quiet=quiet,
        stream=stream,
        clock=clock,
        tty=tty,
    ) as reporter:
        for item in iterable:
            yield item
            reporter.advance()


__all__ = ["ProgressReporter", "track"]
