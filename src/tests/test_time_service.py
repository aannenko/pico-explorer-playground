from __future__ import annotations

import time

import pytest

from services.time_service import (
    TimeService,
    _days_in_month,
    _is_dst,
    _is_leap,
    _mday_of_nth_weekday,
    _next_transition_utc,
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


def test_leap_year_divisible_by_4():
    assert _is_leap(2024) is True


def test_not_leap_year_century():
    assert _is_leap(1900) is False


def test_leap_year_divisible_by_400():
    assert _is_leap(2000) is True


def test_not_leap_year_common():
    assert _is_leap(2023) is False


# ── _days_in_month ───────────────────────────────────────────────────


def test_days_in_february_leap():
    assert _days_in_month(2024, 2) == 29


def test_days_in_february_non_leap():
    assert _days_in_month(2023, 2) == 28


def test_days_in_months():
    expected = {1: 31, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}
    for month, days in expected.items():
        assert _days_in_month(2023, month) == days, f"month={month}"


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


def test_last_sunday_of_march_2026():
    assert _mday_of_nth_weekday(2026, 3, -1, 6) == 29


def test_last_sunday_of_october_2026():
    assert _mday_of_nth_weekday(2026, 10, -1, 6) == 25


def test_last_sunday_of_march_2025():
    assert _mday_of_nth_weekday(2025, 3, -1, 6) == 30


def test_last_sunday_of_october_2025():
    assert _mday_of_nth_weekday(2025, 10, -1, 6) == 26


def test_first_monday_of_january_2024():
    assert _mday_of_nth_weekday(2024, 1, 1, 0) == 1  # Jan 1 2024 is Monday


def test_second_monday_of_january_2024():
    assert _mday_of_nth_weekday(2024, 1, 2, 0) == 8


# ── _transition_utc ─────────────────────────────────────────────────


def test_cet_dst_start_2026():
    # Last Sunday of March 2026 at 02:00 CET = 01:00 UTC
    rule = (3, -1, 6, 2)
    epoch = _transition_utc(2026, rule, offset_sec=3600)
    assert epoch == _utc_epoch(2026, 3, 29, 1, 0, 0)


def test_cest_dst_end_2026():
    # Last Sunday of October 2026 at 03:00 CEST = 01:00 UTC
    rule = (10, -1, 6, 3)
    epoch = _transition_utc(2026, rule, offset_sec=7200)
    assert epoch == _utc_epoch(2026, 10, 25, 1, 0, 0)


# ── _is_dst ──────────────────────────────────────────────────────────


def test_is_dst_winter():
    # January 2026 — definitely not DST
    utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is False


def test_is_dst_summer():
    # July 2026 — definitely DST
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is True


def test_is_dst_just_before_spring_forward():
    # 2026-03-29 00:59 UTC → 01:59 CET, not yet DST
    utc = _utc_epoch(2026, 3, 29, 0, 59, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is False


def test_is_dst_at_spring_forward():
    # 2026-03-29 01:00 UTC → 02:00 CET → clocks jump to 03:00 CEST
    utc = _utc_epoch(2026, 3, 29, 1, 0, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is True


def test_is_dst_just_before_fall_back():
    # 2026-10-25 00:59 UTC → 02:59 CEST, still DST
    utc = _utc_epoch(2026, 10, 25, 0, 59, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is True


def test_is_dst_at_fall_back():
    # 2026-10-25 01:00 UTC → 03:00 CEST → clocks fall back to 02:00 CET
    utc = _utc_epoch(2026, 10, 25, 1, 0, 0)
    assert _is_dst(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END) is False


# ── _next_transition_utc ────────────────────────────────────────────


def test_next_transition_from_winter():
    # January → next transition is spring forward (March)
    utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    nxt = _next_transition_utc(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END)
    assert nxt == _utc_epoch(2026, 3, 29, 1, 0, 0)


def test_next_transition_from_summer():
    # July → next transition is fall back (October)
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    nxt = _next_transition_utc(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END)
    assert nxt == _utc_epoch(2026, 10, 25, 1, 0, 0)


def test_next_transition_after_fall_back():
    # November → next transition is spring forward of next year
    utc = _utc_epoch(2026, 11, 1, 12, 0, 0)
    nxt = _next_transition_utc(utc, _CET_OFFSET_SEC, _CEST_EXTRA_SEC, _DST_START, _DST_END)
    assert nxt == _utc_epoch(2027, 3, 28, 1, 0, 0)


# ── TimeService ─────────────────────────────────────────────────────


def test_now_returns_local_epoch():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: utc,
    )
    # Summer: CET+1 DST+1 = UTC+2
    assert svc.now() == utc + 2 * 3600


def test_now_winter_offset():
    utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: utc,
    )
    # Winter: CET+1 only
    assert svc.now() == utc + 1 * 3600


def test_no_dst_config_uses_tz_only():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=5,
        dst_start_rule=None,
        dst_end_rule=None,
        dst_offset_hours=0,
        get_time=lambda: utc,
    )
    assert svc.now() == utc + 5 * 3600


def test_now_applies_the_spring_forward_from_the_first_read_after_it():
    clock = [_utc_epoch(2026, 3, 29, 0, 30, 0)]  # 00:30 UTC, before spring forward
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
    )
    assert svc.now() == clock[0] + 1 * 3600  # CET

    clock[0] = _utc_epoch(2026, 3, 29, 1, 0, 0)
    assert svc.now() == clock[0] + 2 * 3600  # CEST


