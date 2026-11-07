"""Tests for the placeholder demo streams.

The substantive guarantee is the per-row ``color_index`` assignment:
the four demo rows are 1..4.
"""

import demo_streams
import pytest

from displays.palette import STREAM_SKY, STREAM_YELLOW, STREAM_PINK, STREAM_BLUE
from scheduling.event import Event
from scheduling.event_window import EventWindow

_PAST_SEC = 1800


class _FakeTimeService:
    """Minimal stand-in: demo streams need now()."""

    def __init__(self):
        self.current_time = 1_000_000

    def now(self) -> int:
        return self.current_time


@pytest.fixture
def short_events(monkeypatch):
    monkeypatch.setattr(demo_streams.random, "choice", lambda items: items[0])
    monkeypatch.setattr(demo_streams.random, "randint", lambda low, high: high)


@pytest.fixture
def built_events(monkeypatch) -> list[Event]:
    """Records every event the demo loops build."""
    built: list[Event] = []

    def build_event(*args, **kwargs) -> Event:
        event = Event(*args, **kwargs)
        built.append(event)
        return event

    monkeypatch.setattr(demo_streams, "Event", build_event)
    return built


def _first_event(stream):
    return next(stream.events_iter)


def test_demo_streams_assign_sequential_color_indices():
    streams = demo_streams.build_demo_streams(_FakeTimeService(), _PAST_SEC)

    assert [_first_event(s).color_index for s in streams] == [
        STREAM_SKY, STREAM_YELLOW, STREAM_PINK, STREAM_BLUE,
    ]


def test_demo_streams_returns_four_rows():
    streams = demo_streams.build_demo_streams(_FakeTimeService(), _PAST_SEC)
    assert len(streams) == 4


def test_random_event_loop_stamps_color_index_on_every_event():
    ts = _FakeTimeService()
    gen = demo_streams._random_event_loop(
        labels=("a", "b"),
        durations=(60, 120),
        gap_pct=0,  # no gaps → deterministic yields
        start_timestamp=0,
        time_service=ts,
        color_index=3,
        window_past_sec=_PAST_SEC,
    )

    events = [next(gen) for _ in range(5)]
    assert all(e.color_index == 3 for e in events)


@pytest.mark.parametrize("past_sec", [600, 1800])
@pytest.mark.parametrize("days", [1, 30, 365])
def test_delayed_first_entry_starts_at_current_past_window(
    short_events, built_events, past_sec, days
):
    ts = _FakeTimeService()
    stream = demo_streams.build_demo_streams(ts, past_sec)[0]
    ts.current_time += days * 86400

    event = _first_event(stream)

    assert event.start_timestamp == ts.now() - past_sec
    assert len(built_events) == 1


def test_long_absence_rebases_without_replaying_history(short_events, built_events):
    ts = _FakeTimeService()
    stream = demo_streams.build_demo_streams(ts, _PAST_SEC)[0]
    window = EventWindow(stream.events_iter, stream_colors=[1])
    window.get_visible(ts.now() - _PAST_SEC, ts.now() + 5400)
    ts.current_time += 30 * 86400
    built_events.clear()
    window_start = ts.now() - _PAST_SEC

    visible = window.get_visible(window_start, ts.now() + 5400)

    assert [event.start_timestamp for event, _ in visible] == list(
        range(window_start, window_start + 7200, 900)
    )
    assert len(built_events) == 9  # Eight visible events and one lookahead.


def test_normal_scroll_preserves_events_and_lookahead(short_events, built_events):
    ts = _FakeTimeService()
    stream = demo_streams.build_demo_streams(ts, _PAST_SEC)[0]
    window = EventWindow(stream.events_iter, stream_colors=[1])
    visible = window.get_visible(ts.now() - _PAST_SEC, ts.now() + 5400)
    original = [event for event, _ in visible]
    lookahead = window._next[0]
    built_events.clear()
    ts.current_time += 900

    visible = window.get_visible(ts.now() - _PAST_SEC, ts.now() + 5400)

    assert [event for event, _ in visible] == original[1:] + [lookahead]
    assert len(built_events) == 1


def test_rebase_does_not_move_cursor_backwards(short_events):
    ts = _FakeTimeService()
    stream = demo_streams.build_demo_streams(ts, _PAST_SEC)[0]
    first = _first_event(stream)
    ts.current_time -= 3600

    second = next(stream.events_iter)

    assert second.start_timestamp == (
        first.start_timestamp + first.wall_clock_duration_sec
    )
