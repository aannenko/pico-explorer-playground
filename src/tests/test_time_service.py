from __future__ import annotations

import time

import pytest

from services.time_service import (
    TimeService,
    _days_in_month,
    _is_leap,
    _mday_of_nth_weekday,
    _offset_span,
    _transition_utc,
    _weekday,
)

from conftest import (
    CEST_EXTRA_SEC as _CEST_EXTRA_SEC,
    CET_OFFSET_SEC as _CET_OFFSET_SEC,
    DST_END as _DST_END,
    DST_START as _DST_START,
    utc_epoch as _utc_epoch,
)


# ── _is_leap ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("year, is_leap", [(2024, True), (1900, False), (2000, True), (2023, False)])
def test_is_leap_follows_the_gregorian_rule(year: int, is_leap: bool):
    assert _is_leap(year) is is_leap


# ── _days_in_month ───────────────────────────────────────────────────


@pytest.mark.parametrize("year, february_days", [(2023, 28), (2024, 29)])
def test_days_in_each_month(year: int, february_days: int):
    days = [_days_in_month(year, month) for month in range(1, 13)]
    assert days == [31, february_days, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]


# ── _weekday (Sakamoto) ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "date, expected",
    [
        ((2024, 1, 1), 0),   # Monday
        ((2024, 1, 7), 6),   # Sunday
        ((2026, 3, 29), 6),  # Sunday (last Sun of Mar 2026)
        ((2026, 10, 25), 6), # Sunday (last Sun of Oct 2026)
        ((2025, 3, 30), 6),  # Sunday (last Sun of Mar 2025)
        ((2025, 10, 26), 6), # Sunday (last Sun of Oct 2025)
        ((2000, 1, 1), 5),   # Saturday
        ((2023, 12, 25), 0), # Monday
    ],
)
def test_weekday(date, expected):
    assert _weekday(*date) == expected


# ── _mday_of_nth_weekday ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "year, month, week, weekday, mday",
    [
        # The last Sundays of March and October.
        (2026, 3, -1, 6, 29),
        (2026, 10, -1, 6, 25),
        (2025, 3, -1, 6, 30),
        (2025, 10, -1, 6, 26),
        (2024, 1, 1, 0, 1),  # Jan 1 2024 is Monday
        (2024, 1, 2, 0, 8),
    ],
)
def test_mday_of_the_nth_or_last_weekday(year: int, month: int, week: int, weekday: int, mday: int):
    assert _mday_of_nth_weekday(year, month, week, weekday) == mday


# ── _transition_utc ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule, offset_sec, utc",
    [
        # Last Sunday of March 2026 at 02:00 CET = 01:00 UTC
        ((3, -1, 6, 2), 3600, _utc_epoch(2026, 3, 29, 1, 0, 0)),
        # Last Sunday of October 2026 at 03:00 CEST = 01:00 UTC
        ((10, -1, 6, 3), 7200, _utc_epoch(2026, 10, 25, 1, 0, 0)),
    ],
)
def test_transition_utc_takes_the_rule_hour_at_the_given_offset(
    rule: tuple[int, int, int, int], offset_sec: int, utc: int
):
    assert _transition_utc(2026, rule, offset_sec=offset_sec) == utc


# ── _offset_span ────────────────────────────────────────────────────

_WINTER_2025_26 = (_utc_epoch(2025, 10, 26, 1, 0, 0), _utc_epoch(2026, 3, 29, 1, 0, 0), _CET_OFFSET_SEC)
_SUMMER_2026 = (
    _utc_epoch(2026, 3, 29, 1, 0, 0), _utc_epoch(2026, 10, 25, 1, 0, 0), _CET_OFFSET_SEC + _CEST_EXTRA_SEC
)
_WINTER_2026_27 = (_utc_epoch(2026, 10, 25, 1, 0, 0), _utc_epoch(2027, 3, 28, 1, 0, 0), _CET_OFFSET_SEC)


