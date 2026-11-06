import time

from micropython import const

_SAKAMOTO_T = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
_DAYS_IN_MONTH = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_SEC_PER_HOUR = const(3600)

# _tick reads the wall clock only this often; a minute of slack on the
# transition instant is imperceptible.
_DST_CHECK_INTERVAL_MS = const(60_000)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and _is_leap(year):
        return 29
    return _DAYS_IN_MONTH[month]


def _weekday(year: int, month: int, day: int) -> int:
    """0=Mon .. 6=Sun (MicroPython convention)."""
    y = year
    if month < 3:
        y -= 1
    # Sakamoto returns 0=Sun .. 6=Sat
    dow = (y + y // 4 - y // 100 + y // 400 + _SAKAMOTO_T[month - 1] + day) % 7
    return (dow - 1) % 7


def _mday_of_nth_weekday(year: int, month: int, week: int, weekday: int) -> int:
    if week == -1:
        last_day = _days_in_month(year, month)
        last_wd = _weekday(year, month, last_day)
        return last_day - (last_wd - weekday) % 7
    first_wd = _weekday(year, month, 1)
    return 1 + (weekday - first_wd) % 7 + (week - 1) * 7


def _transition_utc(year: int, rule: tuple, offset_sec: int) -> int:
    """Return the UTC epoch of ``rule``'s transition in ``year``.

    ``offset_sec`` is the UTC offset the rule's hour is expressed in.
    """
    month, week, weekday, hour = rule
    mday = _mday_of_nth_weekday(year, month, week, weekday)
    return time.mktime((year, month, mday, hour, 0, 0, 0, 0)) - offset_sec


def _is_dst(
    utc_epoch: int,
    tz_offset_sec: int,
    dst_offset_sec: int,
    dst_start: tuple,
    dst_end: tuple,
) -> bool:
    year = time.gmtime(utc_epoch)[0]
    start = _transition_utc(year, dst_start, tz_offset_sec)
    end = _transition_utc(year, dst_end, tz_offset_sec + dst_offset_sec)
    if start < end:
        return start <= utc_epoch < end
    # Southern hemisphere: DST wraps around the new year
    return utc_epoch >= start or utc_epoch < end


def _next_transition_utc(
    utc_epoch: int,
    tz_offset_sec: int,
    dst_offset_sec: int,
    dst_start: tuple,
    dst_end: tuple,
) -> int:
    """Returns 0 if no future transition is found (should not happen
    for valid rules within a reasonable year range).
    """
    year = time.gmtime(utc_epoch)[0]
    result = 0
    for y in (year, year + 1):
        s = _transition_utc(y, dst_start, tz_offset_sec)
        e = _transition_utc(y, dst_end, tz_offset_sec + dst_offset_sec)
        if s > utc_epoch and (result == 0 or s < result):
            result = s
        if e > utc_epoch and (result == 0 or e < result):
            result = e
    return result


class TimeService:
    """Central time authority.  Computes local time from UTC + TZ/DST.

    The RTC stays UTC (set by NTP).  Its 1970-epoch times exceed the small-int
    range, so every read allocates: gate per-tick reads with ``time.ticks_ms()``.

    ``dst_start`` and ``dst_end`` are ``(month, week, weekday, hour)`` rules:
    ``week`` 1-5, or -1 for the last; ``weekday`` 0=Mon .. 6=Sun; ``hour`` in
    local standard time for the start and in local DST time for the end.
    ``None`` for either rule disables DST.

    Offsets are hours and may be fractional (e.g. 5.75); they are rounded to
    whole seconds.  ``dst_offset_hours`` must not be negative.

    Must be instantiated after NTP sync so ``time.time()`` is accurate.
    """

    def __init__(
        self,
        tz_offset_hours: float,
        dst_start: tuple[int, int, int, int] | None,
        dst_end: tuple[int, int, int, int] | None,
        dst_offset_hours: float = 0.0,
        get_time=time.time,  # () -> int
        tick_scheduler=None,
    ) -> None:
        # Whole seconds, converted once: a float offset would make every epoch it
        # touches a float, which rp2's single-precision floats round to 128 s.
        self._tz_offset_sec = round(tz_offset_hours * _SEC_PER_HOUR)
        self._dst_offset_sec = round(dst_offset_hours * _SEC_PER_HOUR)
        self._dst_start = dst_start
        self._dst_end = dst_end
        self._get_time = get_time

        self._offset_sec = self._tz_offset_sec
        self._dst_active = False
        self._next_transition = 0
        self._next_dst_check_ms = time.ticks_ms()

        self._update_dst()

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def now(self) -> int:
        """Return the current local-epoch time in seconds."""
        return self._get_time() + self._offset_sec

    def utc_now(self) -> int:
        return self._get_time()

    def total_offset(self, utc_timestamp: int) -> int:
        """Total UTC offset in seconds at a given UTC timestamp (tz + DST if active)."""
        if self._dst_start is None or self._dst_end is None:
            return self._tz_offset_sec
        if _is_dst(
            utc_timestamp,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start,
            self._dst_end,
        ):
            return self._tz_offset_sec + self._dst_offset_sec
        return self._tz_offset_sec

    def to_utc(self, local_epoch: int) -> int:
        """Convert local-epoch to UTC epoch.

        During fall-back overlap (an ambiguous local time), prefers the DST
        (earlier UTC) interpretation — correct for forward-progressing events.
        """
        # Estimating with the max offset never overshoots a fall-back boundary.
        max_offset = self._tz_offset_sec + self._dst_offset_sec
        utc_est = local_epoch - max_offset
        return local_epoch - self.total_offset(utc_est)

    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        """Convert wall-clock duration to real seconds, accounting for DST.

        Exact for any event length and any number of DST transitions, provided
        neither endpoint falls in a spring-forward gap (a nonexistent local time).
        """
        return self.to_utc(local_start + wall_clock_sec) - self.to_utc(local_start)

    def _tick(self) -> None:
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._next_dst_check_ms) < 0:
            return
        self._next_dst_check_ms = time.ticks_add(now_ms, _DST_CHECK_INTERVAL_MS)
        if self._next_transition > 0 and self._get_time() >= self._next_transition:
            self._update_dst()

    def _update_dst(self) -> None:
        if self._dst_start is None or self._dst_end is None:
            return

        utc = self._get_time()
        self._dst_active = _is_dst(
            utc,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start,
            self._dst_end,
        )

        if self._dst_active:
            self._offset_sec = self._tz_offset_sec + self._dst_offset_sec
        else:
            self._offset_sec = self._tz_offset_sec

        self._next_transition = _next_transition_utc(
            utc,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start,
            self._dst_end,
        )
