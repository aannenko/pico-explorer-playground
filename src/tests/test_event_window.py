import pytest

from scheduling.event import Event
from scheduling.event_window import EventWindow, build_event_windows
from scheduling.stream import ERROR, FRESH, STALE, Stream


def _make_event(name: str, start: int, duration: int, color_index: int = 0) -> Event:
    return Event(
        name=name,
        start_timestamp=start,
        wall_clock_duration_sec=duration,
        color_index=color_index,
    )


def _make_events(*specs):
    """Return a list of events from (name, start, duration[, color_index]) tuples."""
    return [_make_event(*spec) for spec in specs]


def _iter_events(*specs):
    """Return an iterator over events from (name, start, duration[, color_index]) tuples."""
    return iter(_make_events(*specs))


# ---------------------------------------------------------------------------
# Buffer fill / prune
# ---------------------------------------------------------------------------

class TestGetVisible:
    def test_returns_events_overlapping_window(self):
        events = _iter_events(
            ("A", 100, 200),   # 100..300
            ("B", 300, 200),   # 300..500
            ("C", 500, 200),   # 500..700
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(250, 550)

        names = [e.name for e, _ in visible]
        assert names == ["A", "B", "C"]

    def test_excludes_events_fully_before_window(self):
        events = _iter_events(
            ("A", 100, 100),   # 100..200
            ("B", 200, 100),   # 200..300
            ("C", 300, 100),   # 300..400
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(300, 500)

        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_includes_event_that_started_before_and_spans_into_window(self):
        events = _iter_events(
            ("A", 0, 500),   # 0..500 — spans into window
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(200, 400)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_prunes_on_successive_calls(self):
        events = _iter_events(
            ("A", 0, 100),     # 0..100
            ("B", 100, 100),   # 100..200
            ("C", 200, 100),   # 200..300
        )
        ew = EventWindow(events, palette=[1])

        ew.get_visible(0, 300)
        assert len(ew._buffer) == 3

        visible = ew.get_visible(200, 400)
        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_empty_iterator_returns_empty(self):
        ew = EventWindow(iter([]), palette=[1])

        visible = ew.get_visible(0, 1000)

        assert visible == []

    def test_no_events_in_window(self):
        events = _iter_events(
            ("A", 0, 100),   # 0..100 — entirely before window
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(200, 400)

        assert visible == []


# ---------------------------------------------------------------------------
# Color resolution (flat palette: pen == palette[color_index])
# ---------------------------------------------------------------------------

class TestColorResolution:
    """The window resolves each event's pen from its flat palette at fill
    time (``palette[color_index]``), so the renderer stays pure geometry."""

    def test_resolves_pen_from_palette_by_color_index(self):
        # color_index 0,0,1,1 → palette[0], palette[0], palette[1], palette[1].
        events = _iter_events(
            ("a", 0, 100, 0),
            ("b", 100, 100, 0),
            ("c", 200, 100, 1),
            ("d", 300, 100, 1),
        )
        ew = EventWindow(events, palette=[10, 30])

        visible = ew.get_visible(0, 500)

        pens = [pen for _, pen in visible]
        assert pens == [10, 10, 30, 30]

    def test_interleaved_categories_resolve_independently(self):
        # color_index 0,1,0,1 — each maps to its own slot regardless of order.
        events = _iter_events(
            ("a", 0, 100, 0),
            ("b", 100, 100, 1),
            ("c", 200, 100, 0),
            ("d", 300, 100, 1),
        )
        ew = EventWindow(events, palette=[10, 30])

        visible = ew.get_visible(0, 500)

        pens = [pen for _, pen in visible]
        assert pens == [10, 30, 10, 30]

    def test_out_of_range_color_index_clamps_to_last_entry(self):
        events = _iter_events(("x", 0, 100, 99),)
        ew = EventWindow(events, palette=[10, 20, 30])

        visible = ew.get_visible(0, 200)

        assert visible[0][1] == 30  # last palette entry

    def test_pen_persists_after_prune(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
            ("C", 200, 100),
        )
        ew = EventWindow(events, palette=[10])

        ew.get_visible(0, 300)
        visible = ew.get_visible(100, 300)  # prune A away

        pens = [(e.name, pen) for e, pen in visible]
        assert pens == [("B", 10), ("C", 10)]


# ---------------------------------------------------------------------------
# Iterator exhaustion
# ---------------------------------------------------------------------------

class TestIteratorExhaustion:
    def test_does_not_raise_on_exhausted_iterator(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, palette=[1])

        ew.get_visible(0, 200)
        visible = ew.get_visible(200, 400)

        assert visible == []

    def test_successive_calls_after_exhaustion(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, palette=[1])

        ew.get_visible(0, 200)
        ew.get_visible(200, 400)
        visible = ew.get_visible(400, 600)

        assert visible == []


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    def test_event_ending_exactly_at_window_start_is_excluded(self):
        events = _iter_events(
            ("A", 0, 100),     # ends at 100
            ("B", 100, 100),   # starts at 100
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(100, 300)

        names = [e.name for e, _ in visible]
        assert names == ["B"]

    def test_event_starting_exactly_at_window_end_is_excluded(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
        )
        ew = EventWindow(events, palette=[1])

        # Window [0, 100) — B starts at 100, should not appear
        visible = ew.get_visible(0, 100)

        names = [e.name for e, _ in visible]
        assert names == ["A"]

    def test_zero_duration_event(self):
        events = _iter_events(
            ("A", 100, 0),
            ("B", 100, 200),
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(50, 300)

        # Zero-duration event A ends at 100, overlaps [50, 300) only if end > start
        # start + duration = 100 > 50, so A is included
        assert any(e.name == "A" for e, _ in visible)

    def test_single_long_event_spanning_entire_window(self):
        events = _iter_events(("A", 0, 10000),)
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(1000, 2000)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_event_after_gap_beyond_window_is_excluded(self):
        events = _iter_events(
            ("A", 0, 50),       # 0..50
            ("B", 1000, 100),   # 1000..1100 — far beyond window
        )
        ew = EventWindow(events, palette=[1])

        visible = ew.get_visible(100, 200)

        assert visible == []


# ---------------------------------------------------------------------------
# Iterator replacement (refreshable buffer)
# ---------------------------------------------------------------------------

class TestReplace:
    def test_clears_all_internal_state(self):
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 100, 100)), palette=[1])
        ew.get_visible(0, 300)
        # Buffer is now populated.
        assert ew._buffer

        ew.replace(_iter_events(("X", 0, 100)))

        assert ew._buffer == []
        assert ew._next is None
        assert ew._exhausted is False

    def test_replace_after_exhaustion_refills_from_new_event_iter(self):
        ew = EventWindow(_iter_events(("A", 0, 100)), palette=[1])
        # Drive past the only event so the iterator exhausts and latches.
        ew.get_visible(0, 200)
        ew.get_visible(200, 400)
        assert ew._exhausted is True

        ew.replace(_iter_events(("B", 200, 100)))
        assert ew._exhausted is False  # reset by replace, before any fill

        visible = ew.get_visible(200, 400)
        names = [e.name for e, _ in visible]
        assert names == ["B"]

    def test_replace_discards_stale_buffered_events(self):
        ew = EventWindow(
            _iter_events(("A", 0, 100), ("B", 100, 100), ("C", 200, 100)),
            palette=[1],
        )
        ew.get_visible(0, 300)
        assert [e.name for e, _ in ew._buffer] == ["A", "B", "C"]

        ew.replace(_iter_events(("X", 0, 100), ("Y", 100, 100)))
        visible = ew.get_visible(0, 300)

        names = [e.name for e, _ in visible]
        assert names == ["X", "Y"]

    def test_replace_with_empty_iter_yields_empty(self):
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 100, 100)), palette=[1])
        ew.get_visible(0, 300)

        ew.replace(iter([]))
        visible = ew.get_visible(0, 300)

        assert visible == []

    def test_replace_clears_pending_peek_slot(self):
        # B starts beyond the window, so it is held in the peek slot.
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 500, 100)), palette=[1])
        ew.get_visible(0, 200)
        assert ew._next is not None  # B is peeked

        ew.replace(_iter_events(("C", 0, 100)))
        visible = ew.get_visible(0, 200)

        names = [e.name for e, _ in visible]
        assert names == ["C"]  # the stale peeked B does not resurface


# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

class TestPalette:
    def test_palette_stored(self):
        ew = EventWindow(iter([]), palette=[10, 12])
        assert ew.palette == [10, 12]

    def test_palette_is_read_only(self):
        ew = EventWindow(iter([]), palette=[10, 11])
        with pytest.raises(AttributeError):
            ew.palette = [1, 2]

    def test_replace_preserves_palette(self):
        ew = EventWindow(_iter_events(("A", 0, 100)), palette=[10, 12])
        ew.get_visible(0, 200)

        ew.replace(_iter_events(("B", 0, 100)))

        assert ew.palette == [10, 12]


# ---------------------------------------------------------------------------
# build_event_windows — shared-palette composition helper
# ---------------------------------------------------------------------------

class TestBuildEventWindows:
    _PALETTE = [10, 20, 30]

    def test_one_window_per_stream(self):
        streams = [
            Stream(_iter_events(("A", 0, 100))),
            Stream(_iter_events(("B", 0, 100))),
        ]

        windows = build_event_windows(self._PALETTE, streams)

        assert len(windows) == 2
        assert all(isinstance(w, EventWindow) for w in windows)

    def test_all_windows_share_the_same_palette(self):
        streams = [Stream(_iter_events(("A", 0, 100))) for _ in range(3)]

        windows = build_event_windows(self._PALETTE, streams)

        # The same palette object is handed to every row.
        for w in windows:
            assert w.palette is self._PALETTE

    def test_window_wraps_its_stream_iterator(self):
        streams = [
            Stream(_iter_events(("first", 0, 100))),
            Stream(_iter_events(("second", 0, 100))),
        ]

        windows = build_event_windows(self._PALETTE, streams)

        assert windows[0].get_visible(0, 200)[0][0].name == "first"
        assert windows[1].get_visible(0, 200)[0][0].name == "second"

    def test_color_index_indexes_the_shared_palette(self):
        # An event's color_index selects globally into the shared palette.
        stream = Stream(iter([
            Event("x", 0, 100, color_index=2),
        ]))

        windows = build_event_windows(self._PALETTE, [stream])
        visible = windows[0].get_visible(0, 200)

        assert visible[0][1] == 30  # palette[2]

    def test_empty_stream_list_yields_no_windows(self):
        assert build_event_windows(self._PALETTE, []) == []


