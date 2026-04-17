from scheduling.event import Event


class EventWindow:
    """Sliding-buffer wrapper over a forward-only event iterator.

    Maintains a small buffer of events covering a requested time window.
    Each call to ``get_visible`` fills the buffer forward and prunes
    events that ended before the window start.

    Args:
        events_iter: Forward-only iterator yielding ``Event`` objects.
        color_a (int): First pen color for alternating events.
        color_b (int): Second pen color for alternating events.
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
        """Return events overlapping ``[window_start, window_end)``.

        Each item is ``(Event, use_alt_color)`` where ``use_alt_color``
        alternates between adjacent events so the caller can pick
        ``color_a`` or ``color_b``.

        Note:
            The returned list is the window's internal buffer, not a copy.
            Callers must treat it as read-only; the buffer is mutated on
            the next ``get_visible`` call (fill-forward + prune-past).
            Returning the buffer directly avoids per-frame list
            allocations in the calendar's hot draw path.
        """
        self._fill_to(window_end)
        self._prune_before(window_start)
        return self._buffer

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
