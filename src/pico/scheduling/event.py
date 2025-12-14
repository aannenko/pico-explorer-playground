class Event:
    """
    Represents a scheduled event.

    Attributes:
        name (str): Event name.
        alt_text (str): Alternative text for the event.
        start_timestamp (int): Event start time as seconds since Epoch (Unix timestamp).
        duration_sec (int): Event duration in seconds.
    """
    def __init__(
        self,
        name: str,
        start_timestamp: int,
        duration_sec: int,
    ) -> None:
        if not name:
            raise ValueError("Event name cannot be empty")

        if start_timestamp < 0:
            raise ValueError("Event start timestamp cannot be negative")

        if duration_sec < 0:
            raise ValueError("Event duration cannot be negative")

        self.name = name
        self.start_timestamp = start_timestamp
        self.duration_sec = duration_sec

    def __repr__(self) -> str:
        return (
            f"Event(name={self.name}, "
            f"start_timestamp={self.start_timestamp}, "
            f"duration_sec={self.duration_sec})"
        )