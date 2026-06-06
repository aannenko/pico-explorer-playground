from scheduling.event import Event


class EventWindow:
    """Sliding-buffer wrapper over a forward-only event iterator.

    Each ``get_visible`` call fills the buffer forward to the requested
    window end and prunes events that ended before its start.
    ``color_a`` / ``color_b`` are pens used by callers to alternate
    adjacent bars.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        color_a: int,
        color_b: int,
    ) -> None:
        self._events = events_iter
        self.color_a: int = color_a
        self.color_b: int = color_b
        self._buffer: list[tuple[Event, bool]] = []
        self._use_alt: bool = False
        self._next: tuple[Event, bool] | None = None
        self._exhausted: bool = False

    def get_visible(
        self,
        window_start: int,
        window_end: int,
    ) -> list[tuple[Event, bool]]:
        """Return ``[(Event, use_alt_color), ...]`` overlapping ``[window_start, window_end)``.

        ``use_alt_color`` alternates between adjacent events so callers
        can pick ``color_a`` or ``color_b``.

        Note: the returned list is the window's internal buffer (mutated
        on the next call) — callers must treat it as read-only.  This
        avoids per-frame list allocations on the calendar's hot path.
        """
        self._fill_to(window_end)
        self._prune_before(window_start)
        return self._buffer

    def replace(self, event_iter) -> None:  # event_iter: Iterator[Event]
        """Swap in a fresh event iterator, discarding all buffered state.

        Required for network-backed streams whose underlying data is
        re-fetched periodically: the buffer, peek slot, color toggle
        and exhaustion latch are all reset so the next ``get_visible``
        repopulates from ``event_iter``.  Unlike the forward-only fill
        path, this is the only way to clear ``_exhausted`` once a
        bounded iterator has run out.
        """
        self._events = event_iter
        self._buffer = []
        self._use_alt = False
        self._next = None
        self._exhausted = False

    def _fill_to(self, window_end: int) -> None:
        if self._exhausted:
            return

        while True:
            # Buffer covers window when last event extends past window_end
            if self._buffer:
                last = self._buffer[-1][0]
                if last.start_timestamp + last.wall_clock_duration_sec > window_end:
                    break

            # Get next event from peek slot or iterator
            if self._next is not None:
                event, alt = self._next
                self._next = None
            else:
                try:
                    event = next(self._events)
                except StopIteration:
                    self._exhausted = True
                    break
                alt = self._use_alt
                self._use_alt = not self._use_alt

            # Event starts beyond window — hold in peek slot for later
            if event.start_timestamp >= window_end:
                self._next = (event, alt)
                break

            self._buffer.append((event, alt))

    def _prune_before(self, window_start: int) -> None:
        buf = self._buffer
        while buf:
            event = buf[0][0]
            if event.start_timestamp + event.wall_clock_duration_sec > window_start:
                break
            buf.pop(0)
