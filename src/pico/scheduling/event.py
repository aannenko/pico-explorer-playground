from collections import namedtuple


Event = namedtuple("Event", ("label", "start_utc", "duration_sec", "color_index"))


def create_event(
    label: str,
    start_utc: int,
    duration_sec: int,
    color_index: int = 0,  # index into displays.palette.STREAM_COLORS
) -> Event:
    """Create an immutable event, compared by its four field values.

    ``start_utc`` is UTC epoch seconds and ``duration_sec`` real seconds.
    ``label`` must be non-empty, and the other fields non-negative.
    """
    if not label:
        raise ValueError("Event label cannot be empty")

    if start_utc < 0:
        raise ValueError("Event start timestamp cannot be negative")

    if duration_sec < 0:
        raise ValueError("Event duration cannot be negative")

    if color_index < 0:
        raise ValueError("Event color_index cannot be negative")

    return Event(label, start_utc, duration_sec, color_index)