@pytest.mark.parametrize(
    "utc, span",
    [
        (_utc_epoch(2026, 1, 15, 12, 0, 0), _WINTER_2025_26),
        # 01:59 CET, a minute before the clocks jump to 03:00 CEST.
        (_utc_epoch(2026, 3, 29, 0, 59, 0), _WINTER_2025_26),
        (_utc_epoch(2026, 3, 29, 1, 0, 0), _SUMMER_2026),
        (_utc_epoch(2026, 7, 15, 12, 0, 0), _SUMMER_2026),
        # 02:59 CEST, a minute before the clocks fall back to 02:00 CET.
        (_utc_epoch(2026, 10, 25, 0, 59, 0), _SUMMER_2026),
        (_utc_epoch(2026, 10, 25, 1, 0, 0), _WINTER_2026_27),
        (_utc_epoch(2026, 11, 1, 12, 0, 0), _WINTER_2026_27),
    ],
)
def test_span_runs_from_the_last_change_at_or_before_to_the_next(utc: int, span: tuple[int, int, int]):
    assert _offset_span(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) == span


# ── TimeService ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "utc, offset_sec",
    [
        (_utc_epoch(2026, 1, 15, 12, 0, 0), 3600),
        (_utc_epoch(2026, 7, 15, 12, 0, 0), 7200),
        # 02:30 CEST, in the last hour before the fall-back.
        (_utc_epoch(2026, 10, 25, 0, 30, 0), 7200),
        # 03:00 CEST, just after the spring-forward.
        (_utc_epoch(2026, 3, 29, 1, 0, 0), 7200),
    ],
)
def test_cet_conversions_apply_the_offset_in_force(utc: int, offset_sec: int):
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    assert svc.to_utc(utc + offset_sec) == utc
    assert svc.utc_offset_sec(utc) == offset_sec
    assert svc.now() == utc + offset_sec


@pytest.mark.parametrize(
    "tz_offset_hours, offset_sec",
    [
        (5, 18_000),
        (5.5, 19_800),
        (5.75, 20_700),
        (-3.5, -12_600),
        (12.75, 45_900),
        (14.0, 50_400),
        (-12.0, -43_200),
        # 0.9 s, rounded to the nearest second.
        (0.00025, 1),
        (-0.00025, -1),
    ],
)
def test_without_dst_times_shift_by_the_offset_rounded_to_whole_seconds(tz_offset_hours: float, offset_sec: int):
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=tz_offset_hours, dst_start_rule=None, dst_end_rule=None,
        get_time=lambda: utc,
    )
    local = svc.now()
    assert type(local) is int
    assert local == utc + offset_sec
    utc_offset_sec = svc.utc_offset_sec(utc)
    assert type(utc_offset_sec) is int
    assert utc_offset_sec == offset_sec
    to_utc = svc.to_utc(local)
    assert type(to_utc) is int
    assert to_utc == utc


def test_now_reads_the_wall_clock_once_per_call():
    """Each read allocates a big int, so re-deriving must reuse the instant ``now()`` read."""
    clock = [0]
    reads = [0]

    def get_time() -> int:
        reads[0] += 1
        return clock[0]

    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=get_time,
    )
    # A first read, one that re-derives across the spring-forward, then a plain one.
    for utc in (
        _utc_epoch(2026, 3, 29, 0, 59, 0),
        _utc_epoch(2026, 3, 29, 1, 0, 0),
        _utc_epoch(2026, 3, 29, 1, 1, 0),
    ):
        clock[0] = utc
        reads_before = reads[0]
        svc.now()
        assert reads[0] == reads_before + 1


