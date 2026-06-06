import pytest

from scheduling.event import Event
from scheduling.event_window import EventWindow


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


# A one-entry palette whose main/alt pens differ, so a color_index-0 run
# alternates and tests can read the resolved pen directly.
_ALT = ((10, 20),)


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
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(250, 550)

        names = [e.name for e, _ in visible]
        assert names == ["A", "B", "C"]

    def test_excludes_events_fully_before_window(self):
        events = _iter_events(
            ("A", 100, 100),   # 100..200
            ("B", 200, 100),   # 200..300
            ("C", 300, 100),   # 300..400
        )
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(300, 500)

        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_includes_event_that_started_before_and_spans_into_window(self):
        events = _iter_events(
            ("A", 0, 500),   # 0..500 — spans into window
        )
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(200, 400)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_prunes_on_successive_calls(self):
        events = _iter_events(
            ("A", 0, 100),     # 0..100
            ("B", 100, 100),   # 100..200
            ("C", 200, 100),   # 200..300
        )
        ew = EventWindow(events, palette=((1, 2),))

        ew.get_visible(0, 300)
        assert len(ew._buffer) == 3

        visible = ew.get_visible(200, 400)
        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_empty_iterator_returns_empty(self):
        ew = EventWindow(iter([]), palette=((1, 2),))

        visible = ew.get_visible(0, 1000)

        assert visible == []

    def test_no_events_in_window(self):
        events = _iter_events(
            ("A", 0, 100),   # 0..100 — entirely before window
        )
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(200, 400)

        assert visible == []


# ---------------------------------------------------------------------------
# Run-gated color resolution
# ---------------------------------------------------------------------------

class TestRunGatedColor:
    """The window resolves each event's pen at fill time.

    Within a run of the same ``color_index`` the pen toggles main/alt so
    adjacent same-category bars stay distinguishable; a different
    ``color_index`` resets to that category's main pen.
    """

    def test_alternates_main_alt_within_a_run(self):
        # Bus case: a single distinct (main, alt) pair → A, B, A, B.
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
            ("C", 200, 100),
            ("D", 300, 100),
        )
        ew = EventWindow(events, palette=_ALT)

        visible = ew.get_visible(0, 500)

        pens = [pen for _, pen in visible]
        assert pens == [10, 20, 10, 20]

    def test_first_event_uses_main_pen(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, palette=_ALT)

        visible = ew.get_visible(0, 200)

        assert visible[0][1] == 10  # main pen

    def test_equal_pair_merges_run(self):
        # Precip case: a (C, C) pair makes a same-category run read as one block.
        events = _iter_events(
            ("rain", 0, 100),
            ("rain", 100, 100),
            ("rain", 200, 100),
        )
        ew = EventWindow(events, palette=((10, 10),))

        visible = ew.get_visible(0, 400)

        pens = [pen for _, pen in visible]
        assert pens == [10, 10, 10]

    def test_category_change_resets_to_main(self):
        # color_index 0,0,1,1 → main, alt, main(reset), alt.
        events = _iter_events(
            ("a", 0, 100, 0),
            ("b", 100, 100, 0),
            ("c", 200, 100, 1),
            ("d", 300, 100, 1),
        )
        ew = EventWindow(events, palette=((10, 20), (30, 40)))

        visible = ew.get_visible(0, 500)

        pens = [pen for _, pen in visible]
        assert pens == [10, 20, 30, 40]

    def test_interleaved_categories_each_reset_to_main(self):
        # color_index 0,1,0,1 — every event differs from its predecessor,
        # so each resets to its category's main pen (interleave-safe).
        events = _iter_events(
            ("a", 0, 100, 0),
            ("b", 100, 100, 1),
            ("c", 200, 100, 0),
            ("d", 300, 100, 1),
        )
        ew = EventWindow(events, palette=((10, 20), (30, 40)))

        visible = ew.get_visible(0, 500)

        pens = [pen for _, pen in visible]
        assert pens == [10, 30, 10, 30]

    def test_out_of_range_color_index_clamps_to_last_entry(self):
        events = _iter_events(("x", 0, 100, 99),)
        ew = EventWindow(events, palette=((10, 11), (20, 21), (30, 31)))

        visible = ew.get_visible(0, 200)

        assert visible[0][1] == 30  # main pen of the last palette entry

    def test_pen_resolution_persists_after_prune(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
            ("C", 200, 100),
        )
        ew = EventWindow(events, palette=_ALT)

        ew.get_visible(0, 300)
        # A=main(10), B=alt(20), C=main(10); prune A away.
        visible = ew.get_visible(100, 300)

        pens = [(e.name, pen) for e, pen in visible]
        assert pens == [("B", 20), ("C", 10)]


