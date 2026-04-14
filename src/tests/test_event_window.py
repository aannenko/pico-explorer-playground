import pytest

from scheduling.event import Event
from scheduling.event_window import EventWindow


def _make_event(name: str, start: int, duration: int) -> Event:
    return Event(name=name, start_timestamp=start, wall_clock_duration_sec=duration)


def _make_events(*specs):
    """Return a list of events from (name, start, duration) tuples."""
    return [_make_event(n, s, d) for n, s, d in specs]


def _iter_events(*specs):
    """Return an iterator over events from (name, start, duration) tuples."""
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
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(250, 550)

        names = [e.name for e, _ in visible]
        assert names == ["A", "B", "C"]

    def test_excludes_events_fully_before_window(self):
        events = _iter_events(
            ("A", 100, 100),   # 100..200
            ("B", 200, 100),   # 200..300
            ("C", 300, 100),   # 300..400
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(300, 500)

        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_includes_event_that_started_before_and_spans_into_window(self):
        events = _iter_events(
            ("A", 0, 500),   # 0..500 — spans into window
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(200, 400)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_prunes_on_successive_calls(self):
        events = _iter_events(
            ("A", 0, 100),     # 0..100
            ("B", 100, 100),   # 100..200
            ("C", 200, 100),   # 200..300
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        ew.get_visible(0, 300)
        assert len(ew._buffer) == 3

        visible = ew.get_visible(200, 400)
        names = [e.name for e, _ in visible]
        assert names == ["C"]

    def test_empty_iterator_returns_empty(self):
        ew = EventWindow(iter([]), color_a=1, color_b=2)

        visible = ew.get_visible(0, 1000)

        assert visible == []

    def test_no_events_in_window(self):
        events = _iter_events(
            ("A", 0, 100),   # 0..100 — entirely before window
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(200, 400)

        assert visible == []


# ---------------------------------------------------------------------------
# Color toggle
# ---------------------------------------------------------------------------

class TestColorToggle:
    def test_alternates_between_adjacent_events(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
            ("C", 200, 100),
            ("D", 300, 100),
        )
        ew = EventWindow(events, color_a=10, color_b=20)

        visible = ew.get_visible(0, 500)

        toggles = [alt for _, alt in visible]
        assert toggles == [False, True, False, True]

    def test_color_a_for_first_event(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, color_a=10, color_b=20)

        visible = ew.get_visible(0, 200)

        assert visible[0][1] is False  # color_a

    def test_toggle_persists_after_prune(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
            ("C", 200, 100),
        )
        ew = EventWindow(events, color_a=10, color_b=20)

        ew.get_visible(0, 300)
        # A=False, B=True, C=False
        # Now prune A away
        visible = ew.get_visible(100, 300)

        toggles = [(e.name, alt) for e, alt in visible]
        assert toggles == [("B", True), ("C", False)]


# ---------------------------------------------------------------------------
# Iterator exhaustion
# ---------------------------------------------------------------------------

class TestIteratorExhaustion:
    def test_does_not_raise_on_exhausted_iterator(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, color_a=1, color_b=2)

        ew.get_visible(0, 200)
        visible = ew.get_visible(200, 400)

        assert visible == []

    def test_successive_calls_after_exhaustion(self):
        events = _iter_events(("A", 0, 100),)
        ew = EventWindow(events, color_a=1, color_b=2)

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
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(100, 300)

        names = [e.name for e, _ in visible]
        assert names == ["B"]

    def test_event_starting_exactly_at_window_end_is_excluded(self):
        events = _iter_events(
            ("A", 0, 100),
            ("B", 100, 100),
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        # Window [0, 100) — B starts at 100, should not appear
        visible = ew.get_visible(0, 100)

        names = [e.name for e, _ in visible]
        assert names == ["A"]

    def test_zero_duration_event(self):
        events = _iter_events(
            ("A", 100, 0),
            ("B", 100, 200),
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(50, 300)

        # Zero-duration event A ends at 100, overlaps [50, 300) only if end > start
        # start + duration = 100 > 50, so A is included
        assert any(e.name == "A" for e, _ in visible)

    def test_single_long_event_spanning_entire_window(self):
        events = _iter_events(("A", 0, 10000),)
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(1000, 2000)

        assert len(visible) == 1
        assert visible[0][0].name == "A"

    def test_event_after_gap_beyond_window_is_excluded(self):
        events = _iter_events(
            ("A", 0, 50),       # 0..50
            ("B", 1000, 100),   # 1000..1100 — far beyond window
        )
        ew = EventWindow(events, color_a=1, color_b=2)

        visible = ew.get_visible(100, 200)

        assert visible == []
