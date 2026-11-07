class Event:
    """Scheduled event; ``start_timestamp`` is local epoch.

    ``label`` must be non-empty, and ``start_timestamp``,
    ``wall_clock_duration_sec`` and ``color_index`` non-negative.
    """

    def __init__(
        self,
        label: str,
        start_timestamp: int,
        wall_clock_duration_sec: int,
        color_index: int = 0,  # index into displays.palette.STREAM_COLORS
    ) -> None:
        if not label:
            raise ValueError("Event label cannot be empty")

        if start_timestamp < 0:
            raise ValueError("Event start timestamp cannot be negative")

        if wall_clock_duration_sec < 0:
            raise ValueError("Event duration cannot be negative")

        if color_index < 0:
            raise ValueError("Event color_index cannot be negative")

        self.label = label
        self.start_timestamp = start_timestamp
        self.wall_clock_duration_sec = wall_clock_duration_sec
        self.color_index = color_index

    def __repr__(self) -> str:
        return (
            f"Event(label={self.label}, "
            f"start_timestamp={self.start_timestamp}, "
            f"wall_clock_duration_sec={self.wall_clock_duration_sec}, "
            f"color_index={self.color_index})"
        )