"""Tests for the shared event-run primitives."""

import pytest

from scheduling.event_runs import _level, best_by_priority, merge_runs

_HOUR = 3600
_E0 = 1_700_000_000


# ---------------------------------------------------------------------------
# _level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [(None, 0), (0, 0), (59, 0), (60, 1), (70, 1), (79, 1), (80, 2), (200, 2)],
)
def test_level_bands(value, expected):
    assert _level(value, 60, 80) == expected


def test_level_inclusive_lower_bounds():
    # Exactly at an edge classifies into that band (inclusive >=).
    assert _level(6, 6, 8) == 1
    assert _level(8, 6, 8) == 2


# ---------------------------------------------------------------------------
# best_by_priority
# ---------------------------------------------------------------------------


def test_best_by_priority_empty_is_none():
    assert best_by_priority([]) is None


def test_best_by_priority_single_passthrough():
    assert best_by_priority([(1, "A", 7)]) == ("A", 7)


def test_best_by_priority_max_wins():
    assert best_by_priority([(1, "A", 7), (3, "B", 8), (2, "C", 2)]) == ("B", 8)


def test_best_by_priority_tie_keeps_first():
    # Equal priority -> earliest listed wins (strict > in the comparison).
    assert best_by_priority([(2, "FIRST", 2), (2, "SECOND", 8)]) == ("FIRST", 2)


def test_best_by_priority_returns_label_and_color_only():
    assert best_by_priority([(5, "X", 9)]) == ("X", 9)


# ---------------------------------------------------------------------------
# merge_runs
# ---------------------------------------------------------------------------


def test_merge_runs_empty():
    assert merge_runs([]) == []


def test_merge_runs_single_hour():
    events = merge_runs([(_E0, "RAIN", 7)])

    assert len(events) == 1
    ev = events[0]
    assert ev.name == "RAIN"
    assert ev.start_timestamp == _E0
    assert ev.wall_clock_duration_sec == _HOUR
    assert ev.color_index == 7


def test_merge_runs_contiguous_equal_merge():
    events = merge_runs([
        (_E0, "RAIN", 7),
        (_E0 + _HOUR, "RAIN", 7),
        (_E0 + 2 * _HOUR, "RAIN", 7),
    ])

    assert len(events) == 1
    assert events[0].start_timestamp == _E0
    assert events[0].wall_clock_duration_sec == 3 * _HOUR


def test_merge_runs_label_change_splits():
    events = merge_runs([(_E0, "RAIN", 7), (_E0 + _HOUR, "SNOW", 7)])

    assert [e.name for e in events] == ["RAIN", "SNOW"]
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)


def test_merge_runs_color_change_splits():
    events = merge_runs([(_E0, "RAIN", 7), (_E0 + _HOUR, "RAIN", 2)])

    assert [e.color_index for e in events] == [7, 2]
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)


def test_merge_runs_time_discontinuity_splits_even_without_gap_entry():
    # Two winning hours 2h apart (a below-threshold hour was simply omitted):
    # the adjacency check (epoch == prev_end) must split, not merge into a
    # 2-wide bar.
    events = merge_runs([(_E0, "AQI", 2), (_E0 + 2 * _HOUR, "AQI", 2)])

    assert len(events) == 2
    assert all(e.wall_clock_duration_sec == _HOUR for e in events)
    assert events[1].start_timestamp == _E0 + 2 * _HOUR


def test_merge_runs_adjacent_then_gap():
    events = merge_runs([
        (_E0, "AQI", 2),
        (_E0 + _HOUR, "AQI", 2),
        (_E0 + 3 * _HOUR, "AQI", 2),
    ])

    assert len(events) == 2
    assert events[0].wall_clock_duration_sec == 2 * _HOUR
    assert events[1].start_timestamp == _E0 + 3 * _HOUR
    assert events[1].wall_clock_duration_sec == _HOUR
