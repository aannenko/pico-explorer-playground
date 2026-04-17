"""Demo event streams used by the calendar display.

These are placeholder streams to populate the calendar while the web
configuration server is not yet built.  Expected to be deleted once
users can define their own streams.
"""

from scheduling import event_factory
from services.time_service import TimeService


def build_demo_streams(time_service: TimeService) -> list:
    """Return a list of event iterators (one per demo stream).

    The order matches the stream color pairs in ``palette.DEFAULT_STREAM_COLORS``
    starting at index 1 (index 0 is reserved for the user's real work-week
    stream).
    """
    start = time_service.now() - 30 * 60

    return [
        event_factory.random_weather_loop(
            start_timestamp=start,
            time_service=time_service,
        ),
        event_factory.random_event_loop(
            names=("code", "review", "deploy", "test", "debug"),
            durations=(15 * 60, 30 * 60, 45 * 60, 60 * 60),
            gap_chance=15,
            start_timestamp=start,
            time_service=time_service,
        ),
        event_factory.random_event_loop(
            names=("call", "standup", "retro", "chat"),
            durations=(15 * 60, 30 * 60, 60 * 60),
            gap_chance=40,
            start_timestamp=start,
            time_service=time_service,
        ),
        event_factory.random_event_loop(
            names=("run", "walk", "gym", "yoga", "rest"),
            durations=(20 * 60, 30 * 60, 45 * 60, 60 * 60, 90 * 60),
            gap_chance=25,
            start_timestamp=start,
            time_service=time_service,
        ),
    ]
