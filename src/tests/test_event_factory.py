from __future__ import annotations

import calendar
import time

import pytest

from scheduling import event_factory


def _utc_epoch(*args) -> int:
    """Helper: calendar-style args → UTC epoch (matches conftest mktime stub)."""
    return int(calendar.timegm(args))


_CET_OFFSET = 1
_CEST_EXTRA = 1
_DST_START = (3, -1, 6, 2)   # Last Sun of Mar at 02:00 CET
_DST_END = (10, -1, 6, 3)    # Last Sun of Oct at 03:00 CEST
_WORK_DAYS = {0, 1, 2, 3, 4}


class _FakeTimeService:
    """Minimal TimeService stand-in for factory tests."""

    def __init__(self, utc_epoch: int, tz_offset: int = 1, dst_offset: int = 1,
                 dst_start=_DST_START, dst_end=_DST_END):
        from services.time_service import TimeService
        self._svc = TimeService(
            tz_offset=tz_offset,
            dst_start=dst_start,
            dst_end=dst_end,
            dst_offset=dst_offset,
            get_time=lambda: utc_epoch,
        )

    def now(self) -> int:
        return self._svc.now()

    def to_utc(self, local_epoch: int) -> int:
        return self._svc.to_utc(local_epoch)

    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        return self._svc.real_duration(local_start, wall_clock_sec)


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
    names = [e.name for e in events]
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
            f"gap between event {i} ({events[i].name}) and {i+1} ({events[i+1].name})"


def test_work_duration_is_9h():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.name == "work":
            assert e.wall_clock_duration_sec == 9 * 3600


def test_rest_duration_is_15h():
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.name == "rest":
            assert e.wall_clock_duration_sec == 15 * 3600


def test_weekend_duration_is_63h():
    """Fri 17:00 → Mon 08:00 = 63h wall-clock."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        if e.name == "weekend":
            assert e.wall_clock_duration_sec == 63 * 3600


# ── local-epoch positioning ──────────────────────────────────────────


def test_timestamps_are_local_epoch():
    """Event start_timestamp decomposed via gmtime gives local time components."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)  # Mon 09:00 CEST
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    event = next(gen)  # current event (should be "work" starting at 08:00 local)
    assert event.name == "work"
    t = time.gmtime(event.start_timestamp)
    assert t[3] == 8   # hour
    assert t[4] == 0   # minute
    assert t[6] == 0   # weekday: Monday


# ── DST correction: no crossing ─────────────────────────────────────


def test_no_dst_crossing_real_equals_wall():
    """Summer week — no DST transition, real == wall-clock for all events."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        assert e.real_duration_sec == e.wall_clock_duration_sec, \
            f"{e.name}: real={e.real_duration_sec} != wall={e.wall_clock_duration_sec}"


# ── DST correction: spring forward ──────────────────────────────────


def test_spring_forward_rest_shorter():
    """Rest spanning spring-forward is 1h shorter in real seconds."""
    # Sat 2026-03-28 12:00 CET (winter) = 11:00 UTC
    utc = _utc_epoch(2026, 3, 28, 11, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    # Current event should be weekend (Fri 17:00 CET → Mon 08:00 CEST)
    events = _collect(gen, 10)

    # Find events crossing the spring-forward (Sun 2026-03-29 02:00 CET → 03:00 CEST)
    spring_utc = _utc_epoch(2026, 3, 29, 1, 0, 0)
    for e in events:
        utc_start = ts.to_utc(e.start_timestamp)
        utc_end = utc_start + e.real_duration_sec
        if utc_start < spring_utc < utc_end:
            # This event crosses spring-forward
            assert e.real_duration_sec == e.wall_clock_duration_sec - 3600, \
                f"{e.name}: expected real = wall - 3600, got real={e.real_duration_sec}, wall={e.wall_clock_duration_sec}"
            break
    else:
        pytest.fail("No event found crossing spring-forward transition")


# ── DST correction: fall back ───────────────────────────────────────


def test_fall_back_weekend_longer():
    """Weekend spanning fall-back is 1h longer in real seconds."""
    # Sat 2026-10-24 12:00 CEST (summer) = 10:00 UTC
    utc = _utc_epoch(2026, 10, 24, 10, 0, 0)
    ts = _FakeTimeService(utc)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)

    # Find event crossing fall-back (Sun 2026-10-25 01:00 UTC)
    fall_utc = _utc_epoch(2026, 10, 25, 1, 0, 0)
    for e in events:
        utc_start = ts.to_utc(e.start_timestamp)
        utc_end = utc_start + e.real_duration_sec
        if utc_start < fall_utc < utc_end:
            assert e.real_duration_sec == e.wall_clock_duration_sec + 3600, \
                f"{e.name}: expected real = wall + 3600, got real={e.real_duration_sec}, wall={e.wall_clock_duration_sec}"
            break
    else:
        pytest.fail("No event found crossing fall-back transition")


# ── no DST config ───────────────────────────────────────────────────


def test_no_dst_config_real_equals_wall():
    """Without DST config, real always equals wall-clock."""
    utc = _utc_epoch(2026, 6, 15, 7, 0, 0)
    ts = _FakeTimeService(utc, tz_offset=5, dst_offset=0, dst_start=None, dst_end=None)
    gen = event_factory.work_week_loop(_WORK_DAYS, (8, 0), (17, 0), ts)
    events = _collect(gen, 10)
    for e in events:
        assert e.real_duration_sec == e.wall_clock_duration_sec


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
