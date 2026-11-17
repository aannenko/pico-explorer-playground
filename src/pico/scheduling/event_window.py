from scheduling.event import Event


def build_event_windows(
    stream_colors: list[int],
    streams,  # Iterable[Stream]
) -> list[EventWindow]:
    """Build one ``EventWindow`` per stream, all sharing ``stream_colors``."""
    return [
        EventWindow(
            events_iter=s.events_iter,
            stream_colors=stream_colors,
            events_iter_factory=s.events_iter_factory,
            get_generation=s.get_generation,
        )
        for s in streams
    ]


class EventWindow:
    """Per-stream calendar view-model: a sliding buffer that also colors its events.

    Requires events in nondecreasing start order.

    ``stream_colors`` must be nonempty; it is indexed by ``Event.color_index``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        stream_colors: list[int],
        events_iter_factory=None,  # () -> Iterator[Event]
        get_generation=None,  # () -> int
    ) -> None:
        self._events = events_iter
        self._stream_colors = stream_colors
        self._buffer: list[tuple[Event, int]] = []
        self._next: tuple[Event, int] | None = None
        self._exhausted = False
        self._events_iter_factory = events_iter_factory
        self._get_generation = get_generation
        self._generation = -1

    def get_visible(
        self,
        window_start: int,
        window_end: int,
    ) -> list[tuple[Event, int]]:
        """Return ``(Event, pen)`` pairs, in start order, for the events not over by ``window_start`` that start
        before ``window_end``.

        An event is over once it has started and ended, so one starting at ``window_start`` stays, even with zero
        duration.  After the clock steps back, the pairs can include events starting at or after ``window_end``.
        Returning the internal buffer avoids a per-call allocation; later calls mutate it, so callers must treat it
        as read-only.
        """
        self._refresh_if_changed()
        self._prune(window_start)
        self._fill_to(window_start, window_end)
        return self._buffer

    def replace(self, events_iter) -> None:  # events_iter: Iterator[Event]
        """Restart from a fresh event iterator."""
        self._events = events_iter
        self._buffer = []
        self._next = None
        self._exhausted = False

    def release(self) -> None:
        """Drop the events held by a window that refreshes, until the next ``get_visible`` refills it from the latest
        snapshot; a window that doesn't refresh keeps them, as it couldn't refill."""
        if self._get_generation is None or self._events_iter_factory is None:
            return
        self.replace(iter(()))
        self._generation = -1

    def _resolve_pen(self, color_index: int) -> int:
        idx = color_index
        if idx >= len(self._stream_colors):
            idx = len(self._stream_colors) - 1
        return self._stream_colors[idx]

    def _refresh_if_changed(self) -> None:
        if self._get_generation is None or self._events_iter_factory is None:
            return
        gen = self._get_generation()
        if gen != self._generation:
            self._generation = gen
            self.replace(self._events_iter_factory())

    def _fill_to(self, window_start: int, window_end: int) -> None:
        if self._exhausted:
            return

        while True:
            if self._next is not None:
                event, pen = self._next
                self._next = None
            else:
                try:
                    event = next(self._events)
                except StopIteration:
                    self._exhausted = True
                    break
                pen = self._resolve_pen(event.color_index)

            if event.start_timestamp >= window_end:
                self._next = (event, pen)
                break

            # Skipped rather than buffered, so catching up after a long absence keeps only what's still on.
            if not _is_over(event, window_start):
                self._buffer.append((event, pen))

    def _prune(self, window_start: int) -> None:
        buf = self._buffer
        kept = 0
        for i in range(len(buf)):
            entry = buf[i]
            if not _is_over(entry[0], window_start):
                buf[kept] = entry
                kept += 1
        while len(buf) > kept:
            buf.pop()


def _is_over(event: Event, at: int) -> bool:
    """Return whether ``event`` has started and ended by ``at``."""
    start = event.start_timestamp
    return start < at and start + event.wall_clock_duration_sec <= at
