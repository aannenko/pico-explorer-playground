import struct
import time
import random

from micropython import const
from scheduling.event import Event
from services.time_service import TimeService

_WEEK_DAYS = {0, 1, 2, 3, 4, 5, 6}  # Monday=0 .. Sunday=6
_SEC_IN_DAY = const(24 * 60 * 60)
_SEC_IN_WEEK = const(_SEC_IN_DAY * 7)

_WORK = const(0)
_REST = const(1)
_WEEKEND = const(2)

_STRUCT_FORMAT = "IB"  # event_duration_sec, event_type
_STRUCT_SIZE = struct.calcsize(_STRUCT_FORMAT)


def work_week_loop(
    work_days: set[int],
    work_start: tuple[int, int],
    work_end: tuple[int, int],
    time_service: TimeService,
):
    """
    Yield work-rest-weekend events, starting from the currently running one.

    Operates in local-epoch throughout.  At yield time, each event gets
    a DST-corrected ``real_duration_sec`` via the time service.

    Args:
        work_days (set[int]): Set of work days (0=Monday .. 6=Sunday)
        work_start (tuple[int, int]): Work start time in local time (hour, minute)
        work_end (tuple[int, int]): Work end time in local time (hour, minute)
        time_service: TimeService instance for local time + DST correction

    Returns:
        Iterator[Event]: A sequence of work, rest, and weekend events,
        starting from the currently running one.
    """

    # CONDITIONS:
    # 1. One work shift per work day.
    # 2. Work shifts cannot last 24 hours or more, hence - cannot overlap.
    # 3. All work shifts have the same start time, end time, and duration.
    # 4. Work shifts can cross midnight.
    # 5. Overnight work shift may end on a weekend day.
    # 6. The time between work shifts is rest time, if it's between work shifts on consecutive work days.
    # 7. Rest time spanning over non-work days is weekend time.
    # 8. Each weekend event starts right after a work shift, spans > 24 hours, and finishes at the start of the next shift.
    # 9. There can be zero or more weekend days.

    work_start_hour, work_start_minute = work_start
    if work_start_hour < 0 or work_start_hour > 23 or work_start_minute < 0 or work_start_minute > 59:
        raise ValueError("Work start time is invalid")

    work_end_hour, work_end_minute = work_end
    if work_end_hour < 0 or work_end_hour > 23 or work_end_minute < 0 or work_end_minute > 59:
        raise ValueError("Work end time is invalid")

    if work_start == work_end:
        raise ValueError("Work start and end times cannot be the same")

    if not work_days or not work_days.issubset(_WEEK_DAYS):
        raise ValueError("Work days must be one or more days from {0, 1, 2, 3, 4, 5, 6}")

    is_work_midnight = work_start > work_end

    # Calculate the number of events
    num_events = len(work_days) * 2  # work + rest/weekend per work day

    # Pre-calculate event durations (wall-clock — constant regardless of DST)
    work_start_second_of_day = work_start_hour * 3600 + work_start_minute * 60
    work_end_second_of_day = work_end_hour * 3600 + work_end_minute * 60
    work_duration_sec = (
        work_end_second_of_day - work_start_second_of_day
        if not is_work_midnight
        else _SEC_IN_DAY - work_start_second_of_day + work_end_second_of_day
    )

    rest_duration_sec = _SEC_IN_DAY - work_duration_sec

    # Prepare the binary buffer with all events
    buffer = bytearray(num_events * _STRUCT_SIZE)
    offset = 0
    current_event_index = 0

    # Use local-epoch for positioning: gmtime(local) gives local components
    now_local = time_service.now()
    _, _, _, now_hour, now_minute, now_second, now_weekday, _ = time.gmtime(now_local)
    elapsed_week_sec = now_weekday * _SEC_IN_DAY + now_hour * 3600 + now_minute * 60 + now_second
    week_start_timestamp = now_local - elapsed_week_sec
    current_event_start_timestamp: int

    def _set_if_current(event_start_week_sec: int, event_duration_sec: int) -> None:
        nonlocal elapsed_week_sec, current_event_index, current_event_start_timestamp
        event_end_week_sec = event_start_week_sec + event_duration_sec
        is_current = (
            event_start_week_sec <= elapsed_week_sec < event_end_week_sec
            or event_start_week_sec <= elapsed_week_sec + _SEC_IN_WEEK < event_end_week_sec
        )
        if is_current:
            event_start_week_sec = (
                event_start_week_sec  # event started this week
                if event_start_week_sec <= elapsed_week_sec
                else event_start_week_sec - _SEC_IN_WEEK  # event started last week
            )
            current_event_start_timestamp = week_start_timestamp + event_start_week_sec
            current_event_index = offset // _STRUCT_SIZE

    weekend_days = _WEEK_DAYS - work_days
    for work_day in sorted(work_days):
        # Work event
        work_start_week_sec = work_day * _SEC_IN_DAY + work_start_second_of_day
        struct.pack_into(_STRUCT_FORMAT, buffer, offset, work_duration_sec, _WORK)
        _set_if_current(work_start_week_sec, work_duration_sec)

        offset += _STRUCT_SIZE

        tomorrow = (work_day + 1) % 7
        rest_day = work_day if not is_work_midnight else tomorrow
        rest_start_week_sec = rest_day * _SEC_IN_DAY + work_end_second_of_day
        if tomorrow in work_days:
            # Rest event
            struct.pack_into(_STRUCT_FORMAT, buffer, offset, rest_duration_sec, _REST)
            _set_if_current(rest_start_week_sec, rest_duration_sec)
        else:
            # Weekend event
            weekend_duration_sec = rest_duration_sec
            day = rest_day
            while (day := (day + 1) % 7) in weekend_days:
                weekend_duration_sec += _SEC_IN_DAY

            struct.pack_into(_STRUCT_FORMAT, buffer, offset, weekend_duration_sec, _WEEKEND)
            _set_if_current(rest_start_week_sec, weekend_duration_sec)

        offset += _STRUCT_SIZE

    # Yield events starting from the current one.
    # DST correction is computed at yield time (not pre-stored in buffer).
    while True:
        offset = current_event_index * _STRUCT_SIZE
        event_duration_sec, event_type = struct.unpack_from(_STRUCT_FORMAT, buffer, offset)

        event_name: str
        if event_type == _WORK:
            event_name = "work"
        elif event_type == _REST:
            event_name = "rest"
        else:  # event_type == _WEEKEND
            event_name = "weekend"

        real_dur = time_service.real_duration(current_event_start_timestamp, event_duration_sec)

        yield Event(event_name, current_event_start_timestamp, event_duration_sec, real_dur)

        current_event_start_timestamp += event_duration_sec  # advance by wall-clock
        current_event_index = (current_event_index + 1) % num_events


_WEATHER_NAMES = ("sun", "rain", "snow", "fog")
_WEATHER_DURATIONS = (15 * 60, 30 * 60, 60 * 60, 120 * 60, 150 * 60)
_WEATHER_GAP_CHANCE = const(20)  # percent chance of a gap


def random_weather_loop(
    start_timestamp: int,
    time_service: TimeService,
):  # Iterator[Event]
    """Yield random weather events with occasional gaps, starting from *start_timestamp*."""
    return random_event_loop(
        names=_WEATHER_NAMES,
        durations=_WEATHER_DURATIONS,
        gap_chance=_WEATHER_GAP_CHANCE,
        start_timestamp=start_timestamp,
        time_service=time_service,
    )


def random_event_loop(
    names: tuple,
    durations: tuple,
    gap_chance: int,
    start_timestamp: int,
    time_service: TimeService,
):  # Iterator[Event]
    """Yield random events from *names* with durations from *durations* and occasional gaps."""
    cursor = start_timestamp

    while True:
        dur = random.choice(durations)

        if random.randint(1, 100) <= gap_chance:
            cursor += dur
            continue

        name = random.choice(names)
        real_dur = time_service.real_duration(cursor, dur)
        yield Event(name, cursor, dur, real_dur)
        cursor += dur
