class Event:
    """Scheduled event: it starts at ``start_utc``, UTC epoch seconds, and lasts ``duration_sec`` real seconds.

    ``label`` must be non-empty, and ``start_utc``,
    ``duration_sec`` and ``color_index`` non-negative.
    """

    def __init__(
        self,
        label: str,
        start_utc: int,
        duration_sec: int,
        color_index: int = 0,  # index into displays.palette.STREAM_COLORS
    ) -> None:
        if not label:
            raise ValueError("Event label cannot be empty")

        if start_utc < 0:
            raise ValueError("Event start timestamp cannot be negative")

        if duration_sec < 0:
            raise ValueError("Event duration cannot be negative")

        if color_index < 0:
            raise ValueError("Event color_index cannot be negative")

        self.label = label
        self.start_utc = start_utc
        self.duration_sec = duration_sec
        self.color_index = color_index

    def __repr__(self) -> str:
        return (
            f"Event(label={self.label}, "
            f"start_utc={self.start_utc}, "
            f"duration_sec={self.duration_sec}, "
            f"color_index={self.color_index})"
        )