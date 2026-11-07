from scheduling.event import Event


def build_event_windows(
    palette: list[int],
    streams,  # Iterable[Stream]
) -> list[EventWindow]:
    """Build one ``EventWindow`` per stream, all sharing ``palette``."""
    return [
        EventWindow(
            events_iter=s.events_iter,
            palette=palette,
            events_fn=s.events_fn,
            generation_fn=s.generation_fn,
            status_fn=s.status_fn,
        )
        for s in streams
    ]


class EventWindow:
    """Per-row calendar view-model: a sliding buffer that also colors its bars.

    Requires events in nondecreasing start order.

    ``palette`` must be nonempty; it is indexed by ``Event.color_index``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        palette: list[int],
        events_fn=None,  # () -> Iterator[Event]
        generation_fn=None,  # () -> int
        status_fn=None,  # () -> int
    ) -> None:
        self._events = events_iter
        self._palette = palette
        self._buffer: list[tuple[Event, int]] = []
        self._next: tuple[Event, int] | None = None
        self._exhausted = False
        self._events_fn = events_fn
        self._generation_fn = generation_fn
        self._status_fn = status_fn
        self._generation = -1

    @property
    def palette(self) -> list[int]:
        """Pen slots the bars are colored from."""
        return self._palette

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
        sf = self._status_fn
        return sf() if sf is not None else None

    def replace(self, events_iter) -> None:  # events_iter: Iterator[Event]
        """Restart from a fresh event iterator."""
        self._events = events_iter
        self._buffer = []
        self._next = None
        self._exhausted = False

    def _resolve_pen(self, color_index: int) -> int:
        idx = color_index
        if idx >= len(self._palette):
            idx = len(self._palette) - 1
        return self._palette[idx]

    def _refresh_if_changed(self) -> None:
        if self._generation_fn is None or self._events_fn is None:
            return
        gen = self._generation_fn()
        if gen != self._generation:
            self._generation = gen
            self.replace(self._events_fn())

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
