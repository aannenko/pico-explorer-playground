import time

from scheduling.event import Event
from services.time_service import TimeService

_SEC_PER_WEEK = 7 * 24 * 60 * 60


def build_stream(
    time_service: TimeService,
    pickups: list[tuple[str, int, tuple[int, int, int], int, int, int, int]],
    horizon_sec: int,
    slot_count: int,
):  # -> (int) -> list[Event]
    """Return the waste-collection stream of ``pickups``: a getter that takes the UTC time and returns, in start order,
    at most ``slot_count`` occurrences not over by then that start within ``horizon_sec`` of it.

    A pickup recurs at its local wall-clock time, or occurs once for a non-positive ``period_weeks``.  An occurrence
    starts when ``TimeService.to_utc`` says the clock first shows that time, so one in a skipped hour starts at the
    jump, and lasts its minutes in real time.  Pickups starting together keep their order; labels are upper-cased.
    Each call computes a new list.
    """
    # (anchor_local, label, color_index, duration_sec, period_sec) per pickup; a period of 0 occurs once.
    compiled: list[tuple[int, str, int, int, int]] = []
    for label, color_index, anchor, hh, mm, duration_min, period_weeks in pickups:
        year, month, day = anchor
        compiled.append((
            time.mktime((year, month, day, hh, mm, 0, 0, 0)),
            label.upper(),
            color_index,
            duration_min * 60,
            period_weeks * _SEC_PER_WEEK if period_weeks > 0 else 0,
        ))
    return lambda now_utc: _events(time_service, compiled, horizon_sec, slot_count, now_utc)


def _events(
    time_service: TimeService,
    pickups: list[tuple[int, str, int, int, int]],
    horizon_sec: int,
    slot_count: int,
    now_utc: int,
) -> list[Event]:
    count = len(pickups)
    # Each pickup's next occurrence not over at now_utc: its local start, and its UTC start or -1 once none is left.
    starts_local = [0] * count
    starts_utc = [0] * count
    for pickup_index in range(count):
        _seek(time_service, pickups, pickup_index, now_utc, starts_local, starts_utc)
    events: list[Event] = []
    window_end = now_utc + horizon_sec
    while len(events) < slot_count:
        pickup_index = _earliest_index(starts_utc, window_end)
        if pickup_index < 0:
            break
        _, label, color_index, duration_sec, period_sec = pickups[pickup_index]
        events.append(Event(label, starts_utc[pickup_index], duration_sec, color_index))
        if period_sec:
            starts_local[pickup_index] += period_sec
            starts_utc[pickup_index] = time_service.to_utc(starts_local[pickup_index])
        else:
            starts_utc[pickup_index] = -1
    return events


def _seek(
    time_service: TimeService,
    pickups: list[tuple[int, str, int, int, int]],
    pickup_index: int,
    now_utc: int,
    starts_local: list[int],
    starts_utc: list[int],
) -> None:
    """Set pickup ``pickup_index``'s entries to its first occurrence not over at ``now_utc``."""
    anchor_local, _, _, duration_sec, period_sec = pickups[pickup_index]
    # Over by now_utc exactly when it starts by the cutoff: a zero duration lasts its one instant.
    cutoff_utc = now_utc - (duration_sec if duration_sec else 1)
    # The occurrences at or before the wall time the clock shows at the cutoff are over: the clock first shows each
    # of those times no later than the cutoff.  Skipping them unconverted also spares a past one-off a DST lookup
    # far from now's.
    cutoff_local = cutoff_utc + time_service.utc_offset_sec(cutoff_utc)
    start_local = anchor_local
    if cutoff_local >= anchor_local:
        if not period_sec:
            starts_utc[pickup_index] = -1
            return
        start_local += ((cutoff_local - anchor_local) // period_sec + 1) * period_sec
    start_utc = time_service.to_utc(start_local)
    while start_utc <= cutoff_utc:
        if not period_sec:
            start_utc = -1
            break
        start_local += period_sec
        start_utc = time_service.to_utc(start_local)
    starts_local[pickup_index] = start_local
    starts_utc[pickup_index] = start_utc

def _earliest_index(starts_utc: list[int], window_end: int) -> int:
    """Return the index of the earliest start before ``window_end``, the first of any tied, or -1 if none is; a
    negative start is none."""
    best_index = -1
    best_start = window_end
    for i in range(len(starts_utc)):
        start = starts_utc[i]
        if 0 <= start < best_start:
            best_index = i
            best_start = start
    return best_index