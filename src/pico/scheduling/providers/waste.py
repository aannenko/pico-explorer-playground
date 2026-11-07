import time

from scheduling.event import Event
from scheduling.stream import Stream
from services.time_service import TimeService

_SEC_PER_WEEK = 7 * 24 * 60 * 60


def build_stream(time_service: TimeService, pickups: list) -> Stream:
    """Build the waste-collection stream from ``pickups``.

    Occurrences of all pickups are yielded in start-time order; a pickup with
    a non-positive ``period_weeks`` occurs once.
    """
    return Stream(events_iter=_waste_loop(time_service, pickups))


def _waste_loop(time_service: TimeService, pickups: list):  # Iterator[Event]
    now = time_service.now()
    cursors = []  # [next_start_local, label, color_index, dur_sec, period_sec]
    for label, color_index, anchor, hh, mm, dur_min, period_weeks in pickups:
        year, month, day = anchor
        start = time.mktime((year, month, day, hh, mm, 0, 0, 0))
        dur_sec = dur_min * 60
        period_sec = period_weeks * _SEC_PER_WEEK
        if period_sec > 0:
            while start + dur_sec <= now:
                start += period_sec
        cursors.append([start, label, color_index, dur_sec, period_sec])

    while cursors:
        earliest = 0
        for k in range(1, len(cursors)):
            if cursors[k][0] < cursors[earliest][0]:
                earliest = k

        start, label, color_index, dur_sec, period_sec = cursors[earliest]
        real_dur = time_service.real_duration_sec(start, dur_sec)
        yield Event(label, start, dur_sec, real_dur, color_index=color_index)

        if period_sec > 0:
            cursors[earliest][0] = start + period_sec
        else:
            cursors.pop(earliest)
