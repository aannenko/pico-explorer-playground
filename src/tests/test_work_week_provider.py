"""Tests for the work-week stream provider."""

from scheduling.providers import work_week


class _FakeTimeService:
    def now(self) -> int:
        return 1_000_000

    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        return wall_clock_sec


def test_build_stream_yields_work_rest_weekend_events():
    stream = work_week.build_stream(_FakeTimeService())
    names = {next(stream.events_iter).name for _ in range(6)}
    assert names <= {"work", "rest", "weekend"}


def test_events_use_default_color_index_zero():
    stream = work_week.build_stream(_FakeTimeService())
    assert all(next(stream.events_iter).color_index == 0 for _ in range(6))
