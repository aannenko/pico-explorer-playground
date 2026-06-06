class Event:
    """Scheduled event with both wall-clock and DST-corrected real durations."""

    def __init__(
        self,
        name: str,
        start_timestamp: int,
        wall_clock_duration_sec: int,
        real_duration_sec: int = -1,  # DST-corrected
        severity: int = 0,
    ) -> None:
        if not name:
            raise ValueError("Event name cannot be empty")

        if start_timestamp < 0:
            raise ValueError("Event start timestamp cannot be negative")

        if wall_clock_duration_sec < 0:
            raise ValueError("Event duration cannot be negative")

        if severity < 0:
            raise ValueError("Event severity cannot be negative")

        self.name = name
        self.start_timestamp = start_timestamp
        self.wall_clock_duration_sec = wall_clock_duration_sec
        self.real_duration_sec = real_duration_sec if real_duration_sec >= 0 else wall_clock_duration_sec
        self.severity = severity

    def __repr__(self) -> str:
        return (
            f"Event(name={self.name}, "
            f"start_timestamp={self.start_timestamp}, "
            f"wall_clock_duration_sec={self.wall_clock_duration_sec}, "
            f"real_duration_sec={self.real_duration_sec}, "
            f"severity={self.severity})"
        )