def test_now_applies_the_fall_back_from_the_first_read_after_it():
    clock = [_utc_epoch(2026, 10, 25, 0, 30, 0)]  # 02:30 CEST, before fall back
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
    )
    assert svc.now() == clock[0] + 2 * 3600  # CEST

    clock[0] = _utc_epoch(2026, 10, 25, 1, 0, 0)
    assert svc.now() == clock[0] + 1 * 3600  # CET


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


def test_reads_away_from_a_dst_change_do_no_dst_math(monkeypatch):
    clock = [_utc_epoch(2026, 1, 15, 12, 0, 0)]
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
    )
    svc.now()
    mktime = time.mktime
    mktime_calls = [0]

    def counting_mktime(fields: tuple) -> int:
        mktime_calls[0] += 1
        return mktime(fields)

    monkeypatch.setattr(time, "mktime", counting_mktime)
    for _ in range(5):
        clock[0] += 60
        svc.now()
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


# ── utc_offset_sec ──────────────────────────────────────────────────


def test_utc_offset_sec_winter():
    utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    assert svc.utc_offset_sec(utc) == 1 * 3600


def test_utc_offset_sec_summer():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    assert svc.utc_offset_sec(utc) == 2 * 3600


def test_utc_offset_sec_no_dst_config():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=5, dst_start_rule=None, dst_end_rule=None,
        dst_offset_hours=0, get_time=lambda: utc,
    )
    assert svc.utc_offset_sec(utc) == 5 * 3600


# ── to_utc ──────────────────────────────────────────────────────────


def test_to_utc_winter_round_trip():
    utc = _utc_epoch(2026, 1, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    local = svc.now()
    assert svc.to_utc(local) == utc


def test_to_utc_summer_round_trip():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    local = svc.now()
    assert svc.to_utc(local) == utc


def test_to_utc_no_dst_config():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=5, dst_start_rule=None, dst_end_rule=None,
        dst_offset_hours=0, get_time=lambda: utc,
    )
    local = svc.now()
    assert svc.to_utc(local) == utc