# ---------------------------------------------------------------------------
# Iterator exhaustion
# ---------------------------------------------------------------------------

class TestIteratorExhaustion:
    def test_does_not_raise_on_exhausted_iterator(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, palette=((1, 2),))

        ew.get_visible(0, 200)
        visible = ew.get_visible(200, 400)

        assert visible == []

    def test_successive_calls_after_exhaustion(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, palette=((1, 2),))

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
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(100, 300)

        names = [e.name for e, _ in visible]
        assert names == ["B"]

    def test_event_starting_exactly_at_window_end_is_excluded(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
        )
        ew = EventWindow(events, palette=((1, 2),))

        # Window [0, 100) — B starts at 100, should not appear
        visible = ew.get_visible(0, 100)

        names = [e.name for e, _ in visible]
        assert names == ["A"]

    def test_zero_duration_event(self):
        events = _iter_events(
            ("A", 100, 0),
            ("B", 100, 200),
        )
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(50, 300)

        # Zero-duration event A ends at 100, overlaps [50, 300) only if end > start
        # start + duration = 100 > 50, so A is included
        assert any(e.name == "A" for e, _ in visible)

    def test_single_long_event_spanning_entire_window(self):
        events = _iter_events(("A", 0, 10000),)
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(1000, 2000)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_event_after_gap_beyond_window_is_excluded(self):
        events = _iter_events(
            ("A", 0, 50),       # 0..50
            ("B", 1000, 100),   # 1000..1100 — far beyond window
        )
        ew = EventWindow(events, palette=((1, 2),))

        visible = ew.get_visible(100, 200)

        assert visible == []


# ---------------------------------------------------------------------------
# Iterator replacement (refreshable buffer)
# ---------------------------------------------------------------------------

class TestReplace:
    def test_clears_all_internal_state(self):
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 100, 100)), palette=((1, 2),))
        ew.get_visible(0, 300)
        # Buffer is now populated.
        assert ew._buffer

        ew.replace(_iter_events(("X", 0, 100)))

        assert ew._buffer == []
        assert ew._use_alt is False
        assert ew._prev_color_index == -1
        assert ew._next is None
        assert ew._exhausted is False

    def test_replace_after_exhaustion_refills_from_new_event_iter(self):
        ew = EventWindow(_iter_events(("A", 0, 100)), palette=((1, 2),))
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
            palette=((1, 2),),
        )
        ew.get_visible(0, 300)
        assert [e.name for e, _ in ew._buffer] == ["A", "B", "C"]

        ew.replace(_iter_events(("X", 0, 100), ("Y", 100, 100)))
        visible = ew.get_visible(0, 300)

        names = [e.name for e, _ in visible]
        assert names == ["X", "Y"]

    def test_replace_with_empty_iter_yields_empty(self):
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 100, 100)), palette=((1, 2),))
        ew.get_visible(0, 300)

        ew.replace(iter([]))
        visible = ew.get_visible(0, 300)

        assert visible == []

    def test_replace_restarts_color_alternation(self):
        ew = EventWindow(
            _iter_events(("A", 0, 100), ("B", 100, 100)),
            palette=_ALT,
        )
        ew.get_visible(0, 300)
        # Alternation has advanced (A=main, B=alt), so without a reset the
        # next event would continue from alt.

        ew.replace(_iter_events(("X", 0, 100), ("Y", 100, 100)))
        visible = ew.get_visible(0, 300)

        pens = [pen for _, pen in visible]
        assert pens == [10, 20]  # restarts from the main pen

    def test_replace_clears_pending_peek_slot(self):
        # B starts beyond the window, so it is held in the peek slot.
        ew = EventWindow(_iter_events(("A", 0, 100), ("B", 500, 100)), palette=((1, 2),))
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
    def test_palette_pairs_stored(self):
        ew = EventWindow(iter([]), palette=((10, 11), (12, 13)))
        assert ew.palette == ((10, 11), (12, 13))

    def test_palette_is_read_only(self):
        ew = EventWindow(iter([]), palette=((10, 11),))
        with pytest.raises(AttributeError):
            ew.palette = ((1, 2),)

    def test_replace_preserves_palette(self):
        ew = EventWindow(_iter_events(("A", 0, 100)), palette=((10, 11), (12, 13)))
        ew.get_visible(0, 200)

        ew.replace(_iter_events(("B", 0, 100)))

        assert ew.palette == ((10, 11), (12, 13))
