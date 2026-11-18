import time

from micropython import const
from utilities import ntp
from utilities.log import log_exception

_SAKAMOTO_T = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
_DAYS_IN_MONTH = (0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_SEC_PER_HOUR = const(3600)

_INITIAL_SYNC_ATTEMPTS = const(5)


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


def _transition_utc(year: int, rule: tuple[int, int, int, int], offset_sec: int) -> int:
    """Return the UTC epoch of ``rule``'s transition in ``year``.

    ``offset_sec`` is the UTC offset the rule's hour is expressed in.  Near the
    new year the result can fall in the UTC year before or after ``year``.
    """
    month, week, weekday, hour = rule
    mday = _mday_of_nth_weekday(year, month, week, weekday)
    return time.mktime((year, month, mday, hour, 0, 0, 0, 0)) - offset_sec


def _offset_span(
    utc_epoch: int,
    tz_offset_sec: int,
    dst_offset_sec: int,
    dst_start_rule: tuple[int, int, int, int],
    dst_end_rule: tuple[int, int, int, int],
) -> tuple[int, int, int]:
    """Return ``(start_utc, end_utc, offset_sec)``: the DST changes around ``utc_epoch``, the last at or before it and
    the first after it, and the UTC offset in force from one to the other."""
    year = time.gmtime(utc_epoch)[0]
    start_utc = -1
    end_utc = 0
    is_dst = False
    for y in range(year - 1, year + 2):
        dst_start_utc = _transition_utc(y, dst_start_rule, tz_offset_sec)
        dst_end_utc = _transition_utc(y, dst_end_rule, tz_offset_sec + dst_offset_sec)
        if start_utc < dst_start_utc <= utc_epoch:
            start_utc = dst_start_utc
            is_dst = True
        if start_utc < dst_end_utc <= utc_epoch:
            start_utc = dst_end_utc
            is_dst = False
        if dst_start_utc > utc_epoch and (end_utc == 0 or dst_start_utc < end_utc):
            end_utc = dst_start_utc
        if dst_end_utc > utc_epoch and (end_utc == 0 or dst_end_utc < end_utc):
            end_utc = dst_end_utc
    return start_utc, end_utc, tz_offset_sec + dst_offset_sec if is_dst else tz_offset_sec


def _validate_dst_rule(rule: tuple[int, int, int, int]) -> None:
    month, week, weekday, _ = rule
    if not (1 <= month <= 12 and (week == -1 or 1 <= week <= 5) and 0 <= weekday <= 6):
        raise ValueError("DST rule out of range: %r" % (rule,))


class TimeService:
    """Central time authority.  Computes local time from UTC + TZ/DST.

    The RTC stays UTC (set by NTP).  Its 1970-epoch times exceed the small-int
    range, so every read allocates: gate per-tick reads with ``time.ticks_ms()``.

    ``dst_start_rule`` and ``dst_end_rule`` are ``(month, week, weekday, hour)``:
    ``month`` 1-12; ``week`` 1-5, or -1 for the last; ``weekday`` 0=Mon .. 6=Sun;
    ``hour`` in local standard time for the start and in local DST time for the
    end.  A month, week or weekday out of range raises ``ValueError``.  ``None``
    for either rule disables DST.

    Offsets are hours and may be fractional (e.g. 5.75); they are rounded to
    whole seconds.  ``dst_offset_hours`` must not be negative.

    ``sync_initial`` and ``sync`` set the RTC over NTP; until the first, times
    follow whatever it holds.  Times follow each sync at once.

    Owns no timer: it keeps the two spans between DST changes it looked up last,
    so a lookup inside either does no DST math, wherever the clock moved.
    """

    def __init__(
        self,
        tz_offset_hours: float,
        dst_start_rule: tuple[int, int, int, int] | None,
        dst_end_rule: tuple[int, int, int, int] | None,
        dst_offset_hours: float = 0.0,
        get_time=time.time,  # () -> int
        sync_time=ntp.sync_time,  # (int) -> bool
    ) -> None:
        for rule in (dst_start_rule, dst_end_rule):
            if rule is not None:
                _validate_dst_rule(rule)

        # Whole seconds, converted once: a float offset would make every epoch it
        # touches a float, which rp2's single-precision floats round to 128 s.
        self._tz_offset_sec = round(tz_offset_hours * _SEC_PER_HOUR)
        self._dst_offset_sec = round(dst_offset_hours * _SEC_PER_HOUR)
        self._dst_start_rule = dst_start_rule
        self._dst_end_rule = dst_end_rule
        self._get_time = get_time
        self._sync_time = sync_time

        # (start_utc, end_utc, offset_sec), the span looked up last first: lookups mostly fall near now, or across the
        # next or the last DST change.  An empty span until the first lookup; without DST, the zone's one offset.
        self._span = (0, 0, self._tz_offset_sec)
        self._other_span = self._span

    def sync_initial(self, on_progress=None) -> None:  # on_progress: (str) -> None
        """Block until NTP sets the RTC, else raise ``RuntimeError``.

        ``on_progress`` receives progress messages during this call only; it isn't
        retained, so resyncs never draw over the active view.
        """
        def _notify(msg: str) -> None:
            if on_progress is not None:
                on_progress(msg)

        _notify("sync time")
        if not self.sync(_INITIAL_SYNC_ATTEMPTS):
            _notify("ntp fail")
            raise RuntimeError("Could not sync time")

    def sync(self, attempts: int = 1) -> bool:
        """Blocking NTP sync of the RTC; return whether one of ``attempts`` succeeded."""
        return self._sync_time(attempts)

    def now(self) -> int:
        """Return the current local-epoch time in seconds, as ``to_local`` converts it."""
        return self.to_local(self._get_time())

    def utc_now(self) -> int:
        """Return the current UTC-epoch time in seconds."""
        return self._get_time()

    def to_local(self, utc_epoch: int) -> int:
        """Convert a UTC-epoch time to local epoch.

        Short of heap to look up its offset, it uses the offset of the last time
        looked up, off by at most the DST offset, and the next call retries.
        """
        try:
            return utc_epoch + self._span_at(utc_epoch)[2]
        except MemoryError as e:
            # Rather than raise, so a view drawing the time still draws it, nearly right.
            log_exception("[time] dst err:", e)
            return utc_epoch + self._span[2]

    def utc_offset_sec(self, utc_epoch: int) -> int:
        """Time-zone offset, plus the DST offset when DST is active at ``utc_epoch``."""
        return self._span_at(utc_epoch)[2]

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
        span = self._span_at(local_epoch - max_offset_sec)
        offset_sec = span[2]
        utc = local_epoch - offset_sec
        if utc < span[1] or self.utc_offset_sec(utc) == offset_sec:
            return utc
        # The clock never shows local_epoch, so a spring-forward jump skips it, and
        # that jump ends the estimate's span.
        return span[1]

    def _span_at(self, utc_epoch: int) -> tuple[int, int, int]:
        """Return ``(start_utc, end_utc, offset_sec)`` for the span between DST changes holding ``utc_epoch``; without
        DST, the zone's offset with an empty span."""
        span = self._span
        if span[0] <= utc_epoch < span[1]:
            return span
        other = self._other_span
        if other[0] <= utc_epoch < other[1]:
            self._other_span = span
            self._span = other
            return other
        if self._dst_start_rule is None or self._dst_end_rule is None:
            return span
        found = _offset_span(
            utc_epoch, self._tz_offset_sec, self._dst_offset_sec, self._dst_start_rule, self._dst_end_rule
        )
        self._other_span = span
        self._span = found
        return found