def test_to_utc_last_hour_before_fall_back():
    """00:30 UTC on fall-back day: local is 02:30 CEST, to_utc must give 00:30 UTC."""
    utc = _utc_epoch(2026, 10, 25, 0, 30, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    local = utc + 2 * 3600  # 02:30 CEST
    assert svc.to_utc(local) == utc


def test_to_utc_just_after_spring_forward():
    """03:00 CEST (right after spring-forward) → 01:00 UTC."""
    utc = _utc_epoch(2026, 3, 29, 1, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    local = utc + 2 * 3600  # 03:00 CEST
    assert svc.to_utc(local) == utc


# ── fractional offsets ──────────────────────────────────────────────

# Newfoundland: UTC-3:30, +1 h DST from the 2nd Sunday of March at 02:00 NST
# to the 1st Sunday of November at 02:00 NDT.
_NEWFOUNDLAND_DST_START = (3, 2, 6, 2)
_NEWFOUNDLAND_DST_END = (11, 1, 6, 2)
# Lord Howe Island: UTC+10:30, +30 min DST from the 1st Sunday of October at
# 02:00 LHST to the 1st Sunday of April at 02:00 LHDT.
_LORD_HOWE_DST_START = (10, 1, 6, 2)
_LORD_HOWE_DST_END = (4, 1, 6, 2)


@pytest.mark.parametrize(
    "tz_offset_hours, offset_sec",
    [
        (5.5, 19_800),
        (5.75, 20_700),
        (-3.5, -12_600),
        (12.75, 45_900),
        (14.0, 50_400),
        (-12.0, -43_200),
    ],
)
def test_tz_offset_keeps_times_ints(tz_offset_hours, offset_sec):
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=tz_offset_hours, dst_start_rule=None, dst_end_rule=None,
        get_time=lambda: utc,
    )
    local = svc.now()
    assert type(local) is int
    assert local == utc + offset_sec
    assert type(svc.utc_offset_sec(utc)) is int
    to_utc = svc.to_utc(local)
    assert type(to_utc) is int
    assert to_utc == utc


@pytest.mark.parametrize("tz_offset_hours, offset_sec", [(0.00025, 1), (-0.00025, -1)])
def test_offset_rounds_to_nearest_second(tz_offset_hours, offset_sec):
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=tz_offset_hours, dst_start_rule=None, dst_end_rule=None,
        get_time=lambda: utc,
    )
    assert svc.now() == utc + offset_sec


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


def test_newfoundland_dst_transitions():
    svc = TimeService(
        tz_offset_hours=-3.5, dst_start_rule=_NEWFOUNDLAND_DST_START,
        dst_end_rule=_NEWFOUNDLAND_DST_END, dst_offset_hours=1.0,
        get_time=lambda: _utc_epoch(2026, 1, 15, 12, 0, 0),
    )
    # Sun 2026-03-08 02:00 NST = 05:30 UTC; Sun 2026-11-01 02:00 NDT = 04:30 UTC.
    spring = _utc_epoch(2026, 3, 8, 5, 30, 0)
    fall = _utc_epoch(2026, 11, 1, 4, 30, 0)
    assert svc.utc_offset_sec(spring - 1) == -12_600
    assert svc.utc_offset_sec(spring) == -9_000
    assert svc.utc_offset_sec(fall - 1) == -9_000
    assert svc.utc_offset_sec(fall) == -12_600


def test_lord_howe_half_hour_dst_transitions():
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: _utc_epoch(2026, 7, 15, 12, 0, 0),
    )
    # Sun 2026-04-05 02:00 LHDT = Sat 15:00 UTC; Sun 2026-10-04 02:00 LHST = Sat 15:30 UTC.
    fall = _utc_epoch(2026, 4, 4, 15, 0, 0)
    spring = _utc_epoch(2026, 10, 3, 15, 30, 0)
    assert svc.utc_offset_sec(fall - 1) == 39_600
    assert svc.utc_offset_sec(fall) == 37_800
    assert svc.utc_offset_sec(spring - 1) == 37_800
    assert svc.utc_offset_sec(spring) == 39_600
    assert type(svc.utc_offset_sec(spring)) is int


def test_lord_howe_fall_back_lengthens_by_half_an_hour():
    utc = _utc_epoch(2026, 4, 4, 13, 0, 0)  # Sun 00:00 LHDT
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: utc,
    )
    local_start = svc.now()
    assert type(local_start) is int
    # 00:00 to 04:00 on the wall clock spans the 02:00 LHDT -> 01:30 LHST fall-back.
    real = svc.real_remaining_sec(local_start + 4 * 3600)
    assert type(real) is int
    assert real == 4 * 3600 + 1800


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


