"""Tests for the waste-collection stream."""

import random
import time

import pytest

from conftest import DST_END, DST_START, utc_epoch
from scheduling.event import Event
from scheduling.providers import waste
from services.time_service import TimeService

_MIN = 60
_HOUR = 3600
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY
# Thursday 8 Jan 2026, 06:00 CET: weeks from any DST change.
_ANCHOR = (2026, 1, 8)
_ANCHOR_UTC = utc_epoch(2026, 1, 8, 5, 0, 0)


def _cet() -> TimeService:
    return TimeService(
        tz_offset_hours=1, dst_start_rule=DST_START, dst_end_rule=DST_END, dst_offset_hours=1, get_time=lambda: 0
    )


def _stream(  # -> (int) -> list[Event]
    pickups: list[tuple[str, int, tuple[int, int, int], int, int, int, int]],
    horizon_sec: int = 8 * _WEEK,
    slot_count: int = 20,
    time_service: TimeService | None = None,
):
    return waste.build_stream(time_service or _cet(), pickups, horizon_sec, slot_count)


def _starts(events: list[Event]) -> list[int]:
    return [e.start_utc for e in events]


def test_an_empty_schedule_has_no_events():
    assert _stream([])(_ANCHOR_UTC) == []


@pytest.mark.parametrize("period_weeks", [1, 2])
def test_a_pickup_recurs_every_period_from_its_anchor(period_weeks: int):
    events = _stream([("BIO", 5, _ANCHOR, 6, 0, 60, period_weeks)], horizon_sec=6 * _WEEK)(_ANCHOR_UTC - _DAY)

    assert _starts(events) == list(range(_ANCHOR_UTC, _ANCHOR_UTC + 6 * _WEEK - _DAY, period_weeks * _WEEK))


def test_events_carry_the_upper_cased_label_the_colour_and_the_real_duration():
    event = _stream([("plast", 2, _ANCHOR, 6, 0, 90, 2)])(_ANCHOR_UTC - _DAY)[0]

    assert (event.label, event.color_index, event.duration_sec) == ("PLAST", 2, 90 * _MIN)


def test_pickups_merge_in_start_order_and_ties_keep_their_order():
    pickups = [
        ("PAPER", 1, (2026, 1, 9), 6, 0, 60, 1),
        ("BIO", 5, _ANCHOR, 6, 0, 60, 1),
        ("GLASS", 7, (2026, 1, 9), 6, 0, 60, 1),
    ]

    events = _stream(pickups, horizon_sec=2 * _WEEK)(_ANCHOR_UTC - _DAY)

    assert [e.label for e in events] == ["BIO", "PAPER", "GLASS", "BIO", "PAPER", "GLASS"]


def test_the_slot_count_and_the_horizon_bound_the_list():
    pickup = [("BIO", 5, _ANCHOR, 6, 0, 60, 1)]

    assert len(_stream(pickup, slot_count=2)(_ANCHOR_UTC - _DAY)) == 2
    assert _starts(_stream(pickup, horizon_sec=_WEEK + _DAY)(_ANCHOR_UTC)) == [_ANCHOR_UTC, _ANCHOR_UTC + _WEEK]


@pytest.mark.parametrize(
    "duration_min, listed_sec",
    [
        (60, _HOUR),
        # A zero duration lasts its one instant.
        (0, 1),
    ],
)
def test_an_occurrence_is_listed_until_it_is_over(duration_min: int, listed_sec: int):
    stream = _stream([("BIO", 5, _ANCHOR, 6, 0, duration_min, 1)])

    assert _starts(stream(_ANCHOR_UTC + listed_sec - 1))[0] == _ANCHOR_UTC
    assert _starts(stream(_ANCHOR_UTC + listed_sec))[0] == _ANCHOR_UTC + _WEEK


def test_a_one_off_ends_for_good_but_shows_again_after_the_clock_steps_back():
    stream = _stream([("BULKY", 3, _ANCHOR, 6, 0, 60, 0)])

    assert stream(_ANCHOR_UTC + _HOUR) == []
    assert _starts(stream(_ANCHOR_UTC + _HOUR - 1)) == [_ANCHOR_UTC]


def test_far_from_its_anchor_the_next_occurrence_comes_first():
    events = _stream([("BIO", 5, _ANCHOR, 6, 0, 60, 2)])(_ANCHOR_UTC + 6 * _WEEK + _DAY)

    assert events[0].start_utc == _ANCHOR_UTC + 8 * _WEEK


def test_the_wall_clock_time_holds_across_dst_changes():
    time_service = _cet()
    # Weekly at 06:00 from Thursday 19 March 2026, across the spring-forward on Sunday 29 March.
    events = _stream([("BIO", 5, (2026, 3, 19), 6, 0, 60, 1)], time_service=time_service)(
        utc_epoch(2026, 3, 18, 0, 0, 0)
    )

    assert [time.gmtime(time_service.to_local(e.start_utc))[3:5] for e in events[:3]] == [(6, 0)] * 3
    assert events[2].start_utc - events[1].start_utc == _WEEK - _HOUR


@pytest.mark.parametrize(
    "day, start_utc",
    [
        pytest.param((2026, 3, 29), utc_epoch(2026, 3, 29, 1, 0, 0), id="in the skipped hour, at the jump"),
        pytest.param((2026, 10, 25), utc_epoch(2026, 10, 25, 0, 30, 0), id="in the repeated hour, at its first pass"),
    ],
)
def test_a_pickup_starts_when_the_clock_first_shows_its_time(day: tuple[int, int, int], start_utc: int):
    events = _stream([("BIO", 5, day, 2, 30, 60, 0)])(utc_epoch(*day, 0, 0, 0) - _DAY)

    assert _starts(events) == [start_utc]


