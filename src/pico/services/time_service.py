import time

from micropython import const

_SAKAMOTO_T = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
_DAYS_IN_MONTH = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_SEC_PER_HOUR = const(3600)

# How often ``_tick`` samples the wall clock to check for a DST transition.
# ``time.time()`` heap-allocates a big int on builds whose epoch puts the
# current year past the small-int range (e.g. the 1970-epoch rp2 build, where
# 2026 ≈ 1.78e9 > 2**30), so reading it every 500 ms tick to compare against a
# boundary that is *months* away is pure allocation churn.  A minute of slack on
# the transition instant is imperceptible.
_DST_CHECK_INTERVAL_MS = const(60_000)


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def _days_in_month(year: int, month: int) -> int:
    if month == 2 and _is_leap(year):
        return 29
    return _DAYS_IN_MONTH[month]


def _weekday(year: int, month: int, day: int) -> int:
    """Day of week: 0=Mon .. 6=Sun (MicroPython convention).

    Uses Sakamoto's algorithm (pure integer math, no mktime/gmtime).
    """
    y = year
    if month < 3:
        y -= 1
    # Sakamoto returns 0=Sun .. 6=Sat
    dow = (y + y // 4 - y // 100 + y // 400 + _SAKAMOTO_T[month - 1] + day) % 7
    return (dow - 1) % 7


def _nth_weekday_mday(year: int, month: int, week: int, weekday: int) -> int:
    """Day-of-month for the Nth weekday occurrence.

    week: 1-5 for first-fifth, -1 for last.
    weekday: 0=Mon .. 6=Sun.
    """
    if week == -1:
        last_day = _days_in_month(year, month)
        last_wd = _weekday(year, month, last_day)
        return last_day - (last_wd - weekday) % 7
    first_wd = _weekday(year, month, 1)
    return 1 + (weekday - first_wd) % 7 + (week - 1) * 7


def _transition_utc(year: int, rule: tuple, offset_hours: int) -> int:
    """UTC epoch of a DST transition.

    rule: (month, week, weekday, hour).
    offset_hours: UTC offset the transition hour is expressed in
                  (standard offset for DST start, DST offset for DST end).
    """
    month, week, weekday, hour = rule
    mday = _nth_weekday_mday(year, month, week, weekday)
    return time.mktime((year, month, mday, hour, 0, 0, 0, 0)) - offset_hours * _SEC_PER_HOUR


def _is_dst(utc_epoch: int, tz_offset: int, dst_offset: int, dst_start: tuple, dst_end: tuple) -> bool:
    """True if DST is active at the given UTC epoch."""
    year = time.gmtime(utc_epoch)[0]
    start = _transition_utc(year, dst_start, tz_offset)
    end = _transition_utc(year, dst_end, tz_offset + dst_offset)
    if start < end:
        return start <= utc_epoch < end
    # Southern hemisphere: DST wraps around the new year
    return utc_epoch >= start or utc_epoch < end


def _next_transition_utc(utc_epoch: int, tz_offset: int, dst_offset: int, dst_start: tuple, dst_end: tuple) -> int:
    """UTC epoch of the next DST transition after utc_epoch.

    Returns 0 if no future transition is found (should not happen
    for valid rules within a reasonable year range).
    """
    year = time.gmtime(utc_epoch)[0]
    result = 0
    for y in (year, year + 1):
        s = _transition_utc(y, dst_start, tz_offset)
        e = _transition_utc(y, dst_end, tz_offset + dst_offset)
        if s > utc_epoch and (result == 0 or s < result):
            result = s
        if e > utc_epoch and (result == 0 or e < result):
            result = e
    return result


class TimeService:
    """Central time authority.  Computes local time from UTC + TZ/DST.

    The RTC stays UTC (set by NTP).  This service adds the correct
    offset (timezone + optional DST) so all consumers get local time
    via ``now()``.  DST transitions are detected automatically on each
    ``_tick()`` call — no coupling to NTP sync.

    Must be instantiated after NTP sync so ``time.time()`` is accurate.
    """

    def __init__(
        self,
        tz_offset: int,
        dst_start: tuple[int, int, int, int] | None,  # (month, week, weekday, hour)
        dst_end: tuple[int, int, int, int] | None,  # (month, week, weekday, hour)
        dst_offset: int = 0,
        get_time=time.time,
        tick_scheduler=None,
    ) -> None:
        self._tz_offset = tz_offset
        self._dst_start = dst_start
        self._dst_end = dst_end
        self._dst_offset = dst_offset
        self._get_time = get_time

        self._offset_sec: int = tz_offset * _SEC_PER_HOUR
        self._dst_active: bool = False
        self._next_transition: int = 0
        # Monotonic-clock gate for the wall-clock DST check (see _tick).
        self._next_dst_check_ms: int = time.ticks_ms()

        self._update_dst()

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def now(self) -> int:
        return self._get_time() + self._offset_sec

    def utc_now(self) -> int:
        return self._get_time()

    def total_offset(self, utc_timestamp: int) -> int:
        """Total UTC offset in seconds at a given UTC timestamp (tz + DST if active)."""
        if self._dst_start is None or self._dst_end is None:
            return self._tz_offset * _SEC_PER_HOUR
        if _is_dst(utc_timestamp, self._tz_offset, self._dst_offset, self._dst_start, self._dst_end):
            return (self._tz_offset + self._dst_offset) * _SEC_PER_HOUR
        return self._tz_offset * _SEC_PER_HOUR

    def to_utc(self, local_epoch: int) -> int:
        """Convert local-epoch to UTC epoch.

        Two-step: initial estimate using max offset (tz + dst), then
        refine with actual total_offset at the estimate.  Using max
        offset ensures the estimate never overshoots a fall-back boundary.

        During fall-back overlap (ambiguous local hour), prefers the DST
        (earlier UTC) interpretation — correct for forward-progressing events.
        """
        max_offset = (self._tz_offset + self._dst_offset) * _SEC_PER_HOUR
        utc_est = local_epoch - max_offset
        return local_epoch - self.total_offset(utc_est)

    def real_duration(self, local_start: int, wall_clock_sec: int) -> int:
        """Convert wall-clock duration to real seconds, accounting for DST.

        Uses endpoint conversion: to_utc(local_end) - to_utc(local_start).
        Exact for any event length and any number of DST transitions.
        """
        return self.to_utc(local_start + wall_clock_sec) - self.to_utc(local_start)

    def _tick(self) -> None:
        # Throttle the (big-int-allocating) wall-clock read to ~once a minute
        # via the allocation-free ms clock; the DST boundary is far away.
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
            self._tz_offset,
            self._dst_offset,
            self._dst_start,
            self._dst_end,
        )

        if self._dst_active:
            self._offset_sec = (self._tz_offset + self._dst_offset) * _SEC_PER_HOUR
        else:
            self._offset_sec = self._tz_offset * _SEC_PER_HOUR

        self._next_transition = _next_transition_utc(
            utc,
            self._tz_offset,
            self._dst_offset,
            self._dst_start,
            self._dst_end,
        )
