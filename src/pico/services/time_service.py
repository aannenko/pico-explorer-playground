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

    ``offset_sec`` is the UTC offset the rule's hour is expressed in.  Near the
    new year the result can fall in the UTC year before or after ``year``.
    """
    month, week, weekday, hour = rule
    mday = _mday_of_nth_weekday(year, month, week, weekday)
    return time.mktime((year, month, mday, hour, 0, 0, 0, 0)) - offset_sec


def _is_dst(
    utc_epoch: int,
    tz_offset_sec: int,
    dst_offset_sec: int,
    dst_start_rule: tuple,
    dst_end_rule: tuple,
) -> bool:
    year = time.gmtime(utc_epoch)[0]
    latest_utc = -1
    is_dst = False
    for y in range(year - 1, year + 2):
        start = _transition_utc(y, dst_start_rule, tz_offset_sec)
        if latest_utc < start <= utc_epoch:
            latest_utc = start
            is_dst = True
        end = _transition_utc(y, dst_end_rule, tz_offset_sec + dst_offset_sec)
        if latest_utc < end <= utc_epoch:
            latest_utc = end
            is_dst = False
    return is_dst


def _next_transition_utc(
    utc_epoch: int,
    tz_offset_sec: int,
    dst_offset_sec: int,
    dst_start_rule: tuple,
    dst_end_rule: tuple,
) -> int:
    """Returns 0 if no future transition is found (should not happen
    for valid rules within a reasonable year range).
    """
    year = time.gmtime(utc_epoch)[0]
    result = 0
    for y in range(year - 1, year + 2):
        s = _transition_utc(y, dst_start_rule, tz_offset_sec)
        e = _transition_utc(y, dst_end_rule, tz_offset_sec + dst_offset_sec)
        if s > utc_epoch and (result == 0 or s < result):
            result = s
        if e > utc_epoch and (result == 0 or e < result):
            result = e
    return result


class TimeService:
    """Central time authority.  Computes local time from UTC + TZ/DST.

    The RTC stays UTC (set by NTP).  Its 1970-epoch times exceed the small-int
    range, so every read allocates: gate per-tick reads with ``time.ticks_ms()``.

    ``dst_start_rule`` and ``dst_end_rule`` are ``(month, week, weekday, hour)``:
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
        dst_start_rule: tuple[int, int, int, int] | None,
        dst_end_rule: tuple[int, int, int, int] | None,
        dst_offset_hours: float = 0.0,
        get_time=time.time,  # () -> int
        tick_scheduler=None,
    ) -> None:
        # Whole seconds, converted once: a float offset would make every epoch it
        # touches a float, which rp2's single-precision floats round to 128 s.
        self._tz_offset_sec = round(tz_offset_hours * _SEC_PER_HOUR)
        self._dst_offset_sec = round(dst_offset_hours * _SEC_PER_HOUR)
        self._dst_start_rule = dst_start_rule
        self._dst_end_rule = dst_end_rule
        self._get_time = get_time

        self._offset_sec = self._tz_offset_sec
        self._dst_active = False
        self._next_transition_utc = 0
        self._next_dst_check_ms = time.ticks_ms()

        self._update_dst()

        if tick_scheduler is not None:
            tick_scheduler.register(self._tick)

    def now(self) -> int:
        """Return the current local-epoch time in seconds."""
        return self._get_time() + self._offset_sec

    def utc_offset_sec(self, utc_epoch: int) -> int:
        """Time-zone offset, plus the DST offset when DST is active at ``utc_epoch``."""
        if self._dst_start_rule is None or self._dst_end_rule is None:
            return self._tz_offset_sec
        if _is_dst(
            utc_epoch,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start_rule,
            self._dst_end_rule,
        ):
            return self._tz_offset_sec + self._dst_offset_sec
        return self._tz_offset_sec

    def to_utc(self, local_epoch: int) -> int:
        """Convert a local-epoch time to UTC epoch.

        Near a DST change a local time can occur twice or not at all.  Either way
        this returns the moment the clock first reaches it, which is when an event
        starting or ending at that time happens:
        - twice, when clocks fall back (e.g. 03:00 CEST to 02:00 CET repeats
          02:00-02:59): the earlier occurrence;
        - never, when clocks spring forward (e.g. 02:00 CET to 03:00 CEST skips
          02:00-02:59): the instant of the jump.
        So a later local time never maps to an earlier UTC instant.
        """
        # Estimating with the max offset never overshoots a fall-back boundary.
        max_offset_sec = self._tz_offset_sec + self._dst_offset_sec
        utc_estimate = local_epoch - max_offset_sec
        offset_sec = self.utc_offset_sec(utc_estimate)
        utc = local_epoch - offset_sec
        if self.utc_offset_sec(utc) == offset_sec:
            return utc
        # The clock never shows local_epoch, so a spring-forward jump skips it, and
        # that jump is the first transition after the estimate.
        return _next_transition_utc(
            utc_estimate,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start_rule,
            self._dst_end_rule,
        )

    def real_remaining_sec(self, local_epoch: int) -> int:
        """Return the real seconds from now until the clock first reaches local time ``local_epoch``.

        A DST change in between counts, as on a stopwatch; negative once that
        moment has passed.
        """
        # Measured from the true current instant: in a repeated hour now() doesn't
        # say which pass it is, so to_utc(now()) would be off by the DST offset.
        return self.to_utc(local_epoch) - self._get_time()

    def _tick(self) -> None:
        now_ms = time.ticks_ms()
        if time.ticks_diff(now_ms, self._next_dst_check_ms) < 0:
            return
        self._next_dst_check_ms = time.ticks_add(now_ms, _DST_CHECK_INTERVAL_MS)
        if self._next_transition_utc > 0 and self._get_time() >= self._next_transition_utc:
            self._update_dst()

    def _update_dst(self) -> None:
        if self._dst_start_rule is None or self._dst_end_rule is None:
            return

        utc_epoch = self._get_time()
        self._dst_active = _is_dst(
            utc_epoch,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start_rule,
            self._dst_end_rule,
        )

        if self._dst_active:
            self._offset_sec = self._tz_offset_sec + self._dst_offset_sec
        else:
            self._offset_sec = self._tz_offset_sec

        self._next_transition_utc = _next_transition_utc(
            utc_epoch,
            self._tz_offset_sec,
            self._dst_offset_sec,
            self._dst_start_rule,
            self._dst_end_rule,
        )
