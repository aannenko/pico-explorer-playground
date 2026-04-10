import calendar
import pytest
from datetime import UTC, datetime
from scheduling.event_factory import work_week_loop


def _to_timestamp(dt: datetime) -> int:
    return calendar.timegm(dt.utctimetuple())


class _FakeTimeService:
    """Minimal stand-in for TimeService in factory tests."""
    def __init__(self, now_value: int):
        self._now = now_value
    def now(self) -> int:
        return self._now
    def to_utc(self, local_epoch: int) -> int:
        return local_epoch  # identity: tests assume local == UTC
    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        return wall_clock_sec  # no DST correction in legacy tests


def _mock_gmtime(monkeypatch: pytest.MonkeyPatch, dt: datetime) -> int:
    """Freeze gmtime() to a MicroPython-like 8-tuple and return the matching timestamp."""
    timestamp = _to_timestamp(dt)
    gmtime_tuple = (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.weekday(),
        dt.timetuple().tm_yday,
    )
    monkeypatch.setattr("scheduling.event_factory.time.gmtime", lambda _: gmtime_tuple)
    return timestamp


def test_work_week_loop_daytime_schedule_sequence(monkeypatch: pytest.MonkeyPatch) -> None:
    now_dt = datetime(2024, 1, 3, 10, 30, tzinfo=UTC)
    now_timestamp = _mock_gmtime(monkeypatch, now_dt)

    ts = _FakeTimeService(now_timestamp)
    gen = work_week_loop({0, 1, 2, 3, 4}, (9, 0), (17, 0), time_service=ts)
    events = [next(gen) for _ in range(6)]

    expected = [
        ("work", datetime(2024, 1, 3, 9, 0, tzinfo=UTC), 8 * 3600),
        ("rest", datetime(2024, 1, 3, 17, 0, tzinfo=UTC), 16 * 3600),
        ("work", datetime(2024, 1, 4, 9, 0, tzinfo=UTC), 8 * 3600),
        ("rest", datetime(2024, 1, 4, 17, 0, tzinfo=UTC), 16 * 3600),
        ("work", datetime(2024, 1, 5, 9, 0, tzinfo=UTC), 8 * 3600),
        ("weekend", datetime(2024, 1, 5, 17, 0, tzinfo=UTC), 64 * 3600),
    ]

    for event, (name, dt, duration) in zip(events, expected):
        assert event.name == name
        assert event.start_timestamp == _to_timestamp(dt)
        assert event.duration_sec == duration


def test_work_week_loop_midnight_shift_weekend(monkeypatch: pytest.MonkeyPatch) -> None:
    now_dt = datetime(2024, 1, 8, 12, 0, tzinfo=UTC)
    now_timestamp = _mock_gmtime(monkeypatch, now_dt)

    ts = _FakeTimeService(now_timestamp)
    gen = work_week_loop({4, 5}, (22, 0), (6, 0), time_service=ts)

    weekend_event = next(gen)
    assert weekend_event.name == "weekend"
    assert weekend_event.start_timestamp == _to_timestamp(datetime(2024, 1, 7, 6, 0, tzinfo=UTC))
    assert weekend_event.duration_sec == 112 * 3600

    work_event = next(gen)
    assert work_event.name == "work"
    assert work_event.start_timestamp == weekend_event.start_timestamp + weekend_event.duration_sec
    assert work_event.duration_sec == 8 * 3600

    rest_event = next(gen)
    assert rest_event.name == "rest"
    assert rest_event.start_timestamp == work_event.start_timestamp + work_event.duration_sec
    assert rest_event.duration_sec == 16 * 3600


def test_work_week_loop_validates_input(monkeypatch: pytest.MonkeyPatch) -> None:
    now_dt = datetime(2024, 1, 1, 0, 0, tzinfo=UTC)
    now_timestamp = _mock_gmtime(monkeypatch, now_dt)

    ts = _FakeTimeService(now_timestamp)
    gen = work_week_loop(set(), (9, 0), (17, 0), time_service=ts)
    with pytest.raises(ValueError, match="Work days must be one or more"):
        next(gen)
