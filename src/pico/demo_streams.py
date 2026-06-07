"""Demo event streams used by the calendar display.

These are placeholder streams to populate the calendar while the web
configuration server is not yet built.  Expected to be deleted once
users can define their own streams.
"""

import random

from displays.palette import STREAM_SKY, STREAM_YELLOW, STREAM_PINK, STREAM_TEAL
from scheduling.event import Event
from scheduling.stream import Stream
from services.time_service import TimeService

_WEATHER_NAMES = ("sun", "rain", "snow", "fog")
_WEATHER_DURATIONS = (15 * 60, 30 * 60, 60 * 60, 120 * 60, 150 * 60)
_WEATHER_GAP_CHANCE = 20  # percent chance of a gap


def _random_event_loop(
    names: tuple,
    durations: tuple,
    gap_chance: int,
    start_timestamp: int,
    time_service: TimeService,
    color_index: int,
):  # Iterator[Event]
    """Yield random events from *names* with durations from *durations* and occasional gaps.

    Every event is tagged with *color_index* so the whole row renders in
    one color.
    """
    cursor = start_timestamp

    while True:
        dur = random.choice(durations)

        if random.randint(1, 100) <= gap_chance:
            cursor += dur
            continue

        name = random.choice(names)
        real_dur = time_service.real_duration(cursor, dur)
        yield Event(name, cursor, dur, real_dur, color_index=color_index)
        cursor += dur


def build_demo_streams(time_service: TimeService) -> list[Stream]:
    """Return the placeholder demo streams (weather + random events)."""
    start = time_service.now() - 30 * 60

    # One color_index per row (work_week is row 0).
    iterators = [
        _random_event_loop(
            names=_WEATHER_NAMES,
            durations=_WEATHER_DURATIONS,
            gap_chance=_WEATHER_GAP_CHANCE,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_SKY,
        ),
        _random_event_loop(
            names=("code", "review", "deploy", "test", "debug"),
            durations=(15 * 60, 30 * 60, 45 * 60, 60 * 60),
            gap_chance=15,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_YELLOW,
        ),
        _random_event_loop(
            names=("call", "standup", "retro", "chat"),
            durations=(15 * 60, 30 * 60, 60 * 60),
            gap_chance=40,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_PINK,
        ),
        _random_event_loop(
            names=("run", "walk", "gym", "yoga", "rest"),
            durations=(20 * 60, 30 * 60, 45 * 60, 60 * 60, 90 * 60),
            gap_chance=25,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_TEAL,
        ),
    ]

    return [Stream(events_iter=it) for it in iterators]