def test_lookups_either_side_of_one_dst_change_do_its_dst_math_once(monkeypatch):
    winter_utc = _utc_epoch(2026, 3, 20, 12, 0, 0)
    summer_utc = _utc_epoch(2026, 4, 3, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END, dst_offset_hours=1,
        get_time=lambda: winter_utc,
    )
    mktime = time.mktime
    mktime_calls = [0]

    def counting_mktime(fields: tuple) -> int:
        mktime_calls[0] += 1
        return mktime(fields)

    monkeypatch.setattr(time, "mktime", counting_mktime)
    svc.utc_offset_sec(winter_utc)
    svc.utc_offset_sec(summer_utc)
    calls_for_both_spans = mktime_calls[0]

    for i in range(3):
        assert svc.now() == winter_utc + 3600
        assert svc.to_local(summer_utc + i) == summer_utc + i + 7200
        assert svc.to_utc(summer_utc + 7200) == summer_utc
    assert mktime_calls[0] == calls_for_both_spans


def test_a_new_span_replaces_the_one_used_least_recently(monkeypatch):
    winter_utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END, dst_offset_hours=1,
        get_time=lambda: winter_utc,
    )
    for utc in (winter_utc, _utc_epoch(2026, 7, 15, 12, 0, 0), winter_utc, _utc_epoch(2026, 12, 15, 12, 0, 0)):
        svc.utc_offset_sec(utc)
    mktime = time.mktime
    mktime_calls = [0]

    def counting_mktime(fields: tuple) -> int:
        mktime_calls[0] += 1
        return mktime(fields)

    monkeypatch.setattr(time, "mktime", counting_mktime)
    svc.utc_offset_sec(winter_utc)

    assert mktime_calls[0] == 0


@pytest.mark.parametrize("which", ["dst_start_rule", "dst_end_rule"])
@pytest.mark.parametrize(
    "rule",
    [(0, -1, 6, 2), (13, -1, 6, 2), (3, 0, 6, 2), (3, 6, 6, 2), (3, -2, 6, 2), (3, -1, -1, 2), (3, -1, 7, 2)],
)
def test_rejects_a_dst_rule_out_of_range(which: str, rule: tuple[int, int, int, int]):
    kwargs = {"dst_start_rule": _DST_START, "dst_end_rule": _DST_END, which: rule}
    with pytest.raises(ValueError):
        TimeService(tz_offset_hours=1, dst_offset_hours=1, get_time=lambda: 0, **kwargs)


# ── fractional offsets ──────────────────────────────────────────────

# Newfoundland: UTC-3:30, +1 h DST from the 2nd Sunday of March at 02:00 NST
# to the 1st Sunday of November at 02:00 NDT.
_NEWFOUNDLAND_DST_START = (3, 2, 6, 2)
_NEWFOUNDLAND_DST_END = (11, 1, 6, 2)
# Lord Howe Island: UTC+10:30, +30 min DST from the 1st Sunday of October at
# 02:00 LHST to the 1st Sunday of April at 02:00 LHDT.
_LORD_HOWE_DST_START = (10, 1, 6, 2)
_LORD_HOWE_DST_END = (4, 1, 6, 2)

_ZONE_KWARGS = {
    "CET": {
        "tz_offset_hours": 1, "dst_offset_hours": 1,
        "dst_start_rule": _DST_START, "dst_end_rule": _DST_END,
    },
    "Newfoundland": {
        "tz_offset_hours": -3.5, "dst_offset_hours": 1.0,
        "dst_start_rule": _NEWFOUNDLAND_DST_START, "dst_end_rule": _NEWFOUNDLAND_DST_END,
    },
    "Lord Howe": {
        "tz_offset_hours": 10.5, "dst_offset_hours": 0.5,
        "dst_start_rule": _LORD_HOWE_DST_START, "dst_end_rule": _LORD_HOWE_DST_END,
    },
}


def _zone_service(zone: str) -> TimeService:
    return TimeService(**_ZONE_KWARGS[zone], get_time=lambda: _utc_epoch(2026, 1, 15, 12, 0, 0))


@pytest.mark.parametrize(
    "utc",
    [
        _utc_epoch(2026, 3, 29, 0, 59, 0),
        _utc_epoch(2026, 3, 29, 1, 0, 0),
        _utc_epoch(2026, 10, 25, 0, 59, 0),
        _utc_epoch(2026, 10, 25, 1, 0, 0),
    ],
)
def test_zero_dst_offset_ignores_the_default_dst_rules(utc):
    # A zone without DST (India) keeps the default EU rules with a zero DST offset.
    svc = TimeService(
        tz_offset_hours=5.5, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=0, get_time=lambda: utc,
    )
    local = svc.now()
    assert type(local) is int
    assert local == utc + 19_800


