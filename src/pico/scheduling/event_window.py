from scheduling.event import Event


def build_event_windows(palette, streams):  # palette: list[int]; streams: Iterable[Stream]
    """Build one ``EventWindow`` per stream, all sharing ``palette``.

    Kept import-free of config/hardware so it is unit-testable with a
    fake palette and fake streams.  Refresh/status callables ride along
    from each stream so network-backed rows refresh and show a glyph.
    """
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

    Each ``get_visible`` fills the buffer forward and prunes events that
    ended before the window start.  The pen is resolved at fill time so
    ``get_visible`` returns ``(Event, pen)`` and the renderer stays pure
    geometry.  ``palette`` is a list of pen slots indexed by ``color_index``.
    """

    def __init__(
        self,
        events_iter,  # Iterator[Event]
        palette: list[int],  # pen slot per category, indexed by color_index
        events_fn=None,  # () -> Iterator[Event]; fresh-iterator factory for refresh
        generation_fn=None,  # () -> int; bumps when the source snapshot changes
        status_fn=None,  # () -> int; freshness, or None for static streams
    ) -> None:
        self._events = events_iter
        self._palette: list[int] = palette
        self._buffer: list[tuple[Event, int]] = []
        self._next: tuple[Event, int] | None = None
        self._exhausted: bool = False
        self._events_fn = events_fn
        self._generation_fn = generation_fn
        self._status_fn = status_fn
        self._generation: int = -1

    @property
    def palette(self) -> list[int]:
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
        self._refresh_if_changed()
        self._fill_to(window_end)
        self._prune_before(window_start)
        return self._buffer

    def status(self) -> int | None:
        """Freshness code for the row glyph, or None for static streams."""
        sf = self._status_fn
        return sf() if sf is not None else None

    def replace(self, event_iter) -> None:  # event_iter: Iterator[Event]
        """Swap in a fresh event iterator, discarding all buffered state.

        Required for network-backed streams whose underlying data is
        re-fetched periodically: the buffer, peek slot and exhaustion latch
        are all reset so the next ``get_visible`` repopulates from
        ``event_iter``.  Unlike the forward-only fill path, this is the only
        way to clear ``_exhausted`` once a bounded iterator has run out.
        """
        self._events = event_iter
        self._buffer = []
        self._next = None
        self._exhausted = False

    def _resolve_pen(self, color_index: int) -> int:
        """Pick the pen slot for ``color_index``.

        Out-of-range indices clamp to the last palette entry.
        """
        idx = color_index
        if idx >= len(self._palette):
            idx = len(self._palette) - 1
        return self._palette[idx]

    def _refresh_if_changed(self) -> None:
        # Pull a fresh snapshot when the source's generation has advanced.
        # replace() resets the buffer/alternation/exhaustion latch so the
        # next fill repopulates from the new iterator.
        if self._generation_fn is None or self._events_fn is None:
            return
        gen = self._generation_fn()
        if gen != self._generation:
            self._generation = gen
            self.replace(self._events_fn())

    def _fill_to(self, window_end: int) -> None:
        # Relies on events arriving in nondecreasing start order: the fill
        # stops at the first event starting at/after window_end.
        if self._exhausted:
            return

        while True:
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
