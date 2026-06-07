"""Waste-collection calendar stream from a recurring schedule.

Pure on-device generator: no network, no service lifecycle.  Each schedule
entry recurs every ``period_weeks``; events are emitted in start-time order
across all entries.
"""

import time

from scheduling.event import Event
from scheduling.stream import Stream
from services.time_service import TimeService

_SEC_PER_WEEK = 7 * 24 * 60 * 60


def build_stream(time_service: TimeService, schedule: list) -> Stream:
    return Stream(events_iter=_waste_loop(time_service, schedule))


def _waste_loop(time_service: TimeService, schedule: list):  # Iterator[Event]
    # Entry: (label, color_index, (year, month, day), hour, minute, duration_min, period_weeks)
    now = time_service.now()
    cursors = []  # [next_start_local, label, color_index, dur_sec, period_sec]
    for label, color_index, anchor, hh, mm, dur_min, period_weeks in schedule:
        year, month, day = anchor
        start = time.mktime((year, month, day, hh, mm, 0, 0, 0))
        dur_sec = dur_min * 60
        period_sec = period_weeks * _SEC_PER_WEEK
        if period_sec > 0:
            # Skip occurrences already in the past so we begin near the window.
            while start + dur_sec <= now:
                start += period_sec
        cursors.append([start, label, color_index, dur_sec, period_sec])

    while cursors:
        earliest = 0
        for k in range(1, len(cursors)):
            if cursors[k][0] < cursors[earliest][0]:
                earliest = k

        start, label, color_index, dur_sec, period_sec = cursors[earliest]
        real_dur = time_service.real_duration(start, dur_sec)
        yield Event(label, start, dur_sec, real_dur, color_index=color_index)

        if period_sec > 0:
            cursors[earliest][0] = start + period_sec
        else:
            cursors.pop(earliest)  # non-recurring entry: emit once
