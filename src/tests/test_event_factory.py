from __future__ import annotations

import time

import pytest

from scheduling import event_factory

from conftest import (
    DST_END as _DST_END,
    DST_START as _DST_START,
    utc_epoch as _utc_epoch,
)

_WORK_DAYS = {0, 1, 2, 3, 4}


class _FakeTimeService:
    """Minimal TimeService stand-in for factory tests."""

    def __init__(self, utc_epoch: int) -> None:
        from services.time_service import TimeService
        self._svc = TimeService(
            tz_offset_hours=1,
            dst_start_rule=_DST_START,
            dst_end_rule=_DST_END,
            dst_offset_hours=1,
            get_time=lambda: utc_epoch,
        )

    def now(self) -> int:
        return self._svc.now()


def _collect(gen, n: int) -> list:
    """Collect n events from a generator."""
    return [next(gen) for _ in range(n)]


# ── basic structure ──────────────────────────────────────────────────


def test_yields_10_events_per_cycle():
    """Mon–Fri schedule has 5 work + 5 rest/weekend = 10 events per week."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)  # Mon 09:00 CEST (summer)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    names = [e.label for e in events]
    assert names.count("work") == 5
    assert names.count("rest") == 4
    assert names.count("weekend") == 1


def test_events_are_contiguous():
    """Each event's start + duration_sec == next event's start (wall-clock)."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 20)
    for i in range(len(events) - 1):
        assert events[i].start_timestamp + events[i].wall_clock_duration_sec == events[i + 1].start_timestamp, \
            f"gap between event {i} ({events[i].label}) and {i+1} ({events[i+1].label})"


def test_work_duration_is_9h():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.label == "work":
            assert e.wall_clock_duration_sec == 9 * 3600


def test_rest_duration_is_15h():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.label == "rest":
            assert e.wall_clock_duration_sec == 15 * 3600


def test_weekend_duration_is_63h():
    """Fri 17:00 → Mon 08:00 = 63h wall-clock."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.label == "weekend":
            assert e.wall_clock_duration_sec == 63 * 3600


def test_overnight_weekend_ends_at_next_shift():
    utc = _utc_epoch(2026, 6, 15, 21, 0, 0)  # Mon 23:00 CEST, inside Mon's 22:00 shift
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (22, 0), (6, 0), ts)
    events = _collect(gen, 11)
    assert [e.label for e in events[8:]] == ["work", "weekend", "work"]
    assert events[9].wall_clock_duration_sec == 64 * 3600
    _, _, _, hour, minute, _, weekday, _ = time.gmtime(events[10].start_timestamp)
    assert (weekday, hour, minute) == (0, 22, 0)


# ── local-epoch positioning ──────────────────────────────────────────


def test_timestamps_are_local_epoch():
    """Event start_timestamp decomposed via gmtime gives local time components."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)  # Mon 09:00 CEST
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    event = next(gen)  # current event (should be "work" starting at 08:00 local)
    assert event.label == "work"
    t = time.gmtime(event.start_timestamp)
    assert t[3] == 8   # hour
    assert t[4] == 0   # minute
    assert t[6] == 0   # weekday: Monday


# ── validation ──────────────────────────────────────────────────────


def test_invalid_work_start_raises():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    with pytest.raises(ValueError, match="Work start time is invalid"):
        next(event_factory.work_week_loop(_WORK_DAYS, (25, 0), (17, 0), ts))


def test_invalid_work_end_raises():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    with pytest.raises(ValueError, match="Work end time is invalid"):
        next(event_factory.work_week_loop(_WORK_DAYS, (8, 0), (-1, 0), ts))


def test_same_start_end_raises():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    with pytest.raises(ValueError, match="same"):
        next(event_factory.work_week_loop(_WORK_DAYS, (8, 0), (8, 0), ts))


def test_empty_work_days_raises():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    with pytest.raises(ValueError, match="Work days"):
        next(event_factory.work_week_loop(set(), (8, 0), (17, 0), ts))


def test_invalid_work_days_raises():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    with pytest.raises(ValueError, match="Work days"):
        next(event_factory.work_week_loop({7}, (8, 0), (17, 0), ts))