def test_an_occurrence_in_progress_across_the_spring_forward_is_listed():
    # Sundays at 01:00 CET for two hours: on 29 March the clock jumps at 01:00 UTC, mid-way.
    events = _stream([("BIO", 5, (2026, 3, 22), 1, 0, 120, 1)])(utc_epoch(2026, 3, 29, 1, 30, 0))

    assert events[0].start_utc == utc_epoch(2026, 3, 29, 0, 0, 0)


def test_an_occurrence_over_in_the_repeated_hour_is_not_listed():
    # Sundays at 02:50 for ten minutes; now 02:40 CET, the repeated hour's second pass, after 02:50 CEST ended.
    events = _stream([("BIO", 5, (2026, 10, 18), 2, 50, 10, 1)])(utc_epoch(2026, 10, 25, 1, 40, 0))

    assert events[0].start_utc == utc_epoch(2026, 11, 1, 1, 50, 0)


def test_past_one_offs_cost_no_dst_math(monkeypatch):
    pickups = [
        ("BIO", 5, _ANCHOR, 6, 0, 60, 1),
        ("WINTER", 3, (2025, 1, 7), 6, 0, 60, 0),
        ("SUMMER", 3, (2025, 7, 1), 6, 0, 60, 0),
    ]
    stream = _stream(pickups)
    stream(_ANCHOR_UTC - _DAY)
    mktime = time.mktime
    mktime_calls = [0]

    def counting_mktime(fields: tuple) -> int:
        mktime_calls[0] += 1
        return mktime(fields)

    monkeypatch.setattr(time, "mktime", counting_mktime)
    stream(_ANCHOR_UTC - _DAY + _HOUR)

    assert mktime_calls[0] == 0

def _reference(
    time_service: TimeService,
    pickups: list[tuple[str, int, tuple[int, int, int], int, int, int, int]],
    now_utc: int,
    horizon_sec: int,
    slot_count: int,
) -> list[tuple[int, str, int, int]]:
    """Every occurrence, enumerated from its anchor, that isn't over at ``now_utc`` and starts within the horizon."""
    found = []
    for index, (label, color_index, (year, month, day), hh, mm, duration_min, period_weeks) in enumerate(pickups):
        anchor_local = time.mktime((year, month, day, hh, mm, 0, 0, 0))
        duration_sec = duration_min * _MIN
        period_sec = period_weeks * _WEEK if period_weeks > 0 else 0
        k_values = [0]
        if period_sec:
            # Durations here stay under 21 days, so earlier occurrences are over.
            first_k = max(0, (now_utc - 22 * _DAY - anchor_local) // period_sec)
            k_values = range(first_k, max(first_k, (now_utc + horizon_sec + _DAY - anchor_local) // period_sec + 2))
        for k in k_values:
            start_utc = time_service.to_utc(anchor_local + k * period_sec)
            if start_utc + max(duration_sec, 1) > now_utc and start_utc < now_utc + horizon_sec:
                found.append((start_utc, index, label.upper(), duration_sec, color_index))
    found.sort()
    return [(start_utc, label, duration_sec, color_index) for start_utc, _, label, duration_sec, color_index in found][
        :slot_count
    ]


@pytest.mark.parametrize(
    "time_service",
    [
        pytest.param(_cet(), id="CET"),
        pytest.param(TimeService(10.5, (10, 1, 6, 2), (4, 1, 6, 2), 0.5, get_time=lambda: 0), id="Lord Howe"),
        pytest.param(TimeService(1, DST_START, DST_END, 0, get_time=lambda: 0), id="no DST offset"),
    ],
)
def test_matches_every_occurrence_enumerated_from_the_anchors(time_service: TimeService):
    rng = random.Random(20261117)
    hours = (0, 1, 2, 3, 6, 8, 22, 23)
    for _ in range(150):
        pickups = [
            (
                "P%d" % i,
                i,
                (rng.choice((2025, 2026, 2027)), rng.randint(1, 12), rng.randint(1, 28)),
                rng.choice(hours),
                rng.choice((0, 30, 59)),
                rng.choice((0, 1, 60, 120, 24 * 60, 20 * 24 * 60)),
                rng.choice((0, 1, 1, 2, 3)),
            )
            for i in range(rng.randint(1, 5))
        ]
        horizon_sec = rng.choice((_DAY, _WEEK))
        slot_count = rng.choice((2, 7))
        stream = waste.build_stream(time_service, pickups, horizon_sec, slot_count)
        for _ in range(12):
            # Mostly near a DST change of 2026, where wall-clock and UTC arithmetic part.
            now_utc = rng.choice((
                utc_epoch(2026, 3, 29, 1, 0, 0), utc_epoch(2026, 10, 25, 1, 0, 0), utc_epoch(2026, 4, 5, 15, 0, 0),
                utc_epoch(2026, 10, 4, 15, 0, 0),
            )) + rng.randint(-3 * _WEEK, 3 * _WEEK)
            got = [(e.start_utc, e.label, e.duration_sec, e.color_index) for e in stream(now_utc)]
            assert got == _reference(time_service, pickups, now_utc, horizon_sec, slot_count), (pickups, now_utc)