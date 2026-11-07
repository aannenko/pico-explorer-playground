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
            get_status=s.get_status,
        )
        for s in streams
    ]


class EventWindow:
    """Per-row calendar view-model: a sliding buffer that also colors its bars.

    Requires events in nondecreasing start order.

    ``stream_colors`` must be nonempty; it is indexed by ``Event.color_index``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        stream_colors: list[int],
        events_iter_factory=None,  # () -> Iterator[Event]
        get_generation=None,  # () -> int
        get_status=None,  # () -> int
    ) -> None:
        self._events = events_iter
        self._stream_colors = stream_colors
        self._buffer: list[tuple[Event, int]] = []
        self._next: tuple[Event, int] | None = None
        self._exhausted = False
        self._events_iter_factory = events_iter_factory
        self._get_generation = get_generation
        self._get_status = get_status
        self._generation = -1

    @property
    def stream_colors(self) -> list[int]:
        return self._stream_colors

    def get_visible(
        self,
        window_start: int,
        window_end: int,
    ) -> list[tuple[Event, int]]:
        """Return ``(Event, pen)`` pairs for ``[window_start, window_end)``.

        Events wholly before the window after next-start clipping are pruned.
        Returning the internal buffer avoids a per-call allocation; later calls
        mutate it, so callers must treat it as read-only.
        """
        self._refresh_if_changed()
        self._prune_before(window_start)
        self._fill_to(window_start, window_end)
        return self._buffer

    def status(self) -> int | None:
        """Return the freshness code, or None when no status hook is provided."""
        sf = self._get_status
        return sf() if sf is not None else None

    def replace(self, events_iter) -> None:  # events_iter: Iterator[Event]
        """Restart from a fresh event iterator."""
        self._events = events_iter
        self._buffer = []
        self._next = None
        self._exhausted = False

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

            self._buffer.append((event, pen))
            # Prune during catch-up too, or after a long absence the buffer would
            # hold every event that expired meanwhile.
            self._prune_before(window_start)

    def _prune_before(self, window_start: int) -> None:
        buf = self._buffer
        while buf:
            event = buf[0][0]
            end = event.start_timestamp + event.wall_clock_duration_sec
            # Clip at the next start, as the calendar renderer does, so an
            # interrupted long event neither pins expired successors nor
            # reappears after they expire.
            if len(buf) > 1:
                end = min(end, buf[1][0].start_timestamp)
            if end > window_start:
                break
            buf.pop(0)
