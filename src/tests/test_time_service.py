from __future__ import annotations

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


class FakeScheduler:
    def __init__(self):
        self.callbacks = []

    def register(self, cb):
        self.callbacks.append(cb)


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


def test_utc_now_returns_raw_time():
    utc = _utc_epoch(2026, 7, 15, 12, 0, 0)
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: utc,
    )
    assert svc.utc_now() == utc


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


def test_tick_triggers_dst_transition():
    """Simulate crossing from winter into summer via tick."""
    clock = [_utc_epoch(2026, 3, 29, 0, 30, 0)]  # 00:30 UTC, before spring forward

    sched = FakeScheduler()
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
        tick_scheduler=sched,
    )
    assert len(sched.callbacks) == 1
    assert svc._dst_active is False
    assert svc.now() == clock[0] + 1 * 3600  # CET

    # Advance clock past the spring-forward transition (01:00 UTC)
    clock[0] = _utc_epoch(2026, 3, 29, 1, 0, 0)
    svc._tick()

    assert svc._dst_active is True
    assert svc.now() == clock[0] + 2 * 3600  # CEST


def test_tick_no_transition_when_not_reached():
    clock = [_utc_epoch(2026, 1, 15, 12, 0, 0)]

    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
    )
    initial_offset = svc._offset_sec

    # Advance by 1 hour — still winter, no transition
    clock[0] += 3600
    svc._tick()

    assert svc._offset_sec == initial_offset


def test_tick_fall_back_transition():
    """Simulate crossing from summer into winter via tick."""
    clock = [_utc_epoch(2026, 10, 25, 0, 30, 0)]  # 02:30 CEST, before fall back

    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=lambda: clock[0],
    )
    assert svc._dst_active is True
    assert svc.now() == clock[0] + 2 * 3600  # CEST

    # Advance past fall-back (01:00 UTC)
    clock[0] = _utc_epoch(2026, 10, 25, 1, 0, 0)
    svc._tick()

    assert svc._dst_active is False
    assert svc.now() == clock[0] + 1 * 3600  # CET


def test_tick_throttles_wall_clock_reads(fake_ticks):
    """``_tick`` samples the (big-int-allocating) wall clock ~once a minute, not
    every tick — the DST boundary is far away, so per-tick reads are pure churn.
    """
    clock = [_utc_epoch(2026, 1, 15, 12, 0, 0)]  # winter, far from any transition
    reads = [0]

    def get_time():
        reads[0] += 1
        return clock[0]

    fake_ticks[0] = 0
    svc = TimeService(
        tz_offset_hours=1,
        dst_start_rule=_DST_START,
        dst_end_rule=_DST_END,
        dst_offset_hours=1,
        get_time=get_time,
    )
    reads_after_init = reads[0]

    # First tick (gate initialised to construction time) is due → one read.
    svc._tick()
    assert reads[0] == reads_after_init + 1

    # Ticks within the throttle window must not touch the wall clock.
    for t in (1, 250, 30_000, 59_999):
        fake_ticks[0] = t
        svc._tick()
    assert reads[0] == reads_after_init + 1

    # Once the window elapses, it samples again.
    fake_ticks[0] = 60_000
    svc._tick()
    assert reads[0] == reads_after_init + 2


def test_constructor_registers_tick():
    sched = FakeScheduler()
    TimeService(
        tz_offset_hours=0,
        dst_start_rule=None,
        dst_end_rule=None,
        get_time=lambda: 0,
        tick_scheduler=sched,
    )
    assert len(sched.callbacks) == 1


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


# ── real_duration_sec ───────────────────────────────────────────────


def test_real_duration_sec_no_crossing():
    utc = _utc_epoch(2026, 6, 15, 6, 0, 0)  # summer, Mon
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc,
    )
    local_start = svc.now()
    assert svc.real_duration_sec(local_start, 9 * 3600) == 9 * 3600


def test_real_duration_sec_spring_forward():
    """Rest event Sat 17:00 CET → Sun 08:00 CEST spans spring-forward: 14h real, 15h wall."""
    # Sat 2026-03-28 17:00 CET = 16:00 UTC. Transition: Sun 2026-03-29 01:00 UTC.
    utc_start = _utc_epoch(2026, 3, 28, 16, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc_start,
    )
    local_sat_1700 = utc_start + 1 * 3600  # 17:00 CET
    wall_clock = 15 * 3600  # 15h wall-clock rest
    real = svc.real_duration_sec(local_sat_1700, wall_clock)
    assert real == 14 * 3600  # 1h shorter due to spring forward


def test_real_duration_sec_fall_back():
    """Rest event Sat 17:00 CEST → Sun 08:00 CET spans fall-back: 16h real, 15h wall."""
    # Sat 2026-10-24 17:00 CEST = 15:00 UTC. Transition: Sun 2026-10-25 01:00 UTC.
    utc_start = _utc_epoch(2026, 10, 24, 15, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc_start,
    )
    local_sat_1700 = utc_start + 2 * 3600  # 17:00 CEST
    wall_clock = 15 * 3600  # 15h wall-clock rest
    real = svc.real_duration_sec(local_sat_1700, wall_clock)
    assert real == 16 * 3600  # 1h longer due to fall back


def test_real_duration_sec_weekend_fall_back():
    """Weekend Fri 17:00 CEST → Mon 08:00 CET = 63h wall, 64h real."""
    utc_start = _utc_epoch(2026, 10, 23, 15, 0, 0)
    svc = TimeService(
        tz_offset_hours=1, dst_start_rule=_DST_START, dst_end_rule=_DST_END,
        dst_offset_hours=1, get_time=lambda: utc_start,
    )
    local_fri_1700 = utc_start + 2 * 3600
    wall_clock = 63 * 3600  # Fri 17:00 → Mon 08:00 = 63h wall
    real = svc.real_duration_sec(local_fri_1700, wall_clock)
    assert real == 64 * 3600


def test_real_duration_sec_no_dst_config():
    utc = _utc_epoch(2026, 7, 15, 6, 0, 0)
    svc = TimeService(
        tz_offset_hours=5, dst_start_rule=None, dst_end_rule=None,
        dst_offset_hours=0, get_time=lambda: utc,
    )
    local = svc.now()
    assert svc.real_duration_sec(local, 9 * 3600) == 9 * 3600


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
    real = svc.real_duration_sec(local_start, 4 * 3600)
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
    assert svc.real_duration_sec(svc.now(), 3 * 3600) == 3 * 3600 - 1800


def test_tick_applies_fractional_dst_offset():
    clock = [_utc_epoch(2026, 10, 3, 15, 0, 0)]  # 30 min before Lord Howe's spring-forward
    sched = FakeScheduler()
    svc = TimeService(
        tz_offset_hours=10.5, dst_start_rule=_LORD_HOWE_DST_START,
        dst_end_rule=_LORD_HOWE_DST_END, dst_offset_hours=0.5,
        get_time=lambda: clock[0], tick_scheduler=sched,
    )
    assert svc.now() == clock[0] + 37_800
    clock[0] = _utc_epoch(2026, 10, 3, 15, 30, 0)
    svc._next_dst_check_ms = 0
    sched.callbacks[0]()
    local = svc.now()
    assert type(local) is int
    assert local == clock[0] + 39_600