def test_lord_howe_spring_forward_shortens_by_half_an_hour():
    utc = _utc_epoch(2026, 10, 3, 14, 30, 0)  # Sun 01:00 LHST
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: utc,
    )
    # 01:00 to 04:00 on the wall clock spans the 02:00 LHST -> 02:30 LHDT gap.
    assert svc.real_remaining_sec(svc.now() + 3 * 3600) == 3 * 3600 - 1800


def test_now_applies_a_fractional_dst_offset():
    clock = [_utc_epoch(2026, 10, 3, 15, 0, 0)]  # 30 min before Lord Howe's spring-forward
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: clock[0],
    )
    assert svc.now() == clock[0] + 37_800
    clock[0] = _utc_epoch(2026, 10, 3, 15, 30, 0)
    local = svc.now()
    assert type(local) is int
    assert local == clock[0] + 39_600


# ── spring-forward gap ──────────────────────────────────────────────

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


def test_now_applies_a_transition_from_the_previous_rule_year() -> None:
    clock = [_utc_epoch(2027, 1, 1, 1, 0, 0)]
    svc = TimeService(**_DECEMBER_END_KWARGS, get_time=lambda: clock[0])
    assert svc.now() == clock[0] - 14_400
    clock[0] = _utc_epoch(2027, 1, 1, 3, 0, 0)
    assert svc.now() == clock[0] - 18_000


# ── real_remaining_sec ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "utc_now, local_end, expected_sec",
    [
        # Sat 12:00 CEST to Mon 08:00 CET: 44 h on the wall clock across the fall-back.
        pytest.param((2026, 10, 24, 10, 0), (2026, 10, 26, 8, 0), 45 * 3600, id="fall-back ahead"),
        # Sat 12:00 CET to Mon 08:00 CEST: 44 h on the wall clock across the spring-forward.
        pytest.param((2026, 3, 28, 11, 0), (2026, 3, 30, 8, 0), 43 * 3600, id="spring-forward ahead"),
        # 02:30 CET, the repeated hour's second pass, to 08:00 CET.
        pytest.param((2026, 10, 25, 1, 30), (2026, 10, 25, 8, 0), 5 * 3600 + 1800, id="repeated hour"),
        # 12:00 CEST, an hour after 11:00 CEST.
        pytest.param((2026, 10, 24, 10, 0), (2026, 10, 24, 11, 0), -3600, id="passed"),
    ],
)
def test_real_remaining_sec_counts_real_seconds_from_now(
    utc_now: tuple[int, int, int, int, int], local_end: tuple[int, int, int, int, int], expected_sec: int
) -> None:
    utc = _utc_epoch(*utc_now, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    assert svc.real_remaining_sec(_local_epoch(*local_end)) == expected_sec


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


def test_sync_initial_without_on_progress():
    ntp = _FakeNtp(_WINTER_UTC)
    _cet_service(ntp).sync_initial()
    assert ntp.calls == [5]


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


def test_sync_that_steps_the_clock_back_restores_the_offset_and_transitions():
    # A bad NTP reply put the RTC in summer 2036; the next sync steps it back to winter 2026.
    ntp = _FakeNtp(_SUMMER_2036_UTC, synced_utc=_WINTER_UTC)
    svc = _cet_service(ntp)
    assert svc.now() == ntp.clock[0] + 7200
    svc.sync()
    assert svc.now() == ntp.clock[0] + 3600
    ntp.clock[0] = _utc_epoch(2026, 3, 29, 1, 0, 0)  # the 2026 spring-forward
    assert svc.now() == ntp.clock[0] + 7200


def test_failed_sync_that_moved_the_clock_still_leaves_the_right_offset():
    ntp = _FakeNtp(_SUMMER_2036_UTC, synced_utc=_WINTER_UTC, ok=False)
    svc = _cet_service(ntp)
    svc.now()
    svc.sync()
    assert svc.now() == ntp.clock[0] + 3600


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