@pytest.mark.parametrize(
    "zone, dst_start_fields, dst_end_fields, standard_offset_sec, dst_offset_sec",
    [
        # Sun 2026-03-08 02:00 NST = 05:30 UTC; Sun 2026-11-01 02:00 NDT = 04:30 UTC.
        ("Newfoundland", (2026, 3, 8, 5, 30), (2026, 11, 1, 4, 30), -12_600, -9_000),
        # Sun 2026-10-04 02:00 LHST = Sat 15:30 UTC; Sun 2026-04-05 02:00 LHDT = Sat 15:00 UTC.
        ("Lord Howe", (2026, 10, 3, 15, 30), (2026, 4, 4, 15, 0), 37_800, 39_600),
    ],
)
def test_a_fractional_offset_changes_at_each_dst_change(
    zone: str,
    dst_start_fields: tuple[int, int, int, int, int],
    dst_end_fields: tuple[int, int, int, int, int],
    standard_offset_sec: int,
    dst_offset_sec: int,
) -> None:
    svc = _zone_service(zone)
    dst_start_utc = _utc_epoch(*dst_start_fields, 0)
    dst_end_utc = _utc_epoch(*dst_end_fields, 0)
    assert svc.utc_offset_sec(dst_start_utc - 1) == standard_offset_sec
    assert svc.utc_offset_sec(dst_start_utc) == dst_offset_sec
    assert svc.utc_offset_sec(dst_end_utc - 1) == dst_offset_sec
    assert svc.utc_offset_sec(dst_end_utc) == standard_offset_sec
    assert type(svc.utc_offset_sec(dst_start_utc)) is int


@pytest.mark.parametrize(
    "utc, wall_hours, real_sec",
    [
        # From Sun 00:00 LHDT, 4 h on the wall clock span the 02:00 LHDT -> 01:30 LHST fall-back.
        pytest.param(_utc_epoch(2026, 4, 4, 13, 0, 0), 4, 4 * 3600 + 1800, id="fall-back"),
        # From Sun 01:00 LHST, 3 h on the wall clock span the 02:00 LHST -> 02:30 LHDT gap.
        pytest.param(_utc_epoch(2026, 10, 3, 14, 30, 0), 3, 3 * 3600 - 1800, id="spring-forward"),
    ],
)
def test_lord_howe_dst_changes_lengthen_or_shorten_wall_clock_hours_by_half_an_hour(
    utc: int, wall_hours: int, real_sec: int
) -> None:
    svc = TimeService(**_ZONE_KWARGS["Lord Howe"], get_time=lambda: utc)
    local_start = svc.now()
    assert type(local_start) is int
    real = svc.to_utc(local_start + wall_hours * 3600) - utc
    assert type(real) is int
    assert real == real_sec


def test_lord_howe_ambiguous_local_time_prefers_dst():
    utc = _utc_epoch(2026, 4, 4, 13, 0, 0)  # Sun 00:00 LHDT
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: utc,
    )
    # 01:45 occurs at 14:45 UTC (LHDT) and again at 15:15 UTC (LHST).
    local_0145 = svc.now() + 105 * 60
    assert svc.to_utc(local_0145) == _utc_epoch(2026, 4, 4, 14, 45, 0)


# ── spring-forward gap ──────────────────────────────────────────────


