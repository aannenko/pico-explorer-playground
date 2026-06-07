"""Tests for the waste-collection stream provider."""

import time

import pytest

from scheduling.providers import waste

_DAY = 24 * 60 * 60
_WEEK = 7 * _DAY


class _FakeTimeService:
    def __init__(self, now: int) -> None:
        self._now = now

    def now(self) -> int:
        return self._now

    def real_duration(self, start: int, dur: int) -> int:
        return dur


def _epoch(y: int, m: int, d: int, hh: int = 6, mm: int = 0) -> int:
    return time.mktime((y, m, d, hh, mm, 0, 0, 0))


def _take(stream, n: int) -> list:
    return [next(stream.events_iter) for _ in range(n)]


def test_empty_schedule_yields_nothing():
    stream = waste.build_stream(_FakeTimeService(0), [])
    with pytest.raises(StopIteration):
        next(stream.events_iter)


def test_single_entry_biweekly_cadence():
    now = _epoch(2026, 6, 4) - _DAY  # day before anchor → no fast-forward
    sched = [("BIO", 5, (2026, 6, 4), 6, 0, 60, 2)]

    starts = [e.start_timestamp for e in _take(waste.build_stream(_FakeTimeService(now), sched), 3)]

    base = _epoch(2026, 6, 4)
    assert starts == [base, base + 2 * _WEEK, base + 4 * _WEEK]


def test_weekly_cadence():
    now = _epoch(2026, 6, 4) - _DAY
    sched = [("X", 0, (2026, 6, 4), 6, 0, 30, 1)]

    starts = [e.start_timestamp for e in _take(waste.build_stream(_FakeTimeService(now), sched), 3)]

    base = _epoch(2026, 6, 4)
    assert starts == [base, base + _WEEK, base + 2 * _WEEK]


def test_event_carries_label_color_index_and_duration():
    now = _epoch(2026, 6, 4) - _DAY
    sched = [("PLAST", 2, (2026, 6, 4), 6, 0, 60, 2)]

    event = _take(waste.build_stream(_FakeTimeService(now), sched), 1)[0]

    assert event.name == "PLAST"
    assert event.color_index == 2
    assert event.wall_clock_duration_sec == 60 * 60


def test_multiple_entries_yield_in_start_order():
    now = _epoch(2026, 6, 4) - _DAY
    sched = [
        ("BIO", 5, (2026, 6, 4), 6, 0, 60, 2),    # Thu
        ("PAPER", 1, (2026, 6, 5), 6, 0, 60, 2),  # Fri
    ]

    events = _take(waste.build_stream(_FakeTimeService(now), sched), 4)

    starts = [e.start_timestamp for e in events]
    assert starts == sorted(starts)
    assert [e.name for e in events] == ["BIO", "PAPER", "BIO", "PAPER"]


def test_fast_forwards_past_occurrences():
    # now is 10 weeks (5 biweekly periods) after the anchor.
    now = _epoch(2026, 8, 13)
    sched = [("BIO", 5, (2026, 6, 4), 6, 0, 60, 2)]

    event = _take(waste.build_stream(_FakeTimeService(now), sched), 1)[0]

    # First emitted occurrence is the one still in/after the window, not the anchor.
    assert event.start_timestamp + event.wall_clock_duration_sec > now
    base = _epoch(2026, 6, 4)
    assert (event.start_timestamp - base) % (2 * _WEEK) == 0


def test_wall_clock_hour_stable_across_periods():
    # The configured 06:00 wall-clock time is preserved as occurrences advance.
    now = _epoch(2026, 3, 25) - _DAY
    sched = [("BIO", 5, (2026, 3, 25), 6, 0, 60, 2)]

    events = _take(waste.build_stream(_FakeTimeService(now), sched), 3)

    for event in events:
        assert time.gmtime(event.start_timestamp)[3] == 6  # hour stays 06:00


def test_real_duration_is_applied():
    class _SentinelTS(_FakeTimeService):
        def real_duration(self, start: int, dur: int) -> int:
            return dur + 7

    now = _epoch(2026, 6, 4) - _DAY
    sched = [("BIO", 5, (2026, 6, 4), 6, 0, 60, 2)]

    event = _take(waste.build_stream(_SentinelTS(now), sched), 1)[0]

    assert event.real_duration_sec == 60 * 60 + 7


def test_overlapping_entries_do_not_raise():
    now = _epoch(2026, 6, 4) - _DAY
    sched = [
        ("BIO", 5, (2026, 6, 4), 6, 0, 120, 2),
        ("PLAST", 2, (2026, 6, 4), 6, 30, 120, 2),  # overlaps BIO
    ]

    events = _take(waste.build_stream(_FakeTimeService(now), sched), 4)

    assert len(events) == 4
