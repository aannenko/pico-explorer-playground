"""Tests for the shared event-run primitives."""

import pytest

from scheduling.event_runs import RunBuilder, level

_HOUR = 3600
_T0 = 1_794_855_600
_COLORS = (2, 0, 8)
_CEST_SEC = 7200


def _builder(max_events: int = 10, utc_offset_sec=lambda utc: _CEST_SEC, now_utc: int = 0) -> RunBuilder:
    return RunBuilder(_COLORS, utc_offset_sec, max_events, now_utc)


def _spans(events) -> list[tuple]:
    return [(e.label, e.start_timestamp, e.wall_clock_duration_sec, e.color_index) for e in events]


# ---------------------------------------------------------------------------
# level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(None, 0), (0, 0), (59, 0), (60, 1), (79, 1), (80, 2), (99, 2), (100, 3), (500, 3)],
)
def test_level_counts_the_thresholds_reached(value, expected):
    assert level(value, (60, 80, 100)) == expected


def test_level_reaches_a_zero_threshold_with_zero():
    # Precipitation's level 1 starts at any amount, including a reported 0.0 mm.
    assert level(0.0, (0.0, 2.5, 7.6)) == 1
    assert level(2.49, (0.0, 2.5, 7.6)) == 1
    assert level(7.6, (0.0, 2.5, 7.6)) == 3


# ---------------------------------------------------------------------------
# RunBuilder
# ---------------------------------------------------------------------------


def test_no_hours_build_no_events():
    assert _builder().events() == []


def test_one_hour_is_one_local_event_coloured_by_its_level():
    builder = _builder()
    builder.add(_T0, "RAIN", 2)

    assert _spans(builder.events()) == [("RAIN", _T0 + _CEST_SEC, _HOUR, 0)]


def test_adjacent_hours_with_one_label_join_at_their_highest_level():
    builder = _builder()
    for i, hour_level in enumerate((1, 3, 2)):
        builder.add(_T0 + i * _HOUR, "UV", hour_level)

    assert _spans(builder.events()) == [("UV", _T0 + _CEST_SEC, 3 * _HOUR, 8)]


@pytest.mark.parametrize(
    "second",
    [
        (_T0 + _HOUR, "SNOW", 1),  # another label
        (_T0 + 2 * _HOUR, "RAIN", 1),  # an hour later than adjacent
    ],
)
def test_another_label_or_a_gap_starts_a_new_event(second):
    builder = _builder()
    builder.add(_T0, "RAIN", 1)
    builder.add(*second)

    assert [(e.start_timestamp - _CEST_SEC, e.label) for e in builder.events()] == [(_T0, "RAIN"), second[:2]]


@pytest.mark.parametrize("quiet_hour", [("RAIN", 0), (None, 0), (None, 2)])
def test_a_quiet_hour_ends_the_event(quiet_hour):
    builder = _builder()
    builder.add(_T0, "RAIN", 1)
    builder.add(_T0 + _HOUR, *quiet_hour)
    builder.add(_T0 + 2 * _HOUR, "RAIN", 1)

    assert [e.start_timestamp - _CEST_SEC for e in builder.events()] == [_T0, _T0 + 2 * _HOUR]


def test_hours_after_max_events_are_ignored():
    builder = _builder(max_events=2)
    for i, label in enumerate(("RAIN", "SNOW", "RAIN", "SNOW")):
        builder.add(_T0 + i * _HOUR, label, 1)

    assert [e.label for e in builder.events()] == ["RAIN", "SNOW"]


def test_events_over_by_now_are_dropped_and_leave_their_places_to_later_ones():
    builder = _builder(max_events=14, now_utc=_T0 + _HOUR // 2)
    for i in range(24, 0, -1):
        builder.add(_T0 - i * _HOUR, "RAIN" if i % 2 else "SNOW", 1)
    builder.add(_T0, "STORM", 3)

    assert _spans(builder.events()) == [("STORM", _T0 + _CEST_SEC, _HOUR, 8)]


def test_an_event_in_progress_keeps_its_past_hours():
    builder = _builder(now_utc=_T0 + _HOUR // 2)
    for i in range(-2, 2):
        builder.add(_T0 + i * _HOUR, "RAIN", 1)

    assert _spans(builder.events()) == [("RAIN", _T0 - 2 * _HOUR + _CEST_SEC, 4 * _HOUR, 2)]


def test_a_run_across_the_fall_back_lasts_its_wall_clock_time():
    # Clocks go back from CEST to CET at 01:00 UTC.
    def utc_offset_sec(utc: int) -> int:
        return 7200 if utc < _T0 + _HOUR else 3600

    builder = _builder(utc_offset_sec=utc_offset_sec)
    for i in range(3):
        builder.add(_T0 + i * _HOUR, "RAIN", 1)

    assert _spans(builder.events()) == [("RAIN", _T0 + 7200, 2 * _HOUR, 2)]


def test_a_one_hour_run_ending_at_the_fall_back_is_empty_in_local_time():
    def utc_offset_sec(utc: int) -> int:
        return 7200 if utc < _T0 + _HOUR else 3600

    builder = _builder(utc_offset_sec=utc_offset_sec)
    builder.add(_T0, "RAIN", 1)

    assert _spans(builder.events()) == [("RAIN", _T0 + 7200, 0, 2)]


def test_a_run_across_the_spring_forward_lasts_its_wall_clock_time():
    def utc_offset_sec(utc: int) -> int:
        return 3600 if utc < _T0 + _HOUR else 7200

    builder = _builder(utc_offset_sec=utc_offset_sec)
    for i in range(2):
        builder.add(_T0 + i * _HOUR, "RAIN", 1)

    assert _spans(builder.events()) == [("RAIN", _T0 + 3600, 3 * _HOUR, 2)]
