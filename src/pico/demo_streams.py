import random

from displays.palette import STREAM_SKY, STREAM_YELLOW, STREAM_PINK, STREAM_BLUE
from scheduling.event import Event
from scheduling.stream import Stream
from services.time_service import TimeService

_WEATHER_NAMES = ("sun", "rain", "snow", "fog")
_WEATHER_DURATIONS = (15 * 60, 30 * 60, 60 * 60, 120 * 60, 150 * 60)
_WEATHER_GAP_PCT = 20


def _random_event_loop(
    names: tuple,
    durations: tuple,
    gap_pct: int,
    start_timestamp: int,
    time_service: TimeService,
    color_index: int,
    window_past_sec: int,
):  # Iterator[Event]
    """Yield random events from ``names`` and ``durations`` forever, with occasional gaps."""
    cursor = start_timestamp

    while True:
        # Unseen placeholder history need not be replayed after a long absence.
        window_start = time_service.now() - window_past_sec
        if cursor < window_start:
            cursor = window_start
        dur = random.choice(durations)

        if random.randint(1, 100) <= gap_pct:
            cursor += dur
            continue

        name = random.choice(names)
        real_dur = time_service.real_duration_sec(cursor, dur)
        yield Event(name, cursor, dur, real_dur, color_index=color_index)
        cursor += dur


def build_demo_streams(
    time_service: TimeService, window_past_sec: int
) -> list[Stream]:
    """Return placeholder streams of random events, starting ``window_past_sec`` ago."""
    start = time_service.now() - window_past_sec

    iterators = [
        _random_event_loop(
            names=_WEATHER_NAMES,
            durations=_WEATHER_DURATIONS,
            gap_pct=_WEATHER_GAP_PCT,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_SKY,
            window_past_sec=window_past_sec,
        ),
        _random_event_loop(
            names=("code", "review", "deploy", "test", "debug"),
            durations=(15 * 60, 30 * 60, 45 * 60, 60 * 60),
            gap_pct=15,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_YELLOW,
            window_past_sec=window_past_sec,
        ),
        _random_event_loop(
            names=("call", "standup", "retro", "chat"),
            durations=(15 * 60, 30 * 60, 60 * 60),
            gap_pct=40,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_PINK,
            window_past_sec=window_past_sec,
        ),
        _random_event_loop(
            names=("run", "walk", "gym", "yoga", "rest"),
            durations=(20 * 60, 30 * 60, 45 * 60, 60 * 60, 90 * 60),
            gap_pct=25,
            start_timestamp=start,
            time_service=time_service,
            color_index=STREAM_BLUE,
            window_past_sec=window_past_sec,
        ),
    ]

    return [Stream(events_iter=it) for it in iterators]
