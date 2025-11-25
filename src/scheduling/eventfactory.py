import struct
import time

from scheduling.event import Event

_WEEK_DAYS = {0, 1, 2, 3, 4, 5, 6}  # Monday=0 .. Sunday=6
_SEC_IN_DAY = const(24 * 60 * 60)
_SEC_IN_WEEK = const(_SEC_IN_DAY * 7)

_WORK = const(0)
_REST = const(1)
_WEEKEND = const(2)

_STRUCT_FORMAT = "IB"  # duration_sec, event_type
_STRUCT_SIZE = struct.calcsize(_STRUCT_FORMAT)


def work_week_loop(
    work_days: set[int],
    work_start_utc: tuple[int, int],
    work_end_utc: tuple[int, int],
):
    """
    Yield work-rest-weekend events, starting from the currently running one

    Args:
        work_days (set[int]): Set of work days (0=Monday .. 6=Sunday)
        work_start_utc (tuple[int, int]): Work start time in UTC (hour, minute)
        work_end_utc (tuple[int, int]): Work end time in UTC (hour, minute)

    Returns:
        Iterable[Event]: A sequence of work, rest, and weekend events,
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
    work_start_hour, work_start_minute = work_start_utc
    if work_start_hour < 0 or work_start_hour > 23 or work_start_minute < 0 or work_start_minute > 59:
        raise ValueError("Work start time is invalid")

    work_end_hour, work_end_minute = work_end_utc
    if work_end_hour < 0 or work_end_hour > 23 or work_end_minute < 0 or work_end_minute > 59:
        raise ValueError("Work end time is invalid")

    if work_start_utc == work_end_utc:
        raise ValueError("Work start and end times cannot be the same")

    if not work_days or not work_days.issubset(_WEEK_DAYS):
        raise ValueError("Work days must be one or more days from {0, 1, 2, 3, 4, 5, 6}")

    is_work_midnight = work_start_utc > work_end_utc

    # Calculate the number of events
    num_events = len(work_days) * 2  # work + rest/weekend per work day

    # Pre-calculate event durations
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

    now_timestamp = time.time()
    _, _, _, now_hour, now_minute, now_second, now_weekday, _ = time.gmtime(now_timestamp)
    elapsed_week_sec = now_weekday * _SEC_IN_DAY + now_hour * 3600 + now_minute * 60 + now_second
    week_start_timestamp = now_timestamp - elapsed_week_sec
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

    # Yield events starting from the current one
    while True:
        offset = current_event_index * _STRUCT_SIZE
        duration_sec, event_type = struct.unpack_from(_STRUCT_FORMAT, buffer, offset)
        yield Event(
            name=(
                "work" if event_type == _WORK
                else "rest" if event_type == _REST
                else "weekend"),
            start_timestamp=current_event_start_timestamp,
            duration_sec=duration_sec,
        )
        current_event_start_timestamp += duration_sec
        current_event_index = (current_event_index + 1) % num_events
