class Event:
    """
    Represents a scheduled event.

    Attributes:
        name (str): Event name.
        alt_text (str): Alternative text for the event.
        start_timestamp (int): Event start time as seconds since Epoch.
        wall_clock_duration_sec (int): Event duration in wall-clock seconds.
        real_duration_sec (int): Event duration in real seconds (DST-corrected).
    """
    def __init__(
        self,
        name: str,
        start_timestamp: int,
        wall_clock_duration_sec: int,
        real_duration_sec: int = -1,
    ) -> None:
        if not name:
            raise ValueError("Event name cannot be empty")

        if start_timestamp < 0:
            raise ValueError("Event start timestamp cannot be negative")

        if wall_clock_duration_sec < 0:
            raise ValueError("Event duration cannot be negative")

        self.name = name
        self.start_timestamp = start_timestamp
        self.wall_clock_duration_sec = wall_clock_duration_sec
        self.real_duration_sec = real_duration_sec if real_duration_sec >= 0 else wall_clock_duration_sec

    def __repr__(self) -> str:
        return (
            f"Event(name={self.name}, "
            f"start_timestamp={self.start_timestamp}, "
            f"wall_clock_duration_sec={self.wall_clock_duration_sec}, "
            f"real_duration_sec={self.real_duration_sec})"
        )