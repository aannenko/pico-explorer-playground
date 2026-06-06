from scheduling.event import Event


class EventWindow:
    """Sliding-buffer wrapper over a forward-only event iterator.

    Each ``get_visible`` call fills the buffer forward to the requested
    window end and prunes events that ended before its start.  ``palette``
    holds one ``(main_pen, alt_pen)`` pair per category; an event's
    ``color_index`` selects the pair, and the window resolves the final
    pen at fill time (run-gated alternation, see ``_resolve_pen``).
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        palette: tuple[tuple[int, int], ...],  # (main_pen, alt_pen) per category
    ) -> None:
        self._events = events_iter
        self._palette: tuple[tuple[int, int], ...] = palette
        self._buffer: list[tuple[Event, int]] = []
        self._use_alt: bool = False
        self._prev_color_index: int = -1
        self._next: tuple[Event, int] | None = None
        self._exhausted: bool = False

    @property
    def palette(self) -> tuple[tuple[int, int], ...]:
        return self._palette

    def get_visible(
        self,
        window_start: int,
        window_end: int,
    ) -> list[tuple[Event, int]]:
        """Return ``[(Event, pen), ...]`` overlapping ``[window_start, window_end)``.

        The pen is resolved from the window's ``palette`` at fill time, so
        the renderer only has to ``set_pen`` and draw geometry.

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
        re-fetched periodically: the buffer, peek slot, alternation state
        and exhaustion latch are all reset so the next ``get_visible``
        repopulates from ``event_iter`` and restarts coloring from each
        category's main pen.  Unlike the forward-only fill path, this is
        the only way to clear ``_exhausted`` once a bounded iterator has
        run out.
        """
        self._events = event_iter
        self._buffer = []
        self._use_alt = False
        self._prev_color_index = -1
        self._next = None
        self._exhausted = False

    def _resolve_pen(self, color_index: int) -> int:
        """Pick the pen for ``color_index`` using run-gated alternation.

        Within a run of the same ``color_index`` the pen toggles
        main/alt/main/alt so adjacent same-category bars stay
        distinguishable; a different ``color_index`` resets to main.
        Keyed on the previously emitted event, so it is interleave-safe.
        A ``(main, alt)`` pair with ``main == alt`` collapses the toggle
        to a single solid color.  Out-of-range indices clamp to the last
        palette entry.
        """
        if color_index == self._prev_color_index:
            self._use_alt = not self._use_alt
        else:
            self._use_alt = False
        self._prev_color_index = color_index

        idx = color_index
        if idx >= len(self._palette):
            idx = len(self._palette) - 1
        pair = self._palette[idx]
        return pair[1] if self._use_alt else pair[0]

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
                event, pen = self._next
                self._next = None
            else:
                try:
                    event = next(self._events)
                except StopIteration:
                    self._exhausted = True
                    break
                pen = self._resolve_pen(event.color_index)

            # Event starts beyond window — hold in peek slot for later
            if event.start_timestamp >= window_end:
                self._next = (event, pen)
                break

            self._buffer.append((event, pen))

    def _prune_before(self, window_start: int) -> None:
        buf = self._buffer
        while buf:
            event = buf[0][0]
            if event.start_timestamp + event.wall_clock_duration_sec > window_start:
                break
            buf.pop(0)