def _local_epoch(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return time.mktime((year, month, day, hour, minute, 0, 0, 0))


@pytest.mark.parametrize(
    "zone, gap_local, jump_utc",
    [
        # 02:00 CET jumps to 03:00 CEST at 01:00 UTC.
        ("CET", (2026, 3, 29, 2, 30), (2026, 3, 29, 1, 0)),
        # 02:00 NST jumps to 03:00 NDT at 05:30 UTC.
        ("Newfoundland", (2026, 3, 8, 2, 30), (2026, 3, 8, 5, 30)),
        # 02:00 LHST jumps to 02:30 LHDT at 15:30 UTC the day before.
        ("Lord Howe", (2026, 10, 4, 2, 15), (2026, 10, 3, 15, 30)),
    ],
)
def test_to_utc_maps_a_gap_time_to_the_jump(
    zone: str, gap_local: tuple[int, int, int, int, int], jump_utc: tuple[int, int, int, int, int]
) -> None:
    assert _zone_service(zone).to_utc(_local_epoch(*gap_local)) == _utc_epoch(*jump_utc, 0)


@pytest.mark.parametrize(
    "zone, transition_days",
    [
        ("CET", ((2026, 3, 29), (2026, 10, 25))),
        ("Newfoundland", ((2026, 3, 8), (2026, 11, 1))),
        ("Lord Howe", ((2026, 4, 5), (2026, 10, 4))),
    ],
)
def test_to_utc_never_decreases_across_transitions(
    zone: str, transition_days: tuple[tuple[int, int, int], ...]
) -> None:
    svc = _zone_service(zone)
    for year, month, day in transition_days:
        # Every transition here moves the clocks between 01:00 and 03:00.
        midnight = _local_epoch(year, month, day, 0)
        utcs = [svc.to_utc(local) for local in range(midnight, midnight + 5 * 3600, 5 * 60)]
        assert utcs == sorted(utcs)


# ── transitions in another UTC year ─────────────────────────────────

# DST starts on the 1st Thursday of January at 00:00 UTC+1: 2025-12-31 23:00 UTC in 2026.
_JANUARY_START_KWARGS = {
    "tz_offset_hours": 1, "dst_offset_hours": 1,
    "dst_start_rule": (1, 1, 3, 0), "dst_end_rule": (7, 1, 3, 2),
}
# DST ends on the last Thursday of December at 23:00 UTC-4: 2027-01-01 03:00 UTC in 2026.
_DECEMBER_END_KWARGS = {
    "tz_offset_hours": -5, "dst_offset_hours": 1,
    "dst_start_rule": (3, 2, 6, 2), "dst_end_rule": (12, -1, 3, 23),
}


@pytest.mark.parametrize(
    "kwargs, utc_fields, offset_sec",
    [
        pytest.param(_JANUARY_START_KWARGS, (2025, 12, 31, 22, 59), 3600, id="before a January start"),
        pytest.param(_JANUARY_START_KWARGS, (2025, 12, 31, 23, 0), 7200, id="after a January start"),
        pytest.param(_DECEMBER_END_KWARGS, (2027, 1, 1, 2, 59), -14_400, id="before a December end"),
        pytest.param(_DECEMBER_END_KWARGS, (2027, 1, 1, 3, 0), -18_000, id="after a December end"),
    ],
)
def test_offset_follows_a_transition_in_another_utc_year(
    kwargs: dict, utc_fields: tuple[int, int, int, int, int], offset_sec: int
) -> None:
    utc = _utc_epoch(*utc_fields, 0)
    svc = TimeService(**kwargs, get_time=lambda: utc)
    assert svc.utc_offset_sec(utc) == offset_sec
    assert svc.now() == utc + offset_sec


@pytest.mark.parametrize(
    "kwargs, local_fields, utc_fields",
    [
        # The clocks jump from 00:00 to 01:00.
        pytest.param(_JANUARY_START_KWARGS, (2026, 1, 1, 0, 30), (2025, 12, 31, 23, 0), id="January gap"),
        pytest.param(_JANUARY_START_KWARGS, (2026, 1, 1, 1, 30), (2025, 12, 31, 23, 30), id="after a January jump"),
        # The clocks go back from 23:00 to 22:00, so 22:30 occurs twice.
        pytest.param(_DECEMBER_END_KWARGS, (2026, 12, 31, 22, 30), (2027, 1, 1, 2, 30), id="December overlap"),
        pytest.param(_DECEMBER_END_KWARGS, (2026, 12, 31, 23, 30), (2027, 1, 1, 4, 30), id="after a December end"),
    ],
)
def test_to_utc_around_a_transition_in_another_utc_year(
    kwargs: dict, local_fields: tuple[int, int, int, int, int], utc_fields: tuple[int, int, int, int, int]
) -> None:
    svc = TimeService(**kwargs, get_time=lambda: _utc_epoch(2026, 6, 15, 12, 0, 0))
    assert svc.to_utc(_local_epoch(*local_fields)) == _utc_epoch(*utc_fields, 0)


# ── reads across a DST change ───────────────────────────────────────


@pytest.mark.parametrize(
    "kwargs, before_fields, change_fields, offset_before_sec, offset_after_sec",
    [
        pytest.param(
            _ZONE_KWARGS["CET"], (2026, 3, 29, 0, 30), (2026, 3, 29, 1, 0), 3600, 7200, id="CET spring-forward"
        ),
        pytest.param(
            _ZONE_KWARGS["CET"], (2026, 10, 25, 0, 30), (2026, 10, 25, 1, 0), 7200, 3600, id="CET fall-back"
        ),
        pytest.param(
            _ZONE_KWARGS["Lord Howe"], (2026, 10, 3, 15, 0), (2026, 10, 3, 15, 30), 37_800, 39_600,
            id="Lord Howe half-hour spring-forward",
        ),
        pytest.param(
            _DECEMBER_END_KWARGS, (2027, 1, 1, 1, 0), (2027, 1, 1, 3, 0), -14_400, -18_000,
            id="a December end in the next UTC year",
        ),
    ],
)
def test_now_applies_a_dst_change_from_the_first_read_after_it(
    kwargs: dict,
    before_fields: tuple[int, int, int, int, int],
    change_fields: tuple[int, int, int, int, int],
    offset_before_sec: int,
    offset_after_sec: int,
) -> None:
    clock = [_utc_epoch(*before_fields, 0)]
    svc = TimeService(**kwargs, get_time=lambda: clock[0])
    assert svc.now() == clock[0] + offset_before_sec
    clock[0] = _utc_epoch(*change_fields, 0)
    local = svc.now()
    assert type(local) is int
    assert local == clock[0] + offset_after_sec


# ── NTP sync ────────────────────────────────────────────────────────

_WINTER_UTC = _utc_epoch(2026, 1, 15, 12, 0, 0)
_SUMMER_2036_UTC = _utc_epoch(2036, 7, 1, 12, 0, 0)


class _FakeNtp:
    """Records ``sync_time`` calls; each sets the clock to ``synced_utc`` if given, then returns ``ok``."""

    def __init__(self, utc: int, synced_utc: int | None = None, ok: bool = True) -> None:
        self.clock = [utc]
        self.calls: list[int] = []
        self._synced_utc = synced_utc
        self._ok = ok

    def sync_time(self, attempts: int) -> bool:
        self.calls.append(attempts)
        if self._synced_utc is not None:
            self.clock[0] = self._synced_utc
        return self._ok


def _cet_service(ntp: _FakeNtp, sync_time=None) -> TimeService:  # sync_time: (int) -> bool
    return TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END, dst_offset_hours=1,
        get_time=lambda: ntp.clock[0], sync_time=sync_time or ntp.sync_time,
    )