# ---------------------------------------------------------------------------
# Overlapping events — fill must not drop a later overlapping event
# ---------------------------------------------------------------------------

class TestOverlapFill:
    def test_later_event_overlapping_long_earlier_is_not_dropped(self):
        # A is long and ends past window_end; B starts inside the window.
        ew = EventWindow(_iter_events(("A", 0, 1000), ("B", 100, 100)), palette=[1])

        visible = ew.get_visible(0, 500)

        assert [e.name for e, _ in visible] == ["A", "B"]

    def test_multiple_events_overlapping_one_long_event(self):
        ew = EventWindow(
            _iter_events(("A", 0, 1000), ("B", 100, 50), ("C", 200, 50)),
            palette=[1],
        )

        visible = ew.get_visible(0, 500)

        assert [e.name for e, _ in visible] == ["A", "B", "C"]

    def test_long_event_then_exhausts_finite_iterator(self):
        ew = EventWindow(_iter_events(("A", 0, 10000)), palette=[1])

        visible = ew.get_visible(1000, 2000)

        assert [e.name for e, _ in visible] == ["A"]
        assert ew._exhausted is True  # pulled A, then hit StopIteration
        # A stays visible on a repeat call without raising.
        assert [e.name for e, _ in ew.get_visible(1000, 2000)] == ["A"]


# ---------------------------------------------------------------------------
# Status + generation-driven refresh (network-backed rows)
# ---------------------------------------------------------------------------


class _FakeSource:
    """Stand-in for a network service: a mutable snapshot + generation/status."""

    def __init__(self, specs, generation: int = 0, status: int = FRESH) -> None:
        self.specs = specs
        self.generation = generation
        self.status = status
        self.iter_calls = 0

    def events_iter(self):  # -> Iterator[Event]
        self.iter_calls += 1
        return iter(_make_events(*self.specs))

    def gen(self) -> int:
        return self.generation

    def stat(self) -> int:
        return self.status

    def _window(self, palette=None) -> EventWindow:
        return EventWindow(
            self.events_iter(),
            palette=palette if palette is not None else [1],
            events_fn=self.events_iter,
            generation_fn=self.gen,
            status_fn=self.stat,
        )


class TestStatus:
    def test_status_none_without_status_fn(self):
        ew = EventWindow(iter([]), palette=[1])

        assert ew.status() is None

    def test_status_delegates_to_status_fn(self):
        box = {"v": FRESH}
        ew = EventWindow(iter([]), palette=[1], status_fn=lambda: box["v"])

        assert ew.status() == FRESH
        box["v"] = ERROR
        assert ew.status() == ERROR


class TestGenerationRefresh:
    def test_refresh_pulls_new_snapshot_on_generation_bump(self):
        src = _FakeSource([("A", 0, 100)], generation=0)
        ew = src._window()

        assert [e.name for e, _ in ew.get_visible(0, 1000)] == ["A"]

        src.specs = [("B", 0, 100)]
        src.generation = 1

        assert [e.name for e, _ in ew.get_visible(0, 1000)] == ["B"]

    def test_no_refresh_when_generation_unchanged(self):
        src = _FakeSource([("A", 0, 100)], generation=5)
        ew = src._window()

        ew.get_visible(0, 1000)
        calls_after_first = src.iter_calls
        ew.get_visible(0, 1000)
        ew.get_visible(0, 1000)

        # events_fn was not invoked again while generation stayed at 5.
        assert src.iter_calls == calls_after_first

    def test_static_window_never_refreshes(self):
        # No generation_fn → the initial iterator is used forever.
        ew = EventWindow(_iter_events(("A", 0, 100)), palette=[1])

        assert [e.name for e, _ in ew.get_visible(0, 1000)] == ["A"]
        assert [e.name for e, _ in ew.get_visible(0, 1000)] == ["A"]


class TestBuildEventWindowsThreading:
    def test_status_and_refresh_thread_from_stream(self):
        src = _FakeSource([("A", 0, 100)], generation=0, status=STALE)
        stream = Stream(
            src.events_iter(),
            events_fn=src.events_iter,
            generation_fn=src.gen,
            status_fn=src.stat,
        )

        window = build_event_windows([1], [stream])[0]

        assert window.status() == STALE
        assert [e.name for e, _ in window.get_visible(0, 1000)] == ["A"]

        src.specs = [("B", 0, 100)]
        src.generation = 1
        assert [e.name for e, _ in window.get_visible(0, 1000)] == ["B"]