def test_sync_initial_reports_progress_and_makes_five_attempts():
    ntp = _FakeNtp(_WINTER_UTC)
    progress: list[str] = []
    _cet_service(ntp).sync_initial(on_progress=progress.append)
    assert ntp.calls == [5]
    assert progress == ["sync time"]


def test_sync_initial_raises_when_every_attempt_fails():
    ntp = _FakeNtp(_WINTER_UTC, ok=False)
    progress: list[str] = []
    with pytest.raises(RuntimeError, match="Could not sync time"):
        _cet_service(ntp).sync_initial(on_progress=progress.append)
    assert progress == ["sync time", "ntp fail"]


def test_sync_initial_applies_the_synced_offset_at_once():
    # The unsynced RTC reads winter; the sync lands in summer.
    ntp = _FakeNtp(_utc_epoch(2021, 1, 1, 0, 0, 0), synced_utc=_utc_epoch(2026, 7, 15, 12, 0, 0))
    svc = _cet_service(ntp)
    assert svc.now() == ntp.clock[0] + 3600
    svc.sync_initial()
    assert svc.now() == ntp.clock[0] + 7200


@pytest.mark.parametrize("ok", [True, False])
def test_sync_makes_one_attempt_by_default_and_returns_its_result(ok: bool):
    ntp = _FakeNtp(_WINTER_UTC, ok=ok)
    assert _cet_service(ntp).sync() is ok
    assert ntp.calls == [1]


@pytest.mark.parametrize("ok", [True, False])
def test_sync_that_steps_the_clock_back_restores_the_offset_and_transitions_even_if_it_fails(ok: bool):
    # A bad NTP reply put the RTC in summer 2036; the next sync steps it back to winter 2026.
    ntp = _FakeNtp(_SUMMER_2036_UTC, synced_utc=_WINTER_UTC, ok=ok)
    svc = _cet_service(ntp)
    assert svc.now() == ntp.clock[0] + 7200
    svc.sync()
    assert svc.now() == ntp.clock[0] + 3600
    ntp.clock[0] = _utc_epoch(2026, 3, 29, 1, 0, 0)  # the 2026 spring-forward
    assert svc.now() == ntp.clock[0] + 7200


def test_sync_that_raises_after_moving_the_clock_still_leaves_the_right_offset():
    ntp = _FakeNtp(_SUMMER_2036_UTC, synced_utc=_WINTER_UTC)

    def raising_sync_time(attempts: int) -> bool:
        ntp.sync_time(attempts)
        raise OSError("socket closed")

    svc = _cet_service(ntp, sync_time=raising_sync_time)
    svc.now()
    with pytest.raises(OSError):
        svc.sync()
    assert svc.now() == ntp.clock[0] + 3600


def _fail_dst_math_once(monkeypatch) -> None:
    mktime = time.mktime
    failures = [1]

    def failing_mktime(fields: tuple) -> int:
        if failures[0]:
            failures[0] -= 1
            raise MemoryError
        return mktime(fields)

    monkeypatch.setattr(time, "mktime", failing_mktime)


def test_failed_rederive_after_a_sync_keeps_the_old_offset_until_the_next_read(monkeypatch, capsys):
    ntp = _FakeNtp(_SUMMER_2036_UTC, synced_utc=_WINTER_UTC)
    svc = _cet_service(ntp)
    svc.now()
    svc.sync()
    _fail_dst_math_once(monkeypatch)
    assert svc.now() == ntp.clock[0] + 7200
    assert "[time] dst err:" in capsys.readouterr().out
    assert svc.now() == ntp.clock[0] + 3600


def test_failed_rederive_at_a_dst_change_keeps_the_old_offset_until_the_next_read(monkeypatch, capsys):
    ntp = _FakeNtp(_utc_epoch(2026, 3, 29, 0, 59, 0))
    svc = _cet_service(ntp)
    svc.now()
    ntp.clock[0] = _utc_epoch(2026, 3, 29, 1, 0, 0)  # the spring-forward
    _fail_dst_math_once(monkeypatch)
    assert svc.now() == ntp.clock[0] + 3600
    assert "[time] dst err:" in capsys.readouterr().out
    assert svc.now() == ntp.clock[0] + 7200


def test_dst_math_errors_other_than_memory_still_raise(monkeypatch):
    svc = _cet_service(_FakeNtp(_WINTER_UTC))

    def broken_mktime(fields: tuple) -> int:
        raise OverflowError

    monkeypatch.setattr(time, "mktime", broken_mktime)
    with pytest.raises(OverflowError):
        svc.now()
